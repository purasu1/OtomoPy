"""
Relay commands for Holodex integration.

This module provides commands for managing YouTube channel relays via Holodex.
"""

import logging
from typing import List

import discord
from discord import app_commands

logger = logging.getLogger(__name__)


def register_commands(bot):
    """Register relay commands with the bot.

    Args:
        bot: The DiscordBot instance
    """

    async def channel_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete callback for channel search.

        Args:
            interaction: The Discord interaction
            current: Current input string

        Returns:
            List of matching channel choices
        """
        logger.info(f"Autocomplete request with query: '{current}'")
        if not current or len(current.strip()) < 2:
            logger.info("Query too short, returning empty results")
            return []

        # Normalize the search query
        query = current.lower().strip()

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

        # Search the cache for matching channels
        matches = []
        for channel in cached_channels:
            channel_name = channel.get("name", "").lower()
            channel_english_name = channel.get("english_name")
            channel_english_name = "" if not channel_english_name else channel_english_name.lower()

            # Check if query is in either name
            if query in channel_name or query in channel_english_name:
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

        logger.info(f"Returning {len(choices)} autocomplete choices")
        return choices

    @bot.tree.command(
        name="relay",
        description="Add a YouTube channel to relay in this Discord channel",
    )
    @app_commands.describe(channel_id="The YouTube channel name or ID to relay")
    @app_commands.autocomplete(channel_id=channel_autocomplete)
    @discord.app_commands.default_permissions(manage_messages=True)
    async def relay_add(interaction: discord.Interaction, channel_id: str):
        """Add a YouTube channel to relay in the current Discord channel.

        This will relay both stream notifications and live chat translations
        from the specified YouTube channel to this Discord channel.

        Args:
            interaction: The Discord interaction
            channel_id: The YouTube channel ID to relay
        """
        # Defer the response since this might take time
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild or not isinstance(
            interaction.channel, (discord.TextChannel, discord.Thread)
        ):
            await interaction.followup.send(
                "This command can only be used in a server text channel or thread.", ephemeral=True
            )
            return

        # Verify the channel exists on YouTube via Holodex
        channel_info = await bot.holodex_manager.api.get_channel_info(channel_id)
        if not channel_info:
            await interaction.followup.send(
                f"Could not find YouTube channel with ID `{channel_id}`. "
                f"Please verify the ID is correct.\n\n"
                f"The ID should start with 'UC' and be 24 characters long.",
                ephemeral=True,
            )
            return

        # Add the relay configuration
        success = bot.config.add_relay_channel(
            interaction.guild.id, interaction.channel.id, channel_id
        )

        channel_name = channel_info.get("name", channel_id)
        channel_photo = channel_info.get("photo", "")

        # Create an embed for a nicer response
        embed = discord.Embed(
            title="YouTube Channel Relay" if success else "Relay Already Exists",
            color=discord.Color.green() if success else discord.Color.blue(),
        )

        embed.add_field(name="Channel", value=f"**{channel_name}**", inline=False)
        embed.add_field(name="Discord Channel", value=f"<#{interaction.channel.id}>", inline=False)
        if channel_photo:
            embed.set_thumbnail(url=channel_photo)

        if success:
            # Update the set of tracked channels
            await bot.update_tracked_channels()
            embed.description = "✅ Successfully added relay for this YouTube channel!"
        else:
            embed.description = (
                "ℹ️ This YouTube channel is already being relayed to this Discord channel."
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(
        name="unrelay",
        description="Remove a YouTube channel relay from this Discord channel",
    )
    @app_commands.describe(channel_id="The YouTube channel name or ID to stop relaying")
    @app_commands.autocomplete(channel_id=channel_autocomplete)
    @discord.app_commands.default_permissions(manage_messages=True)
    async def relay_remove(interaction: discord.Interaction, channel_id: str):
        """Remove a YouTube channel relay from the current Discord channel.

        Args:
            interaction: The Discord interaction
            channel_id: The YouTube channel ID to stop relaying
        """
        # Defer the response since this might take time
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild or not isinstance(
            interaction.channel, (discord.TextChannel, discord.Thread)
        ):
            await interaction.followup.send(
                "This command can only be used in a server text channel or thread.", ephemeral=True
            )
            return

        # Try to get channel info for a better response message
        channel_info = await bot.holodex_manager.api.get_channel_info(channel_id)
        channel_name = channel_info.get("name", channel_id) if channel_info else channel_id

        # Remove the relay configuration
        success = bot.config.remove_relay_channel(
            interaction.guild.id, interaction.channel.id, channel_id
        )

        # Create an embed for a nicer response
        embed = discord.Embed(
            title="YouTube Relay Removed" if success else "Relay Not Found",
            color=discord.Color.orange() if success else discord.Color.red(),
            description=(
                "✅ Successfully removed relay."
                if success
                else "❌ This channel is not being relayed here."
            ),
        )

        embed.add_field(
            name="Channel",
            value=f"**{channel_name}**" if channel_info else f"`{channel_id}`",
            inline=False,
        )
        embed.add_field(name="Discord Channel", value=f"<#{interaction.channel.id}>", inline=False)

        if success:
            # Update the set of tracked channels
            await bot.update_tracked_channels()
            if channel_info and channel_info.get("photo"):
                embed.set_thumbnail(url=channel_info.get("photo"))

        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(
        name="relays",
        description="List all YouTube channel relays for this Discord channel",
    )
    @discord.app_commands.default_permissions(manage_messages=True)
    async def relay_list(interaction: discord.Interaction):
        """List all YouTube channel relays for the current Discord channel.

        Args:
            interaction: The Discord interaction
        """
        # Defer the response since this might take time if there are many channels
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild or not isinstance(
            interaction.channel, (discord.TextChannel, discord.Thread)
        ):
            await interaction.followup.send(
                "This command can only be used in a server text channel or thread.", ephemeral=True
            )
            return

        # Get relay configurations for this Discord channel
        relay_channels = bot.config.get_relay_channels(interaction.guild.id, interaction.channel.id)

        if not relay_channels:
            embed = discord.Embed(
                title="Channel Relays",
                description="No YouTube channels are being relayed to this Discord channel.",
                color=discord.Color.blue(),
            )
            embed.add_field(
                name="How to add",
                value="Use `/relay` and type at least 2 characters of a VTuber name to see autocomplete suggestions",
                inline=False,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Create an embed for the list
        embed = discord.Embed(
            title="YouTube Channel Relays",
            description=f"The following channels are being relayed to <#{interaction.channel.id}>",
            color=discord.Color.blue(),
        )

        # Add each channel as a field
        for i, youtube_id in enumerate(relay_channels.keys(), 1):
            # Try to get channel info from Holodex
            channel_info = await bot.holodex_manager.api.get_channel_info(youtube_id)

            if channel_info:
                channel_name = channel_info.get("name", youtube_id)
                channel_type = channel_info.get("type", "Unknown")

                # Format the field content
                field_value = f"ID: `{youtube_id}`\nType: {channel_type}"

                # Set a thumbnail for the first channel in the list
                if i == 1 and channel_info.get("photo"):
                    embed.set_thumbnail(url=channel_info.get("photo"))

                embed.add_field(name=f"{i}. {channel_name}", value=field_value, inline=True)
            else:
                embed.add_field(
                    name=f"{i}. Unknown Channel",
                    value=f"ID: `{youtube_id}`",
                    inline=True,
                )

        # Add a footer with a hint
        embed.set_footer(
            text="Use /unrelay and type at least 2 characters of a VTuber name to see autocomplete suggestions"
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    # Slash command for blacklisting by username
    @bot.tree.command(
        name="blacklist_vtuber",
        description="Add a VTuber to the blacklist",
    )
    @app_commands.describe(channel_id="The YouTube channel name or ID to blacklist")
    @app_commands.autocomplete(channel_id=channel_autocomplete)
    @discord.app_commands.default_permissions(manage_messages=True)
    async def blacklist_vtuber(interaction: discord.Interaction, channel_id: str):
        """Blacklist a VTuber.

        Args:
            interaction: The Discord interaction
            username: The VTuber to blacklist
        """
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server", ephemeral=True
            )
            return

        channel_info = await bot.holodex_manager.api.get_channel_info(channel_id)
        username = channel_info["name"]

        # Use the username directly without any modifications
        # Check if already blacklisted
        if bot.config.is_user_blacklisted(interaction.guild.id, username):
            await interaction.response.send_message(
                f"**{username}** is already blacklisted", ephemeral=True
            )
            return

        # Add to blacklist
        success = bot.config.add_blacklisted_user(interaction.guild.id, username)

        if success:
            await interaction.response.send_message(
                f"✅ **{username}** has been added to the blacklist.\n"
                f"Their messages will no longer be relayed in this server.",
                ephemeral=True,
            )
            logger.info(
                f"User {interaction.user} blacklisted VTuber {username} "
                f"in guild {interaction.guild.name} ({interaction.guild.id})"
            )
        else:
            await interaction.response.send_message(
                f"Failed to blacklist **{username}**", ephemeral=True
            )
