"""Argos Translate backend (local, free)."""

from __future__ import annotations


class ArgosBackend:
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """Translate text with the local Argos Translate library; returns the original text if it's not installed.

        Instantiated by translation.py's _get_backend() when the "argos" backend is selected.
        """
        try:
            import argostranslate.translate

            return argostranslate.translate.translate(text, source_lang, target_lang)
        except ImportError:
            return text  # graceful fallback

    def supported_languages(self) -> list[str]:
        """List language codes this backend can translate to/from."""
        return ["en", "fr", "de", "es", "it", "pt", "nl", "ru", "zh", "ja", "ar"]
