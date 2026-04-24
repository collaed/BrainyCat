"""AI book companion — recap, Q&A, character tracker, semantic search via pgvector + Intello."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from brainycat.config import settings
from brainycat.db import execute, fetch_all, fetch_one
from brainycat.http_client import get_client


async def _llm(
    prompt: str, system: str = "You are a helpful book companion. Never reveal spoilers beyond the reader's current position."
) -> str:
    try:
        client = get_client()
        resp = await client.post(
            f"{settings.intello_url}/v1/chat/completions",
            json={
                "model": "auto",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "task_hint": "analysis",
                "max_tokens": 1024,
            },
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return "LLM unavailable"


async def index_book_content(book_id: str) -> dict[str, Any]:
    """Chunk book content and store with embeddings for semantic search."""
    file_row = await fetch_one(
        "SELECT file_path, format FROM book_files WHERE book_id = $1 AND format IN ('epub','pdf') LIMIT 1",
        UUID(book_id),
    )
    if not file_row:
        return {"ok": False, "error": "no file"}

    from brainycat.fingerprints import _extract_full_text

    text = _extract_full_text(file_row["file_path"], file_row["format"])
    if len(text) < 500:
        return {"ok": False, "error": "too short"}

    # Chunk into ~1000 char pieces
    from brainycat.embeddings import _text_to_vector

    chunks = []
    chunk_size = 1000
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        if len(chunk) < 100:
            continue
        vec = _text_to_vector(chunk)
        vec_str = "[" + ",".join(str(v) for v in vec) + "]"
        chunks.append((i // chunk_size, chunk, vec_str))

    # Store chunks
    await execute("DELETE FROM content_chunks WHERE book_id = $1", UUID(book_id))
    for idx, chunk_text, vec_str in chunks:
        await execute(
            "INSERT INTO content_chunks (book_id, chapter_index, chunk_index, text_content, embedding) VALUES ($1, 0, $2, $3, $4::vector)",
            UUID(book_id),
            idx,
            chunk_text,
            vec_str,
        )

    return {"ok": True, "chunks": len(chunks)}


async def semantic_search(book_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search book content by meaning using pgvector cosine similarity."""
    from brainycat.embeddings import _text_to_vector

    vec = _text_to_vector(query)
    vec_str = "[" + ",".join(str(v) for v in vec) + "]"

    rows = await fetch_all(
        """
        SELECT chunk_index, text_content, embedding <=> $1::vector as distance
        FROM content_chunks
        WHERE book_id = $2
        ORDER BY distance ASC
        LIMIT $3
    """,
        vec_str,
        UUID(book_id),
        limit,
    )

    return [{"chunk": r["chunk_index"], "text": r["text_content"][:300], "relevance": round(1 - r["distance"], 3)} for r in rows]


async def recap(book_id: str, user_id: str) -> dict[str, str]:
    """Generate a recap up to the user's current reading position."""
    progress = await fetch_one("SELECT percentage FROM reading_progress WHERE book_id = $1 AND user_id = $2", UUID(book_id), UUID(user_id))
    pct = progress["percentage"] if progress else 0
    book = await fetch_one("SELECT title FROM books WHERE id = $1", UUID(book_id))
    title = book["title"] if book else "this book"

    # Get content chunks up to current position
    chunks = await fetch_all(
        "SELECT text_content FROM content_chunks WHERE book_id = $1 ORDER BY chapter_index, chunk_index",
        UUID(book_id),
    )
    if not chunks:
        # Try to index first
        result = await index_book_content(book_id)
        if not result.get("ok"):
            return {"recap": "No content indexed. The book may be a scanned PDF that needs OCR first."}
        chunks = await fetch_all(
            "SELECT text_content FROM content_chunks WHERE book_id = $1 ORDER BY chapter_index, chunk_index",
            UUID(book_id),
        )

    cutoff = max(1, int(len(chunks) * pct / 100))
    text = "\n".join(c["text_content"] for c in chunks[:cutoff])[:6000]

    recap_text = await _llm(
        f"Summarize what has happened so far in '{title}' (reader is at {pct:.0f}%). Be concise, 3-5 paragraphs:\n\n{text}"
    )
    return {"recap": recap_text, "percentage": pct}


async def ask(book_id: str, user_id: str, question: str) -> dict[str, str]:
    """Answer a question about the book without spoilers."""
    progress = await fetch_one("SELECT percentage FROM reading_progress WHERE book_id = $1 AND user_id = $2", UUID(book_id), UUID(user_id))
    pct = progress["percentage"] if progress else 100

    # Semantic search for relevant chunks
    relevant = await semantic_search(book_id, question, limit=3)
    if not relevant:
        # Index and retry
        await index_book_content(book_id)
        relevant = await semantic_search(book_id, question, limit=3)

    context = "\n---\n".join(r["text"] for r in relevant)
    answer = await _llm(f"Based on the text below (reader is at {pct:.0f}%), answer: {question}\n\nRelevant passages:\n{context}")
    return {"answer": answer, "sources": len(relevant)}


async def auto_tag(book_id: str) -> dict[str, Any]:
    """Auto-tag a book using LLM analysis of text samples."""
    chunks = await fetch_all("SELECT text_content FROM content_chunks WHERE book_id = $1 ORDER BY chunk_index", UUID(book_id))
    if not chunks:
        await index_book_content(book_id)
        chunks = await fetch_all("SELECT text_content FROM content_chunks WHERE book_id = $1 ORDER BY chunk_index", UUID(book_id))
    if not chunks:
        return {"error": "No content"}

    # Sample 5 points
    indices = [0, len(chunks) // 4, len(chunks) // 2, 3 * len(chunks) // 4, max(0, len(chunks) - 1)]
    samples = [chunks[min(i, len(chunks) - 1)]["text_content"][:400] for i in indices]
    text = "\n---\n".join(samples)

    result = await _llm(
        f'Analyze these book excerpts and return JSON: {{"genres": [], "mood": "", "themes": [], "pace": "slow/medium/fast", "audience": "", "one_liner": ""}}\n\n{text}',
        system="You are a literary analyst. Return valid JSON only.",
    )
    return {"tags": result}
