# Heimdall CLI (Blocking Discord Middleware)

Heimdall is a "Human-in-the-Loop" middleware tool that blocks execution until a user confirms an action via Discord. It acts as a safety gate for autonomous agents.

## Architecture

Instead of polling the Discord REST API, Heimdall connects to the **Discord Gateway via WebSocket** (using `discord.py`). This eliminates polling delays and HTTP 429 rate-limit errors.

Each project gets its own **Discord Thread** for clean, multi-project routing:

```
CLI call (heimdall "Deploy?")
  → ConfigManager loads config + looks up project's thread_id
  → HeimdallBot connects to Discord Gateway (WebSocket)
  → Resolves or creates a Thread for the project
  → Posts an embed to the Thread
  → wait_for("message") listens for the first human reply (event-driven)
  → Prints "USER_CONFIRMED: <reply>" to stdout, disconnects
  → ConfigManager saves the new thread_id if first run for this project
```

## Installation

### Prerequisites
- Python 3.8+
- Discord Bot Token with **Message Content Intent** enabled (Discord Developer Portal → Bot → Privileged Gateway Intents)
- Bot permissions: `Send Messages`, `Read Messages/View Channels`, `Create Public Threads`, `Add Reactions`

### Install from Source
```bash
pip install .
```

### Development Setup
```bash
pip install -e .
```

## Configuration

Config file: `~/.config/heimdall/config.json`

Run `heimdall "Init"` once to auto-generate the template, then fill in your credentials:

```json
{
    "discord_token": "YOUR_BOT_TOKEN_HERE",
    "channel_id": "YOUR_PARENT_CHANNEL_ID",
    "project_threads": {}
}
```

`project_threads` is managed automatically — Heimdall writes project→thread mappings here after each first run per project.

## Usage

```bash
# Basic usage (project name = current directory name)
heimdall "Should I deploy to production?"

# Explicit project name (useful in CI or scripts)
heimdall --project my-api "Migrate the production database?"

# Custom timeout in seconds (default: 3600 / 1 hour)
heimdall --timeout 300 "Quick approval needed?"
```

### Output on success:
```
USER_CONFIRMED: Yes, go ahead.
```

### In a Bash Script

```bash
#!/bin/bash
RESPONSE=$(heimdall --project my-app "Build complete. Deploy to production?")

if [[ "$RESPONSE" == *"Yes"* ]] || [[ "$RESPONSE" == *"yes"* ]]; then
    echo "Deploying..."
else
    echo "Deployment cancelled."
    exit 1
fi
```

### In Python (subprocess)

```python
import subprocess

result = subprocess.check_output(
    ["heimdall", "--project", "my-app", "Delete old backups?"], text=True
)
answer = result.strip().replace("USER_CONFIRMED: ", "")
```
