"""OAuth provider that proxies Google OAuth for MCP authentication."""

import json
import logging
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthToken,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull

logger = logging.getLogger("visual-engine")

CONFIG_DIR = Path.home() / ".config" / "visual-engine"
GOOGLE_TOKEN_FILE = CONFIG_DIR / "google_token.json"
MCP_STATE_DIR = CONFIG_DIR / "state"

# Google Cloud SDK's public OAuth client credentials (same as gcloud CLI)
GOOGLE_CLIENT_ID = (
    "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com"
)
GOOGLE_CLIENT_SECRET = "d-FL95Q19q7MQmFpd7hHD0Ty"

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
]


def _ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    MCP_STATE_DIR.mkdir(parents=True, exist_ok=True)


class GoogleOAuthProvider:
    """MCP OAuth provider that proxies to Google for Gemini API access."""

    def __init__(self, server_port: int):
        self._server_port = server_port
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}
        # Maps google_state -> (mcp_params, client) for the OAuth proxy flow
        self._pending_auth: dict[str, tuple[AuthorizationParams, OAuthClientInformationFull]] = {}
        _ensure_dirs()

    @property
    def google_callback_url(self) -> str:
        return f"http://localhost:{self._server_port}/google/callback"

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if client_info.client_id:
            self._clients[client_info.client_id] = client_info

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        # Save MCP client's params so we can complete the flow after Google auth
        google_state = secrets.token_urlsafe(32)
        self._pending_auth[google_state] = (params, client)

        # Build Google OAuth URL
        google_params = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": self.google_callback_url,
            "response_type": "code",
            "scope": " ".join(GOOGLE_SCOPES),
            "state": google_state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{GOOGLE_AUTH_URI}?{urlencode(google_params)}"

    def get_pending_auth(self, google_state: str):
        """Get and remove pending auth params for a Google OAuth state."""
        return self._pending_auth.pop(google_state, None)

    def save_google_tokens(self, token_data: dict):
        """Save Google OAuth tokens to disk."""
        _ensure_dirs()
        GOOGLE_TOKEN_FILE.write_text(json.dumps(token_data))
        GOOGLE_TOKEN_FILE.chmod(0o600)

    def store_auth_code(self, code: AuthorizationCode):
        """Store an MCP authorization code for later exchange."""
        self._auth_codes[code.code] = code

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        return self._auth_codes.get(authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        # Remove used auth code
        self._auth_codes.pop(authorization_code.code, None)

        # Generate MCP access + refresh tokens
        access_token_str = secrets.token_urlsafe(32)
        refresh_token_str = secrets.token_urlsafe(32)
        expires_in = 3600 * 24 * 365  # 1 year for local server

        access_token = AccessToken(
            token=access_token_str,
            client_id=client.client_id or "",
            scopes=authorization_code.scopes,
            expires_at=int(time.time()) + expires_in,
        )
        refresh_token = RefreshToken(
            token=refresh_token_str,
            client_id=client.client_id or "",
            scopes=authorization_code.scopes,
        )
        self._access_tokens[access_token_str] = access_token
        self._refresh_tokens[refresh_token_str] = refresh_token

        return OAuthToken(
            access_token=access_token_str,
            token_type="Bearer",
            expires_in=expires_in,
            refresh_token=refresh_token_str,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        return self._refresh_tokens.get(refresh_token)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # Remove old refresh token
        self._refresh_tokens.pop(refresh_token.token, None)

        # Generate new tokens
        access_token_str = secrets.token_urlsafe(32)
        new_refresh_str = secrets.token_urlsafe(32)
        expires_in = 3600 * 24 * 365

        access_token = AccessToken(
            token=access_token_str,
            client_id=client.client_id or "",
            scopes=scopes or refresh_token.scopes,
            expires_at=int(time.time()) + expires_in,
        )
        new_refresh = RefreshToken(
            token=new_refresh_str,
            client_id=client.client_id or "",
            scopes=scopes or refresh_token.scopes,
        )
        self._access_tokens[access_token_str] = access_token
        self._refresh_tokens[new_refresh_str] = new_refresh

        return OAuthToken(
            access_token=access_token_str,
            token_type="Bearer",
            expires_in=expires_in,
            refresh_token=new_refresh_str,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        access_token = self._access_tokens.get(token)
        if access_token and access_token.expires_at and access_token.expires_at < time.time():
            self._access_tokens.pop(token, None)
            return None
        return access_token

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, AccessToken):
            self._access_tokens.pop(token.token, None)
        elif isinstance(token, RefreshToken):
            self._refresh_tokens.pop(token.token, None)
