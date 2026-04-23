"""Google Translate backend."""

from __future__ import annotations

from brainycat.http_client import get_client


class GoogleTranslateBackend:
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        client = get_client()
        resp = await client.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": source_lang, "tl": target_lang, "dt": "t", "q": text},
        )
        if resp.status_code == 200:
            data = resp.json()
            return "".join(s[0] for s in data[0] if s[0])
        return text

    def supported_languages(self) -> list[str]:
        return ["en", "fr", "de", "es", "it", "pt", "nl", "ru", "zh", "ja", "ko", "ar", "hi", "tr"]
