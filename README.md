# visual-engine-mcp

MCP server for AI-powered image analysis using Google Gemini via Vertex AI.

Analyze screenshots, compare UI layouts against Figma designs, detect visual bugs, and check alignment — all from within Claude Code.

## Setup

```bash
./install.sh
```

This handles everything:
- Creates a Python venv and installs dependencies
- Installs a macOS launchd service (auto-start on boot, auto-restart on crash)
- Registers the MCP server with Claude Code

On first use from Claude Code, click **Authenticate** to sign in with Google via the browser. No API keys or env vars needed.

## Usage

The server exposes one tool: `analyze_images`

```
mcp__visual-engine__analyze_images
  images: ["/path/to/screenshot.png", "/path/to/figma-export.png"]
  prompt: "Compare these two images for alignment differences"
  model: "gemini-2.5-pro"  # optional, default
```

### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `images` | Yes | List of absolute file paths (JPEG, PNG, WebP, GIF, BMP) |
| `prompt` | Yes | Question or instruction about the images |
| `model` | No | `gemini-2.5-pro` (default) or `gemini-2.5-flash` (faster) |

### Tips

- Pass **both** images in a single call for comparisons
- Be specific: "compare padding between header and content" > "compare these"
- Use `gemini-2.5-flash` for speed, `gemini-2.5-pro` for accuracy

## Service Management

```bash
# Logs
cat /tmp/visual-engine-mcp.log

# Stop
launchctl unload ~/Library/LaunchAgents/com.visual-engine.mcp.plist

# Start
launchctl load ~/Library/LaunchAgents/com.visual-engine.mcp.plist
```

## How It Works

- Runs as an HTTP MCP server on `http://localhost:9876/mcp`
- Authenticates with Google via OAuth (MCP OAuth protocol — browser-based, no API keys)
- Calls Gemini via Vertex AI using the authenticated Google credentials
- Auto-discovers a GCP project with Vertex AI enabled and caches it

## Requirements

- Python 3.10+
- macOS (uses launchd for service management)
- A Google account with access to a GCP project that has Vertex AI API enabled
