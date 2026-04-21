"""Argos Translate backend (local, free)."""

from __future__ import annotations


class ArgosBackend:
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        try:
            import argostranslate.translate

            return argostranslate.translate.translate(text, source_lang, target_lang)
        except ImportError:
            return text  # graceful fallback

    def supported_languages(self) -> list[str]:
        return ["en", "fr", "de", "es", "it", "pt", "nl", "ru", "zh", "ja", "ar"]
