"""Routes: ai."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from brainycat import companion
from brainycat.auth import get_current_user
from brainycat.config import settings
from brainycat.http_client import get_client

router = APIRouter(prefix="/api/v1", tags=["ai"])


@router.get("/ai/recap/{book_id}")
async def ai_recap(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, str]:
    return await companion.recap(book_id, str(user["id"]))


@router.post("/ai/ask/{book_id}")
async def ai_ask(book_id: str, question: str = Query(...), user: Any = Depends(get_current_user)) -> dict[str, str]:
    return await companion.ask(book_id, str(user["id"]), question)


@router.post("/ai/auto-tag/{book_id}")
async def ai_tag(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await companion.auto_tag(book_id)


# Reviews: see aggregated endpoint below


# ── Stats & Notes ────────────────────────────────────────────────────────


@router.post("/ai/explain")
async def ai_explain(body: dict[str, Any], _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    text = body.get("text", "")[:1000]
    if not text:
        return {"error": "no text"}
    try:
        client = get_client()
        resp = await client.post(
            f"{settings.intello_url}/v1/chat/completions",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": f'Explain this passage briefly (2-3 sentences). If it\'s from a book, provide context:\n\n"{text}"',
                    }
                ],
                "task_hint": "analysis",
                "max_tokens": 200,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {"explanation": data.get("choices", [{}])[0].get("message", {}).get("content", "")}
    except Exception:
        pass
    return {"error": "AI explanation unavailable — Intello not connected"}


@router.post("/ai/translate")
async def ai_translate(body: dict[str, Any], _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    text = body.get("text", "")[:1000]
    if not text:
        return {"error": "no text"}
    try:
        client = get_client()
        resp = await client.post(
            f"{settings.intello_url}/v1/chat/completions",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": f'Translate this to English. If already English, translate to French. Just the translation, nothing else:\n\n"{text}"',
                    }
                ],
                "max_tokens": 300,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {"translation": data.get("choices", [{}])[0].get("message", {}).get("content", "")}
    except Exception:
        pass
    return {"error": "Translation unavailable — Intello not connected"}


# ── AI explain/translate already added above ──────────────────────────────
# (endpoints POST /api/v1/ai/explain and /api/v1/ai/translate)


# ── First-run setup ──────────────────────────────────────────────────────


# ── Ask This Book ─────────────────────────────────────────────────────────
@router.post("/books/{book_id}/ask")
async def ask_book(book_id: str, body: dict[str, Any], user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Ask a question about a book — LLM answers grounded in its content."""
    question = body.get("question", "")
    if not question:
        return {"error": "provide 'question'"}

    from uuid import UUID

    import fitz

    # Get book text (first ~5000 words for context window)
    row = await db.fetch_one(
        "SELECT bf.file_path, bf.format, b.title FROM book_files bf JOIN books b ON b.id = bf.book_id WHERE bf.book_id = $1 LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "no file"}

    text = ""
    if row["format"] == "pdf":
        doc = fitz.open(row["file_path"])
        for i in range(min(30, len(doc))):
            text += doc[i].get_text() + "\n"
            if len(text.split()) > 5000:
                break
        doc.close()
    elif row["format"] == "epub":
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub

        book = epub.read_epub(row["file_path"], options={"ignore_ncx": True})
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text += soup.get_text() + "\n"
            if len(text.split()) > 5000:
                break

    if not text:
        return {"error": "could not extract text"}

    # Truncate to ~4000 words
    words = text.split()[:4000]
    context = " ".join(words)

    # Ask LLM
    import httpx

    from brainycat.config import settings

    prompt = f"""Based on the following text from the book "{row["title"]}", answer this question.

BOOK TEXT:
{context[:8000]}

QUESTION: {question}

Answer concisely based only on the book content. If the answer isn't in the text, say so."""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{settings.intello_url}/v1/chat/completions",
                json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2},
            )
            if r.status_code == 200:
                answer = r.json()["choices"][0]["message"]["content"]
                return {"answer": answer, "context_words": len(words)}
    except Exception as e:
        return {"error": str(e)}

    return {"error": "LLM unavailable"}
