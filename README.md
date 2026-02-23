# Heimdall CLI (Blocking Discord Middleware)

Heimdall is a "Human-in-the-Loop" middleware tool that blocks execution until a user confirms an action via Discord. It acts as a safety gate for autonomous agents.

It operates in two modes:
- **Ask** — One-shot blocking confirmation. Blocks a script until you reply on Discord.
- **Daemon** — Persistent C2 server. Listens 24/7 for `!prompt` commands and drops task files into `.agent_inbox/` for your IDE agent.

## Architecture

Heimdall connects to the **Discord Gateway via WebSocket** (using `discord.py`) — no polling.

Each project gets its own **Discord Thread** for clean multi-project routing:

```
# Ask mode
heimdall "Deploy?"
  → ConfigManager loads config + looks up project's thread_id
  → HeimdallBot connects (WebSocket), posts embed, wait_for(reply)
  → Prints "USER_CONFIRMED: <reply>" to stdout, disconnects

# Daemon mode
heimdall daemon
  → HeimdallDaemon connects (WebSocket), stays online forever
  → on_message: filters !prompt commands in the project thread
  → InboxWriter writes .agent_inbox/task_<timestamp>.md
  → Bot reacts 👀 → writes file → reacts ✅
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

### Mode 1: Ask (One-shot Blocking Confirmation)

```bash
# Shorthand — project name = current directory
heimdall "Should I deploy to production?"

# Explicit subcommand
heimdall ask "Should I deploy to production?"

# Custom project name and timeout
heimdall ask --project my-api --timeout 300 "Migrate the production database?"
```

**Output on success:**
```
USER_CONFIRMED: Yes, go ahead.
```

### Mode 2: Daemon (Persistent C2 Server)

```bash
# Start daemon in your project directory
cd /path/to/your/project
heimdall daemon

# With explicit project name
heimdall daemon --project my-api
```

From Discord, type in the project thread:
```
!prompt write a README for this project
!prompt add unit tests for the auth module
```

Task files appear in `.agent_inbox/task_<timestamp>.md`. Add `.agent_inbox/` to `.gitignore`.

### In a Bash Script

```bash
#!/bin/bash
RESPONSE=$(heimdall ask --project my-app "Build complete. Deploy to production?")

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
    ["heimdall", "ask", "--project", "my-app", "Delete old backups?"], text=True
)
answer = result.strip().replace("USER_CONFIRMED: ", "")
```
