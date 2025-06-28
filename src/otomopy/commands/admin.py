"""
Admin slash commands for OtomoPy.
"""

import discord
from discord import app_commands

from otomopy.permissions import Privilege, require_privilege


def register_commands(bot):
    """Register admin commands with the bot.

    Args:
        bot: The DiscordBot instance
    """

    @bot.tree.command(
        name="add_admin_role", description="Add a role to the admin roles list"
    )
    @app_commands.describe(role="The role to add as an admin role")
    @require_privilege(Privilege.ADMIN)
    async def add_admin_role(interaction: discord.Interaction, role: discord.Role):
        """Add a role to the admin roles list for this guild.

        Args:
            interaction: The Discord interaction
            role: The role to add as an admin role
        """
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server", ephemeral=True
            )
            return

        success = bot.config.add_admin_role(interaction.guild.id, role.id)
        if success:
            await interaction.response.send_message(
                f"Added {role.name} to admin roles", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{role.name} is already an admin role", ephemeral=True
            )

    @bot.tree.command(
        name="remove_admin_role", description="Remove a role from the admin roles list"
    )
    @app_commands.describe(role="The role to remove from admin roles")
    @require_privilege(Privilege.ADMIN)
    async def remove_admin_role(interaction: discord.Interaction, role: discord.Role):
        """Remove a role from the admin roles list for this guild.

        Args:
            interaction: The Discord interaction
            role: The role to remove from admin roles
        """
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server", ephemeral=True
            )
            return

        success = bot.config.remove_admin_role(interaction.guild.id, role.id)
        if success:
            await interaction.response.send_message(
                f"Removed {role.name} from admin roles", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{role.name} is not an admin role", ephemeral=True
            )

    @bot.tree.command(
        name="list_admin_roles", description="List all admin roles for this server"
    )
    @require_privilege(Privilege.REGULAR)
    async def list_admin_roles(interaction: discord.Interaction):
        """List all admin roles for this guild.

        Args:
            interaction: The Discord interaction
        """
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server", ephemeral=True
            )
            return

        guild_config = bot.config.get_guild_config(interaction.guild.id)
        admin_role_ids = guild_config.get("admin_roles", [])

        if not admin_role_ids:
            await interaction.response.send_message(
                "No admin roles configured for this server", ephemeral=True
            )
            return

        admin_roles = []
        for role_id in admin_role_ids:
            role = interaction.guild.get_role(int(role_id))
            if role:
                admin_roles.append(f"- {role.name}")
            else:
                # Role was deleted but still in config
                bot.config.remove_admin_role(interaction.guild.id, int(role_id))

        if admin_roles:
            await interaction.response.send_message(
                f"Admin roles:\n{('\n').join(admin_roles)}", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "No admin roles configured for this server", ephemeral=True
            )
