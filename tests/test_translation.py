"""Tests for the translation wrapper and the language table.

The provider subclasses talk to a network, so what is exercised here is the
logic layered on top of them: the suppression rule that keeps `translate` from
echoing a relayed message twice, and the code mapping each backend needs.
"""

import asyncio
from collections.abc import Coroutine
from typing import Any, override

import pytest

from otomopy.translation import languages
from otomopy.translation.base import DeepLProvider, TranslationProvider, TranslationResult


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Await `coro` from a sync test; the suite carries no async plugin."""
    return asyncio.run(coro)


class StubProvider(TranslationProvider):
    """A provider that returns a canned result and records how it was called."""

    name: str = "Stub"

    def __init__(self, result: TranslationResult | None):
        self.result: TranslationResult | None = result
        self.calls: list[tuple[str, str, str | None]] = []

    @override
    async def translate_text(
        self, text: str, target_lang: str = "en", source_lang: str | None = None
    ) -> TranslationResult | None:
        self.calls.append((text, target_lang, source_lang))
        return self.result


class TestRelayTranslate:
    """`translate` is the relay path: it stays silent when it adds nothing."""

    def test_returns_translation_of_foreign_text(self) -> None:
        provider = StubProvider(TranslationResult("Hello", "JA"))
        assert run(provider.translate("こんにちは")) == "Hello"

    def test_suppresses_text_already_in_target_language(self) -> None:
        provider = StubProvider(TranslationResult("Hello", "EN"))
        assert run(provider.translate("Hello there")) is None

    def test_suppresses_regional_variant_of_target_language(self) -> None:
        """A detected "EN-GB" against an "en" target is still the target language."""
        provider = StubProvider(TranslationResult("Hello", "EN-GB"))
        assert run(provider.translate("Hello there")) is None

    def test_suppresses_unchanged_translation(self) -> None:
        provider = StubProvider(TranslationResult("Hello", "JA"))
        assert run(provider.translate("hello  ")) is None

    def test_suppresses_provider_failure(self) -> None:
        assert run(StubProvider(None).translate("こんにちは")) is None

    def test_returns_the_translation_verbatim(self) -> None:
        """Escaping for Discord belongs to the caller, not the provider."""
        provider = StubProvider(TranslationResult("a `code` word", "JA"))
        assert run(provider.translate("コード")) == "a `code` word"

    def test_never_pins_the_source_language(self) -> None:
        """Relayed chat is of unknown origin, so detection must stay on."""
        provider = StubProvider(TranslationResult("Hello", "JA"))
        run(provider.translate("こんにちは", target_lang="en"))
        assert provider.calls == [("こんにちは", "en", None)]


class TestDeepLLanguageCodes:
    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("en", "EN-GB"),  # DeepL rejects a bare "EN" target
            ("pt", "PT-BR"),
            ("zh", "ZH-HANS"),
            ("ja", "JA"),
            ("zh-Hant", "ZH-HANT"),
            ("pt-PT", "PT-PT"),
        ],
    )
    def test_target_code(self, code: str, expected: str) -> None:
        assert DeepLProvider.target_code(code) == expected

    @pytest.mark.parametrize(
        ("code", "expected"),
        [("en", "EN"), ("ja", "JA"), ("zh-Hans", "ZH"), ("pt-PT", "PT")],
    )
    def test_source_code_drops_regional_variant(self, code: str, expected: str) -> None:
        assert DeepLProvider.source_code(code) == expected


class TestLanguages:
    @pytest.mark.parametrize("code", ["en", "ja", "zh-Hans", "pt-BR", "EN-US"])
    def test_accepts_language_tags(self, code: str) -> None:
        assert languages.is_language_code(code)

    @pytest.mark.parametrize("code", ["Japanese", "", "j", "en_US", "!!", "日本語"])
    def test_rejects_everything_else(self, code: str) -> None:
        assert not languages.is_language_code(code)

    def test_name_is_looked_up_case_insensitively(self) -> None:
        assert languages.language_name("JA") == "Japanese"

    def test_unknown_code_displays_as_itself(self) -> None:
        assert languages.language_name("xx-YY") == "xx-YY"

    def test_missing_code_reads_as_detected(self) -> None:
        assert languages.language_name(None) == "Auto-detected"
        assert languages.language_name("") == "Auto-detected"

    def test_search_matches_name_and_code(self) -> None:
        assert ("ja", "Japanese") in languages.search("japan")
        assert ("ja", "Japanese") in languages.search("ja")

    def test_search_prefers_prefix_matches(self) -> None:
        """Both "German" and "Romanian" contain "man"; neither starts with it."""
        assert languages.search("german")[0] == ("de", "German")

    def test_search_never_exceeds_discord_choice_limit(self) -> None:
        assert len(languages.search("")) == 25

    def test_every_code_is_a_valid_tag(self) -> None:
        assert all(languages.is_language_code(code) for code, _ in languages.LANGUAGES)
