"""Local MCP server for Claude Desktop: forwards every call to the upstream MCP server and masks what comes back.

Claude Desktop ignores plugin hooks in chat, so the masking the plugin does in a hook happens here instead.
Configured by environment variables, which the desktop extension's manifest fills in.
"""

import dataclasses
import json
import os
import sys

from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from fastmcp.server import create_proxy
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.providers.proxy import ProxyClient
from fastmcp.tools import ToolResult
from mcp.types import TextContent

from . import masking, upstreams

# Kinds that the result masking finds again by format, so a token unmasked in a query cannot come back in clear.
UNMASKABLE_KINDS = frozenset({"CPF", "CNPJ", "EMAIL", "PHONE"})


def _names(raw: str | None) -> frozenset:
    return frozenset(n.strip() for n in (raw or "").split(",") if n.strip())


@dataclasses.dataclass(frozen=True)
class Settings:
    url: str
    preset: str = ""
    headers: dict = dataclasses.field(default_factory=dict)
    oauth: bool = False
    oauth_port: int = 0
    allow_tools: frozenset = frozenset()
    block_tools: frozenset = frozenset()
    unmask_kinds: frozenset = frozenset()

    def __post_init__(self):
        if self.preset not in upstreams.PROFILES:
            raise ValueError(f"unknown preset {self.preset!r}: {', '.join(sorted(p for p in upstreams.PROFILES if p))}")
        unknown = self.unmask_kinds - UNMASKABLE_KINDS
        if unknown:
            raise ValueError(f"cannot unmask {', '.join(sorted(unknown))}: only {', '.join(sorted(UNMASKABLE_KINDS))}")

    @classmethod
    def from_env(cls, env=os.environ) -> "Settings":
        return cls(
            url=env["PII_PROXY_URL"],
            preset=env.get("PII_PROXY_PRESET", "").strip().lower(),
            headers=json.loads(env.get("PII_PROXY_HEADERS") or "{}"),
            oauth=env.get("PII_PROXY_AUTH", "").strip().lower() == "oauth",
            oauth_port=int(env.get("PII_PROXY_OAUTH_PORT") or 0),
            allow_tools=_names(env.get("PII_PROXY_ALLOW_TOOLS")),
            block_tools=_names(env.get("PII_PROXY_BLOCK_TOOLS")),
            unmask_kinds=frozenset(k.upper() for k in _names(env.get("PII_PROXY_UNMASK"))),
        )

    def allows(self, tool) -> bool:
        if tool.name in self.block_tools:
            return False
        if tool.name in self.allow_tools:
            return True
        profile = upstreams.PROFILES[self.preset]
        if tool.name in profile.block:
            return False
        if tool.name in profile.allow:
            return True
        return bool(tool.annotations and tool.annotations.read_only_hint)


# Without this, Claude guessed that tokens change between conversations and explained the masking unasked.
def own_instructions(unmask_kinds: frozenset, distinct: bool = True) -> str:
    """What Claude needs to know about the tokens; the part on queries depends on the Unmask in queries field, and the
    promise of one token per value holds only when the vault has its key (without it every CPF is CPF#????????)."""
    if unmask_kinds:
        follow = (f"A {', '.join(sorted(unmask_kinds))} token written in a query reaches the server as the real value, "
                  "so it can be used as a filter. Names never do: to follow a person, filter by an ID.")
    else:
        follow = ("A token written in a query reaches the server as plain text and matches nothing: to follow a record "
                  "in a later query, filter by an ID or another column that comes back in clear.")
    same = ("On this computer and user account the same value gets the same token in every conversation, so tokens can "
            "be counted and compared." if distinct else
            "Here the tokens cannot tell values apart (no system keyring): do not count or compare them.")
    return ("pii-tokens: personal data in these results (CPF, CNPJ, email, phone, names in query tables) arrives as "
            f"tokens such as CPF#3f1a9c0d22e4. {same} {follow} Do not explain the masking unless the user asks.")


def _resolve(schema, definitions: dict):
    """The field's schema with a local $ref and a one-item allOf followed; None when it cannot be read: an unknown
    reference, or a schema that says nothing about the value (no type, choices or options), which takes anything."""
    for _ in range(10):
        if not isinstance(schema, dict):
            return None
        if "$ref" in schema:
            ref = schema["$ref"]
            if not ref.startswith("#/$defs/") or ref[8:] not in definitions:
                return None
            schema = definitions[ref[8:]]
        elif len(schema.get("allOf", ())) == 1:
            schema = schema["allOf"][0]
        else:
            options = schema.get("anyOf") or schema.get("oneOf")
            if options:
                return schema if all(_resolve(option, definitions) is not None for option in options) else None
            return schema if {"type", "enum", "const"} & schema.keys() else None
    return None


def _accepts(schema, kind: str, definitions: dict) -> bool:
    """Whether the field takes null (kind "null") or the text "null" (kind "string")."""
    schema = _resolve(schema, definitions)
    if schema is None:
        return True
    options = schema.get("anyOf") or schema.get("oneOf")
    if options:
        return any(_accepts(option, kind, definitions) for option in options)
    # A closed choice takes the text only when "null" is one of its choices.
    if "const" in schema:
        return schema["const"] is None if kind == "null" else schema["const"] == "null"
    if "enum" in schema:
        return None in schema["enum"] if kind == "null" else "null" in schema["enum"]
    declared = schema.get("type")
    if declared is None:
        return False
    return declared == kind or (isinstance(declared, list) and kind in declared)


def _closed_with_null_text(schema, definitions: dict) -> bool:
    """A closed choice that lists the text "null" among its values: there the text is a real choice."""
    schema = _resolve(schema, definitions)
    if schema is None:
        return False
    options = schema.get("anyOf") or schema.get("oneOf")
    if options:
        return any(_closed_with_null_text(option, definitions) for option in options)
    return schema.get("const") == "null" or "null" in schema.get("enum", ())


def without_null_text(arguments: dict, parameters: dict) -> dict:
    """Claude sometimes writes an empty argument as the text "null" ("limit": "null"), and the server refuses the
    whole call. Where the field takes null and "null" is not one of its choices, it goes as null; where the field takes
    neither null nor that text and is optional, it is left out. Otherwise, or when the schema cannot be read, the
    text goes as sent."""
    parameters = parameters or {}
    fields = parameters.get("properties", {})
    definitions = parameters.get("$defs", {})
    required = set(parameters.get("required", []))
    fixed = {}
    for key, value in arguments.items():
        schema = fields.get(key)
        if value != "null" or _resolve(schema, definitions) is None:
            fixed[key] = value
        elif _accepts(schema, "null", definitions) and not _closed_with_null_text(schema, definitions):
            fixed[key] = None
            print(f"[pii-tokens] argument {key!r} came as the text null: sent as null", file=sys.stderr)
        elif key in required or _accepts(schema, "string", definitions):
            fixed[key] = value
        else:
            print(f"[pii-tokens] argument {key!r} came as the text null: left out", file=sys.stderr)
    return fixed


class InstructionsMiddleware(Middleware):
    """Masks the instructions the upstream sends on connect, and adds ours. It must run outermost: the proxy adds
    those instructions in a middleware of its own, after the inner ones have already seen the result."""

    def __init__(self, masker: masking.Masker, own: str):
        self.masker = masker
        self.own = own

    def _masked(self, result):
        if not hasattr(result, "instructions"):
            return result
        upstream = self.masker.written(result.instructions) if result.instructions else ""
        return result.model_copy(update={"instructions": f"{upstream}\n\n{self.own}".strip()})

    async def on_initialize(self, context, call_next):
        return self._masked(await call_next(context))

    async def on_discover(self, context, call_next):
        return self._masked(await call_next(context))


class MaskingMiddleware(Middleware):
    def __init__(self, settings: Settings, masker: masking.Masker):
        self.settings = settings
        self.masker = masker

    async def on_list_tools(self, context: MiddlewareContext, call_next):
        tools = await call_next(context)
        # Masking turns typed values into token strings, so an output schema would no longer hold.
        # The tool name stays as is (Claude calls it by that name); its texts are masked like any result.
        return [
            t.model_copy(update={
                "output_schema": None,
                "title": t.title and self.masker.written(t.title),
                "description": t.description and self.masker.written(t.description),
                "parameters": self.masker.schema(t.parameters),
                "annotations": t.annotations and t.annotations.model_copy(
                    update={"title": t.annotations.title and self.masker.written(t.annotations.title)}),
                "meta": None,
            })
            for t in tools
            if self.settings.allows(t)
        ]

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        name = context.message.name
        tool = await context.fastmcp_context.fastmcp.get_tool(name)
        if tool is None or not self.settings.allows(tool):
            raise ToolError(f"Tool {name!r} is not available through this proxy.")
        arguments = self.masker.unmask(context.message.arguments or {})
        arguments = without_null_text(arguments, tool.parameters)
        context = context.copy(message=context.message.model_copy(update={"arguments": arguments}))
        try:
            result = await call_next(context)
        except Exception as e:
            raise ToolError(self._masked_message(str(e))) from None
        if not isinstance(result, ToolResult):
            return result
        return self._masked(result)

    def _masked(self, result: ToolResult) -> ToolResult:
        try:
            content = [self._masked_block(block) for block in result.content]
            structured = None if result.structured_content is None else self.masker.value(result.structured_content)
        except Exception as e:
            print(f"[pii-tokens] result withheld: {type(e).__name__}", file=sys.stderr)
            raise ToolError("Result withheld: it could not be masked with certainty.") from None
        return ToolResult(content=content, structured_content=structured, meta=None, is_error=result.is_error)

    def _masked_block(self, block):
        if not isinstance(block, TextContent):
            raise masking.Withheld(f"{block.type} content")
        return TextContent(type="text", text=self.masker.text(block.text))

    def _masked_message(self, message: str) -> str:
        try:
            return self.masker.text(message)
        except Exception:
            return "The upstream server failed, and its message could not be masked with certainty."


def upstream_transport(settings: Settings) -> StreamableHttpTransport:
    from . import auth

    return StreamableHttpTransport(
        settings.url,
        auth=auth.oauth(settings.url, settings.headers, settings.oauth_port) if settings.oauth else None,
        httpx_client_factory=auth.client_factory(settings.url, settings.headers),
    )


async def _refuse(*args):
    raise ToolError("pii-tokens does not forward this request: its text could not be masked.")


async def _ignore_progress(progress, total, message):
    pass


def _log_handler(masker):
    async def log(message):
        print(f"[upstream {message.level}] {masker.text(str(message.data))}", file=sys.stderr)

    return log


def build(settings: Settings, upstream=None):
    target = upstream if upstream is not None else upstream_transport(settings)
    masker = masking.Masker(masking.vault(), settings.unmask_kinds)
    # Besides results, the upstream can send logs, progress and sampling or elicitation requests, which the
    # default proxy forwards to Claude as they come. Logs go to the extension's log file masked; the rest stops here.
    client = ProxyClient(
        target,
        # The upstream era is negotiated on its own: mirroring Claude's era fails on a server that speaks only one.
        mode="auto",
        sampling_handler=_refuse,
        elicitation_handler=_refuse,
        log_handler=_log_handler(masker),
        progress_handler=_ignore_progress,
    )
    proxy = create_proxy(client, name="pii-tokens")
    # Resources and prompts would be another way out for data; nothing here masks them yet.
    proxy.disable(components={"resource", "template", "prompt"})
    proxy.add_middleware(MaskingMiddleware(settings, masker))
    distinct = "?" not in masking.pii.Vault(store=False).token_for("CPF", "00000000000")
    proxy.middleware.insert(0, InstructionsMiddleware(masker, own_instructions(settings.unmask_kinds, distinct)))
    return proxy


def main():
    # The banner's emoji turns into mojibake in the Windows log, and it says nothing about the masking.
    build(Settings.from_env()).run(show_banner=False)
