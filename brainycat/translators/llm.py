"""LLM translation backend via Intello."""

from __future__ import annotations

from brainycat.config import settings
from brainycat.http_client import get_client


class LLMBackend:
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """Translate text via the Intello chat-completions API. Selected by
        `translation._get_backend("llm")`, used by `translation.py`'s translation job runner."""
        prompt = f"Translate the following text from {source_lang} to {target_lang}. Return only the translation, nothing else.\n\n{text}"
        client = get_client()
        resp = await client.post(
            f"{settings.intello_url}/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": prompt}], "task_hint": "translation", "max_tokens": 2048},
        )
        if resp.status_code == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        return text

    def supported_languages(self) -> list[str]:
        """Languages this backend can translate to/from — not currently called anywhere in the codebase."""
        return ["en", "fr", "de", "es", "it", "pt", "nl", "ru", "zh", "ja", "ko", "ar", "hi", "tr", "pl", "uk"]
