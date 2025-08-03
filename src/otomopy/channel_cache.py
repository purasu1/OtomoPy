"""
Channel cache for Holodex integration.

This module provides a class to cache YouTube channel data from Holodex.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

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
            self.cache_dir = Path.cwd()
        else:
            self.cache_dir = Path(cache_dir)

        # Create cache directory if it doesn't exist
        os.makedirs(self.cache_dir, exist_ok=True)

        self.cache_file = self.cache_dir / "holodex_channels_cache.json"
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
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Check for required fields in cache format
            if not isinstance(data, dict) or "channels" not in data or "last_update" not in data:
                logger.warning("Invalid channel cache format")
                return False

            self.channels = data["channels"]
            self.last_update = data["last_update"]

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
        try:
            data = {"channels": self.channels, "last_update": time.time()}

            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            self.last_update = data["last_update"]
            logger.info(f"Saved {len(self.channels)} channels to cache")
            return True
        except Exception:
            logger.exception("Error saving channel cache:")
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

        matches = []
        for channel in self.channels:
            name = channel.get("name", "").lower()
            english_name = channel.get("english_name", "").lower()

            if query in name or (english_name and query in english_name):
                matches.append(channel)

        return matches
