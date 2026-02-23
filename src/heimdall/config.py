"""
Configuration manager for Heimdall.

Single Responsibility: all config file I/O (load, validate, persist) lives here.
No Discord or CLI logic should be placed in this module.
"""

import json
import logging
import sys
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("heimdall.config")

CONFIG_DIR: Path = Path.home() / ".config" / "heimdall"
CONFIG_FILE: Path = CONFIG_DIR / "config.json"

_TEMPLATE: Dict = {
    "discord_token": "YOUR_BOT_TOKEN_HERE",
    "channel_id": "YOUR_CHANNEL_ID_HERE",
    # Maps project names to their Discord thread IDs.
    # Populated automatically on first run per project.
    "project_threads": {},
}


class ConfigManager:
    """Loads, validates, and persists Heimdall configuration from disk.

    Usage:
        manager = ConfigManager()
        config = manager.load()           # exits on invalid config (fail-fast)
        tid = manager.get_thread_id(name) # None if not yet mapped
        manager.save_thread_id(name, tid) # persist new project → thread mapping
    """

    def __init__(self, config_file: Path = CONFIG_FILE) -> None:
        self._config_file = config_file
        self._data: Optional[Dict] = None

    def load(self) -> Dict:
        """Load config from disk.

        On first run: creates a template file and exits (fail-fast).
        On malformed JSON or placeholder credentials: exits with code 1.

        Returns:
            The validated config dict.
        """
        config_dir = self._config_file.parent
        config_dir.mkdir(parents=True, exist_ok=True)

        if not self._config_file.exists():
            with open(self._config_file, "w") as f:
                json.dump(_TEMPLATE, f, indent=4)
            logger.error(
                "Config not found. Template created at %s. "
                "Please fill in your Discord Bot Token and Channel ID.",
                self._config_file,
            )
            sys.exit(1)

        try:
            with open(self._config_file, "r") as f:
                data: Dict = json.load(f)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse config file: %s", e)
            sys.exit(1)

        if data.get("discord_token") == "YOUR_BOT_TOKEN_HERE":
            logger.error(
                "Placeholder credentials detected. Please update %s with valid values.",
                self._config_file,
            )
            sys.exit(1)

        # Validate channel_id is a numeric Discord snowflake
        channel_id = data.get("channel_id", "")
        if not channel_id or not str(channel_id).isdigit():
            logger.error(
                "Invalid 'channel_id' in %s. Expected a numeric Discord snowflake ID, "
                "got: '%s'. Right-click a text channel in Discord (Developer Mode) → "
                "Copy Channel ID.",
                self._config_file,
                channel_id,
            )
            sys.exit(1)

        # Ensure the project_threads key exists for backwards compatibility
        data.setdefault("project_threads", {})
        self._data = data
        logger.debug("Config loaded from %s", self._config_file)
        return data

    def get_thread_id(self, project_name: str) -> Optional[int]:
        """Return the saved Discord thread ID for a project, or None if not mapped.

        Args:
            project_name: The project identifier used as the thread name.

        Returns:
            Integer thread ID, or None.
        """
        self._assert_loaded()
        raw = self._data["project_threads"].get(project_name)  # type: ignore[index]
        return int(raw) if raw else None

    def save_thread_id(self, project_name: str, thread_id: int) -> None:
        """Persist a project → thread ID mapping back to config on disk.

        Args:
            project_name: The project identifier.
            thread_id: The Discord thread ID to associate with this project.
        """
        self._assert_loaded()
        # Store as string for JSON compatibility with large Discord snowflake IDs
        self._data["project_threads"][project_name] = str(thread_id)  # type: ignore[index]
        self._write()
        logger.debug("Saved thread mapping: '%s' → %d", project_name, thread_id)

    def _write(self) -> None:
        """Write the current in-memory config back to disk."""
        try:
            with open(self._config_file, "w") as f:
                json.dump(self._data, f, indent=4)
        except OSError as e:
            # Non-fatal: the bot already ran successfully; log and continue.
            logger.error("Failed to write config back to disk: %s", e)

    def _assert_loaded(self) -> None:
        if self._data is None:
            raise RuntimeError("Config not loaded. Call load() before accessing data.")
