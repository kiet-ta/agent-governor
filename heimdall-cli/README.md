# Heimdall CLI (Blocking Discord Middleware)

Heimdall is a "Human-in-the-Loop" middleware tool that blocks execution until a user confirms an action via Discord. It acts as a safety gate for autonomous agents.

## Installation

### Prerequisites
- Python 3.8+
- Discord Bot Token

### Install from Source
```bash
pip install .
```

### Development Setup
```bash
pip install -e .
```

## Configuration
The tool uses `~/.config/heimdall/config.json`.
Run the tool once to generate a template, then edit it with your Discord Bot Token and Channel ID.

## Usage
Calling from CLI:
```bash
heimdall "Should I delete the production database?"
```

Process will wait until you reply on Discord.

### Output on success:
```
USER_CONFIRMED: Yes, go ahead.
```
