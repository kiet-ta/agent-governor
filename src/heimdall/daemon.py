"""
Heimdall Persistent Daemon — Proactive C2 (Command & Control) server mode.

Single Responsibility: maintain a live Discord Gateway connection, listen for
`!prompt <text>` commands in the project's dedicated thread, and hand tasks off
to the local IDE agent via the Inbox / Drop-folder pattern.

Module boundaries:
    InboxWriter  — file-system I/O only. No Discord imports.
    HeimdallDaemon — Discord I/O only. Delegates all file writes to InboxWriter.
"""

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import discord

from heimdall.config import ConfigManager

logger = logging.getLogger("heimdall.daemon")

PROMPT_PREFIX: str = "!prompt "
INBOX_DIR_NAME: str = ".agent_inbox"


# ---------------------------------------------------------------------------
# InboxWriter — Single Responsibility: file-system I/O
# ---------------------------------------------------------------------------


class InboxWriter:
    """Writes incoming prompt tasks to the project's .agent_inbox/ drop-folder.

    The inbox directory is created automatically on first use.
    Each task is written as an individual Markdown file named
    ``task_YYYYMMDD_HHMMSS_ffffff.md`` so tasks are naturally sorted by
    arrival time and never overwrite each other.

    Args:
        project_root: Absolute path to the watched project directory.
    """

    def __init__(self, project_root: Path) -> None:
        self._inbox_dir: Path = project_root / INBOX_DIR_NAME

    def ensure_inbox(self) -> None:
        """Create .agent_inbox/ if it does not already exist."""
        self._inbox_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("Inbox directory ready: %s", self._inbox_dir)

    def write_task(self, prompt: str, author: str) -> Path:
        """Persist a prompt as a task file and return the written path.

        Args:
            prompt: The raw prompt text extracted from the Discord message.
            author: Discord username of the sender, used as metadata.

        Returns:
            Path to the written task file.
        """
        self.ensure_inbox()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        task_file = self._inbox_dir / f"task_{timestamp}.md"

        content = (
            f"# Heimdall Task — {timestamp}\n\n"
            f"**From:** {author}\n\n"
            f"## Prompt\n\n"
            f"{prompt}\n"
        )

        try:
            task_file.write_text(content, encoding="utf-8")
            logger.info("Task written to %s", task_file)
        except OSError as e:
            logger.error("Failed to write task file %s: %s", task_file, e)
            raise

        return task_file


# ---------------------------------------------------------------------------
# HeimdallDaemon — Single Responsibility: Discord I/O
# ---------------------------------------------------------------------------


class HeimdallDaemon(discord.Client):
    """Long-running Discord bot that turns `!prompt` messages into inbox tasks.

    Unlike HeimdallBot (which runs once then closes), HeimdallDaemon stays
    connected indefinitely and is designed for resilience:

    - ``on_error`` logs and continues — the bot never crashes on a bad event.
    - discord.py's built-in reconnect handles temporary network drops.
    - ``on_ready`` fires again after a reconnect, so state is re-validated.

    Lifecycle:
        1. Start via ``asyncio.run(daemon.start(token))`` — blocks forever.
        2. ``on_ready`` → resolve the project thread (create if needed) → log ready.
        3. ``on_message`` → filter by thread + prefix → ``InboxWriter.write_task``.
        4. Bot reacts 👀 before writing, ✅ after — gives mobile Discord feedback.

    Args:
        config_manager: Pre-loaded ConfigManager instance.
        project_name:   Project key used for thread lookup in config.
        project_root:   Directory for the .agent_inbox/ drop-folder.
        channel_id:     Parent Discord TextChannel ID for thread creation.
        token:          Discord bot token.
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        project_name: str,
        project_root: Path,
        channel_id: int,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # Privileged intent — required for on_message content
        super().__init__(intents=intents)

        self._config_manager = config_manager
        self._project_name = project_name
        self._channel_id = channel_id
        self._inbox_writer = InboxWriter(project_root)

        # Populated once the target thread is resolved in on_ready
        self._thread_id: Optional[int] = config_manager.get_thread_id(project_name)
        self._thread: Optional[discord.Thread] = None

    # ------------------------------------------------------------------
    # Discord event handlers
    # ------------------------------------------------------------------

    async def on_ready(self) -> None:
        """Called when the bot connects or reconnects to the Gateway."""
        logger.info(
            "Daemon connected as '%s'. Resolving thread for project '%s'...",
            self.user,
            self._project_name,
        )
        try:
            self._thread = await self._resolve_thread()
            logger.info(
                "Daemon ready. Listening for '!prompt' in thread '%s' (id=%d). "
                "Drop-folder: %s",
                self._thread.name,
                self._thread.id,
                self._inbox_writer._inbox_dir,
            )
        except Exception:
            logger.exception(
                "Failed to resolve thread for project '%s'. "
                "Daemon will keep running — retrying on next reconnect.",
                self._project_name,
            )
            self._thread = None

    async def on_message(self, message: discord.Message) -> None:
        """Fires for every message the bot can see.

        Filters to: correct thread + non-bot author + !prompt prefix.
        """
        # Guard: thread not yet resolved (e.g. startup error)
        if self._thread is None:
            return

        # Only process messages in the project's dedicated thread
        if message.channel.id != self._thread.id:
            return

        # Ignore messages from bots (including self)
        if message.author.bot:
            return

        if not message.content.startswith(PROMPT_PREFIX):
            return

        prompt = message.content[len(PROMPT_PREFIX):].strip()
        if not prompt:
            logger.debug("Empty prompt received from '%s'. Ignoring.", message.author)
            return

        await self._handle_prompt(message, prompt)

    async def on_error(self, event_method: str, *args: object, **kwargs: object) -> None:  # type: ignore[override]
        """Called when an event handler raises an unhandled exception.

        We log the error but do NOT close the connection — the daemon must
        survive individual bad events (e.g. permission errors, malformed data).
        """
        logger.exception(
            "Unhandled exception in event '%s'. Daemon continues running.",
            event_method,
        )

    # ------------------------------------------------------------------
    # Core prompt handling
    # ------------------------------------------------------------------

    async def _handle_prompt(self, message: discord.Message, prompt: str) -> None:
        """Acknowledge, write, and confirm an incoming !prompt command.

        Args:
            message: The Discord message containing the !prompt command.
            prompt:  Extracted prompt text (with !prompt prefix stripped).
        """
        author = str(message.author)

        # 👀 Acknowledge receipt immediately so the user knows the command landed
        await self._react_safe(message, "👀")

        try:
            # Delegate all file I/O to InboxWriter (SRP)
            task_path = self._inbox_writer.write_task(prompt, author)
            logger.info(
                "Prompt from '%s' → task file: %s", author, task_path.name
            )
            # ✅ Confirm handoff after successful write
            await self._react_safe(message, "✅")
        except OSError:
            # InboxWriter already logged the error; surface failure to Discord
            await self._react_safe(message, "❌")
            logger.error(
                "Failed to write task for prompt from '%s'. Inbox may be unwritable.",
                author,
            )

    # ------------------------------------------------------------------
    # Thread management (mirrors HeimdallBot._resolve_thread)
    # ------------------------------------------------------------------

    async def _resolve_thread(self) -> discord.Thread:
        """Return (or create) the persistent thread for this project.

        Reuses the saved thread_id from config if available, unarchiving if
        needed. Falls back to creating a new thread under the parent channel.
        """
        if self._thread_id is not None:
            try:
                channel = await self.fetch_channel(self._thread_id)
                if isinstance(channel, discord.Thread):
                    if channel.archived:
                        logger.info("Thread archived. Unarchiving '%s'...", channel.name)
                        await channel.edit(archived=False)
                    return channel
            except (discord.NotFound, discord.Forbidden) as e:
                logger.warning(
                    "Saved thread %d inaccessible (%s). Creating a new one.",
                    self._thread_id,
                    e,
                )

        return await self._create_thread()

    async def _create_thread(self) -> discord.Thread:
        """Create a new thread under the configured parent TextChannel."""
        try:
            parent = self.get_channel(self._channel_id) or await self.fetch_channel(
                self._channel_id
            )
        except discord.NotFound:
            raise ValueError(
                f"Channel ID {self._channel_id} not found (404). "
                "Please verify 'channel_id' in ~/.config/heimdall/config.json."
            )
        except discord.Forbidden:
            raise ValueError(
                f"Bot lacks permission to access channel {self._channel_id}."
            )

        if not isinstance(parent, discord.TextChannel):
            raise ValueError(
                f"Channel {self._channel_id} is not a TextChannel."
            )

        starter_msg = await parent.send(
            f"🧵 **Heimdall Daemon** | Project: `{self._project_name}` is now online."
        )
        thread = await starter_msg.create_thread(
            name=self._project_name,
            auto_archive_duration=10080,  # 7 days — daemon sessions are long-lived
        )
        # Persist so future daemon starts reuse this thread
        self._config_manager.save_thread_id(self._project_name, thread.id)
        self._thread_id = thread.id
        logger.info("Thread created: '%s' (id=%d).", thread.name, thread.id)
        return thread

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _react_safe(self, message: discord.Message, emoji: str) -> None:
        """Add a reaction; swallow DiscordException (fire-and-forget UX)."""
        try:
            await message.add_reaction(emoji)
        except discord.DiscordException as e:
            logger.debug("Could not add reaction '%s' (non-critical): %s", emoji, e)
