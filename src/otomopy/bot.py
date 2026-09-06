"""
OtomoPy Discord bot module.
"""

# on_ready is registered by @bot.event, never called by name. The commands package
# is imported inside main() and imports DiscordBot back under TYPE_CHECKING only.
# pyright: reportUnusedFunction=false, reportImportCycles=false

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, override

import discord
from discord import app_commands
from dotenv import find_dotenv, load_dotenv

from otomopy.config import GuildConfig
from otomopy.holodex import ChatMessage, HolodexManager, StreamEvent
from otomopy.translation.base import TranslationProvider
from otomopy.webhook_manager import WebhookManager

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(pathname)s:%(lineno)d - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

SCRUB_EMOTES = re.compile(r":([^:]+):https://[^\s]+")


@dataclass
class DotEnvConfig:
    token: str
    owner_id: int
    # Legacy JSON config, imported once and then archived. None when unset.
    config_file: str | None
    db_file: str
    holodex_api_key: str
    translation_backend: str
    deepl_api_key: str | None
    azure_translator_key: str | None
    azure_translator_region: str | None
    azure_translator_endpoint: str | None

    @staticmethod
    def find_env_file() -> str | None:
        """Locate the .env file to load, resolving from the working directory.

        python-dotenv's default resolves relative to the *calling source file*,
        so it walks up from ``src/otomopy/`` and silently ignores a .env sitting
        in the working directory -- which means running the bot from a scratch
        directory can pick up a development checkout's real credentials. That
        default also flips to the working directory on its own under a debugger,
        coverage, or a profiler, so the same command can load different files.

        ``usecwd=True`` only changes the starting point; the search still walks
        up to the filesystem root, so running from a subdirectory of a checkout
        still finds the .env at its root.
        """
        explicit = os.getenv("OTOMOPY_ENV_FILE")
        if explicit:
            if not pathlib.Path(explicit).is_file():
                raise RuntimeError(f"OTOMOPY_ENV_FILE is set to {explicit}, which does not exist")
            return explicit
        return find_dotenv(usecwd=True) or None

    @classmethod
    def load_env(cls) -> DotEnvConfig:
        env_file = cls.find_env_file()
        if env_file:
            load_dotenv(env_file)
            logger.info(f"Loaded environment from {env_file}")
        else:
            logger.warning(
                f"No .env file found searching upwards from {os.getcwd()}; "
                f"using the existing process environment"
            )

        def require(name: str) -> str:
            """Read a required setting, saying where we looked when it is absent."""
            value = os.getenv(name)
            if value is not None:
                return value
            if env_file is None:
                raise RuntimeError(
                    f"{name} is not set, and no .env file was found searching upwards "
                    f"from {os.getcwd()}. Run the bot from the directory holding your "
                    f".env, or set OTOMOPY_ENV_FILE to point at it."
                )
            raise RuntimeError(f"{name} is not set. Please add it to {env_file}")

        token = require("DISCORD_TOKEN")

        owner_id = require("OWNER_ID")
        try:
            owner_id = int(owner_id)
        except ValueError as e:
            raise ValueError("Invalid owner ID. Please ensure it is an integer.") from e

        # State lives in the database. CONFIG_FILE names the deprecated JSON
        # config: when it exists and the database is empty it is imported once
        # and archived. Both settings are optional.
        # Paths are resolved so that they, and the data directory derived from
        # them, do not depend on the working directory later changing.
        db_file = str(pathlib.Path(os.getenv("DB_FILE") or "otomopy.db").resolve())

        config_file = os.getenv("CONFIG_FILE")
        if config_file is not None:
            config_file = str(pathlib.Path(config_file).resolve())
        elif pathlib.Path("config.json").is_file() and not pathlib.Path(db_file).exists():
            logger.warning(
                "Found config.json in the working directory but CONFIG_FILE is not set, "
                "so it will not be imported. Set CONFIG_FILE to migrate it."
            )

        holodex_api_key = require("HOLODEX_API_KEY")

        translation_backend = os.getenv("TRANSLATION_BACKEND", "deepl")
        deepl_api_key = os.getenv("DEEPL_API_KEY")
        azure_translator_key = os.getenv("AZURE_TRANSLATOR_KEY")
        azure_translator_region = os.getenv("AZURE_TRANSLATOR_REGION")
        azure_translator_endpoint = os.getenv("AZURE_TRANSLATOR_ENDPOINT")

        return cls(
            token,
            owner_id,
            config_file,
            db_file,
            holodex_api_key,
            translation_backend,
            deepl_api_key,
            azure_translator_key,
            azure_translator_region,
            azure_translator_endpoint,
        )


class DiscordBot(discord.Client):
    """Discord bot client with slash command support and permissions system."""

    def __init__(self, dotenv: DotEnvConfig):
        # Load config
        self.dotenv: DotEnvConfig = dotenv

        # Set up minimal intents
        intents = discord.Intents.default()
        intents.message_content = (
            False  # Disable message content intent as it's not needed for slash commands
        )

        super().__init__(intents=intents)
        self.tree: app_commands.CommandTree[DiscordBot] = app_commands.CommandTree(self)
        self.config: GuildConfig = GuildConfig(
            db_file=self.dotenv.db_file, legacy_json_path=self.dotenv.config_file
        )

        # Initialize webhook manager
        self.webhook_manager: WebhookManager = WebhookManager()

        # Keep the channel cache alongside the database
        config_dir = os.path.dirname(self.dotenv.db_file)
        os.environ["OTOMOPY_CONFIG_DIR"] = config_dir

        # Holodex integration
        self.holodex_manager: HolodexManager = HolodexManager(dotenv.holodex_api_key, config_dir)
        self.tracked_channels: set[str] = set()
        self.holodex_task: asyncio.Task[None] | None = None
        self.holodex_chat_messages_received: int = 0

        # Translation integration
        self.translator: TranslationProvider | None = None
        if dotenv.translation_backend == "deepl" and dotenv.deepl_api_key:
            try:
                from otomopy.translation.base import DeepLProvider

                self.translator = DeepLProvider(dotenv.deepl_api_key)
            except ImportError:
                logger.warning("DeepL package is not installed. Disabling translation.")
        elif dotenv.translation_backend == "azure" and dotenv.azure_translator_key:
            from otomopy.translation.base import AzureProvider

            self.translator = AzureProvider(
                dotenv.azure_translator_key,
                dotenv.azure_translator_region,
                dotenv.azure_translator_endpoint,
            )

    @override
    async def setup_hook(self):
        """Set up the bot and synchronize commands."""
        # This copies the global commands over to your guild.
        await self.tree.sync()  # For global commands

        # Start tracking Holodex channels
        await self.update_tracked_channels()
        self.holodex_task = asyncio.create_task(self.start_holodex_tracking())

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
                self.tracked_channels,
                self.on_stream_event,
                self.on_chat_message,
                self.on_vtuber_message,
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
        for _guild_id, discord_channel_id in self.config.get_relay_targets(event.channel_id):
            try:
                channel = self.get_channel(discord_channel_id)
                if not isinstance(channel, discord.TextChannel | discord.Thread):
                    logger.warning(f"Channel {discord_channel_id} is not a text channel or thread")
                    continue

                # Send the embed to the Discord channel
                await channel.send(embed=embed)
            except Exception:
                logger.exception("Error sending stream event:")

    async def _format_stream_event(self, event: StreamEvent) -> discord.Embed:
        # Create an embed for the event
        embed = discord.Embed(
            title=event.title,
            url=f"https://www.youtube.com/watch?v={event.video_id}",
            color=self._get_status_color(event.status),
        )

        embed.set_author(name=event.channel_name)
        embed.set_image(url=event.thumbnail)

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
            f"Received chat message #{self.holodex_chat_messages_received}: "
            f"{message.author} - {message.message}"
        )
        logger.debug(f"Message details: {message}")

        # Only process non-vtuber messages from translators
        if not message.is_tl:
            return

        # Log every 10th message to avoid flooding logs at INFO level
        if self.holodex_chat_messages_received % 10 == 0:
            logger.info(
                f"Chat messages received: {self.holodex_chat_messages_received}, "
                f"Latest: {message.author} - {message.message}"
            )

        formatted_message = await self._format_message(message)

        # Find all Discord channels this should be relayed to
        for guild_id, discord_channel_id in self.config.get_relay_targets(message.channel_id):
            # Check if the message author is blacklisted in this guild
            # Use translator name directly without any modifications
            if self.config.is_user_blacklisted(guild_id, message.author):
                logger.debug(
                    f"Skipping message from blacklisted user {message.author} in guild {guild_id}"
                )
                continue

            try:
                # Get the Discord channel
                channel = self.get_channel(discord_channel_id)
                if not channel or not isinstance(channel, discord.TextChannel | discord.Thread):
                    logger.warning(f"Channel {discord_channel_id} is not a text channel or thread")
                    continue

                # Send the message to the Discord channel. Relayed chat is
                # untrusted text: never let it ping, and never let a URL in it
                # unfurl into an embed.
                await channel.send(
                    formatted_message,
                    allowed_mentions=discord.AllowedMentions.none(),
                    suppress_embeds=True,
                )
            except Exception:
                logger.exception("Error sending chat message:")

    async def _format_message(
        self,
        message: ChatMessage,
    ) -> str:
        # Strip emote URLs, then escape so Discord renders the text as it was
        # typed. Pings are stopped by allowed_mentions at send time, not here.
        clean_message = discord.utils.escape_markdown(SCRUB_EMOTES.sub(r":\1:", message.message))

        author_display = f"||{discord.utils.escape_markdown(message.author)}||"
        emote = ":speech_balloon:"

        # Add chat source link
        video_url = f"https://www.youtube.com/watch?v={message.video_id}"

        # Build the message content
        content_parts = [f"{emote} {author_display}: {clean_message}"]

        message_channel = self.holodex_manager.channel_cache.get_channel_by_id(message.channel_id)
        if message_channel is None:
            logger.warning(f"Channel not found for message {message.channel_id}")
        else:
            video_url = f"https://www.youtube.com/watch?v={message.video_id}"
            content_parts.append(f"-# Chat: [{message_channel['name']}](<{video_url}>)")

        # Join all parts with newlines
        return "\n".join(content_parts)

    async def tl_message(self, message: str) -> str | None:
        if self.translator:
            try:
                return await self.translator.translate(message, target_lang="en")
            except Exception:
                logger.exception("Error translating message:")
        return None

    async def on_vtuber_message(self, message: ChatMessage):
        """Handle a vtuber chat message event from Holodex.

        Args:
            message: The chat message
        """

        # Count messages received
        self.holodex_chat_messages_received += 1

        message_author_channel = await self.holodex_manager.get_channel(message.author)
        if message_author_channel is None:
            logger.warning(f"Channel not found for user {message.author}")
            return

        author_name = message_author_channel["english_name"]
        if not author_name:
            # English name is either null or empty, use default name
            author_name = message_author_channel["name"]

        webhook_args: dict[str, Any] = {
            "username": author_name,
            "avatar_url": message_author_channel["photo"],
            "allowed_mentions": discord.AllowedMentions.none(),
            "suppress_embeds": True,
        }

        # Assemble the chat message. The translator gets the unescaped text --
        # escaping is only for how Discord renders it.
        clean_message = SCRUB_EMOTES.sub(r":\1:", message.message)
        content_parts = [discord.utils.escape_markdown(clean_message)]

        message_translation = await self.tl_message(clean_message)
        if message_translation:
            # Use the backend name as a fallback if no specific emote is configured
            backend_name = self.translator.name if self.translator else "Translation"
            icon = self.config.get_emote(backend_name, f"**{backend_name}:**")
            content_parts.append(f"{icon} {discord.utils.escape_markdown(message_translation)}")

        message_channel = self.holodex_manager.channel_cache.get_channel_by_id(message.channel_id)
        if message_channel is None:
            logger.warning(f"Channel not found for message {message.channel_id}")
        else:
            video_url = f"https://www.youtube.com/watch?v={message.video_id}"
            content_parts.append(f"-# Chat: [{message_channel['name']}](<{video_url}>)")

        chat_message = "\n".join(content_parts)

        # Relay to channels subscribed to either the stream or the speaking VTuber
        targets = self.config.get_relay_targets(message.channel_id, message_author_channel["id"])
        for guild_id, discord_channel_id in targets:
            if self.config.is_user_blacklisted(guild_id, message_author_channel["name"]):
                logger.debug(
                    f"Skipping message from blacklisted VTuber {message_author_channel['name']} "
                    f"in guild {guild_id}"
                )
                continue

            try:
                # Get the Discord channel
                channel = self.get_channel(discord_channel_id)
                if not channel or not isinstance(channel, discord.TextChannel | discord.Thread):
                    logger.error(f"Invalid channel ID: {discord_channel_id}")
                    continue

                webhook = await self.webhook_manager.get_or_create_webhook(channel)
                if webhook is None:
                    logger.error(f"Failed to get webhook for channel {channel.id}")
                    continue

                if isinstance(channel, discord.Thread):
                    await webhook.send(chat_message, thread=channel, **webhook_args)
                else:
                    await webhook.send(chat_message, **webhook_args)
            except Exception:
                logger.exception("Error sending chat message:")

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

    async def on_app_command_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        """Report unhandled command errors instead of failing silently.

        Store mutations raise when a change could not be persisted, so the user
        must never be told a change succeeded when it did not. discord.py routes
        every unhandled command and autocomplete exception here.
        """
        logger.error("Unhandled command error", exc_info=error)
        message = (
            "\u26a0\ufe0f Something went wrong and your change was **not** saved. "
            "The bot owner has been notified."
        )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            logger.exception("Could not deliver the error message to the user:")

    bot.tree.on_error = on_app_command_error

    # Import commands here to avoid circular imports
    from otomopy.commands import blacklist, emotes, relay, system, translate

    # Register commands with permission checking enforcement
    blacklist.register_commands(bot)
    relay.register_commands(bot)
    system.register_commands(bot)
    emotes.register_commands(bot)
    translate.register_commands(bot)

    # Run the bot
    logger.info("Starting bot...")
    try:
        bot.run(dotenv.token)
    except Exception:
        logger.exception("Error running bot:")
    finally:
        # Make sure we clean up the Holodex manager task
        if bot.holodex_task and not bot.holodex_task.done():
            try:
                bot.holodex_task.cancel()
                logger.info("Holodex task cancelled")
            except Exception:
                logger.exception("Error cancelling Holodex task:")

        try:
            # Run the event loop one last time to allow the Holodex manager to clean up
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(bot.holodex_manager.stop())
            loop.close()
            logger.info("Holodex manager cleanup complete")
        except Exception:
            logger.exception("Error during Holodex manager cleanup:")

        try:
            # Checkpoints the write-ahead log so the database is a single file at rest
            bot.config.close()
            logger.info("Configuration database closed")
        except Exception:
            logger.exception("Error closing the configuration database:")

        logger.info("Bot shutdown complete")
