import json
import secrets
import sys
import time
import logging

import httpx
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mcp.server.auth.provider import AuthorizationCode, construct_redirect_uri
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP

from .oauth_provider import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_TOKEN_URI,
    GoogleOAuthProvider,
)

logger = logging.getLogger("visual-engine")

SERVER_PORT = 9876

SERVER_INSTRUCTIONS = """visual-engine provides AI-powered image analysis using Google Gemini's vision model.

TOOL: analyze_images
- Takes one or more local image file paths + a text prompt
- Sends images to Gemini for visual analysis, returns text response
- Supports JPEG, PNG, WebP, GIF, BMP

COMMON USE CASES:
1. Visual QA: "Does this UI look correct? Are there any alignment issues?"
2. Figma comparison: Pass a device screenshot AND a Figma export, ask to compare spacing, colors, alignment, missing elements
3. Bug detection: "Is there anything visually wrong with this screenshot?"
4. Layout check: "Are these elements properly centered and aligned?"

TIPS:
- For comparisons, pass BOTH images in a single call (not separate calls)
- Be specific about what to check: "compare padding", "check font sizes", "verify colors match"
- The model handles subtle differences well — ask about specific areas if needed
- Default model is gemini-2.5-pro; override with model param for speed (gemini-2.5-flash) or quality (gemini-2.5-pro)"""

provider = GoogleOAuthProvider(server_port=SERVER_PORT)

mcp = FastMCP(
    "visual-engine",
    instructions=SERVER_INSTRUCTIONS,
    host="127.0.0.1",
    port=SERVER_PORT,
    auth_server_provider=provider,
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(f"http://localhost:{SERVER_PORT}"),
        resource_server_url=AnyHttpUrl(f"http://localhost:{SERVER_PORT}"),
        client_registration_options=ClientRegistrationOptions(enabled=True),
    ),
)


@mcp.custom_route("/google/callback", methods=["GET"])
async def google_callback(request: Request) -> Response:
    """Handle Google OAuth redirect after user authenticates."""
    google_code = request.query_params.get("code")
    google_state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        return Response(
            content=f"Google authentication failed: {error}",
            status_code=400,
        )

    if not google_code or not google_state:
        return Response(
            content="Missing code or state parameter",
            status_code=400,
        )

    # Look up the original MCP auth request
    pending = provider.get_pending_auth(google_state)
    if not pending:
        return Response(
            content="Invalid or expired state. Please try authenticating again.",
            status_code=400,
        )

    mcp_params, mcp_client = pending

    # Exchange Google's code for tokens
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            GOOGLE_TOKEN_URI,
            data={
                "code": google_code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": provider.google_callback_url,
                "grant_type": "authorization_code",
            },
        )

    if token_response.status_code != 200:
        return Response(
            content=f"Failed to exchange Google token: {token_response.text}",
            status_code=500,
        )

    google_tokens = token_response.json()
    provider.save_google_tokens(google_tokens)

    # Generate MCP authorization code for Claude Code
    mcp_auth_code = secrets.token_urlsafe(32)
    auth_code = AuthorizationCode(
        code=mcp_auth_code,
        scopes=mcp_params.scopes or [],
        expires_at=time.time() + 300,
        client_id=mcp_client.client_id or "",
        code_challenge=mcp_params.code_challenge,
        redirect_uri=mcp_params.redirect_uri,
        redirect_uri_provided_explicitly=mcp_params.redirect_uri_provided_explicitly,
    )
    provider.store_auth_code(auth_code)

    # Redirect back to Claude Code with the MCP auth code
    redirect_url = construct_redirect_uri(
        str(mcp_params.redirect_uri),
        code=mcp_auth_code,
        state=mcp_params.state,
    )
    return RedirectResponse(url=redirect_url)


@mcp.tool()
async def analyze_images(
    images: list[str],
    prompt: str,
    model: str = "gemini-2.5-pro",
) -> str:
    """Analyze one or more images using Gemini's vision capabilities.

    Args:
        images: List of absolute file paths to images
        prompt: Question or instruction about the images
        model: Gemini model to use (default: gemini-2.5-pro)
    """
    from .vision import analyze

    return await analyze(images, prompt, model)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        from .auth import setup_auth

        setup_auth()
        return

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
