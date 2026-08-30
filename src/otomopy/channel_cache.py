"""
Channel cache for Holodex integration.

This module provides a class to cache YouTube channel data from Holodex.
"""

import contextlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)


class ChannelCache:
    """Cache for Holodex channel data.

    This class manages caching YouTube channel data from Holodex API to avoid
    making frequent API calls. The cache is stored as a JSON file.
    """

    def __init__(self, cache_dir: str | None = ""):
        """Initialize the channel cache.

        Args:
            cache_dir: Directory to store the cache file. If None, uses the current directory.
        """
        if not cache_dir:
            # Use current directory if no cache directory is specified
            self.cache_dir: Path = Path.cwd()
        else:
            self.cache_dir = Path(cache_dir)

        # Create cache directory if it doesn't exist
        os.makedirs(self.cache_dir, exist_ok=True)

        self.cache_file: Path = self.cache_dir / "holodex_channels_cache.json"
        self._channels: list[dict[str, Any]] = []
        self._channel_by_name: dict[str, dict[str, Any]] = {}
        self._channel_by_id: dict[str, dict[str, Any]] = {}
        self._channel_by_handle: dict[str, dict[str, Any]] = {}
        self.channels = []
        self.last_update: float = 0
        self.cache_ttl: int = 24 * 60 * 60  # Cache TTL in seconds (24 hours)

    @property
    def channels(self) -> list[dict[str, Any]]:
        """Get the list of channels from the cache.

        Returns:
            list[dict[str, Any]]: List of channels
        """
        return self._channels

    @channels.setter
    def channels(self, value: list[dict[str, Any]]) -> None:
        self._channels = value
        self._channel_by_name = {channel["name"]: channel for channel in value}
        self._channel_by_id = {channel["id"]: channel for channel in value}
        self._channel_by_handle = {}  # this is managed by the HolodexManager

    def is_cache_valid(self) -> bool:
        """Check if the cache is valid and not expired.

        Returns:
            bool: True if cache exists and is valid, False otherwise
        """
        if not self.cache_file.exists():
            return False

        # Check if cache file is older than TTL
        current_time = time.time()
        if self.last_update == 0:
            # If last_update is not set, get file modification time
            self.last_update = self.cache_file.stat().st_mtime

        return (current_time - self.last_update) < self.cache_ttl

    def load_cache(self) -> bool:
        """Load channel data from cache file.

        Returns:
            bool: True if cache was loaded successfully, False otherwise
        """
        if not self.cache_file.exists():
            logger.info("Channel cache file does not exist")
            return False

        try:
            with open(self.cache_file, encoding="utf-8") as f:
                raw = json.load(f)

            # Check for required fields in cache format
            if not isinstance(raw, dict) or "channels" not in raw or "last_update" not in raw:
                logger.warning("Invalid channel cache format")
                return False

            data = cast(dict[str, Any], raw)
            self.channels = list(data["channels"])
            self.last_update = float(data["last_update"])

            logger.info(f"Loaded {len(self.channels)} channels from cache")
            return True
        except Exception:
            logger.exception("Error loading channel cache:")
            return False

    def save_cache(self) -> bool:
        """Save channel data to cache file.

        Returns:
            bool: True if cache was saved successfully, False otherwise
        """
        tmp_fd, tmp_name = tempfile.mkstemp(
            dir=str(self.cache_dir), prefix=self.cache_file.name + ".", suffix=".tmp"
        )
        try:
            saved_at = time.time()
            data = {"channels": self.channels, "last_update": saved_at}

            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, self.cache_file)

            self.last_update = saved_at
            logger.info(f"Saved {len(self.channels)} channels to cache")
            return True
        except Exception:
            logger.exception("Error saving channel cache:")
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            return False

    def update_cache(self, channels: list[dict[str, Any]]) -> bool:
        """Update the cache with new channel data.

        Args:
            channels: list of channel data to cache

        Returns:
            bool: True if cache was updated successfully, False otherwise
        """
        if not channels:
            logger.warning("No channels provided to update cache")
            return False

        self.channels = channels
        return self.save_cache()

    def merge_channels(self, new_channels: list[dict[str, Any]]) -> tuple[int, int]:
        """Merge freshly fetched channels into the cache without removing any existing ones.

        Channels already in the cache are updated in place with the latest data.
        Channels that no longer appear in new_channels are left untouched, so a
        VTuber disappearing from the Holodex response (e.g. due to a transient API
        issue or a graduation) can't break anything that still references it, such
        as relay configs.

        Args:
            new_channels: Freshly fetched channel data to merge in

        Returns:
            Tuple of (number of newly added channels, number of existing channels updated)
        """
        merged = {channel["id"]: channel for channel in self.channels}
        added = 0
        updated = 0

        for channel in new_channels:
            channel_id = channel["id"]
            if channel_id in merged:
                updated += 1
            else:
                added += 1
            merged[channel_id] = channel

        self.channels = list(merged.values())
        self.save_cache()
        return added, updated

    def get_channels(self) -> list[dict[str, Any]]:
        """Get all channels from the cache.

        Returns:
            list of channel data
        """
        return self.channels

    def get_channel_by_id(self, channel_id: str) -> dict[str, Any] | None:
        """Get a specific channel by its ID.

        Args:
            channel_id: YouTube channel ID

        Returns:
            Channel data or None if not found
        """
        return self._channel_by_id.get(channel_id)

    def get_channel_by_name(self, channel_name: str) -> dict[str, Any] | None:
        """Get a specific channel by its name.

        Args:
            channel_name: YouTube channel name

        Returns:
            Channel data or None if not found
        """
        return self._channel_by_name.get(channel_name)

    def cache_channel_by_handle(self, channel_handle: str, channel: dict[str, Any]) -> None:
        """Remember a channel under a YouTube handle.

        Handles are not part of the Holodex channel list, so the HolodexManager
        fills this index in as it resolves them.

        Args:
            channel_handle: The YouTube handle, e.g. ``@example``
            channel: The channel data to associate with it
        """
        self._channel_by_handle[channel_handle] = channel

    def get_channel_by_handle(self, channel_handle: str) -> dict[str, Any] | None:
        """Get a specific channel by its handle.

        Args:
            channel_handle: YouTube channel handle

        Returns:
            Channel data or None if not found
        """
        return self._channel_by_handle.get(channel_handle)

    def search_channels(self, query: str) -> list[dict[str, Any]]:
        """Search for channels in the cache by name.

        Args:
            query: Search query (partial channel name)

        Returns:
            list of matching channel data
        """
        query = query.lower().strip()

        if not query or len(query) < 2:
            return []

        matches: list[dict[str, Any]] = []
        for channel in self.channels:
            name = channel.get("name", "").lower()
            english_name = channel.get("english_name", "").lower()

            if query in name or (english_name and query in english_name):
                matches.append(channel)

        return matches
