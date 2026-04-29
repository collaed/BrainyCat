"""LLM-aided OCR post-correction — fixes spelling, formatting, and garbled text."""

from __future__ import annotations

from typing import Any

import httpx

from brainycat.config import settings


async def correct_ocr_text(text: str, language: str = "en") -> dict[str, Any]:
    """Run OCR output through LLM for correction."""
    if not text or len(text) < 50:
        return {"corrected": text, "changes": 0}

    # Process in chunks of ~2000 words
    words = text.split()
    chunks = [" ".join(words[i : i + 2000]) for i in range(0, len(words), 2000)]
    corrected_chunks = []
    total_changes = 0

    for chunk in chunks[:5]:  # Max 5 chunks (~10K words)
        prompt = f"""Fix OCR errors in this text. The text was scanned from a {language} book.
Fix: spelling errors, garbled characters, broken words (hy-phenation), missing spaces, wrong punctuation.
Do NOT change meaning, add content, or summarize. Return ONLY the corrected text.

TEXT:
{chunk}"""

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    f"{settings.intello_url}/v1/chat/completions",
                    json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1},
                )
                if r.status_code == 200:
                    corrected = r.json()["choices"][0]["message"]["content"]
                    # Count differences (rough)
                    orig_words = set(chunk.split())
                    new_words = set(corrected.split())
                    total_changes += len(orig_words.symmetric_difference(new_words))
                    corrected_chunks.append(corrected)
                else:
                    corrected_chunks.append(chunk)
        except Exception:
            corrected_chunks.append(chunk)

    return {"corrected": " ".join(corrected_chunks), "changes": total_changes, "chunks_processed": len(corrected_chunks)}
