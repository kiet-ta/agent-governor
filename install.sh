#!/bin/bash
set -e

echo "Starting Heimdall CLI installation..."

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 could not be found."
    exit 1
fi

if ! command -v pip3 &> /dev/null; then
    echo "Error: pip3 could not be found."
    exit 1
fi

# 2. Install Project
echo "Installing heimdall-cli..."
# Try to install to user site to avoid permission issues and break-system-packages errors
pip3 install . --user --break-system-packages 2>/dev/null || pip3 install . --user

# 3. Setup Config (optional, if first time)
CONFIG_DIR="$HOME/.config/heimdall"
CONFIG_FILE="$CONFIG_DIR/config.json"

if [ ! -d "$CONFIG_DIR" ]; then
    echo "Creating config directory at $CONFIG_DIR..."
    mkdir -p "$CONFIG_DIR"
fi

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Creating empty config file..."
    echo '{}' > "$CONFIG_FILE"
    echo "Please update $CONFIG_FILE with your Discord Token and Channel ID."
fi

echo "Installation complete!"
echo "Make sure your user binary directory (usually ~/.local/bin) is in your PATH."
echo "Heimdall is ready to use. Type 'heimdall --help' to start."
