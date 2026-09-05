import logging

import discord
from discord import Webhook

logger = logging.getLogger(__name__)

# Webhooks are named after the channel's immutable ID rather than its name, so that
# renaming a channel does not orphan its webhook and cause a duplicate to be created.
WEBHOOK_NAME_PREFIX = "OtomoPy - "


def webhook_name(channel: discord.TextChannel | discord.ForumChannel) -> str:
    """Return the canonical webhook name for a channel.

    Args:
        channel: Discord channel object

    Returns:
        Name of the webhook this bot owns in that channel
    """
    return f"{WEBHOOK_NAME_PREFIX}{channel.id}"


class WebhookManager:
    """Manages Discord webhooks organized by guild and channel."""

    def __init__(self):
        """Initialize the webhook manager with an empty nested dictionary."""
        self._webhooks: dict[int, dict[int, Webhook]] = {}

    async def get_or_create_webhook(
        self, channel: discord.TextChannel | discord.ForumChannel | discord.Thread
    ) -> Webhook | None:
        """Get an existing webhook or create a new one for the specified Discord channel.

        Args:
            channel: Discord channel object to create webhook in

        Returns:
            Webhook object if successful, None if failed
        """
        if isinstance(channel, discord.Thread):
            # Get parent channel
            if channel.parent is None:
                logger.error(f"Thread {channel.id} has no parent channel")
                return None
            return await self.get_or_create_webhook(channel.parent)

        # Check if webhook already exists and is valid
        existing_webhook = self._get_webhook(channel)
        if existing_webhook:
            if await self._is_webhook_valid(existing_webhook):
                logger.debug(f"Using existing webhook channel {channel.id}")
                return existing_webhook
            else:
                logger.info(f"Existing webhook for {channel.name} is invalid, removing from cache")
                self._remove_webhook(channel)

        # Create new webhook
        try:
            webhook = await self._create_webhook(channel)
            if webhook is None:
                logger.error(f"Failed to create webhook in channel {channel.id}")
                return None

            # Store webhook in nested dictionary
            self._store_webhook(channel, webhook)

            return webhook

        except discord.HTTPException:
            logger.exception(f"Failed to create webhook in channel {channel.id}")
            return None
        except Exception:
            logger.exception(f"Unexpected error creating webhook for {channel.name}")
            return None

    async def _create_webhook(
        self, channel: discord.TextChannel | discord.ForumChannel
    ) -> Webhook | None:
        """Find this bot's webhook in a channel, creating it if it does not exist yet.

        Args:
            channel: Discord channel object

        Returns:
            Webhook object owned by this bot in that channel
        """
        name = webhook_name(channel)

        # Look for a webhook under the canonical name, falling back to one created under
        # an older naming scheme (which embedded the guild and channel names).
        legacy: Webhook | None = None
        for webhook in await channel.webhooks():
            if webhook.name == name:
                logger.info(f"Found existing webhook in channel {channel.id}")
                return webhook
            if legacy is None and webhook.name and webhook.name.startswith(WEBHOOK_NAME_PREFIX):
                legacy = webhook

        if legacy is not None:
            logger.info(f"Adopting webhook {legacy.name!r} in channel {channel.id} as {name!r}")
            try:
                return await legacy.edit(name=name, reason="Key webhook on the channel ID")
            except discord.HTTPException:
                # Renaming is only a cleanup; the webhook itself is still usable.
                logger.exception(f"Failed to rename webhook in channel {channel.id}")
                return legacy

        # Create new webhook if not found
        logger.info(f"Creating new webhook in channel {channel.id}")
        return await channel.create_webhook(
            name=name, reason=f"Relay VTuber messages in channel {channel.id}"
        )

    def _get_webhook(self, channel: discord.TextChannel | discord.ForumChannel) -> Webhook | None:
        """Get webhook for a specific channel.

        Args:
            channel: Discord channel object

        Returns:
            Webhook object if found, None otherwise
        """
        return self._webhooks.get(channel.guild.id, {}).get(channel.id)

    def _store_webhook(
        self, channel: discord.TextChannel | discord.ForumChannel, webhook: Webhook
    ) -> None:
        """Store webhook in the nested dictionary structure.

        Args:
            channel: Discord channel object
            webhook: Webhook object to store
        """
        if channel.guild.id not in self._webhooks:
            self._webhooks[channel.guild.id] = {}

        self._webhooks[channel.guild.id][channel.id] = webhook

    def _remove_webhook(self, channel: discord.TextChannel | discord.ForumChannel) -> None:
        """Remove webhook from the nested dictionary structure.

        Args:
            channel: Discord channel object
        """
        if channel.guild.id in self._webhooks and channel.id in self._webhooks[channel.guild.id]:

            del self._webhooks[channel.guild.id][channel.id]

    async def _is_webhook_valid(self, webhook: Webhook) -> bool:
        """Check if a webhook is still valid and accessible.

        Args:
            webhook: Webhook object to validate

        Returns:
            True if webhook is valid, False otherwise
        """
        try:
            # Try to fetch webhook to see if it still exists
            await webhook.fetch()
            return True
        except discord.NotFound:
            logger.debug("Webhook no longer exists")
            return False
        except discord.HTTPException as e:
            logger.warning(f"HTTP error validating webhook: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error validating webhook: {e}")
            return False
