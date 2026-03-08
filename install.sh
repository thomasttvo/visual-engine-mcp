#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
PLIST_SRC="$SCRIPT_DIR/com.visual-engine.mcp.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.visual-engine.mcp.plist"
LABEL="com.visual-engine.mcp"

echo "=== Visual Engine MCP Server Setup ==="
echo

# Create venv if needed
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Install package
echo "Installing visual-engine..."
"$VENV_DIR/bin/pip" install -q -e "$SCRIPT_DIR"

# Stop existing service if loaded
if launchctl list "$LABEL" 2>/dev/null | grep -q "PID"; then
    echo "Stopping existing service..."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
fi

# Generate plist with correct paths
echo "Installing launchd service..."
sed "s|__VENV_BIN__|$VENV_DIR/bin|g" "$PLIST_SRC" > "$PLIST_DST"

# Load service
launchctl load "$PLIST_DST"
echo

# Verify
sleep 2
if launchctl list "$LABEL" 2>/dev/null | grep -q "PID"; then
    echo "✓ Service running"
else
    echo "✗ Service failed to start. Check /tmp/visual-engine-mcp.log"
    exit 1
fi

# Register with Claude Code
echo "Registering MCP server with Claude Code..."
claude mcp add --transport http visual-engine http://localhost:9876/mcp 2>/dev/null || true

echo
echo "=== Setup complete ==="
echo "  Server: http://localhost:9876/mcp"
echo "  Logs:   /tmp/visual-engine-mcp.log"
echo "  Stop:   launchctl unload $PLIST_DST"
echo "  Start:  launchctl load $PLIST_DST"
