"""
Heimdall CLI — entry point and orchestrator.

Single Responsibility: argument parsing and subcommand routing only.
No Discord or file I/O logic lives here.

Subcommands:
    heimdall ask "question"   — One-shot blocking confirmation (Human-in-the-Loop).
    heimdall daemon           — Persistent C2 daemon that handles !prompt commands.

Legacy positional shorthand (backwards compatible):
    heimdall "question"       — Equivalent to `heimdall ask "question"`.

Stdout contract (ask mode): callers capture and parse "USER_CONFIRMED: <reply>".
All diagnostic output goes to stderr via logger.
"""

import asyncio
import logging
import os
import sys
import argparse
import warnings
from pathlib import Path
from typing import Optional


class _UnclosedFilter(logging.Filter):
    """Drop aiohttp 'Unclosed connector' noise from asyncio's exception handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage() if record.args else str(record.msg)
        return "Unclosed connector" not in msg


# Suppress the known aiohttp shutdown noise that fires via two paths:
#   1. warnings.warn("Unclosed connector …", ResourceWarning)
#   2. loop.call_exception_handler({"message": "Unclosed connector"})
warnings.filterwarnings("ignore", message="Unclosed.*", category=ResourceWarning)
logging.getLogger("asyncio").addFilter(_UnclosedFilter())

# PyNaCl voice warning is irrelevant — Heimdall never uses Discord voice.
logging.getLogger("discord.client").setLevel(logging.ERROR)

from heimdall.config import ConfigManager
from heimdall.daemon import HeimdallDaemon
from heimdall.discord_client import HeimdallBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("heimdall")


# ---------------------------------------------------------------------------
# Subcommand: ask (one-shot blocking confirmation)
# ---------------------------------------------------------------------------


def _run_ask(question: str, project_name: str, timeout: float) -> None:
    """Block until the user confirms via Discord, then print result to stdout."""
    try:
        config_manager = ConfigManager()
        config = config_manager.load()

        token: str = config["discord_token"]
        channel_id: int = int(config["channel_id"])
        existing_thread_id: Optional[int] = config_manager.get_thread_id(project_name)

        bot = HeimdallBot(
            channel_id=channel_id,
            project_name=project_name,
            question=question,
            existing_thread_id=existing_thread_id,
            timeout=timeout,
        )

        # Blocks until the bot receives a reply or times out.
        asyncio.run(bot.start(token))

        # Persist a newly created thread so future calls for this project reuse it.
        if bot.is_new_thread and bot.reply_thread_id is not None:
            config_manager.save_thread_id(project_name, bot.reply_thread_id)

        if bot.reply_content is None:
            logger.error("No reply received. Exiting with error.")
            sys.exit(1)

        # Only the confirmed result goes to stdout — callers parse this prefix.
        print(f"USER_CONFIRMED: {bot.reply_content}")

    except KeyboardInterrupt:
        logger.info("Operation cancelled by user.")
        sys.exit(130)
    except Exception as e:
        logger.exception("Fatal error: %s", e)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Subcommand: daemon (persistent C2 server)
# ---------------------------------------------------------------------------


def _run_daemon(project_name: str) -> None:
    """Start the persistent HeimdallDaemon — blocks indefinitely until Ctrl-C."""
    project_root = Path(os.getcwd())

    try:
        config_manager = ConfigManager()
        config = config_manager.load()

        token: str = config["discord_token"]
        channel_id: int = int(config["channel_id"])

        daemon = HeimdallDaemon(
            config_manager=config_manager,
            project_name=project_name,
            project_root=project_root,
            channel_id=channel_id,
        )

        logger.info(
            "Starting Heimdall Daemon for project '%s' (root: %s). "
            "Press Ctrl-C to stop.",
            project_name,
            project_root,
        )
        # asyncio.run() blocks indefinitely — discord.py reconnects on network drops.
        asyncio.run(daemon.start(token))

    except KeyboardInterrupt:
        logger.info("Daemon stopped by user (SIGINT).")
        sys.exit(0)
    except Exception as e:
        logger.exception("Daemon fatal error: %s", e)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Heimdall — Human-in-the-Loop Blocking Gateway",
        # Preserve legacy `heimdall "question"` shorthand by not requiring a subcommand.
        # We detect the subcommand by checking if the first arg is "ask" or "daemon".
    )

    subparsers = parser.add_subparsers(dest="subcommand")

    # -- ask subcommand --
    ask_parser = subparsers.add_parser(
        "ask",
        help="Block execution until a human confirms via Discord (default mode)",
    )
    ask_parser.add_argument("question", help="The question or action to confirm")
    ask_parser.add_argument(
        "--project",
        default=None,
        metavar="NAME",
        help="Project name for thread routing (defaults to current directory name)",
    )
    ask_parser.add_argument(
        "--timeout",
        type=float,
        default=3600.0,
        metavar="SECONDS",
        help="Seconds to wait for a reply before aborting (default: 3600)",
    )

    # -- daemon subcommand --
    daemon_parser = subparsers.add_parser(
        "daemon",
        help="Run persistent Discord C2 daemon — listens for !prompt commands",
    )
    daemon_parser.add_argument(
        "--project",
        default=None,
        metavar="NAME",
        help="Project name for thread routing (defaults to current directory name)",
    )

    # Legacy shorthand: heimdall "question" → treated as `heimdall ask "question"`
    # Detect this case by checking if the first arg is not a known subcommand.
    if len(sys.argv) >= 2 and sys.argv[1] not in ("ask", "daemon", "-h", "--help"):
        # Inject "ask" so argparse routes correctly
        sys.argv.insert(1, "ask")

    args = parser.parse_args()
    project_name: str = (
        getattr(args, "project", None) or os.path.basename(os.getcwd())
    )

    if args.subcommand == "daemon":
        _run_daemon(project_name)
    else:
        # Default: ask subcommand
        if not hasattr(args, "question"):
            parser.print_help()
            sys.exit(1)
        _run_ask(args.question, project_name, args.timeout)


if __name__ == "__main__":
    main()
