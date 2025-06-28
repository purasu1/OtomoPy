"""
System slash commands for OtomoPy.

These commands are for system-level operations, typically
only accessible to the bot owner.
"""

import logging

import discord
from discord import app_commands

from otomopy.permissions import Privilege, require_privilege

logger = logging.getLogger(__name__)


def register_commands(bot):
    """Register system commands with the bot.

    Args:
        bot: The DiscordBot instance
    """

    @bot.tree.command(name="shutdown", description="Shutdown the bot (owner only)")
    @require_privilege(Privilege.OWNER)
    async def shutdown_bot(interaction: discord.Interaction):
        """Shutdown the bot safely.

        Only the bot owner can use this command.

        Args:
            interaction: The Discord interaction
        """
        await interaction.response.send_message(
            "Shutting down the bot...", ephemeral=True
        )
        logger.info(f"Bot shutdown requested by owner (ID: {interaction.user.id})")

        # Make sure we clean up the Holodex manager before closing
        if bot.holodex_task and not bot.holodex_task.done():
            bot.holodex_task.cancel()

        try:
            await bot.holodex_manager.stop()
            logger.info("Holodex manager stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping Holodex manager: {e}")

        # Close the bot connection
        await bot.close()

    @bot.tree.command(name="status", description="Get bot status information")
    @require_privilege(Privilege.ADMIN)
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
        embed.add_field(
            name="Tracked YouTube Channels", value=str(tracked_channels), inline=True
        )

        # WebSocket connection status
        ws_status = (
            "Connected"
            if (
                hasattr(bot.holodex_manager, "ws_connected")
                and bot.holodex_manager.ws_connected
            )
            else "Disconnected"
        )
        embed.add_field(name="WebSocket Status", value=ws_status, inline=True)

        # Live streams currently being tracked
        live_stream_count = len(
            [
                s
                for s in bot.holodex_manager.current_streams.values()
                if s.status == "live"
            ]
        )
        embed.add_field(
            name="Current Live Streams", value=str(live_stream_count), inline=True
        )

        # Upcoming streams being tracked
        upcoming_stream_count = len(
            [
                s
                for s in bot.holodex_manager.current_streams.values()
                if s.status == "upcoming"
            ]
        )
        embed.add_field(
            name="Upcoming Streams", value=str(upcoming_stream_count), inline=True
        )

        # Chat message stats
        active_subs = len(getattr(bot.holodex_manager, "active_subscriptions", set()))
        chat_messages = getattr(bot, "holodex_chat_messages_received", 0)
        session_id = getattr(bot.holodex_manager, "session_id", "None")
        embed.add_field(
            name="Active Chat Subscriptions", value=str(active_subs), inline=True
        )
        embed.add_field(
            name="Chat Messages Received", value=str(chat_messages), inline=True
        )

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
                    "\n".join([f"`{ch}`" for ch in recent_channels])
                    if recent_channels
                    else "None"
                ),
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(
        name="debug_streams", description="Debug stream detection (owner only)"
    )
    @require_privilege(Privilege.OWNER)
    async def debug_streams(interaction: discord.Interaction):
        """Debug stream detection by manually checking for streams.

        Args:
            interaction: The Discord interaction
        """
        await interaction.response.defer(ephemeral=True)

        try:
            # Get live streams for tracked channels
            live_data = await bot.holodex_manager.api.get_live_streams(
                bot.tracked_channels
            )

            embed = discord.Embed(
                title="Stream Detection Debug",
                description=f"Found {len(live_data)} live/upcoming streams",
                color=discord.Color.orange(),
            )

            if live_data:
                for i, stream in enumerate(live_data[:10]):  # Limit to first 10
                    channel = stream.get("channel", {})
                    embed.add_field(
                        name=f"Stream {i+1}",
                        value=f"**{stream.get('title', 'Unknown')}**\n"
                        f"Channel: {channel.get('name', 'Unknown')}\n"
                        f"Status: {stream.get('status', 'Unknown')}\n"
                        f"Video ID: `{stream.get('id', 'Unknown')}`",
                        inline=False,
                    )
            else:
                embed.add_field(
                    name="No Streams Found",
                    value="No live or upcoming streams found for tracked channels",
                    inline=False,
                )

            embed.add_field(
                name="Tracked Channels",
                value=f"{len(bot.tracked_channels)} channels: {', '.join(list(bot.tracked_channels)[:3])}{'...' if len(bot.tracked_channels) > 3 else ''}",
                inline=False,
            )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in debug_streams: {e}")
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)

    @bot.tree.command(
        name="test_subscription",
        description="Test websocket subscription to a video ID (owner only)",
    )
    @app_commands.describe(video_id="YouTube video ID to test subscription")
    @require_privilege(Privilege.OWNER)
    async def test_subscription(interaction: discord.Interaction, video_id: str):
        """Test websocket subscription to a specific video ID.

        Args:
            interaction: The Discord interaction
            video_id: YouTube video ID to subscribe to
        """
        await interaction.response.defer(ephemeral=True)

        try:
            if not bot.holodex_manager.ws_connected:
                await interaction.followup.send(
                    "WebSocket is not connected!", ephemeral=True
                )
                return

            # Attempt to subscribe
            await bot.holodex_manager._subscribe_to_chat(video_id)

            embed = discord.Embed(
                title="Subscription Test",
                description=f"Attempted to subscribe to video ID: `{video_id}`",
                color=discord.Color.green(),
            )

            embed.add_field(
                name="WebSocket Status",
                value=(
                    "Connected" if bot.holodex_manager.ws_connected else "Disconnected"
                ),
                inline=True,
            )

            embed.add_field(
                name="Active Subscriptions",
                value=str(len(bot.holodex_manager.active_subscriptions)),
                inline=True,
            )

            if video_id in bot.holodex_manager.active_subscriptions:
                embed.add_field(
                    name="Subscription Status",
                    value="✅ Successfully added to active subscriptions",
                    inline=False,
                )
            else:
                embed.add_field(
                    name="Subscription Status",
                    value="⚠️ Not found in active subscriptions (may still be pending)",
                    inline=False,
                )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in test_subscription: {e}")
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
