"""
OtomoPy Discord bot module.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime

import discord
from discord import app_commands
from dotenv import load_dotenv

from otomopy.config import GuildConfig
from otomopy.holodex import ChatMessage, HolodexManager, StreamEvent
from otomopy.permissions import ensure_permission_checked

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass
class DotEnvConfig:
    token: str
    owner_id: int
    config_file: str
    holodex_api_key: str

    @classmethod
    def load_env(cls) -> DotEnvConfig:
        load_dotenv()
        token = os.getenv("DISCORD_TOKEN")
        if token is None:
            raise RuntimeError(
                "No Discord token found. Please add DISCORD_TOKEN to your .env file"
            )

        owner_id = os.getenv("OWNER_ID")
        if owner_id is None:
            raise RuntimeError(
                "No owner ID found. Please add OWNER_ID to your .env file"
            )
        try:
            owner_id = int(owner_id)
        except ValueError:
            raise ValueError("Invalid owner ID. Please ensure it is an integer.")

        config_file = os.getenv("CONFIG_FILE")
        if config_file is None:
            raise RuntimeError(
                "No config file found. Please add CONFIG_FILE to your .env file"
            )

        holodex_api_key = os.getenv("HOLODEX_API_KEY")
        if holodex_api_key is None:
            raise RuntimeError(
                "No Holodex API key found. Please add HOLODEX_API_KEY to your .env file"
            )

        return cls(token, owner_id, config_file, holodex_api_key)


class DiscordBot(discord.Client):
    """Discord bot client with slash command support and permissions system."""

    def __init__(self, dotenv: DotEnvConfig):
        # Load config
        self.dotenv = dotenv

        # Set up minimal intents
        intents = discord.Intents.default()
        intents.message_content = False  # Disable message content intent as it's not needed for slash commands

        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.config = GuildConfig(self.dotenv.config_file)

        # Set the cache directory to the same directory as the config file
        config_dir = os.path.dirname(os.path.abspath(self.dotenv.config_file))
        os.environ["OTOMOPY_CONFIG_DIR"] = config_dir

        # Holodex integration
        self.holodex_manager = HolodexManager(dotenv.holodex_api_key, config_dir)
        self.tracked_channels: set[str] = set()
        self.holodex_task = None

    async def setup_hook(self):
        """Set up the bot and synchronize commands."""
        # This copies the global commands over to your guild.
        # await self.tree.sync(guild=discord.Object(id=YOUR_GUILD_ID))  # For testing in a specific server
        await self.tree.sync()  # For global commands

        # Start tracking Holodex channels
        await self.update_tracked_channels()
        self.holodex_task = asyncio.create_task(self.start_holodex_tracking())
        self.holodex_chat_messages_received = 0

    def has_permission(self, interaction: discord.Interaction) -> bool:
        """Check if a user has permission to use admin commands.

        Args:
            interaction: The Discord interaction to check permissions for

        Returns:
            bool: True if the user has permission, False otherwise
        """
        # Owner always has permission
        if interaction.user.id == self.dotenv.owner_id:
            return True

        # Check if user has any admin roles
        if (
            interaction.guild
            and isinstance(interaction.user, discord.Member)
            and interaction.user.guild_permissions.administrator
        ):
            return True

        # Check if user has any configured admin roles
        if interaction.guild and isinstance(interaction.user, discord.Member):
            guild_config = self.config.get_guild_config(interaction.guild.id)
            admin_roles = guild_config.get("admin_roles", [])
            user_role_ids = [str(role.id) for role in interaction.user.roles]
            return any(role_id in admin_roles for role_id in user_role_ids)

        return False

    async def update_tracked_channels(self):
        """Update the set of YouTube channels being tracked."""
        tracked_channels = self.config.get_all_youtube_channels()
        if tracked_channels != self.tracked_channels:
            # Pass new set of channels to the HolodexManager
            await self.holodex_manager.update_channels(tracked_channels)

        self.tracked_channels = tracked_channels
        logger.info(f"Now tracking {len(self.tracked_channels)} YouTube channels")

    async def start_holodex_tracking(self):
        """Start tracking live streams from Holodex."""
        try:
            await self.holodex_manager.start(
                self.tracked_channels, self.on_stream_event, self.on_chat_message
            )
        except Exception as e:
            logger.error(f"Error in Holodex tracking: {e}")

    async def on_stream_event(self, event: StreamEvent):
        """Handle a stream event from Holodex.

        Args:
            event: The stream event
        """
        logger.info(
            f"Stream event: {event.channel_name} - {event.title} - {event.status}"
        )

        # Find all Discord channels this should be relayed to
        for guild_id_str, guild_config in self.config.data.items():
            relay_channels = guild_config.get("relay_channels", {})

            # If this YouTube channel is being relayed in this guild
            if event.channel_id in relay_channels:
                discord_channel_ids = relay_channels[event.channel_id]

                for discord_channel_id_str in discord_channel_ids:
                    try:
                        # Get the Discord channel
                        channel = self.get_channel(int(discord_channel_id_str))
                        if not channel:
                            continue

                        # Create an embed for the event
                        embed = discord.Embed(
                            title=event.title,
                            url=f"https://www.youtube.com/watch?v={event.video_id}",
                            color=self._get_status_color(event.status),
                        )

                        embed.set_author(name=event.channel_name)
                        embed.set_thumbnail(url=event.thumbnail)

                        if event.status == "live":
                            embed.description = ":red_circle: **LIVE NOW**"
                            if event.live_viewers:
                                embed.add_field(
                                    name="Viewers", value=f"{event.live_viewers:,}"
                                )
                        elif event.status == "upcoming":
                            embed.description = ":soon: **UPCOMING**"
                            if event.start_time:
                                # Handle the timestamp
                                try:
                                    dt = datetime.fromisoformat(
                                        event.start_time.replace("Z", "+00:00")
                                    )
                                    timestamp = int(dt.timestamp())
                                    embed.add_field(
                                        name="Scheduled for", value=f"<t:{timestamp}:F>"
                                    )
                                except Exception as e:
                                    logger.error(f"Error formatting timestamp: {e}")

                        # Send the embed to the Discord channel
                        if isinstance(channel, discord.TextChannel):
                            await channel.send(embed=embed)
                    except Exception as e:
                        logger.error(f"Error sending relay message: {e}")

    async def on_chat_message(self, message: ChatMessage):
        """Handle a chat message event from Holodex.

        Args:
            message: The chat message
        """
        # Count messages received
        self.holodex_chat_messages_received += 1

        # Add debug logging for every message
        logger.debug(
            f"Received chat message #{self.holodex_chat_messages_received}: {message.author} - {message.message}"
        )
        logger.debug(
            f"Message details - Channel: {message.channel_id}, Video: {message.video_id}, Is Translation: {message.is_translation}"
        )

        # Log every 10th message to avoid flooding logs at INFO level
        if self.holodex_chat_messages_received % 10 == 0:
            logger.info(
                f"Chat messages received: {self.holodex_chat_messages_received}, Latest: {message.author} - {message.message}"
            )

        # Holodex already filters messages, so we relay all messages we receive

        # Find all Discord channels this should be relayed to
        for guild_id_str, guild_config in self.config.data.items():
            relay_channels = guild_config.get("relay_channels", {})

            # If this YouTube channel is being relayed in this guild
            if message.channel_id in relay_channels:
                # Check if the message author is blacklisted in this guild
                # Use translator name directly without any modifications
                guild_id = int(guild_id_str)
                if self.config.is_user_blacklisted(guild_id, message.author):
                    logger.debug(
                        f"Skipping message from blacklisted user {message.author} in guild {guild_id}"
                    )
                    continue

                discord_channel_ids = relay_channels[message.channel_id]

                for discord_channel_id_str in discord_channel_ids:
                    try:
                        # Get the Discord channel
                        channel = self.get_channel(int(discord_channel_id_str))
                        if not channel or not isinstance(channel, discord.TextChannel):
                            continue

                        # Format message like PomuBot - simple text with emojis
                        # Clean up message text by replacing backticks
                        clean_message = message.message.replace("`", "''")

                        # Use spoiler tags for translator name (like PomuBot)
                        author_display = f"||{message.author}:||"

                        # Build the message content
                        content_parts = [
                            f":speech_balloon: {author_display} `{clean_message}`"
                        ]

                        # Add chat source link
                        video_url = (
                            f"https://www.youtube.com/watch?v={message.video_id}"
                        )

                        # Get channel name from current streams if available
                        channel_name = "YouTube Chat"
                        if (
                            hasattr(self, "holodex_manager")
                            and message.video_id in self.holodex_manager.current_streams
                        ):
                            stream_event = self.holodex_manager.current_streams[
                                message.video_id
                            ]
                            channel_name = stream_event.channel_name

                        content_parts.append(
                            f"**Chat:** [{channel_name}](<{video_url}>)"
                        )

                        # Join all parts with newlines
                        content = "\n".join(content_parts)

                        # Send the message to the Discord channel
                        await channel.send(content)
                    except Exception as e:
                        logger.error(f"Error sending chat message: {e}")

    def _get_status_color(self, status: str) -> discord.Color:
        """Get the embed color for a stream status.

        Args:
            status: The stream status

        Returns:
            discord.Color: The color to use for the embed
        """
        if status == "live":
            return discord.Color.red()
        elif status == "upcoming":
            return discord.Color.blue()
        else:
            return discord.Color.light_grey()


def main():
    """Main entry point for the bot."""

    dotenv = DotEnvConfig.load_env()
    bot = DiscordBot(dotenv)

    @bot.event
    async def on_ready():
        """Event handler for when the bot is ready."""
        logger.info(f"{bot.user} has connected to Discord!")
        logger.info(f"Connected to {len(bot.guilds)} guilds")
        logger.info(f"Owner ID: {dotenv.owner_id}")

    # Import commands here to avoid circular imports
    from otomopy.commands import admin, blacklist, relay, system

    # Register commands with permission checking enforcement
    register_admin = ensure_permission_checked()(admin.register_commands)
    register_blacklist = ensure_permission_checked()(blacklist.register_commands)
    register_relay = ensure_permission_checked()(relay.register_commands)
    register_system = ensure_permission_checked()(system.register_commands)

    register_admin(bot)
    register_blacklist(bot)
    register_relay(bot)
    register_system(bot)

    # Run the bot
    logger.info("Starting bot...")
    try:
        bot.run(dotenv.token)
    except Exception as e:
        logger.error(f"Error running bot: {e}")
    finally:
        # Make sure we clean up the Holodex manager task
        if bot.holodex_task and not bot.holodex_task.done():
            try:
                bot.holodex_task.cancel()
                logger.info("Holodex task cancelled")
            except Exception as e:
                logger.error(f"Error cancelling Holodex task: {e}")

        try:
            # Run the event loop one last time to allow the Holodex manager to clean up
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(bot.holodex_manager.stop())
            loop.close()
            logger.info("Holodex manager cleanup complete")
        except Exception as e:
            logger.error(f"Error during Holodex manager cleanup: {e}")

        logger.info("Bot shutdown complete")
