"""
System slash commands for OtomoPy.

These commands are for system-level operations, typically
only accessible to the bot owner.
"""

import logging

import discord

logger = logging.getLogger(__name__)


def register_commands(bot):
    """Register system commands with the bot.

    Args:
        bot: The DiscordBot instance
    """

    @bot.tree.command(name="status", description="Get bot status information")
    @discord.app_commands.default_permissions(manage_messages=True)
    async def status(interaction: discord.Interaction):
        """Get detailed information about the bot's status.

        Args:
            interaction: The Discord interaction
        """
        # Create a nice embed with status information
        embed = discord.Embed(
            title="Bot Status",
            description="Current operational status of the bot",
            color=discord.Color.blue(),
        )

        # Basic info
        embed.add_field(name="Uptime", value="Running", inline=True)
        embed.add_field(name="Guilds", value=str(len(bot.guilds)), inline=True)

        # Holodex tracking info
        tracked_channels = len(bot.tracked_channels)
        embed.add_field(name="Tracked YouTube Channels", value=str(tracked_channels), inline=True)

        # WebSocket connection status
        ws_status = (
            "Connected"
            if (hasattr(bot.holodex_manager, "ws_connected") and bot.holodex_manager.ws_connected)
            else "Disconnected"
        )
        embed.add_field(name="WebSocket Status", value=ws_status, inline=True)

        # Live streams currently being tracked
        live_stream_count = len(
            [s for s in bot.holodex_manager.current_streams.values() if s.status == "live"]
        )
        embed.add_field(name="Current Live Streams", value=str(live_stream_count), inline=True)

        # Upcoming streams being tracked
        upcoming_stream_count = len(
            [s for s in bot.holodex_manager.current_streams.values() if s.status == "upcoming"]
        )
        embed.add_field(name="Upcoming Streams", value=str(upcoming_stream_count), inline=True)

        # Chat message stats
        active_subs = len(getattr(bot.holodex_manager, "active_subscriptions", set()))
        chat_messages = getattr(bot, "holodex_chat_messages_received", 0)
        session_id = getattr(bot.holodex_manager, "session_id", "None")
        embed.add_field(name="Active Chat Subscriptions", value=str(active_subs), inline=True)
        embed.add_field(name="Chat Messages Received", value=str(chat_messages), inline=True)

        embed.add_field(
            name="WebSocket Session ID",
            value=(
                session_id[:8] + "..."
                if session_id and session_id != "None" and len(session_id) > 10
                else session_id
            ),
            inline=True,
        )

        # Show some recent tracked channels if available
        if tracked_channels > 0:
            recent_channels = list(bot.tracked_channels)[:5]
            embed.add_field(
                name="Some Tracked Channels",
                value=(
                    "\n".join([f"`{ch}`" for ch in recent_channels]) if recent_channels else "None"
                ),
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(
        name="refresh_channels",
        description="Refresh the known VTuber channel list from Holodex (owner only)",
    )
    @discord.app_commands.default_permissions(administrator=True)
    async def refresh_channels(interaction: discord.Interaction):
        """Manually refresh the cached list of VTuber channels from Holodex.

        Only the bot owner is allowed to use this command. Refresh is append-only:
        newly discovered channels are added, known channels are updated, but no
        channel is ever removed, even if Holodex no longer lists it.

        Args:
            interaction: The Discord interaction
        """
        if interaction.user.id != bot.dotenv.owner_id:
            await interaction.response.send_message(
                "You are not authorized to use this command.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        result = await bot.holodex_manager.refresh_channels()

        if result is None:
            await interaction.followup.send(
                "❌ Failed to refresh the channel list from Holodex. Check the logs for details.",
                ephemeral=True,
            )
            return

        added, updated = result
        total = len(bot.holodex_manager.channel_cache.get_channels())
        await interaction.followup.send(
            f"✅ Channel list refreshed: **{added}** new, **{updated}** updated, "
            f"**{total}** total known channels.\n"
            "-# Channels are never removed from the list, even if Holodex stops listing them.",
            ephemeral=True,
        )
        logger.info(
            f"User {interaction.user} manually refreshed the channel list "
            f"({added} added, {updated} updated, {total} total)"
        )
