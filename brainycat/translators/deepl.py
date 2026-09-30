"""DeepL translation backend."""

from __future__ import annotations

from brainycat.http_client import get_client


class DeepLBackend:
    def __init__(self, api_key: str = "") -> None:
        """Store the DeepL API key used for translate() requests."""
        self.api_key = api_key

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """Translate text via the DeepL API; returns the original text on failure.

        Note: not currently wired into translation.py's _get_backend() dispatch —
        only "argos" and "llm" are instantiated there today.
        """
        client = get_client()
        resp = await client.post(
            "https://api-free.deepl.com/v2/translate",
            data={
                "auth_key": self.api_key,
                "text": text,
                "source_lang": source_lang.upper(),
                "target_lang": target_lang.upper(),
            },
        )
        if resp.status_code == 200:
            return resp.json()["translations"][0]["text"]
        return text

    def supported_languages(self) -> list[str]:
        """List language codes this backend can translate to/from."""
        return ["en", "fr", "de", "es", "it", "pt", "nl", "ru", "zh", "ja", "ko", "pl", "uk"]
