import logging
from abc import ABC, abstractmethod
from typing import Any, override

import aiohttp

logger = logging.getLogger(__name__)


class TranslationProvider(ABC):
    """Abstract base class for all translation providers."""

    #: Human-readable name used for display (e.g. emote lookup, log messages).
    name: str = "Translation"

    @abstractmethod
    async def translate(self, text: str, target_lang: str = "en") -> str | None:
        """
        Translates the given text to the target language.

        Args:
            text: The text to be translated.
            target_lang: The ISO 639-1 code for the target language.

        Returns:
            The translated text, or None if translation is not needed
            or fails.
        """


class DeepLProvider(TranslationProvider):
    """DeepL API implementation of TranslationProvider."""

    name: str = "DeepL"

    def __init__(self, api_key: str):
        """
        Initialize the DeepL provider.

        Args:
            api_key: The DeepL API key.
        """
        self.api_key: str = api_key
        # deepl is an optional dependency, so its client carries no types here.
        self.client: Any = None
        try:
            import deepl  # pyright: ignore[reportMissingImports]

            self.client = deepl.DeepLClient(api_key)  # pyright: ignore[reportUnknownMemberType]
        except ImportError:
            logger.warning("DeepL package is not installed. DeepLProvider will fail if used.")
        except Exception as e:
            logger.error(f"Failed to initialize DeepL client: {e}")

    @override
    async def translate(self, text: str, target_lang: str = "en") -> str | None:
        """
        Translates text using the DeepL API.
        """
        if not self.client:
            return None

        try:
            # DeepL uses specific language codes (e.g., EN-GB)
            # For now, we'll assume target_lang is compatible or needs mapping
            # but to keep it simple and similar to original code:
            target_lang_code = "EN-GB" if target_lang.lower() == "en" else target_lang

            result = self.client.translate_text(text, target_lang=target_lang_code)

            if isinstance(result, list):
                raise ValueError("Only a single translation result was expected")

            # Only return the translation if the detected source language isn't English,
            # and the translation differs from the original message.
            if (
                result.detected_source_lang != "EN"
                and result.text.lower().strip() != text.lower().strip()
            ):
                return result.text.replace("`", "''")

        except Exception:
            logger.exception("Error translating message with DeepL:")

        return None


class AzureProvider(TranslationProvider):
    """Azure AI Translator implementation of TranslationProvider."""

    name: str = "Azure"

    DEFAULT_ENDPOINT: str = "https://api.cognitive.microsofttranslator.com"

    def __init__(self, api_key: str, region: str | None = None, endpoint: str | None = None):
        """
        Initialize the Azure Translator provider.

        Args:
            api_key: The Azure Translator resource key.
            region: The Azure resource region (required for multi-service
                "Azure AI services" resources; not needed for single-service
                global Translator resources).
            endpoint: The Translator API endpoint. Defaults to the standard
                global endpoint.
        """
        self.api_key: str = api_key
        self.region: str | None = region
        self.endpoint: str = endpoint or self.DEFAULT_ENDPOINT

    @override
    async def translate(self, text: str, target_lang: str = "en") -> str | None:
        """
        Translates text using the Azure AI Translator API, auto-detecting the
        source language.
        """
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/json",
        }
        if self.region:
            headers["Ocp-Apim-Subscription-Region"] = self.region

        params = {"api-version": "3.0", "to": target_lang}

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    f"{self.endpoint}/translate",
                    params=params,
                    headers=headers,
                    json=[{"Text": text}],
                ) as response,
            ):
                response.raise_for_status()
                result = await response.json()

            translation = result[0]
            detected_lang = translation.get("detectedLanguage", {}).get("language", "")
            translated_text = translation["translations"][0]["text"]

            # Only return the translation if the detected source language isn't the
            # target language, and the translation differs from the original message.
            if (
                detected_lang.lower() != target_lang.lower()
                and translated_text.lower().strip() != text.lower().strip()
            ):
                return translated_text.replace("`", "''")

        except Exception:
            logger.exception("Error translating message with Azure:")

        return None
