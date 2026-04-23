"""DeepL translation backend."""

from __future__ import annotations

from brainycat.http_client import get_client


class DeepLBackend:
    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
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
        return ["en", "fr", "de", "es", "it", "pt", "nl", "ru", "zh", "ja", "ko", "pl", "uk"]
