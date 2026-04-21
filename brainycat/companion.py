"""AI book companion — recap, Q&A, character tracker via Intello."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from brainycat.config import settings
from brainycat.db import fetch_all, fetch_one


async def _llm_call(
    prompt: str,
    system: str = "You are a helpful book companion. Never reveal spoilers beyond the reader's current position.",
) -> str:
    """Call Intello LLM."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{settings.intello_url}/v1/chat/completions",
            json={
                "model": "auto",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "max_tokens": 2048,
            },
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
    return "LLM unavailable"


async def recap(book_id: str, user_id: str) -> dict[str, str]:
    """Generate a recap up to the user's current reading position."""
    progress = await fetch_one(
        "SELECT percentage FROM reading_progress WHERE book_id = $1 AND user_id = $2", UUID(book_id), UUID(user_id)
    )
    pct = progress["percentage"] if progress else 0
    book = await fetch_one("SELECT title FROM books WHERE id = $1", UUID(book_id))
    title = book["title"] if book else "this book"

    # Get content chunks up to current position
    chunks = await fetch_all(
        "SELECT text_content FROM content_chunks WHERE book_id = $1 ORDER BY chapter_index, chunk_index",
        UUID(book_id),
    )
    if not chunks:
        return {"recap": "No content indexed yet. Open the book first to enable AI features."}

    cutoff = max(1, int(len(chunks) * pct / 100))
    text = "\n".join(c["text_content"] for c in chunks[:cutoff])[:8000]

    recap_text = await _llm_call(
        f"Summarize what has happened so far in '{title}' based on this text (the reader is at {pct:.0f}%):\n\n{text}"
    )
    return {"recap": recap_text, "percentage": pct}


async def ask(book_id: str, user_id: str, question: str) -> dict[str, str]:
    """Answer a question about the book without spoilers."""
    progress = await fetch_one(
        "SELECT percentage FROM reading_progress WHERE book_id = $1 AND user_id = $2", UUID(book_id), UUID(user_id)
    )
    pct = progress["percentage"] if progress else 0

    chunks = await fetch_all(
        "SELECT text_content FROM content_chunks WHERE book_id = $1 ORDER BY chapter_index, chunk_index",
        UUID(book_id),
    )
    cutoff = max(1, int(len(chunks) * pct / 100))
    text = "\n".join(c["text_content"] for c in chunks[:cutoff])[:6000]

    answer = await _llm_call(f"Based on the text below (reader is at {pct:.0f}%), answer: {question}\n\nText:\n{text}")
    return {"answer": answer}


async def auto_tag(book_id: str) -> dict[str, Any]:
    """Auto-tag a book using LLM analysis."""
    chunks = await fetch_all(
        "SELECT text_content FROM content_chunks WHERE book_id = $1 ORDER BY chapter_index, chunk_index", UUID(book_id)
    )
    if not chunks:
        return {"error": "No content indexed"}

    # Sample 5 points
    indices = [0, len(chunks) // 4, len(chunks) // 2, 3 * len(chunks) // 4, len(chunks) - 1]
    samples = [chunks[min(i, len(chunks) - 1)]["text_content"][:500] for i in indices]
    text = "\n---\n".join(samples)

    result = await _llm_call(
        f"Analyze these book excerpts and return JSON with: genres (list), subgenres (list), mood (string), themes (list), pace (slow/medium/fast), target_audience (string), content_warnings (list), one_liner (string).\n\n{text}",
        system="You are a literary analyst. Return valid JSON only.",
    )
    return {"tags": result}
