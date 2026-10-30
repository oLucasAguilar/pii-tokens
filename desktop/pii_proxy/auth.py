"""Upstream authentication: OAuth with the tokens kept encrypted on disk, and fixed headers on every request.

The fixed headers are for an auth proxy in front of the upstream (Cloudflare Access service tokens, a
gateway key). The OAuth flow builds its own requests (discovery, registration, token, refresh), which skip
the client's default headers, so a request hook adds them instead.
"""


import httpx2
from fastmcp.client.auth import OAuth
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp.client.auth.exceptions import OAuthFlowError
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    create_oauth_metadata_request,
    credentials_match_issuer,
    handle_auth_metadata_response,
    handle_protected_resource_response,
    validate_metadata_issuer,
)

from .masking import pii

# The MCP transports' defaults: a server may hold a response stream open for minutes.
DEFAULT_TIMEOUT = httpx2.Timeout(30.0, read=300.0)

# A fixed port keeps the redirect URI the client registered valid across restarts.
DEFAULT_CALLBACK_PORT = 47213


def client_factory(fixed_headers: dict):
    async def add_headers(request):
        request.headers.update(fixed_headers)

    def factory(headers=None, timeout=None, auth=None, follow_redirects=False):
        return httpx2.AsyncClient(
            headers=headers,
            timeout=timeout or DEFAULT_TIMEOUT,
            auth=auth,
            follow_redirects=follow_redirects,
            event_hooks={"request": [add_headers]},
        )

    return factory


def token_store():
    """OAuth tokens on disk, encrypted with a key from the system keyring.

    The keyring alone would not do: Windows Credential Manager refuses values over 2560 bytes.
    """
    import keyring
    from cryptography.fernet import Fernet

    key = keyring.get_password(pii.KEYRING_SERVICE, "oauth")
    if not key:
        key = Fernet.generate_key().decode()
        keyring.set_password(pii.KEYRING_SERVICE, "oauth", key)
    directory = pii.DATA_DIR / "oauth"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    # The OAuth keys are URLs; unsanitized, their slashes would become directories.
    store = FileTreeStore(
        data_directory=directory,
        key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(directory),
        collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(directory),
    )
    return FernetEncryptionWrapper(store, fernet=Fernet(key.encode()))


async def authorization_server_metadata(client_factory, server_url: str, client_info):
    """The token endpoint and the rest of the authorization server's metadata, discovered as the SDK does.

    None when the upstream does not advertise its authorization server, or the stored client was
    registered with another one: the SDK's own flow then takes over, as before.
    """
    async with client_factory() as client:
        for url in build_protected_resource_metadata_discovery_urls(None, server_url):
            resource = await handle_protected_resource_response(await client.send(create_oauth_metadata_request(url)))
            if resource:
                break
        else:
            return None
        issuer = str(resource.authorization_servers[0])
        if client_info is not None and not credentials_match_issuer(client_info, issuer, None):
            return None
        for url in build_oauth_authorization_server_metadata_discovery_urls(issuer, server_url):
            found, metadata = await handle_auth_metadata_response(await client.send(create_oauth_metadata_request(url)))
            if not found:
                return None
            if metadata:
                validate_metadata_issuer(metadata, issuer)
                return metadata
    return None


class RefreshSafeOAuth(OAuth):
    """OAuth whose refresh works with tokens loaded from the store, and with a second copy of the proxy.

    Every failed refresh sends the user to sign in again in the browser. Two ways it failed:
    - The SDK learns the authorization server's metadata only while signing in. With tokens loaded
      from the store it refreshes at {origin}/token, where a server may answer an empty 200.
    - Claude Desktop runs two copies of the proxy on one store. The SDK reads the store once, and
      a server may rotate the refresh token: when one copy refreshes, the other's dies.
    """

    async def _refresh_token(self):
        context = self.context
        stored = await context.storage.get_tokens()
        if stored is not None and stored.refresh_token:
            context.current_tokens = stored
        if context.oauth_metadata is None:
            try:
                context.oauth_metadata = await authorization_server_metadata(
                    self.httpx_client_factory, context.server_url, context.client_info
                )
            except (httpx2.HTTPError, OAuthFlowError):
                pass  # the SDK's flow re-authorizes, as without this class
        return await super()._refresh_token()

    async def _handle_refresh_response(self, response):
        used = self.context.current_tokens
        if await super()._handle_refresh_response(response):
            return True
        # Lost a race: the other copy refreshed with the same token a moment earlier.
        stored = await self.context.storage.get_tokens()
        if stored is None or used is None or stored.refresh_token == used.refresh_token:
            return False
        self.context.current_tokens = stored
        self.context.token_expiry_time = await self.token_storage_adapter.get_token_expiry()
        return self.context.is_token_valid()


def oauth(url: str, fixed_headers: dict, callback_port: int = 0) -> OAuth:
    return RefreshSafeOAuth(
        mcp_url=url,
        client_name="pii-tokens",
        token_storage=token_store(),
        callback_port=callback_port or DEFAULT_CALLBACK_PORT,
        httpx_client_factory=client_factory(fixed_headers),
    )
