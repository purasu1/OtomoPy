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

    @bot.tree.command(name="set_emote", description="Set an emote for the bot")
    @discord.app_commands.default_permissions(administrator=True)
    async def set_emote(interaction: discord.Interaction, name: str, emote: str):
        """Set an emote for the bot. Only the owner is allowed to use this command."""
        if interaction.user.id != bot.dotenv.owner_id:
            await interaction.response.send_message(
                "You are not authorized to use this command.", ephemeral=True
            )
            return
        bot.config.set_emote(name, emote)
        await interaction.response.send_message("Emote set successfully.", ephemeral=True)

    @bot.tree.command(name="unset_emote", description="Unset an emote for the bot")
    @discord.app_commands.default_permissions(administrator=True)
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
