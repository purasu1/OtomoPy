"""
Relay commands for Holodex integration.

This module provides commands for managing YouTube channel relays via Holodex.
"""

import logging
from typing import List

import discord
from discord import app_commands

from .autocomplete import channel_autocomplete

logger = logging.getLogger(__name__)


def register_commands(bot):
    """Register relay commands with the bot.

    Args:
        bot: The DiscordBot instance
    """

    async def channel_autocomplete_wrapper(
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """Wrapper for the shared channel autocomplete function."""
        return await channel_autocomplete(bot, interaction, current)

    async def relay_remove_autocomplete_wrapper(
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """Wrapper for the shared channel autocomplete function (relayed only)."""
        return await channel_autocomplete(bot, interaction, current, filter_relayed_only=True)

    # Create a command group for relay commands
    relay_group = app_commands.Group(name="relay", description="Manage YouTube channel relays")

    @relay_group.command(
        name="add",
        description="Add a YouTube channel to relay in this Discord channel",
    )
    @app_commands.describe(channel_id="The YouTube channel name or ID to relay")
    @app_commands.autocomplete(channel_id=channel_autocomplete_wrapper)
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

        # First check if channel exists in our cache
        channel_info = bot.holodex_manager.channel_cache.get_channel_by_id(channel_id)

        # If not in cache, verify the channel exists on YouTube via Holodex API
        if not channel_info:
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

    @relay_group.command(
        name="remove",
        description="Remove a YouTube channel relay from this Discord channel",
    )
    @app_commands.describe(channel_id="The YouTube channel name or ID to stop relaying")
    @app_commands.autocomplete(channel_id=relay_remove_autocomplete_wrapper)
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

        # Try to get channel info from cache for a better response message
        channel_info = bot.holodex_manager.channel_cache.get_channel_by_id(channel_id)
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

    @relay_group.command(
        name="list",
        description="List all YouTube channel relays for this Discord channel",
    )
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
                value="Use `/relay add` and type at least 2 characters of a VTuber name to see autocomplete suggestions",
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
            # Try to get channel info from cache
            channel_info = bot.holodex_manager.channel_cache.get_channel_by_id(youtube_id)

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
            text="Use `/relay remove` and type at least 2 characters of a VTuber name to see autocomplete suggestions"
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    class RelayListView(discord.ui.View):
        """View for paginated relay list display."""

        def __init__(self, pages: List[discord.Embed], timeout: float = 300.0):
            super().__init__(timeout=timeout)
            self.pages = pages
            self.current_page = 0

            # Disable buttons if only one page
            if len(pages) <= 1:
                self.previous_page.disabled = True
                self.next_page.disabled = True
            else:
                self.previous_page.disabled = True  # Start with previous disabled

        def update_buttons(self):
            """Update button states based on current page."""
            self.previous_page.disabled = self.current_page == 0
            self.next_page.disabled = self.current_page == len(self.pages) - 1

        @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
        async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.current_page > 0:
                self.current_page -= 1
                self.update_buttons()
                await interaction.response.edit_message(
                    embed=self.pages[self.current_page], view=self
                )

        @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
        async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.current_page < len(self.pages) - 1:
                self.current_page += 1
                self.update_buttons()
                await interaction.response.edit_message(
                    embed=self.pages[self.current_page], view=self
                )

        async def on_timeout(self):
            """Disable all buttons when the view times out."""
            for item in self.children:
                item.disabled = True

    async def create_relay_pages(
        guild_id: int, channels_data: dict, title_prefix: str, description: str
    ) -> List[discord.Embed]:
        """Create paginated embeds for relay data.

        Args:
            guild_id: The guild ID
            channels_data: Dict mapping discord channel IDs to lists of YouTube channel IDs
            title_prefix: Prefix for embed titles
            description: Description for the embeds

        Returns:
            List of Discord embeds for pagination
        """
        if not channels_data:
            embed = discord.Embed(
                title=f"{title_prefix} - No Relays",
                description="No YouTube channels are being relayed in the specified scope.",
                color=discord.Color.blue(),
            )
            embed.add_field(
                name="How to add",
                value="Use `/relay add` in a channel and type at least 2 characters of a VTuber name to see autocomplete suggestions",
                inline=False,
            )
            return [embed]

        pages = []
        channels_per_page = 5
        current_page_channels = 0
        current_embed = None

        for discord_channel_id, youtube_channels in channels_data.items():
            # Create new embed if needed
            if current_embed is None or current_page_channels >= channels_per_page:
                if current_embed is not None:
                    pages.append(current_embed)

                page_num = len(pages) + 1
                current_embed = discord.Embed(
                    title=f"{title_prefix} (Page {page_num})",
                    description=description,
                    color=discord.Color.blue(),
                )
                current_page_channels = 0

            # Format YouTube channels list
            youtube_channel_lines = []
            for i, youtube_id in enumerate(
                youtube_channels[:10], 1
            ):  # Limit to 10 per Discord channel
                # Try to get channel info from cache
                channel_info = bot.holodex_manager.channel_cache.get_channel_by_id(youtube_id)
                if channel_info:
                    channel_display = f"**{channel_info.get('name', youtube_id)}**"
                else:
                    channel_display = f"`{youtube_id}`"

                youtube_channel_lines.append(f"{i}. {channel_display}")

            if len(youtube_channels) > 10:
                youtube_channel_lines.append(f"... and {len(youtube_channels) - 10} more")

            field_value = (
                "\n".join(youtube_channel_lines) if youtube_channel_lines else "No channels"
            )
            current_embed.add_field(
                name=f"<#{discord_channel_id}>", value=field_value, inline=False
            )
            current_page_channels += 1

        # Add the last embed if it exists
        if current_embed is not None:
            pages.append(current_embed)

        # Update page numbers in titles if multiple pages
        if len(pages) > 1:
            for i, page in enumerate(pages, 1):
                page.title = f"{title_prefix} (Page {i}/{len(pages)})"
                page.set_footer(
                    text=f"Use `/relay add` in a channel to add new relays • Page {i}/{len(pages)}"
                )
        else:
            pages[0].title = title_prefix
            pages[0].set_footer(text="Use `/relay add` in a channel to add new relays")

        return pages

    @relay_group.command(
        name="list-guild",
        description="List all YouTube channel relays for the entire server",
    )
    async def relay_list_guild(interaction: discord.Interaction):
        """List all YouTube channel relays for the entire guild.

        Args:
            interaction: The Discord interaction
        """
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild:
            await interaction.followup.send(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        # Get all relay configurations for this guild
        all_relay_channels = bot.config.get_relay_channels(interaction.guild.id)

        # Reorganize data by Discord channel for better display
        channels_data = {}
        for youtube_id, discord_channel_ids in all_relay_channels.items():
            for discord_channel_id in discord_channel_ids:
                if discord_channel_id not in channels_data:
                    channels_data[discord_channel_id] = []
                channels_data[discord_channel_id].append(youtube_id)

        # Create paginated embeds
        pages = await create_relay_pages(
            interaction.guild.id,
            channels_data,
            f"🌐 All Server Relays - {interaction.guild.name}",
            f"All YouTube channel relays across the entire server ({len(channels_data)} channels with relays)",
        )

        # Send with pagination if multiple pages
        if len(pages) > 1:
            view = RelayListView(pages)
            await interaction.followup.send(embed=pages[0], view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=pages[0], ephemeral=True)

    @relay_group.command(
        name="list-category",
        description="List all YouTube channel relays for channels in the current category",
    )
    async def relay_list_category(interaction: discord.Interaction):
        """List all YouTube channel relays for channels in the current category.

        Args:
            interaction: The Discord interaction
        """
        logging.info("Listing relays for category")
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild or not isinstance(
            interaction.channel, (discord.TextChannel, discord.Thread)
        ):
            await interaction.followup.send(
                "This command can only be used in a server text channel or thread.", ephemeral=True
            )
            return

        # Get the category of the current channel
        current_channel = interaction.channel
        if isinstance(current_channel, discord.Thread):
            current_channel = current_channel.parent
        if current_channel is None:
            await interaction.followup.send(
                "This command can only be used in a server text channel or thread.", ephemeral=True
            )
            return

        category = current_channel.category
        category_name = category.name if category else "Uncategorized"
        category_id = category.id if category else None

        # Collect all channels or threads with existing relays on the guild
        relay_channels = bot.config.get_relay_channels(interaction.guild.id)
        channels_data = {}
        for youtube_id, discord_channel_ids in relay_channels.items():
            for discord_channel_id in discord_channel_ids:
                channel = interaction.guild.get_channel_or_thread(int(discord_channel_id))
                if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                    logging.warning(f"Channel {discord_channel_id} is not a text channel or thread")
                    continue
                if channel is None:
                    continue
                if isinstance(channel, discord.Thread) and channel.parent is not None:
                    channel = channel.parent
                if channel.category_id == category_id:
                    channels_data[discord_channel_id] = []
                    channels_data[discord_channel_id].append(youtube_id)

        # Create paginated embeds
        pages = await create_relay_pages(
            interaction.guild.id,
            channels_data,
            f"📁 Category Relays - {category_name}",
            f"YouTube channel relays in the '{category_name}' category ({len(channels_data)} channels with relays)",
        )

        # Send with pagination if multiple pages
        if len(pages) > 1:
            view = RelayListView(pages)
            await interaction.followup.send(embed=pages[0], view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=pages[0], ephemeral=True)

    # Add the relay group to the command tree with proper permissions
    relay_group.default_permissions = discord.Permissions(manage_messages=True)
    bot.tree.add_command(relay_group)
