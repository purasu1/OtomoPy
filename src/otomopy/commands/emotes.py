"""
System slash commands for OtomoPy.

These commands are for system-level operations, typically
only accessible to the bot owner.
"""

import logging

import discord
from discord import app_commands

logger = logging.getLogger(__name__)


def register_commands(bot):
    """Register system commands with the bot.

    Args:
        bot: The DiscordBot instance
    """

    # Create a command group for emote commands
    emote_group = app_commands.Group(name="emote", description="Manage bot emotes")

    @emote_group.command(name="set", description="Set an emote for the bot")
    async def set_emote(interaction: discord.Interaction, name: str, emote: str):
        """Set an emote for the bot. Only the owner is allowed to use this command."""
        if interaction.user.id != bot.dotenv.owner_id:
            await interaction.response.send_message(
                "You are not authorized to use this command.", ephemeral=True
            )
            return
        bot.config.set_emote(name, emote)
        await interaction.response.send_message("Emote set successfully.", ephemeral=True)

    @emote_group.command(name="unset", description="Unset an emote for the bot")
    async def unset_emote(interaction: discord.Interaction, name: str):
        """Unset an emote for the bot. Only the owner is allowed to use this command."""
        if interaction.user.id != bot.owner_id:
            await interaction.response.send_message(
                "You are not authorized to use this command.", ephemeral=True
            )
            return

        if not bot.config.unset_emote(name):
            await interaction.response.send_message("This emote is not set.", ephemeral=True)
        await interaction.response.send_message("Emote unset successfully.", ephemeral=True)

    # Add the emote group to the command tree with proper permissions
    emote_group.default_permissions = discord.Permissions(administrator=True)
    bot.tree.add_command(emote_group)
