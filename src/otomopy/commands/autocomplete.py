"""
Shared autocomplete utilities for Discord commands.

This module provides reusable autocomplete functions that can be used
across different command modules.
"""

import logging
from typing import List

import discord
from discord import app_commands

logger = logging.getLogger(__name__)


async def channel_autocomplete(
    bot,
    interaction: discord.Interaction,
    current: str,
    filter_relayed_only: bool = False,
) -> List[app_commands.Choice[str]]:
    """Autocomplete callback for channel search.

    Args:
        bot: The DiscordBot instance
        interaction: The Discord interaction
        current: Current input string
        filter_relayed_only: If True, only show channels currently relayed in this Discord channel

    Returns:
        List of matching channel choices
    """
    logger.info(
        f"Autocomplete request with query: '{current}', filter_relayed_only: {filter_relayed_only}"
    )

    # For regular search, require at least 2 characters, but for relayed-only allow shorter queries
    min_length = 1 if filter_relayed_only else 2
    if not current or len(current.strip()) < min_length:
        if not filter_relayed_only:
            logger.info("Query too short, returning empty results")
            return []

    # Normalize the search query
    query = current.lower().strip() if current else ""

    if not hasattr(bot, "holodex_manager"):
        logger.info("Holodex manager not initialized")
        return []

    if not hasattr(bot.holodex_manager, "channel_cache"):
        logger.info("Channel cache not initialized")
        return []

    cached_channels = bot.holodex_manager.channel_cache.get_channels()
    if not cached_channels:
        logger.info("No cached channels found")
        return []

    # If filtering for relayed channels only, get the list of relayed channel IDs
    relayed_channel_ids = []
    if filter_relayed_only:
        # For relayed-only filtering, we need guild and channel context
        if interaction.guild is None or not isinstance(
            interaction.channel, (discord.TextChannel, discord.Thread)
        ):
            logger.info("Not in a valid guild/channel context for relayed filtering")
            return []

        relay_channels = bot.config.get_relay_channels(interaction.guild.id, interaction.channel.id)
        if not relay_channels:
            logger.info("No relay channels found for this Discord channel")
            return []
        relayed_channel_ids = list(relay_channels.keys())
        logger.info(f"Found {len(relayed_channel_ids)} relayed channels")

    # Search the cache for matching channels
    matches = []
    for channel in cached_channels:
        # If filtering for relayed only, skip channels not in the relayed list
        channel_id = channel.get("id", "")
        if filter_relayed_only and channel_id not in relayed_channel_ids:
            continue

        channel_name = channel.get("name", "").lower()
        channel_english_name = channel.get("english_name")
        channel_english_name = "" if not channel_english_name else channel_english_name.lower()

        # Check if query is in either name (or if no query for relayed-only mode)
        if not query or query in channel_name or query in channel_english_name:
            matches.append(channel)

    # Format results as choices
    choices = []
    for vtuber in matches[:25]:  # Discord limits to 25 choices
        name = vtuber.get("name", "")
        channel_id = vtuber.get("id", "")
        org = vtuber.get("org", "")
        english_name = vtuber.get("english_name", "")

        # Format the display name
        if english_name and english_name.lower() not in name.lower():
            display_name = f"{english_name} ({name})"
        else:
            display_name = name

        # Add organization
        if org:
            display_name = f"{display_name} [{org}]"

        # Add to choices
        choices.append(
            app_commands.Choice(
                name=display_name[:100],  # Discord limits to 100 chars
                value=channel_id,
            )
        )

    suffix = " (relayed only)" if filter_relayed_only else ""
    logger.info(f"Returning {len(choices)} autocomplete choices{suffix}")
    return choices
