"""Ollama translation backend (local LLM)."""

from __future__ import annotations

from brainycat.http_client import get_client


class OllamaBackend:
    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        """Store the Ollama server URL to call. `translation.list_backends()` advertises "ollama" as
        an available backend, but `translation._get_backend()` has no branch for it, so this class is
        currently never instantiated."""
        self.base_url = base_url

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """Translate text via a local Ollama /api/generate call. See class docstring — not currently
        wired up to any caller."""
        prompt = f"Translate from {source_lang} to {target_lang}. Return only the translation:\n\n{text}"
        client = get_client()
        resp = await client.post(f"{self.base_url}/api/generate", json={"model": "llama3", "prompt": prompt, "stream": False})
        if resp.status_code == 200:
            return resp.json().get("response", text).strip()
        return text

    def supported_languages(self) -> list[str]:
        """Languages this backend can translate to/from — not currently called anywhere in the codebase."""
        return ["en", "fr", "de", "es", "it", "pt", "nl", "ru", "zh", "ja"]
