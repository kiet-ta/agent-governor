# Heimdall CLI — Copilot Instructions

## Project Overview

Heimdall is a **Human-in-the-Loop blocking CLI gateway** (ask mode) and a **Persistent C2 Daemon** (daemon mode). Ask mode pauses script execution until a human confirms via Discord. Daemon mode stays connected 24/7, receives `!prompt` commands, and drops task files into `.agent_inbox/` for a local IDE agent to process.

## Architecture

```
src/heimdall/
├── cli.py            # Thin orchestrator: arg parsing + subcommand routing only
├── config.py         # ConfigManager: all file I/O, config validation, thread-id persistence
├── discord_client.py # HeimdallBot(discord.Client): one-shot ask mode
├── daemon.py         # HeimdallDaemon(discord.Client) + InboxWriter: persistent C2 mode
└── __init__.py
src/main.py           # DEPRECATED legacy copy — do not edit
```

**SOLID module boundaries** (do not cross them):
- `ConfigManager` — only reads/writes `~/.config/heimdall/config.json`. No Discord imports.
- `HeimdallBot` — one-shot Discord cycle. No file I/O or `sys.exit()` calls.
- `HeimdallDaemon` — persistent Discord listener. No file I/O (delegates to `InboxWriter`).
- `InboxWriter` — file-system writes to `.agent_inbox/` only. No Discord imports.
- `cli.py` — only parses args and calls `_run_ask()` or `_run_daemon()`.

Installed command (`pyproject.toml`): `heimdall = "heimdall.cli:main"`. Always update `cli.py`.

## Key Data Flow

### Ask mode (one-shot)
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

### Daemon mode (persistent C2)
```
CLI arg → ConfigManager.load() → get_thread_id(project)
  → HeimdallDaemon.start(token)       ← asyncio.run() blocks indefinitely
      → on_ready() → _resolve_thread() → log ready
      → on_message():  filter thread_id + non-bot + "!prompt " prefix
          → _react_safe("👀")           ← immediate acknowledgement
          → InboxWriter.write_task()   ← .agent_inbox/task_TIMESTAMP.md
          → _react_safe("✅")           ← handoff confirmed
      → on_error(): log + CONTINUE     ← never closes on bad events
  → Ctrl-C → KeyboardInterrupt → sys.exit(0)
```

The inbox file is a Markdown task with `# Heimdall Task`, `**From:**`, and `## Prompt` sections. The local IDE agent polls `.agent_inbox/` for new files to process.

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

# Ask mode (one-shot blocking confirmation)
heimdall "test question"                      # legacy shorthand — injects 'ask'
heimdall ask "Deploy to prod?"                # explicit form
heimdall ask --project my-api "Deploy?"       # explicit project name
heimdall ask --timeout 120 "Quick check?"     # custom timeout

# Daemon mode (persistent C2 server)
heimdall daemon                               # listens in current dir's project thread
heimdall daemon --project my-api             # explicit project name
# Then send in Discord thread: !prompt <task description>
# Task files appear in .agent_inbox/task_YYYYMMDD_HHMMSS_ffffff.md
```

Config auto-created at `~/.config/heimdall/config.json` on first run. Bot requires **Message Content Intent** (privileged) enabled in Discord Developer Portal.

Do not commit `.agent_inbox/` — add it to `.gitignore`.

## Conventions

- **Python ≥ 3.8** — no walrus operators, no 3.10+ match statements
- **Type hints required** on all function signatures (`mypy` with `disallow_untyped_defs = true`)
- **Ruff** for linting, line length 100
- **Logging**: use `logger.info/warning/error/debug` (→ stderr). Only `print(f"USER_CONFIRMED: ...")` goes to stdout
- **Exit codes**: `1` on error, `130` on `KeyboardInterrupt`
- **`react_to_message` / `_acknowledge_reply`**: always fire-and-forget — catch `discord.DiscordException`, never raise
- **Config errors are fatal**: `ConfigManager.load()` always calls `sys.exit(1)` on invalid config — never return partial state
- Store Discord snowflake IDs as `str` in JSON, cast to `int` when passing to discord.py APIs
