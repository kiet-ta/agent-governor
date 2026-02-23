"""
Heimdall CLI — entry point and orchestrator.

Single Responsibility: argument parsing, wiring ConfigManager + HeimdallBot,
and writing the final result to stdout. No Discord or file I/O logic lives here.

Stdout contract: callers capture and parse "USER_CONFIRMED: <reply>".
All diagnostic output (logs) is written to stderr.
"""

import asyncio
import logging
import os
import sys
import argparse
import warnings
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
from heimdall.discord_client import HeimdallBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("heimdall")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Heimdall — Human-in-the-Loop Blocking Gateway"
    )
    parser.add_argument("question", help="The question or action to confirm via Discord")
    parser.add_argument(
        "--project",
        default=None,
        metavar="NAME",
        help="Project name used for thread routing (defaults to current directory name)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3600.0,
        metavar="SECONDS",
        help="Seconds to wait for a reply before aborting (default: 3600)",
    )
    args = parser.parse_args()

    project_name: str = args.project or os.path.basename(os.getcwd())

    try:
        config_manager = ConfigManager()
        config = config_manager.load()

        token: str = config["discord_token"]
        channel_id: int = int(config["channel_id"])
        existing_thread_id: Optional[int] = config_manager.get_thread_id(project_name)

        bot = HeimdallBot(
            channel_id=channel_id,
            project_name=project_name,
            question=args.question,
            existing_thread_id=existing_thread_id,
            timeout=args.timeout,
        )

        # Blocks until the bot receives a reply or times out.
        # discord.py manages the asyncio event loop internally via bot.start().
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


if __name__ == "__main__":
    main()
