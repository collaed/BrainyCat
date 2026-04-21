"""Ollama translation backend (local LLM)."""

from __future__ import annotations

import httpx


class OllamaBackend:
    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self.base_url = base_url

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        prompt = f"Translate from {source_lang} to {target_lang}. Return only the translation:\n\n{text}"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.base_url}/api/generate", json={"model": "llama3", "prompt": prompt, "stream": False}
            )
            if resp.status_code == 200:
                return resp.json().get("response", text).strip()
        return text

    def supported_languages(self) -> list[str]:
        return ["en", "fr", "de", "es", "it", "pt", "nl", "ru", "zh", "ja"]
