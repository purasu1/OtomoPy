"""
Translation slash command for OtomoPy.

Exposes the bot's translation backend directly, so a user can translate a piece
of text on demand rather than waiting for a relayed VTuber message.
"""

# Slash-command callbacks are registered by their decorators, never called by name.
# pyright: reportUnusedFunction=false

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from otomopy.translation import languages

if TYPE_CHECKING:  # bot.py imports this package lazily to break the import cycle
    from otomopy.bot import DiscordBot

logger = logging.getLogger(__name__)

#: Discord rejects messages over 2000 characters; leave room for the footer line.
MAX_TRANSLATION_LENGTH = 1800


async def language_autocomplete(
    _interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete callback offering the known language codes.

    Args:
        _interaction: The Discord interaction (unused; the list is not per-guild)
        current: Current input string

    Returns:
        List of matching language choices
    """
    return [
        app_commands.Choice(name=f"{name} ({code})", value=code)
        for code, name in languages.search(current)
    ]


def register_commands(bot: "DiscordBot") -> None:
    """Register the translation command with the bot.

    Args:
        bot: The DiscordBot instance
    """

    @bot.tree.command(
        name="translate",
        description="Translate text into another language",
    )
    @app_commands.describe(
        text="The text to translate",
        to_lang="The language to translate into (default: English)",
        from_lang="The language of the text (default: detect it automatically)",
    )
    @app_commands.rename(to_lang="to", from_lang="from")
    @app_commands.autocomplete(to_lang=language_autocomplete, from_lang=language_autocomplete)
    async def translate(
        interaction: discord.Interaction,
        text: app_commands.Range[str, 1, 1000],
        to_lang: str | None = None,
        from_lang: str | None = None,
    ):
        """Translate `text` and post the result in the current channel.

        The result is deliberately public -- it is the point of running the
        command -- while every failure is reported ephemerally, so an
        unconfigured backend or a bad language code does not clutter the
        channel.

        Args:
            interaction: The Discord interaction
            text: The text to translate
            to_lang: Target language code, defaulting to English
            from_lang: Source language code, or None to auto-detect
        """
        translator = bot.translator
        if translator is None:
            await interaction.response.send_message(
                "⚠️ Translation is not configured on this bot.", ephemeral=True
            )
            return

        for label, code in (("to", to_lang), ("from", from_lang)):
            if code is not None and not languages.is_language_code(code):
                await interaction.response.send_message(
                    f"❌ `{code}` is not a language code. Pick a `{label}:` suggestion "
                    "from the autocomplete list, or type a code such as `ja` or `pt-BR`.",
                    ephemeral=True,
                )
                return

        target_lang = to_lang or "en"

        # The result is public, so the "thinking" placeholder must be too.
        await interaction.response.defer(thinking=True)

        result = await translator.translate_text(
            text, target_lang=target_lang, source_lang=from_lang
        )

        if result is None:
            logger.info(
                f"Translation failed for {interaction.user} "
                f"({from_lang or 'auto'} -> {target_lang}) via {translator.name}"
            )
            # Drop the public placeholder so the failure stays out of the channel.
            await interaction.delete_original_response()
            await interaction.followup.send(
                "❌ Could not translate that. "
                f"{translator.name} may not support this language pair, "
                "or it may be temporarily unavailable.",
                ephemeral=True,
            )
            return

        translated = result.text
        if len(translated) > MAX_TRANSLATION_LENGTH:
            translated = translated[:MAX_TRANSLATION_LENGTH] + "…"

        source_name = languages.language_name(from_lang or result.detected_source_lang)
        footer = (
            f"-# {source_name} → {languages.language_name(target_lang)}"
            f" · translated by {translator.name}"
        )

        await interaction.edit_original_response(
            content=f"{translated}\n{footer}",
            allowed_mentions=discord.AllowedMentions.none(),
        )
