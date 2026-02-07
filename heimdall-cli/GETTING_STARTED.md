# Getting Started with Heimdall CLI 🚀

Heimdall acts as a "Human-in-the-Loop" gateway, pausing critical operations until you approve them via Discord. This guide will walk you through setting it up.

## Prerequisites

Before starting, you need a **Discord Bot Token** and a **Channel ID**.

### 1. Create a Discord Bot
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** → Name it "Heimdall" (or whatever you like).
3. Go to the **Bot** tab → Click **Add Bot**.
4. copy the **Token**. Keep this secret! 🔑
5. Under **Privileged Gateway Intents**, enable **Message Content Intent**.

### 2. Add Bot to a Server
1. Go to **OAuth2** → **URL Generator**.
2. Select scopes: `bot`.
3. Select permissions: `Send Messages`, `Read Messages/View Channels`, `Add Reactions`.
4. Copy the generated URL and open it to invite the bot to your server.

### 3. Get Channel ID
1. In Discord, go to **User Settings** → **Advanced** → Enable **Developer Mode**.
2. Right-click the channel where you want Heimdall to ask for permission.
3. Click **Copy Channel ID**.

---

## Installation

### From Source
Navigate to the project directory and install:

```bash
pip install .
```

### For Development
If you want to modify the code:

```bash
pip install -e .
```

---

## Configuration

Run `heimdall` for the first time to generate the configuration file:

```bash
heimdall "Init"
```

It will fail and tell you where the config file is located (usually `~/.config/heimdall/config.json` or `%USERPROFILE%\.config\heimdall\config.json` on Windows).

Open that file and paste your credentials:

```json
{
  "discord_token": "YOUR_COPIED_BOT_TOKEN",
  "channel_id": "YOUR_COPIED_CHANNEL_ID"
}
```

---

## Usage Examples

### Basic Usage
Ask a simple Yes/No question:

```bash
heimdall "Should I deploy to production?"
```
The terminal will pause. Go to Discord and reply to the bot's message.
- If you reply "Yes", the command exits successfully and prints "Yes".
- If you reply "No", the command exits successfully and prints "No".

### In a Bash Script
Heimdall is designed to guard critical steps in scripts.

```bash
#!/bin/bash

echo "Building project..."
# build steps...

# Ask for confirmation before deploy
RESPONSE=$(heimdall "Build complete. Deploy to production?")

if [[ "$RESPONSE" == *"Yes"* || "$RESPONSE" == *"yes"* ]]; then
    echo "Deploying..."
    # deploy steps...
else
    echo "Deployment cancelled."
    exit 1
fi
```

### In a Python Script
You can also use it as a library or via `subprocess`.

```python
import subprocess
import sys

def ask_heimdall(question):
    try:
        result = subprocess.check_output(["heimdall", question], text=True)
        return result.strip().replace("USER_CONFIRMED: ", "")
    except subprocess.CalledProcessError:
        return "Error"

answer = ask_heimdall("Delete old backups?")
if answer.lower() in ["yes", "y"]:
    print("Deleting backups...")
else:
    print("Skipped.")
```
