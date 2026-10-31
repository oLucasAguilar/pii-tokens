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


class MaskingMiddleware(Middleware):
    def __init__(self, settings: Settings, masker: masking.Masker):
        self.settings = settings
        self.masker = masker

    async def on_list_tools(self, context: MiddlewareContext, call_next):
        tools = await call_next(context)
        # Masking turns typed values into token strings, so an output schema would no longer hold.
        return [t.model_copy(update={"output_schema": None}) for t in tools if self.settings.allows(t)]

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        name = context.message.name
        tool = await context.fastmcp_context.fastmcp.get_tool(name)
        if tool is None or not self.settings.allows(tool):
            raise ToolError(f"Tool {name!r} is not available through this proxy.")
        arguments = self.masker.unmask(context.message.arguments or {})
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
    return proxy


def main():
    # The banner's emoji turns into mojibake in the Windows log, and it says nothing about the masking.
    build(Settings.from_env()).run(show_banner=False)
