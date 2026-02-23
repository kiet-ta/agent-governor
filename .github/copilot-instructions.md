# Heimdall CLI — Copilot Instructions

## Project Overview

Heimdall is a **Human-in-the-Loop blocking CLI gateway** that pauses autonomous agent/script execution until a human confirms via Discord. It sends a Discord embed to a per-project thread, listens for a reply over the **Discord WebSocket Gateway** (no polling), then prints the result to stdout for the calling process to consume.

## Architecture

```
src/heimdall/
├── cli.py            # Thin orchestrator: arg parsing + wiring only (canonical entry point)
├── config.py         # ConfigManager: all file I/O, config validation, thread-id persistence
├── discord_client.py # HeimdallBot(discord.Client): all Discord communication
└── __init__.py
src/main.py           # DEPRECATED legacy copy — do not edit
```

**SOLID module boundaries** (do not cross them):
- `ConfigManager` — only reads/writes `~/.config/heimdall/config.json`. No Discord imports.
- `HeimdallBot` — only talks to Discord. No file I/O or `sys.exit()` calls.
- `cli.py` — only parses args, calls the above two, and routes the result to stdout.

Installed command (`pyproject.toml`): `heimdall = "heimdall.cli:main"`. Always update `cli.py`.

## Key Data Flow

```
CLI arg → ConfigManager.load() → get_thread_id(project)
  → HeimdallBot.start(token)          ← asyncio.run() blocks here
      → on_ready() → _resolve_thread() → _send_embed() → wait_for("message")
      → reply received → _acknowledge_reply() → close()
  → asyncio.run() returns
  → save_thread_id() if new thread
  → print("USER_CONFIRMED: <reply>") to stdout
```

**Stdout contract**: callers parse the `USER_CONFIRMED: <reply>` prefix. All logs go to **stderr** via `logger`.

## Event-Driven vs Polling

The previous implementation used a `while True` REST polling loop with `requests`. The current implementation uses **`discord.py` WebSockets**:

```python
# discord_client.py — the event-driven pattern
reply = await self.wait_for("message", check=is_valid_reply, timeout=self._timeout)
```

`wait_for` raises `asyncio.TimeoutError` after `timeout` seconds (default 3600s = 1 hour). Never add polling loops.

## Multi-Project Thread Routing

Config schema (new field `project_threads`):
```json
{
  "discord_token": "...",
  "channel_id": "...",
  "project_threads": {
    "my-api": "1234567890123456789",
    "infra-tools": "9876543210987654321"
  }
}
```

Thread resolution priority in `_resolve_thread()`:
1. Fetch saved thread by ID → reuse (unarchive if needed via `thread.edit(archived=False)`)
2. Fall back to `_create_thread()` which sends a starter message then calls `starter_msg.create_thread()`
3. `is_new_thread = True` → CLI saves mapping via `config_manager.save_thread_id()`

## Development Setup

```bash
pip install -e .                              # editable install
heimdall "test question"                      # requires valid config
heimdall --project my-project "Deploy?"       # explicit project name
heimdall --timeout 120 "Quick check?"         # custom timeout
```

Config auto-created at `~/.config/heimdall/config.json` on first run. Bot requires **Message Content Intent** (privileged) enabled in Discord Developer Portal.

## Conventions

- **Python ≥ 3.8** — no walrus operators, no 3.10+ match statements
- **Type hints required** on all function signatures (`mypy` with `disallow_untyped_defs = true`)
- **Ruff** for linting, line length 100
- **Logging**: use `logger.info/warning/error/debug` (→ stderr). Only `print(f"USER_CONFIRMED: ...")` goes to stdout
- **Exit codes**: `1` on error, `130` on `KeyboardInterrupt`
- **`react_to_message` / `_acknowledge_reply`**: always fire-and-forget — catch `discord.DiscordException`, never raise
- **Config errors are fatal**: `ConfigManager.load()` always calls `sys.exit(1)` on invalid config — never return partial state
- Store Discord snowflake IDs as `str` in JSON, cast to `int` when passing to discord.py APIs
