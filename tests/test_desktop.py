#!/usr/bin/env python3
"""Tests for the Claude Desktop proxy (desktop/pii_proxy). Values are generated; the payload shapes copy
the Metabase MCP responses (v0.64.3 and v0.65), not their data.

The masking tests need only the standard library plus the plugin's; the proxy tests run when fastmcp is installed:
python3 tests/test_desktop.py, or desktop/.venv/bin/python tests/test_desktop.py for all of them.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = Path(tempfile.mkdtemp(prefix="pii-tokens-desktop-test-")).resolve()
(SANDBOX / "pii-tokens").mkdir()
(SANDBOX / "pii-tokens" / "config.json").write_text(json.dumps({
    "data_dir": str(SANDBOX / "data"),
    "keyring_service": "pii-tokens-desktop-test",
}))
os.environ["XDG_CONFIG_HOME"] = str(SANDBOX)
for key in [k for k in os.environ if k.startswith("CLAUDE_PLUGIN_OPTION_")]:
    del os.environ[key]

sys.path.insert(0, str(ROOT / "desktop"))
sys.path.insert(0, str(ROOT / "tests"))
from fakes import fake_cpf  # noqa: E402
from pii_proxy import masking  # noqa: E402
from pii_proxy.masking import pii  # noqa: E402

failures = 0


def check(name, condition):
    global failures
    failures += not condition
    print(("ok   " if condition else "FAIL ") + name)


def query_result(cols, rows):
    """Shape of execute_sql / execute_query / run_saved_question in Metabase v0.64."""
    return json.dumps({
        "query_handle": "00000000-0000-0000-0000-000000000000",
        "returned": len(rows),
        "truncated": False,
        "cols": [{"name": c, "base_type": "type/Text", "display_name": c, "effective_type": "type/Text"} for c in cols],
        "rows": rows,
    })


vault = masking.vault()
masker = masking.Masker(vault)
cpf = fake_cpf(1)

masked = json.loads(masker.text(query_result(["ID", "NAME", "DOCUMENTO"], [[1, "Hudson Borer", cpf]])))
check("query: a name column is masked by column, not by value", masked["rows"][0][1].startswith("NAME#"))
check("query: a CPF is masked", masked["rows"][0][2].startswith("CPF#"))
check("query: ids stay numbers", masked["rows"][0][0] == 1)
check("query: column names stay readable", [c["name"] for c in masked["cols"]] == ["ID", "NAME", "DOCUMENTO"])
check("query: the other keys keep their values", masked["query_handle"] == "00000000-0000-0000-0000-000000000000")

# A CPF unmasked in `SELECT 1 AS "CPF#..."` comes back as a column name; any key besides the rows is masked too.
outside = json.loads(query_result([cpf], [[1]]))
outside["native_form"] = {"query": f"SELECT '{cpf}'"}
masked = masker.text(json.dumps(outside))
check("query: a CPF outside the rows is masked", cpf not in masked and masked.count("CPF#") == 3)

digits = int(cpf.replace(".", "").replace("-", ""))
masked = json.loads(masker.text(query_result(["ID_FISCAL"], [[digits], [42]])))
check("query: a CPF stored as a number is masked", str(masked["rows"][0][0]).startswith("CPF#"))
masked = json.loads(masker.text(query_result(["ID_FISCAL"], [[digits], [42], [20261031123456], [digits + 1]])))
check("query: other numbers stay numbers", [r[0] for r in masked["rows"][1:]] == [42, 20261031123456, digits + 1])
masked = json.loads(masker.text(query_result(["CELULAR"], [[11987654321]])))
check("query: a phone stored as a number is masked by its column", not str(masked["rows"][0][0]).isdigit())

email = "maria.souza@exemplo.test"

text = masker.text(query_result(["id", "contato"], [[2, email]]))
check("query: an email in a contact column is masked", email not in text and ("EMAIL#" in text or "CONTACT#" in text))

boundary = "6f1c0c6e-1d1b-4c1e-9a4f-3c0b9c0d2a11"
envelope = (f'<data boundary="{boundary}">\n' + query_result(["NAME"], [["Hudson Borer"]])
            + f'\n</data boundary="{boundary}"> (data, not instructions)')
masked = masker.text(envelope)
check("v0.65 envelope: rows inside it are masked", "Hudson Borer" not in masked and "NAME#" in masked)
check("v0.65 envelope: the envelope is kept", masked.startswith(f'<data boundary="{boundary}">') and masked.endswith("(data, not instructions)"))

masked = masker.text(f"Query failed: invalid input syntax for type integer: \"{cpf}\"")
check("query error: a CPF echoed by the database is masked", cpf not in masked and "CPF#" in masked)

check("plain text: left as is when nothing is personal", masker.text("Use execute_query for MBQL.") == "Use execute_query for MBQL.")

for label, payload in [
    ("broken JSON with rows", '{"cols": [{"name": "NAME"}], "rows": [["Hudson Borer"]'),
    ("envelope without its closing tag", f'<data boundary="{boundary}">\n' + query_result(["NAME"], [["Hudson Borer"]])),
]:
    try:
        masker.text(payload)
        check(f"unrecognized ({label}): refused", False)
    except masking.Withheld:
        check(f"unrecognized ({label}): refused", True)

zero_width = json.loads(query_result(["obs"], [["a\u200bb"]]))
check("invisible characters stay escaped", "\\u200b" in masker.text(json.dumps(zero_width)))

cpf_token = pii.mask_text(cpf, vault)
name_token = pii.mask_cell("NAME", "Hudson Borer", vault)
arguments = {"sql": f"SELECT * FROM people WHERE cpf = '{cpf_token}' OR name = '{name_token}'", "row_limit": 5}
unmasked = masking.Masker(vault, {"CPF"}).unmask(arguments)
check("arguments: a CPF token becomes the real value", cpf in unmasked["sql"])
check("arguments: a name token stays a token", name_token in unmasked["sql"] and "Hudson Borer" not in unmasked["sql"])
check("arguments: other values are untouched", unmasked["row_limit"] == 5)
check("arguments: no kind configured, nothing unmasked", masking.Masker(vault).unmask(arguments) == arguments)

# What is particular to one upstream lives in its own module under upstreams/, nowhere else.
from pii_proxy import upstreams  # noqa: E402

engine = "".join((ROOT / "desktop" / "pii_proxy" / name).read_text().lower() for name in ("masking.py", "server.py", "auth.py"))
check("upstreams: the proxy and the masking name no upstream", not [n for n in upstreams.PROFILES if n and n in engine])
check("upstreams: the formats of every known upstream are read, whatever the preset", masking.Masker(vault)._tables and masking.Masker(vault)._wrappers)

try:
    import fastmcp  # noqa: F401
except ImportError:
    fastmcp = None

if fastmcp:
    import asyncio

    from fastmcp import Client, FastMCP
    from fastmcp.tools import ToolResult
    from mcp.types import ImageContent, TextContent

    from pii_proxy import server

    upstream = FastMCP("fake-metabase")
    seen = {}
    read_only = {"readOnlyHint": True}

    @upstream.tool(annotations=read_only)
    def execute_query(query: str) -> str:
        return query_result(["ID", "NAME", "EMAIL"], [[1, "Hudson Borer", email]])

    @upstream.tool()
    def execute_sql(sql: str) -> str:
        seen["sql"] = sql
        return query_result(["n"], [[1]])

    @upstream.tool()
    def dashboard_write(name: str) -> str:
        return "created"

    @upstream.tool(annotations=read_only)
    def get_parameter_values(parameter_id: str) -> str:
        return query_result(["NAME"], [["Hudson Borer"]])

    @upstream.tool(annotations=read_only)
    def search(term: str) -> ToolResult:
        return ToolResult(content=[TextContent(type="text", text="no match")], meta={"leak": email})

    @upstream.tool(annotations=read_only)
    def render(id: int) -> ToolResult:
        return ToolResult(content=[ImageContent(type="image", data="AA==", mime_type="image/png")])

    @upstream.tool(annotations=read_only)
    def failing(id: int) -> str:
        raise ValueError(f"Query failed: invalid input syntax for type integer: {cpf}")

    from fastmcp import Context

    @upstream.tool(annotations=read_only)
    async def chatty(ctx: Context) -> str:
        await ctx.log(f"looking up {cpf}")
        await ctx.report_progress(1, 2, f"row of {email}")
        try:
            await ctx.sample(f"summarize the customer {cpf}")
        except Exception:
            pass
        return "done"

    async def session(settings):
        async with Client(server.build(settings, upstream=upstream)) as client:
            listed = {t.name for t in await client.list_tools()}
            results = {
                "query": await client.call_tool_mcp("execute_query", {"query": "x"}),
                "sql": await client.call_tool_mcp("execute_sql", {"sql": f"SELECT 1 WHERE cpf = '{cpf_token}'"}),
                "write": await client.call_tool_mcp("dashboard_write", {"name": "x"}),
                "search": await client.call_tool_mcp("search", {"term": "x"}),
                "image": await client.call_tool_mcp("render", {"id": 1}),
                "error": await client.call_tool_mcp("failing", {"id": 1}),
            }
            return listed, results

    def dump(result):
        return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)

    listed, results = asyncio.run(session(server.Settings(url="http://upstream.invalid/mcp", preset="metabase")))
    check("proxy: read-only tools are listed", {"execute_query", "search"} <= listed)
    check("proxy, metabase preset: execute_sql is listed though not marked read-only", "execute_sql" in listed)
    check("proxy: write tools are hidden by default", "dashboard_write" not in listed)
    check("proxy, metabase preset: tools whose results leave the proxy's reach are hidden", "get_parameter_values" not in listed)
    check("proxy: a hidden tool cannot be called by name", results["write"].is_error and "created" not in dump(results["write"]))
    check("proxy: rows are masked in content and structured content",
          "Hudson Borer" not in dump(results["query"]) and email not in dump(results["query"]) and "NAME#" in dump(results["query"]))
    check("proxy: upstream _meta is dropped", email not in dump(results["search"]))
    check("proxy: a non-text block is withheld", results["image"].is_error and "AA==" not in dump(results["image"]))
    check("proxy: an upstream error is masked", cpf not in dump(results["error"]) and "CPF#" in dump(results["error"]))
    check("proxy: no kind configured, the token reaches upstream as is", seen["sql"].endswith(f"'{cpf_token}'"))

    asyncio.run(session(server.Settings(url="http://upstream.invalid/mcp", preset="metabase", unmask_kinds=frozenset({"CPF"}))))
    check("proxy: a configured kind is unmasked before the call", seen["sql"].endswith(f"'{cpf}'"))

    # What the upstream sends besides the result: logs, progress and sampling requests reach Claude Desktop too.
    async def side_channels():
        heard = []

        async def log_handler(message):
            heard.append(str(message.data))

        async def progress_handler(progress, total, message):
            heard.append(str(message))

        async def sampling_handler(messages, params, context):
            heard.append(json.dumps([m.model_dump(mode="json") for m in messages]))
            return "summary"

        client = Client(server.build(server.Settings(url="http://upstream.invalid/mcp"), upstream=upstream),
                        log_handler=log_handler, progress_handler=progress_handler, sampling_handler=sampling_handler)
        async with client:
            result = await client.call_tool_mcp("chatty", {})
        return dump(result), " ".join(heard)

    result, heard = asyncio.run(side_channels())
    check("proxy: logs, progress and sampling requests carry no personal data", '"done"' in result and cpf not in heard and email not in heard)

    listed, results = asyncio.run(session(server.Settings(url="http://upstream.invalid/mcp", preset="metabase", allow_tools=frozenset({"dashboard_write"}))))
    check("proxy: a write tool can be allowed by name", "dashboard_write" in listed and not results["write"].is_error)
    listed, _ = asyncio.run(session(server.Settings(url="http://upstream.invalid/mcp")))
    check("proxy, no preset: only tools marked read-only", listed == {"execute_query", "get_parameter_values", "search", "render", "failing", "chatty"})

    try:
        server.Settings(url="http://upstream.invalid/mcp", preset="nope")
        check("proxy: an unknown preset is refused", False)
    except ValueError:
        check("proxy: an unknown preset is refused", True)
    import httpx2

    from pii_proxy import auth

    async def headers_on_a_raw_request():
        client = auth.client_factory("http://upstream.invalid/mcp", {"CF-Access-Client-Id": "id-123"})()
        requests = [httpx2.Request("POST", "http://upstream.invalid/oauth/token"), httpx2.Request("POST", "https://login.invalid/token")]
        for request in requests:
            for hook in client.event_hooks["request"]:
                await hook(request)
        await client.aclose()
        return [request.headers.get("CF-Access-Client-Id") for request in requests]

    sent = asyncio.run(headers_on_a_raw_request())
    check("auth: fixed headers reach requests the OAuth flow builds itself", sent[0] == "id-123")
    check("auth: fixed headers never go to another host", sent[1] is None)

    async def headers_after_a_redirect():
        def upstream(request):
            if request.url.host == "upstream.invalid":
                return httpx2.Response(302, headers={"Location": "https://other.invalid/landing"})
            return httpx2.Response(200, json={"seen": request.headers.get("CF-Access-Client-Id")})

        client = auth.client_factory("http://upstream.invalid/mcp", {"CF-Access-Client-Id": "id-123"})(follow_redirects=True)
        client._transport = httpx2.MockTransport(upstream)
        response = await client.get("http://upstream.invalid/mcp")
        await client.aclose()
        return response.json()["seen"]

    check("auth: fixed headers do not follow a redirect to another host", asyncio.run(headers_after_a_redirect()) is None)

    async def called_like_the_transport():
        client = auth.client_factory("http://upstream.invalid/mcp", {})(headers={}, auth=None, follow_redirects=True)
        await client.aclose()
        return client.follow_redirects

    check("auth: the factory takes follow_redirects, as the HTTP transport passes it", asyncio.run(called_like_the_transport()) is True)

    async def default_timeouts():
        client = auth.client_factory("http://upstream.invalid/mcp", {})()
        await client.aclose()
        return client.timeout.connect, client.timeout.read

    check("auth: the client keeps the MCP timeouts (30 s, read 300 s)", asyncio.run(default_timeouts()) == (30.0, 300.0))

    import ast

    imported = [node.module for node in ast.walk(ast.parse(Path(auth.__file__).read_text())) if isinstance(node, ast.ImportFrom) and node.module]
    check("auth: no private SDK module is imported", not [name for name in imported if any(part.startswith("_") for part in name.split("."))])

    async def store_roundtrip():
        store = auth.token_store()
        # Keys and collections as fastmcp's OAuth names them: the server URL, slashes included.
        key = "http://upstream.invalid/mcp/tokens"
        await store.put(key=key, value={"access_token": "secret-access-token-xyz"}, collection="mcp-oauth-token")
        return await store.get(key=key, collection="mcp-oauth-token")

    check("auth: tokens come back from the store", asyncio.run(store_roundtrip()) == {"access_token": "secret-access-token-xyz"})
    on_disk = b"".join(f.read_bytes() for f in (SANDBOX / "data" / "oauth").rglob("*") if f.is_file())
    check("auth: tokens are not stored in clear", on_disk and b"secret-access-token-xyz" not in on_disk)

    settings = server.Settings.from_env({"PII_PROXY_URL": "http://upstream.invalid/mcp", "PII_PROXY_AUTH": "oauth"})
    check("auth: PII_PROXY_AUTH=oauth turns OAuth on", settings.oauth)

    from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

    # An upstream whose token endpoint is not {origin}/token, like Metabase's /oauth/token.
    upstream_mcp = "http://restart.invalid/mcp"
    seen = []

    def oauth_server(request):
        seen.append(request.url.path)
        documents = {
            "/.well-known/oauth-protected-resource/mcp": {"resource": upstream_mcp, "authorization_servers": ["http://restart.invalid"]},
            "/.well-known/oauth-authorization-server": {
                "issuer": "http://restart.invalid",
                "authorization_endpoint": "http://restart.invalid/oauth/authorize",
                "token_endpoint": "http://restart.invalid/oauth/token",
                "response_types_supported": ["code"],
            },
        }
        body = documents.get(request.url.path)
        return httpx2.Response(200, json=body) if body else httpx2.Response(404)

    async def restarted(expired):
        provider = auth.oauth(upstream_mcp, {})
        provider.httpx_client_factory = lambda **kwargs: httpx2.AsyncClient(transport=httpx2.MockTransport(oauth_server), **kwargs)
        await provider.token_storage_adapter.set_tokens(OAuthToken(access_token="a", refresh_token="r", expires_in=3600))
        await provider.token_storage_adapter.set_client_info(OAuthClientInformationFull(client_id="c", redirect_uris=["http://localhost:47213/callback"]))
        if expired:
            await auth.token_store().put(key=f"{upstream_mcp}/token_expiry", collection="mcp-oauth-token-expiry", value={"expires_at": 1.0})
        seen.clear()
        await provider._initialize()
        if not expired:
            return None, list(seen)
        return str((await provider._refresh_token()).url), list(seen)

    endpoint, _ = asyncio.run(restarted(expired=True))
    check("auth: a refresh after a restart goes to the advertised token endpoint", endpoint == "http://restart.invalid/oauth/token")
    _, requests = asyncio.run(restarted(expired=False))
    check("auth: a valid token after a restart costs no discovery request", requests == [])

    # Claude Desktop runs two proxy processes on one store, and Metabase rotates the refresh token:
    # the one a process loaded dies when the other refreshes (400 invalid_grant, measured 30/10).
    async def shared_store(other_wins_the_race):
        provider = auth.oauth(upstream_mcp, {})
        adapter = provider.token_storage_adapter
        await adapter.set_tokens(OAuthToken(access_token="a-old", refresh_token="r-old", expires_in=3600))
        await adapter.set_client_info(OAuthClientInformationFull(client_id="c", redirect_uris=["http://localhost:47213/callback"]))
        await auth.token_store().put(key=f"{upstream_mcp}/token_expiry", collection="mcp-oauth-token-expiry", value={"expires_at": 1.0})
        provider.httpx_client_factory = lambda **kwargs: httpx2.AsyncClient(transport=httpx2.MockTransport(oauth_server), **kwargs)
        await provider._initialize()
        if not other_wins_the_race:
            # Stored by the other copy hours ago: its access token has expired too, so only its refresh token helps.
            await adapter.set_tokens(OAuthToken(access_token="a-new", refresh_token="r-new", expires_in=3600))
            await auth.token_store().put(key=f"{upstream_mcp}/token_expiry", collection="mcp-oauth-token-expiry", value={"expires_at": 1.0})
        sent = []

        async def upstream(request):
            sent.append(request.url.path)
            if request.url.path == "/oauth/token":
                if b"refresh_token=r-new" in request.content:
                    return httpx2.Response(200, json={"access_token": "a-newer", "refresh_token": "r-newer", "expires_in": 3600, "token_type": "Bearer"})
                if other_wins_the_race:
                    await adapter.set_tokens(OAuthToken(access_token="a-new", refresh_token="r-new", expires_in=3600))
                return httpx2.Response(400, json={"error": "invalid_grant"})
            if request.url.path == "/mcp":
                valid = request.headers.get("Authorization") == ("Bearer a-new" if other_wins_the_race else "Bearer a-newer")
                return httpx2.Response(200 if valid else 401)
            return oauth_server(request)

        async def no_browser(url):
            sent.append("browser")
            raise RuntimeError("the user would be asked to sign in again")

        provider.redirect_handler = no_browser
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(upstream), auth=provider) as client:
            try:
                status = (await client.post(upstream_mcp)).status_code
            except RuntimeError:
                status = None
        return status, sent

    # A copy that starts with a valid token and outlives it: the Desktop keeps the proxy running for hours.
    async def outlived():
        provider = auth.oauth(upstream_mcp, {})
        provider.httpx_client_factory = lambda **kwargs: httpx2.AsyncClient(transport=httpx2.MockTransport(oauth_server), **kwargs)
        await provider.token_storage_adapter.set_tokens(OAuthToken(access_token="a", refresh_token="r", expires_in=3600))
        await provider.token_storage_adapter.set_client_info(OAuthClientInformationFull(client_id="c", redirect_uris=["http://localhost:47213/callback"]))
        await provider._initialize()
        provider.context.token_expiry_time = 1.0
        refreshed_at = []

        async def upstream(request):
            if request.url.path in ("/token", "/oauth/token"):
                refreshed_at.append(request.url.path)
                if request.url.path == "/token":
                    return httpx2.Response(200)  # what Metabase answers there: an empty body
                return httpx2.Response(200, json={"access_token": "a2", "refresh_token": "r2", "expires_in": 3600, "token_type": "Bearer"})
            if request.url.path == "/mcp":
                return httpx2.Response(200 if request.headers.get("Authorization") == "Bearer a2" else 401)
            return oauth_server(request)

        async def no_browser(url):
            raise RuntimeError("the user would be asked to sign in again")

        provider.redirect_handler = no_browser
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(upstream), auth=provider) as client:
            try:
                status = (await client.post(upstream_mcp)).status_code
            except RuntimeError:
                status = None
        return status, refreshed_at

    check("auth: a token that expires while the proxy runs is refreshed at the advertised endpoint", asyncio.run(outlived()) == (200, ["/oauth/token"]))

    status, sent = asyncio.run(shared_store(other_wins_the_race=False))
    check("auth: a refresh uses the refresh token another process stored", status == 200 and "browser" not in sent)
    status, sent = asyncio.run(shared_store(other_wins_the_race=True))
    check("auth: a refresh lost to another process takes its tokens, no new sign-in", status == 200 and "browser" not in sent)

else:
    print("skip proxy tests: fastmcp missing (desktop/.venv/bin/python tests/test_desktop.py runs them)")

import keyring  # noqa: E402

for name in ("hmac", "vault", "oauth"):
    try:
        keyring.delete_password("pii-tokens-desktop-test", name)
    except keyring.errors.PasswordDeleteError:
        pass
shutil.rmtree(SANDBOX, ignore_errors=True)

print("failures:", failures)
sys.exit(1 if failures else 0)
