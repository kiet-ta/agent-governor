"""
Ephemeral Discord Gateway client for Heimdall.

Single Responsibility: all Discord communication (connecting, thread management,
embed sending, reply listening) lives here. No file I/O or config logic.

Architecture note:
    HeimdallBot subclasses discord.Client and runs one complete confirmation
    cycle inside on_ready(). The caller launches it with asyncio.run(bot.start(token))
    which blocks until close() is called, then reads results from bot attributes.
"""

import asyncio
import logging
from typing import Optional

import discord

logger = logging.getLogger("heimdall.discord_client")

DEFAULT_TIMEOUT_SECONDS: float = 3600.0  # 1 hour before giving up


class HeimdallBot(discord.Client):
    """An ephemeral Discord bot for one Human-in-the-Loop confirmation cycle.

    Lifecycle (single run):
        1. Connect to Discord Gateway via WebSocket (no polling).
        2. on_ready() fires → _run_flow() executes the full workflow.
        3. Resolve or create a per-project thread under the configured channel.
        4. Post an embed with the question to the thread.
        5. Await the first non-bot reply via wait_for (event-driven, zero polling).
        6. Acknowledge with ✅ reaction, store result, call close().

    Results are accessible as attributes after asyncio.run(bot.start(token)) returns:
        bot.reply_content   – The human's reply text, or None on timeout/error.
        bot.reply_thread_id – The Discord thread ID used (new or existing).
        bot.is_new_thread   – True if a new thread was created this run.
    """

    def __init__(
        self,
        channel_id: int,
        project_name: str,
        question: str,
        existing_thread_id: Optional[int] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        # MESSAGE_CONTENT is a privileged intent required to read message text.
        # Must be enabled in the Discord Developer Portal under Bot → Privileged Intents.
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

        self._channel_id = channel_id
        self._project_name = project_name
        self._question = question
        self._existing_thread_id = existing_thread_id
        self._timeout = timeout

        # Public output — populated after run, read by the CLI caller
        self.reply_content: Optional[str] = None
        self.reply_thread_id: Optional[int] = None
        self.is_new_thread: bool = False

    # ------------------------------------------------------------------
    # Discord event handlers
    # ------------------------------------------------------------------

    async def on_ready(self) -> None:
        """Called once the bot has authenticated and connected to the Gateway."""
        logger.info(
            "Bot connected as '%s'. Running confirmation flow for project '%s'.",
            self.user,
            self._project_name,
        )
        try:
            await self._run_flow()
        except Exception:
            logger.exception("Unhandled error during bot flow.")
        finally:
            # Always disconnect cleanly — the asyncio.run() call will then return.
            await self.close()

    # ------------------------------------------------------------------
    # Core workflow
    # ------------------------------------------------------------------

    async def _run_flow(self) -> None:
        """Orchestrates: resolve thread → send embed → await reply."""
        thread = await self._resolve_thread()
        self.reply_thread_id = thread.id

        await self._send_embed(thread)

        def is_valid_reply(message: discord.Message) -> bool:
            """Accept the first non-bot message posted in the project thread."""
            return message.channel.id == thread.id and not message.author.bot

        try:
            logger.info(
                "Waiting for reply in thread '%s' (id=%d). Timeout: %.0fs.",
                thread.name,
                thread.id,
                self._timeout,
            )
            reply = await self.wait_for("message", check=is_valid_reply, timeout=self._timeout)
            self.reply_content = reply.content.strip()
            logger.info("Reply received from '%s'.", reply.author)
            await self._acknowledge_reply(reply)
        except asyncio.TimeoutError:
            logger.error(
                "Timed out after %.0f seconds. No reply received for project '%s'.",
                self._timeout,
                self._project_name,
            )

    # ------------------------------------------------------------------
    # Thread management
    # ------------------------------------------------------------------

    async def _resolve_thread(self) -> discord.Thread:
        """Return an active thread for this project.

        Priority:
            1. Reuse the thread saved in config (if still valid and not archived).
            2. Unarchive it automatically if archived (requires MANAGE_THREADS perm).
            3. Fall back to creating a brand-new thread.
        """
        if self._existing_thread_id is not None:
            try:
                channel = await self.fetch_channel(self._existing_thread_id)
                if isinstance(channel, discord.Thread):
                    if channel.archived:
                        logger.info(
                            "Thread '%s' is archived. Unarchiving...", channel.name
                        )
                        await channel.edit(archived=False)
                    logger.info(
                        "Reusing existing thread: '%s' (id=%d).",
                        channel.name,
                        channel.id,
                    )
                    return channel
            except (discord.NotFound, discord.Forbidden) as e:
                logger.warning(
                    "Saved thread %d is inaccessible (%s). Creating a new one.",
                    self._existing_thread_id,
                    e,
                )

        return await self._create_thread()

    async def _create_thread(self) -> discord.Thread:
        """Create a new public thread under the configured parent TextChannel.

        Uses a starter message attached to the thread, which avoids requiring
        the CREATE_PUBLIC_THREADS (no-message) permission on non-Community servers.
        """
        parent = self.get_channel(self._channel_id) or await self.fetch_channel(
            self._channel_id
        )

        if not isinstance(parent, discord.TextChannel):
            raise ValueError(
                f"Channel {self._channel_id} is not a TextChannel. "
                "Heimdall requires a standard Discord text channel as the parent."
            )

        # The starter message anchors the thread; it appears in the channel feed.
        starter_msg = await parent.send(
            f"🧵 **Heimdall** | New session for project: `{self._project_name}`"
        )
        thread = await starter_msg.create_thread(
            name=self._project_name,
            auto_archive_duration=1440,  # Archive after 24 h of inactivity
        )
        self.is_new_thread = True
        logger.info("Thread created: '%s' (id=%d).", thread.name, thread.id)
        return thread

    # ------------------------------------------------------------------
    # Messaging helpers
    # ------------------------------------------------------------------

    async def _send_embed(self, thread: discord.Thread) -> None:
        """Post the confirmation request embed to the given thread."""
        embed = discord.Embed(
            title=f"🚨 Action Required: {self._project_name}",
            description=self._question,
            color=discord.Color.orange(),
        )
        embed.set_footer(text="Reply in this thread to confirm or reject.")
        await thread.send(embed=embed)
        logger.info("Question posted to thread '%s'.", thread.name)

    async def _acknowledge_reply(self, message: discord.Message) -> None:
        """React to the reply with ✅ to signal receipt.

        Fire-and-forget: failures are swallowed since this is non-critical UX.
        """
        try:
            await message.add_reaction("✅")
        except discord.DiscordException as e:
            logger.debug("Could not add acknowledgement reaction (non-critical): %s", e)
