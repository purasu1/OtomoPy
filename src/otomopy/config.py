"""
Configuration management for OtomoPy.
"""

import json
import logging
import pathlib

logger = logging.getLogger(__name__)


class GuildConfig:
    """Manages guild configuration data."""

    def __init__(self, config_file: str):
        """Initialize the configuration manager."""
        self.config_file = config_file
        self.data: dict[str, dict] = {}
        self.load()

    def load(self):
        """Load configuration data from file."""
        try:
            if pathlib.Path(self.config_file).exists():
                with open(self.config_file, "r") as f:
                    self.data = json.load(f)
            logger.info(f"Loaded configuration for {len(self.data)} guilds")
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            self.data = {}

    def save(self):
        """Save configuration data to file."""
        try:
            with open(self.config_file, "w") as f:
                json.dump(self.data, f, indent=2)
            logger.info("Configuration saved")
        except Exception as e:
            logger.error(f"Error saving config: {e}")

    def get_guild_config(self, guild_id: int) -> dict:
        """Get configuration for a specific guild, creating it if it doesn't exist.

        Args:
            guild_id: The Discord guild ID

        Returns:
            Dict: The guild configuration dictionary
        """
        guild_id_str = str(guild_id)
        if guild_id_str not in self.data:
            self.data[guild_id_str] = {
                "admin_roles": [],
                "relay_channels": {},
                "tl_blacklist": [],
            }
            self.save()
        return self.data[guild_id_str]

    def add_admin_role(self, guild_id: int, role_id: int) -> bool:
        """Add a role to the admin roles list for a guild.

        Args:
            guild_id: The Discord guild ID
            role_id: The Discord role ID to add

        Returns:
            bool: True if the role was added, False if it was already an admin role
        """
        guild_config = self.get_guild_config(guild_id)
        role_id_str = str(role_id)
        if role_id_str not in guild_config.get("admin_roles", []):
            if "admin_roles" not in guild_config:
                guild_config["admin_roles"] = []
            guild_config["admin_roles"].append(role_id_str)
            self.save()
            return True
        return False

    def remove_admin_role(self, guild_id: int, role_id: int) -> bool:
        """Remove a role from the admin roles list for a guild.

        Args:
            guild_id: The Discord guild ID
            role_id: The Discord role ID to remove

        Returns:
            bool: True if the role was removed, False if it wasn't an admin role
        """
        guild_config = self.get_guild_config(guild_id)
        role_id_str = str(role_id)
        if "admin_roles" in guild_config and role_id_str in guild_config["admin_roles"]:
            guild_config["admin_roles"].remove(role_id_str)
            self.save()
            return True
        return False

    def is_admin_role(self, guild_id: int, role_id: int) -> bool:
        """Check if a role is an admin role for a guild.

        Args:
            guild_id: The Discord guild ID
            role_id: The Discord role ID to check

        Returns:
            bool: True if the role is an admin role, False otherwise
        """
        guild_config = self.get_guild_config(guild_id)
        return str(role_id) in guild_config.get("admin_roles", [])

    def add_relay_channel(
        self, guild_id: int, discord_channel_id: int, youtube_channel_id: str
    ) -> bool:
        """Add a YouTube channel to relay to a Discord channel.

        Args:
            guild_id: The Discord guild ID
            discord_channel_id: The Discord channel ID to relay to
            youtube_channel_id: The YouTube channel ID to relay from

        Returns:
            bool: True if the channel was added, False if it was already configured
        """
        guild_config = self.get_guild_config(guild_id)

        # Initialize relay_channels if it doesn't exist
        if "relay_channels" not in guild_config:
            guild_config["relay_channels"] = {}

        # Get the current relay configuration
        relay_channels = guild_config["relay_channels"]

        # If this YouTube channel isn't in the config yet, add it with an empty list
        if youtube_channel_id not in relay_channels:
            relay_channels[youtube_channel_id] = []

        # Check if this Discord channel is already in the list for this YouTube channel
        discord_channel_id_str = str(discord_channel_id)
        if discord_channel_id_str in relay_channels[youtube_channel_id]:
            return False  # Already configured

        # Add this Discord channel to the list
        relay_channels[youtube_channel_id].append(discord_channel_id_str)
        self.save()
        return True

    def remove_relay_channel(
        self, guild_id: int, discord_channel_id: int, youtube_channel_id: str
    ) -> bool:
        """Remove a YouTube channel relay from a Discord channel.

        Args:
            guild_id: The Discord guild ID
            discord_channel_id: The Discord channel ID to stop relaying to
            youtube_channel_id: The YouTube channel ID to stop relaying from

        Returns:
            bool: True if the channel was removed, False if it wasn't configured
        """
        guild_config = self.get_guild_config(guild_id)

        # Check if relay_channels exists
        if "relay_channels" not in guild_config:
            return False

        relay_channels = guild_config["relay_channels"]

        # Check if this YouTube channel is in the config
        if youtube_channel_id not in relay_channels:
            return False

        # Check if this Discord channel is in the list
        discord_channel_id_str = str(discord_channel_id)
        if discord_channel_id_str not in relay_channels[youtube_channel_id]:
            return False

        # Remove this Discord channel from the list
        relay_channels[youtube_channel_id].remove(discord_channel_id_str)

        # If the list is now empty, remove the YouTube channel from the config
        if not relay_channels[youtube_channel_id]:
            del relay_channels[youtube_channel_id]

        self.save()
        return True

    def get_relay_channels(
        self, guild_id: int, discord_channel_id: int | None = None
    ) -> dict:
        """Get all relay channel configurations for a guild or a specific Discord channel.

        Args:
            guild_id: The Discord guild ID
            discord_channel_id: Optional Discord channel ID to filter by

        Returns:
            dict: Dictionary mapping YouTube channel IDs to lists of Discord channel IDs
        """
        guild_config = self.get_guild_config(guild_id)
        relay_channels = guild_config.get("relay_channels", {})

        # If no specific Discord channel is requested, return all configurations
        if discord_channel_id is None:
            return relay_channels

        # Filter for only configurations that include the specified Discord channel
        discord_channel_id_str = str(discord_channel_id)
        filtered_relay_channels = {}

        for youtube_id, discord_ids in relay_channels.items():
            if discord_channel_id_str in discord_ids:
                filtered_relay_channels[youtube_id] = discord_ids

        return filtered_relay_channels

    def get_all_youtube_channels(self) -> set:
        """Get all YouTube channel IDs that are being relayed across all guilds.

        Returns:
            set: Set of all YouTube channel IDs
        """
        all_channels = set()

        for guild_config in self.data.values():
            relay_channels = guild_config.get("relay_channels", {})
            if relay_channels:
                all_channels.update(relay_channels.keys())

        return all_channels

    def add_blacklisted_user(
        self, guild_id: int, user_name: str,
    ) -> bool:
        """Add a user to the translation blacklist for a guild.

        Args:
            guild_id: The Discord guild ID
            user_name: The user to blacklist

        Returns:
            bool: True if the user was added, False if they were already blacklisted
        """
        guild_config = self.get_guild_config(guild_id)

        # Initialize blacklist if it doesn't exist
        if "tl_blacklist" not in guild_config:
            guild_config["tl_blacklist"] = []

        # Check if user is already blacklisted
        if user_name in guild_config["tl_blacklist"]:
            return False  # Already blacklisted

        # Add user to blacklist
        guild_config["tl_blacklist"].append(user_name)
        self.save()
        return True

    def remove_blacklisted_user(self, guild_id: int, user_name: str) -> bool:
        """Remove a user from the translation blacklist for a guild.

        Args:
            guild_id: The Discord guild ID
            user_name: The user to remove from blacklist

        Returns:
            bool: True if the user was removed, False if they weren't blacklisted
        """
        guild_config = self.get_guild_config(guild_id)

        if "tl_blacklist" not in guild_config:
            return False

        # Find and remove the user
        try:
            guild_config["tl_blacklist"].remove(user_name)
        except ValueError:
            return False
        finally:
            self.save()
            return True

    def is_user_blacklisted(self, guild_id: int, user_name: str) -> bool:
        """Check if a user is blacklisted for translations in a guild.

        Args:
            guild_id: The Discord guild ID
            user_name: The user to check

        Returns:
            bool: True if the user is blacklisted, False otherwise
        """
        guild_config = self.get_guild_config(guild_id)
        blacklist = guild_config.get("tl_blacklist", [])

        return user_name in blacklist

    def get_blacklisted_users(self, guild_id: int) -> list:
        """Get all blacklisted users for a guild.

        Args:
            guild_id: The Discord guild ID

        Returns:
            list: List of blacklist entries with user_name and added_at
        """
        guild_config = self.get_guild_config(guild_id)
        return guild_config.get("tl_blacklist", [])
