"""Google credential management for Gemini API access via Vertex AI."""

import json
import logging
import sys
from pathlib import Path

import httpx

logger = logging.getLogger("visual-engine")

CONFIG_DIR = Path.home() / ".config" / "visual-engine"
GOOGLE_TOKEN_FILE = CONFIG_DIR / "google_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
]

GOOGLE_CLIENT_ID = "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET = "d-FL95Q19q7MQmFpd7hHD0Ty"


def _load_google_credentials():
    """Load and refresh Google OAuth credentials from stored tokens."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not GOOGLE_TOKEN_FILE.exists():
        raise RuntimeError(
            "Not authenticated with Google. "
            "Connect to the MCP server from Claude Code to authenticate."
        )

    token_data = json.loads(GOOGLE_TOKEN_FILE.read_text())
    creds = Credentials(
        token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_data["access_token"] = creds.token
        GOOGLE_TOKEN_FILE.write_text(json.dumps(token_data))

    return creds


def _find_gcp_project(creds):
    """Find a GCP project with Vertex AI enabled, cache the result."""
    token_data = json.loads(GOOGLE_TOKEN_FILE.read_text())
    cached = token_data.get("gcp_project")
    if cached:
        return cached

    resp = httpx.get(
        "https://cloudresourcemanager.googleapis.com/v1/projects",
        headers={"Authorization": f"Bearer {creds.token}"},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to list GCP projects: {resp.text}")

    projects = resp.json().get("projects", [])
    active = [p["projectId"] for p in projects if p.get("lifecycleState") == "ACTIVE"]
    if not active:
        raise RuntimeError("No active GCP projects found.")

    from google import genai

    for project_id in active:
        try:
            client = genai.Client(
                vertexai=True,
                credentials=creds,
                project=project_id,
                location="us-central1",
            )
            client.models.generate_content(
                model="gemini-2.5-flash",
                contents="test",
            )
            # Cache the working project
            token_data["gcp_project"] = project_id
            GOOGLE_TOKEN_FILE.write_text(json.dumps(token_data))
            logger.info(f"Using GCP project: {project_id}")
            return project_id
        except Exception:
            continue

    raise RuntimeError(
        "No GCP project with Vertex AI API enabled. "
        "Enable it at https://console.cloud.google.com/apis/api/aiplatform.googleapis.com"
    )


def get_client():
    """Get a Gemini client using stored Google OAuth credentials via Vertex AI."""
    from google import genai

    creds = _load_google_credentials()
    project = _find_gcp_project(creds)
    return genai.Client(
        vertexai=True,
        credentials=creds,
        project=project,
        location="us-central1",
    )


def setup_auth():
    """Manual auth setup via CLI (fallback for troubleshooting)."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    print("Visual Engine - Logging in with Google...")
    print()

    client_config = {
        "installed": {
            "client_id": "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com",
            "client_secret": "d-FL95Q19q7MQmFpd7hHD0Ty",
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    token_data = {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
    }
    GOOGLE_TOKEN_FILE.write_text(json.dumps(token_data))
    GOOGLE_TOKEN_FILE.chmod(0o600)

    if creds and creds.valid:
        print("Login successful! visual-engine is ready to use.")
    else:
        print("Authentication failed.")
        sys.exit(1)
