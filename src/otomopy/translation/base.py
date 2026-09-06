import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, override

import aiohttp

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranslationResult:
    """A translation as the provider returned it, before any filtering."""

    #: The translated text.
    text: str
    #: The source language the provider detected, or the one it was told to use.
    #: Spelling varies by backend ("EN", "en", "zh-Hans"); compare with _base_lang.
    detected_source_lang: str


def _base_lang(code: str) -> str:
    """The primary subtag of a language tag, lowercased ("EN-GB" -> "en")."""
    return code.split("-")[0].lower()


class TranslationProvider(ABC):
    """Abstract base class for all translation providers."""

    #: Human-readable name used for display (e.g. emote lookup, log messages).
    name: str = "Translation"

    @abstractmethod
    async def translate_text(
        self, text: str, target_lang: str = "en", source_lang: str | None = None
    ) -> TranslationResult | None:
        """
        Translates the given text, returning the provider's result unfiltered.

        Args:
            text: The text to be translated.
            target_lang: The language code to translate into.
            source_lang: The language code of `text`, or None to let the
                provider detect it.

        Returns:
            The translation, or None if the provider could not produce one.
        """

    async def translate(self, text: str, target_lang: str = "en") -> str | None:
        """
        Translates a relayed chat message, or returns None if it adds nothing.

        Unlike :meth:`translate_text`, this drops the result when the message was
        already in the target language or came back unchanged: a relayed message
        would otherwise be echoed twice under its own translation. Callers that
        asked for a translation explicitly -- the ``/translate`` command -- want
        :meth:`translate_text`, which reports whatever the provider said.

        Args:
            text: The text to be translated.
            target_lang: The ISO 639-1 code for the target language.

        Returns:
            The translated text, or None if translation is not needed or fails.
        """
        result = await self.translate_text(text, target_lang=target_lang)
        if result is None:
            return None

        if _base_lang(result.detected_source_lang) == _base_lang(target_lang):
            return None
        if result.text.lower().strip() == text.lower().strip():
            return None

        return result.text


class DeepLProvider(TranslationProvider):
    """DeepL API implementation of TranslationProvider."""

    name: str = "DeepL"

    #: DeepL rejects these as *target* languages without a regional variant.
    TARGET_LANG_OVERRIDES: ClassVar[dict[str, str]] = {
        "en": "EN-GB",
        "pt": "PT-BR",
        "zh": "ZH-HANS",
    }

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

    @classmethod
    def target_code(cls, code: str) -> str:
        """DeepL's spelling of `code` as a target language."""
        return cls.TARGET_LANG_OVERRIDES.get(code.lower(), code.upper())

    @classmethod
    def source_code(cls, code: str) -> str:
        """DeepL's spelling of `code` as a source language.

        Source languages take no regional variant, so "pt-PT" and "zh-Hans"
        narrow to "PT" and "ZH".
        """
        return _base_lang(code).upper()

    @override
    async def translate_text(
        self, text: str, target_lang: str = "en", source_lang: str | None = None
    ) -> TranslationResult | None:
        """
        Translates text using the DeepL API.
        """
        if not self.client:
            return None

        try:
            # The deepl client is synchronous, so it would block the event loop --
            # and with it every relay -- for the length of the API call.
            result = await asyncio.to_thread(
                self.client.translate_text,
                text,
                target_lang=self.target_code(target_lang),
                source_lang=self.source_code(source_lang) if source_lang else None,
            )

            if isinstance(result, list):
                raise ValueError("Only a single translation result was expected")

            return TranslationResult(
                text=result.text,
                detected_source_lang=result.detected_source_lang or (source_lang or ""),
            )

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
    async def translate_text(
        self, text: str, target_lang: str = "en", source_lang: str | None = None
    ) -> TranslationResult | None:
        """
        Translates text using the Azure AI Translator API, auto-detecting the
        source language unless one is given.
        """
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/json",
        }
        if self.region:
            headers["Ocp-Apim-Subscription-Region"] = self.region

        params = {"api-version": "3.0", "to": target_lang}
        if source_lang:
            params["from"] = source_lang

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
            # Azure omits detectedLanguage when it was told the source language.
            detected_lang = translation.get("detectedLanguage", {}).get("language", "")

            return TranslationResult(
                text=translation["translations"][0]["text"],
                detected_source_lang=detected_lang or (source_lang or ""),
            )

        except Exception:
            logger.exception("Error translating message with Azure:")

        return None
