"""
OtomoPy Discord bot module.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime

import discord
from discord import app_commands
from dotenv import load_dotenv

from otomopy.config import GuildConfig
from otomopy.holodex import ChatMessage, HolodexManager, StreamEvent

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

SCRUB_EMOTES = re.compile(r":([^:]+):https://[^\s]+")


@dataclass
class DotEnvConfig:
    token: str
    owner_id: int
    config_file: str
    holodex_api_key: str
    deepl_api_key: str | None

    @classmethod
    def load_env(cls) -> DotEnvConfig:
        load_dotenv()
        token = os.getenv("DISCORD_TOKEN")
        if token is None:
            raise RuntimeError("No Discord token found. Please add DISCORD_TOKEN to your .env file")

        owner_id = os.getenv("OWNER_ID")
        if owner_id is None:
            raise RuntimeError("No owner ID found. Please add OWNER_ID to your .env file")
        try:
            owner_id = int(owner_id)
        except ValueError:
            raise ValueError("Invalid owner ID. Please ensure it is an integer.")

        config_file = os.getenv("CONFIG_FILE")
        if config_file is None:
            raise RuntimeError("No config file found. Please add CONFIG_FILE to your .env file")

        holodex_api_key = os.getenv("HOLODEX_API_KEY")
        if holodex_api_key is None:
            raise RuntimeError(
                "No Holodex API key found. Please add HOLODEX_API_KEY to your .env file"
            )

        deepl_api_key = os.getenv("DEEPL_API_KEY")

        return cls(token, owner_id, config_file, holodex_api_key, deepl_api_key)


class DiscordBot(discord.Client):
    """Discord bot client with slash command support and permissions system."""

    def __init__(self, dotenv: DotEnvConfig):
        # Load config
        self.dotenv = dotenv

        # Set up minimal intents
        intents = discord.Intents.default()
        intents.message_content = (
            False  # Disable message content intent as it's not needed for slash commands
        )

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

        # DeepL integration
        self.deepl = None
        if dotenv.deepl_api_key:
            try:
                from deepl import DeepLClient  # pyright: ignore
            except ImportError:
                logger.warning(
                    "DeepL API key provided, but deepl package is not installed. Disabling translation."
                )
            else:
                self.deepl = DeepLClient(dotenv.deepl_api_key)

    async def setup_hook(self):
        """Set up the bot and synchronize commands."""
        # This copies the global commands over to your guild.
        # await self.tree.sync(guild=discord.Object(id=YOUR_GUILD_ID))  # For testing in a specific server
        await self.tree.sync()  # For global commands

        # Start tracking Holodex channels
        await self.update_tracked_channels()
        self.holodex_task = asyncio.create_task(self.start_holodex_tracking())
        self.holodex_chat_messages_received = 0

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
        logger.info(f"Stream event: {event.channel_name} - {event.title} - {event.status}")

        embed = await self._format_stream_event(event)

        # Find all Discord channels this should be relayed to
        for guild_id_str, guild_config in self.config.data.items():
            relay_channels = guild_config.get("relay_channels", {})

            # If this YouTube channel is being relayed in this guild
            if event.channel_id in relay_channels:
                for discord_channel_id_str in relay_channels[event.channel_id]:
                    # Get the Discord channel
                    channel = self.get_channel(
                        int(discord_channel_id_str)
                    )  # Send the embed to the Discord channel
                    if isinstance(channel, discord.TextChannel):
                        await channel.send(embed=embed)

    async def _format_stream_event(self, event: StreamEvent) -> discord.Embed:
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
                embed.add_field(name="Viewers", value=f"{event.live_viewers:,}")
        elif event.status == "upcoming":
            embed.description = ":soon: **UPCOMING**"
            if event.start_time:
                # Handle the timestamp
                try:
                    dt = datetime.fromisoformat(event.start_time.replace("Z", "+00:00"))
                    timestamp = int(dt.timestamp())
                    embed.add_field(
                        name="Scheduled for",
                        value=f"<t:{timestamp}:F> (<t:{timestamp}:R>)",
                    )
                except Exception as e:
                    logger.error(f"Error formatting timestamp: {e}")
        return embed

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
        logger.debug(f"Message details: {message}")

        # Only process messages from translators or vtubers
        if not (message.is_tl or message.is_vtuber):
            return

        # Log every 10th message to avoid flooding logs at INFO level
        if self.holodex_chat_messages_received % 10 == 0:
            logger.info(
                f"Chat messages received: {self.holodex_chat_messages_received}, Latest: {message.author} - {message.message}"
            )

        # If the message author is a vtuber, see if we can find their channel ID
        message_author_channel_id = None
        if message.is_vtuber:
            message_author_channel = self.holodex_manager.channel_cache.get_channel_by_name(
                message.author
            )
            if message_author_channel is not None:
                message_author_channel_id = message_author_channel.get("id")

        formatted_message = await self._format_message(
            message,
            message_author_channel_id,
        )

        # Find all Discord channels this should be relayed to
        for guild_id_str, guild_config in self.config.data.items():
            # Check if the message author is blacklisted in this guild
            # Use translator name directly without any modifications
            guild_id = int(guild_id_str)
            if self.config.is_user_blacklisted(guild_id, message.author):
                logger.debug(
                    f"Skipping message from blacklisted user {message.author} in guild {guild_id}"
                )
                continue

            # Get all channels on this guild to relay the message to
            relay_channels = guild_config.get("relay_channels", {})
            discord_channels = set(relay_channels.get(message.channel_id, []))
            if message_author_channel_id is not None:
                discord_channels.update(set(relay_channels.get(message_author_channel_id, [])))

            for discord_channel_id_str in discord_channels:
                try:
                    # Get the Discord channel
                    channel = self.get_channel(int(discord_channel_id_str))
                    if not channel or not isinstance(channel, discord.TextChannel):
                        continue

                    # Send the message to the Discord channel
                    await channel.send(formatted_message)
                except Exception:
                    logger.exception("Error sending chat message:")

    async def _format_message(
        self,
        message: ChatMessage,
        message_author_channel_id: int | None,
    ) -> str:
        # Clean up message text by replacing backticks and stripping emote URLs
        clean_message = SCRUB_EMOTES.sub(r":\1:", message.message.replace("`", "''"))

        translation = None
        if self.deepl and message.is_vtuber:
            try:
                result = self.deepl.translate_text(clean_message, target_lang="EN-GB")
                # Don't return the translation if the source language is already English,
                # or if the translation is identical to the original message.
                if (
                    result.detected_source_lang != "EN"
                    and result.text.lower().strip() != clean_message.lower().strip()
                ):
                    # If any backticks happened to get re-inserted by DeepL, remove
                    # them again.
                    translation = result.text.replace("`", "''")
                    logger.debug(f"Translated message: {translation}")
                else:
                    logger.debug("Didn't translate message. Source language is already English")
            except Exception:
                logger.exception("Failed to translate message:")

        emote = ":speech_balloon:"
        if message.is_vtuber:
            # Display vtuber names clearly
            author_display = f"**{message.author}:**"
            channel = self.holodex_manager.channel_cache.get_channel_by_name(message.author)
            if channel is not None:
                emote = self.config.get_emote(channel.get("org", ""), ":speech_balloon:")
        else:
            # Use spoiler tags for translator name
            author_display = f"||{message.author}:||"
            emote = ":speech_balloon:"

        # Add chat source link
        video_url = f"https://www.youtube.com/watch?v={message.video_id}"

        # Build the message content
        content_parts = [f"{emote} [{author_display}](<{video_url}>) `{clean_message}`"]

        # Get channel name from current streams if available
        channel_name = "YouTube Chat"
        if message.video_id in self.holodex_manager.current_streams:
            stream_event = self.holodex_manager.current_streams[message.video_id]
            channel_name = stream_event.channel_name

        if message.channel_id != message_author_channel_id:
            content_parts.append(f"**Chat:** [{channel_name}](<{video_url}>)")

        if translation is not None:
            # TODO: add custom DeepL emote
            deepl_icon = self.config.get_emote("DeepL", "**DeepL:**")
            content_parts.append(f"{deepl_icon} `{translation}`")

        # Join all parts with newlines
        return "\n".join(content_parts)

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
    from otomopy.commands import blacklist, relay, system, emotes

    # Register commands with permission checking enforcement
    blacklist.register_commands(bot)
    relay.register_commands(bot)
    system.register_commands(bot)
    emotes.register_commands(bot)

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
