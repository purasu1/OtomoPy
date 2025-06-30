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
