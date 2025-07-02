"""
Translation blacklist commands for OtomoPy.

This module provides commands for managing the per-guild translation blacklist,
allowing admins to block specific YouTube users from having their messages relayed.
"""

import logging
import re

import discord
from discord import app_commands

logger = logging.getLogger(__name__)

# Look for patterns: :emote_name:||author_name:|| or :emote_name:**author_name:**
MESSAGE_AUTHOR = re.compile(r"^:([^:]+): ?(?:\|\||\*\*)(.+?)(?::\|\||\:\*\*)")


def register_commands(bot):
    """Register blacklist commands with the bot.

    Args:
        bot: The DiscordBot instance
    """

    # Context menu command for right-clicking on messages
    @bot.tree.context_menu(name="Blacklist Translator")
    @discord.app_commands.default_permissions(manage_messages=True)
    async def blacklist_translator_context(
        interaction: discord.Interaction, message: discord.Message
    ):
        """Blacklist a translator via right-click context menu.

        Args:
            interaction: The Discord interaction
            message: The message that was right-clicked
        """
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server", ephemeral=True
            )
            return

        # Check if the message is from our bot
        if message.author.id != bot.user.id:
            await interaction.response.send_message(
                "You can only blacklist translators from translation relay messages",
                ephemeral=True,
            )
            return

        # Parse the message content to extract the translator's username
        translator_name = _extract_translator_from_message(message.content)
        if not translator_name:
            await interaction.response.send_message(
                "Could not extract translator information from this message",
                ephemeral=True,
            )
            return

        # Check if already blacklisted
        if bot.config.is_user_blacklisted(interaction.guild.id, translator_name):
            await interaction.response.send_message(
                f"**{translator_name}** is already blacklisted", ephemeral=True
            )
            return

        # Add to blacklist
        success = bot.config.add_blacklisted_user(interaction.guild.id, translator_name)

        if success:
            await interaction.response.send_message(
                f"✅ **{translator_name}** has been added to the translation blacklist.\n"
                f"Their messages will no longer be relayed in this server.",
                ephemeral=True,
            )
            logger.info(
                f"User {interaction.user} blacklisted translator {translator_name} "
                f"in guild {interaction.guild.name} ({interaction.guild.id})"
            )
        else:
            await interaction.response.send_message(
                f"Failed to blacklist **{translator_name}**", ephemeral=True
            )

    # Slash command for blacklisting by username
    @bot.tree.command(
        name="blacklist_translator",
        description="Add a translator to the blacklist by their YouTube username",
    )
    @app_commands.describe(
        username="The YouTube username of the translator to blacklist (e.g., @vtange)"
    )
    @discord.app_commands.default_permissions(manage_messages=True)
    async def blacklist_translator_slash(interaction: discord.Interaction, username: str):
        """Blacklist a translator by their YouTube username.

        Args:
            interaction: The Discord interaction
            username: The YouTube username to blacklist
        """
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server", ephemeral=True
            )
            return

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
                f"✅ **{username}** has been added to the translation blacklist.\n"
                f"Their messages will no longer be relayed in this server.",
                ephemeral=True,
            )
            logger.info(
                f"User {interaction.user} blacklisted translator {username} "
                f"in guild {interaction.guild.name} ({interaction.guild.id})"
            )
        else:
            await interaction.response.send_message(
                f"Failed to blacklist **{username}**", ephemeral=True
            )

    # Autocomplete function for unblacklist command
    async def unblacklist_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Provide autocomplete suggestions for unblacklist command."""
        if not interaction.guild:
            return []

        blacklisted_users = bot.config.get_blacklisted_users(interaction.guild.id)
        choices = []

        for user_name in blacklisted_users:
            if current.lower() in user_name.lower():
                choices.append(app_commands.Choice(name=user_name, value=user_name))
                if len(choices) >= 25:
                    break

        # Return up to 25 choices (Discord limit)
        return choices[:25]

    # Slash command for removing from blacklist
    @bot.tree.command(
        name="unblacklist_translator",
        description="Remove a translator from the blacklist",
    )
    @app_commands.describe(
        username="The YouTube username of the translator to remove from blacklist"
    )
    @app_commands.autocomplete(username=unblacklist_autocomplete)
    @discord.app_commands.default_permissions(manage_messages=True)
    async def unblacklist_translator(interaction: discord.Interaction, username: str):
        """Remove a translator from the blacklist.

        Args:
            interaction: The Discord interaction
            username: The YouTube username to remove from blacklist
        """
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server", ephemeral=True
            )
            return

        # Use the username directly without any modifications
        # Remove from blacklist
        success = bot.config.remove_blacklisted_user(interaction.guild.id, username)

        if success:
            await interaction.response.send_message(
                f"✅ **{username}** has been removed from the translation blacklist.",
                ephemeral=True,
            )
            logger.info(
                f"User {interaction.user} removed translator {username} "
                f"from blacklist in guild {interaction.guild.name} ({interaction.guild.id})"
            )
        else:
            await interaction.response.send_message(
                f"**{username}** was not found in the blacklist", ephemeral=True
            )

    # Slash command for listing blacklisted users
    @bot.tree.command(
        name="list_blacklisted",
        description="List all blacklisted translators for this server",
    )
    @discord.app_commands.default_permissions(manage_messages=True)
    async def list_blacklisted(interaction: discord.Interaction):
        """List all blacklisted translators for this guild.

        Args:
            interaction: The Discord interaction
        """
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server", ephemeral=True
            )
            return

        blacklisted_users = bot.config.get_blacklisted_users(interaction.guild.id)

        if not blacklisted_users:
            await interaction.response.send_message(
                "No translators are currently blacklisted in this server",
                ephemeral=True,
            )
            return

        # Format the blacklist
        blacklist_lines = []
        for i, user_name in enumerate(blacklisted_users, 1):
            blacklist_lines.append(f"{i}. `{user_name}`")

        # Split into multiple messages if too long
        message_content = "**Blacklisted Translators:**\n" + "\n".join(blacklist_lines)

        if len(message_content) > 2000:
            # Split into chunks
            chunks = []
            current_chunk = "**Blacklisted Translators:**\n"

            for line in blacklist_lines:
                if len(current_chunk + line + "\n") > 1900:  # Leave some buffer
                    chunks.append(current_chunk)
                    current_chunk = line + "\n"
                else:
                    current_chunk += line + "\n"

            if current_chunk.strip():
                chunks.append(current_chunk)

            # Send first chunk as response
            await interaction.response.send_message(chunks[0], ephemeral=True)

            # Send remaining chunks as follow-ups
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk, ephemeral=True)
        else:
            await interaction.response.send_message(message_content, ephemeral=True)


def _extract_translator_from_message(message_content: str) -> str | None:
    """Extract translator information from a bot message.

    Args:
        message_content: The content of the bot's relay message

    Returns:
        str: translator_name or None if not found
    """

    match = MESSAGE_AUTHOR.search(message_content)

    if match:
        translator_name = match.group(2).strip()
        return translator_name if translator_name else None

    return None
