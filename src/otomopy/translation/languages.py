"""
Language codes offered by the translation commands.

The codes are the ones Azure AI Translator accepts directly; DeepL's differing
spellings are handled by ``DeepLProvider`` when it builds its request. Not every
language here is supported by every backend -- DeepL, for instance, has no Hindi
-- so a translation may still be refused by the provider.
"""

import re

#: (code, English name) pairs, ordered by rough usefulness to this bot's servers
#: (VTuber chat is mostly ja/en/ko/zh) and then alphabetically by name.
LANGUAGES: list[tuple[str, str]] = [
    ("en", "English"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("zh-Hans", "Chinese (Simplified)"),
    ("zh-Hant", "Chinese (Traditional)"),
    ("ar", "Arabic"),
    ("bn", "Bengali"),
    ("bg", "Bulgarian"),
    ("cs", "Czech"),
    ("da", "Danish"),
    ("nl", "Dutch"),
    ("et", "Estonian"),
    ("fil", "Filipino"),
    ("fi", "Finnish"),
    ("fr", "French"),
    ("de", "German"),
    ("el", "Greek"),
    ("he", "Hebrew"),
    ("hi", "Hindi"),
    ("hu", "Hungarian"),
    ("id", "Indonesian"),
    ("it", "Italian"),
    ("lv", "Latvian"),
    ("lt", "Lithuanian"),
    ("ms", "Malay"),
    ("nb", "Norwegian"),
    ("fa", "Persian"),
    ("pl", "Polish"),
    ("pt", "Portuguese (Brazil)"),
    ("pt-PT", "Portuguese (Portugal)"),
    ("ro", "Romanian"),
    ("ru", "Russian"),
    ("sk", "Slovak"),
    ("sl", "Slovenian"),
    ("es", "Spanish"),
    ("sv", "Swedish"),
    ("ta", "Tamil"),
    ("th", "Thai"),
    ("tr", "Turkish"),
    ("uk", "Ukrainian"),
    ("vi", "Vietnamese"),
]

#: Lookup from lowercased code to English name.
_NAMES: dict[str, str] = {code.lower(): name for code, name in LANGUAGES}

#: A BCP-47-ish tag: a two or three letter primary subtag, plus optional subtags.
#: Deliberately permissive, so a backend-specific code the list does not carry
#: (say DeepL's "EN-US") still reaches the provider, while a language typed out
#: by hand ("Japanese") is rejected before the command posts anything.
_LANGUAGE_TAG = re.compile(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$")


def is_language_code(code: str) -> bool:
    """Whether `code` is shaped like a language tag a provider might accept."""
    return bool(_LANGUAGE_TAG.match(code.strip()))


def language_name(code: str | None) -> str:
    """The English name for `code`, falling back to the code itself.

    Args:
        code: A language code, or None for an unspecified language.

    Returns:
        A display name suitable for a Discord message.
    """
    if not code:
        return "Auto-detected"
    return _NAMES.get(code.strip().lower(), code)


def search(query: str, limit: int = 25) -> list[tuple[str, str]]:
    """The languages matching `query`, by name or code.

    Args:
        query: The partial name or code typed by the user; empty matches all.
        limit: Maximum number of results (Discord allows 25 autocomplete choices).

    Returns:
        Matching (code, name) pairs, names starting with the query first.
    """
    normalized = query.strip().lower()
    if not normalized:
        return LANGUAGES[:limit]

    prefix: list[tuple[str, str]] = []
    substring: list[tuple[str, str]] = []
    for code, name in LANGUAGES:
        haystack = name.lower()
        if haystack.startswith(normalized) or code.lower().startswith(normalized):
            prefix.append((code, name))
        elif normalized in haystack:
            substring.append((code, name))

    return (prefix + substring)[:limit]
