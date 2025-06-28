"""
Permissions system for OtomoPy.

This module provides decorators for command permission checks.
"""

from enum import Enum, auto
from functools import wraps

import discord


class Privilege(Enum):
    """Privilege levels for command access."""

    REGULAR = auto()
    ADMIN = auto()
    OWNER = auto()


def require_privilege(minimum_privilege: Privilege = Privilege.REGULAR):
    """Decorator to check if a user has the required privilege level.

    Args:
        minimum_privilege: The minimum privilege level required to use the command.

    Returns:
        A decorator function that wraps the command with a permission check.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(interaction: discord.Interaction, *args, **kwargs):
            # Get the bot instance from the command tree
            bot = interaction.client

            # REGULAR privilege doesn't need any special checks
            if minimum_privilege == Privilege.REGULAR:
                return await func(interaction, *args, **kwargs)

            # For OWNER privilege, check if the user is the bot owner
            if minimum_privilege == Privilege.OWNER:
                # We can't directly check bot.dotenv due to type limitations
                # So we use getattr to bypass type checking
                owner_id = getattr(bot, "dotenv", None)
                if owner_id is None or not hasattr(owner_id, "owner_id"):
                    raise AttributeError(
                        "Bot instance does not have dotenv.owner_id attribute"
                    )

                # Get the owner ID using getattr to avoid type checking issues
                bot_owner_id = getattr(getattr(bot, "dotenv"), "owner_id")
                if interaction.user.id != bot_owner_id:
                    await interaction.response.send_message(
                        "Only the bot owner can use this command", ephemeral=True
                    )
                    return

            # For ADMIN privilege, check if the user has permission
            elif minimum_privilege == Privilege.ADMIN:
                if not hasattr(bot, "has_permission"):
                    raise AttributeError(
                        "Bot instance does not have a has_permission method"
                    )

                # Type checking doesn't know our custom DiscordBot class has this method
                # We've checked with hasattr above, so this is safe
                if not getattr(bot, "has_permission")(interaction):
                    await interaction.response.send_message(
                        "You don't have permission to use this command", ephemeral=True
                    )
                    return

            # If permission check passes, call the original function
            return await func(interaction, *args, **kwargs)

        # Add an attribute to mark this function as permission-checked
        # We use setattr instead of direct assignment to avoid type checker complaints
        setattr(wrapper, "__permission_checked__", True)
        setattr(wrapper, "__minimum_privilege__", minimum_privilege)
        return wrapper

    return decorator


def ensure_permission_checked():
    """Decorator factory to ensure all commands have permission checks.

    This can be applied to the register_commands function to verify that
    all commands have been decorated with require_privilege.

    Returns:
        A decorator function that verifies commands have permission checks.
    """

    def decorator(register_func):
        @wraps(register_func)
        def wrapper(bot, *args, **kwargs):
            # Call the original register function
            result = register_func(bot, *args, **kwargs)

            # After registration, inspect all commands to ensure they have permission checks
            for command in bot.tree.get_commands():
                callback = command.callback
                if not hasattr(callback, "__permission_checked__"):
                    raise RuntimeError(
                        f"Command '{command.name}' is missing a permission check decorator. "
                        f"Use @require_privilege(Privilege.LEVEL) to specify required privileges."
                    )

            return result

        return wrapper

    return decorator
