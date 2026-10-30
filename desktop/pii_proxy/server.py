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
from fastmcp.tools import ToolResult
from mcp.types import TextContent

from . import masking


@dataclasses.dataclass(frozen=True)
class Preset:
    allow: frozenset = frozenset()
    block: frozenset = frozenset()


# Tool rules for a known upstream, on top of the generic one (only tools marked read-only).
PRESETS = {
    "metabase": Preset(
        # Runs read-only SQL but is not marked read-only.
        allow=frozenset({"execute_sql"}),
        # Their data reaches Claude without passing through here (a chart iframe) or is raw column values with no column to mask by.
        block=frozenset({"visualize_query", "render_drill_through", "get_parameter_values"}),
    ),
}

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
        if self.preset and self.preset not in PRESETS:
            raise ValueError(f"unknown preset {self.preset!r}: {', '.join(sorted(PRESETS))}")
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
        preset = PRESETS.get(self.preset, Preset())
        if tool.name in preset.block:
            return False
        if tool.name in preset.allow:
            return True
        return bool(tool.annotations and tool.annotations.read_only_hint)


class MaskingMiddleware(Middleware):
    def __init__(self, settings: Settings, vault):
        self.settings = settings
        self.vault = vault

    async def on_list_tools(self, context: MiddlewareContext, call_next):
        tools = await call_next(context)
        # Masking turns typed values into token strings, so an output schema would no longer hold.
        return [t.model_copy(update={"output_schema": None}) for t in tools if self.settings.allows(t)]

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        name = context.message.name
        tool = await context.fastmcp_context.fastmcp.get_tool(name)
        if tool is None or not self.settings.allows(tool):
            raise ToolError(f"Tool {name!r} is not available through this proxy.")
        arguments = masking.unmask_arguments(context.message.arguments or {}, self.settings.unmask_kinds, self.vault)
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
            structured = None if result.structured_content is None else masking.mask_value(result.structured_content, self.vault)
        except Exception as e:
            print(f"[pii-tokens] result withheld: {type(e).__name__}", file=sys.stderr)
            raise ToolError("Result withheld: it could not be masked with certainty.") from None
        return ToolResult(content=content, structured_content=structured, meta=None, is_error=result.is_error)

    def _masked_block(self, block):
        if not isinstance(block, TextContent):
            raise masking.Unrecognized(f"{block.type} content")
        return TextContent(type="text", text=masking.mask_text_block(block.text, self.vault))

    def _masked_message(self, message: str) -> str:
        try:
            return masking.mask_text_block(message, self.vault)
        except Exception:
            return "The upstream server failed, and its message could not be masked with certainty."


def upstream_transport(settings: Settings) -> StreamableHttpTransport:
    from . import auth

    return StreamableHttpTransport(
        settings.url,
        auth=auth.oauth(settings.url, settings.headers, settings.oauth_port) if settings.oauth else None,
        httpx_client_factory=auth.client_factory(settings.headers),
    )


def build(settings: Settings, upstream=None):
    target = upstream if upstream is not None else upstream_transport(settings)
    # The upstream era is negotiated on its own: mirroring Claude's era fails on a server that speaks only one.
    proxy = create_proxy(target, mode="auto", name="pii-tokens")
    # Resources and prompts would be another way out for data; nothing here masks them yet.
    proxy.disable(components={"resource", "template", "prompt"})
    proxy.add_middleware(MaskingMiddleware(settings, masking.vault()))
    return proxy


def main():
    build(Settings.from_env()).run()
