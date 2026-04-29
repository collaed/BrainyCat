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


# ── Book Recap ("Where was I?") ───────────────────────────────────────────
@router.post("/books/{book_id}/recap")
async def book_recap(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Generate a recap of everything read so far, based on reading progress."""
    from uuid import UUID

    import fitz

    # Get progress
    progress = await db.fetch_one(
        "SELECT percentage FROM reading_progress WHERE user_id = $1 AND book_id = $2",
        user["id"],
        UUID(book_id),
    )
    pct = (progress["percentage"] or 0) / 100 if progress else 0.5

    # Get book file
    row = await db.fetch_one(
        "SELECT bf.file_path, bf.format, b.title FROM book_files bf JOIN books b ON b.id = bf.book_id WHERE bf.book_id = $1 LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "no file"}

    # Extract text up to current position
    text = ""
    if row["format"] == "pdf":
        doc = fitz.open(row["file_path"])
        pages_to_read = max(1, int(len(doc) * pct))
        for i in range(min(pages_to_read, 50)):  # Cap at 50 pages for context
            text += doc[i].get_text() + "\n"
        doc.close()

    if not text:
        return {"error": "could not extract text"}

    # Summarize with LLM
    import httpx

    from brainycat.config import settings

    words = text.split()[:3000]
    context = " ".join(words)

    prompt = f"""You are helping a reader get back into a book they paused reading.
Book: "{row["title"]}"
They've read approximately {int(pct * 100)}% of the book.

Here is the text they've read so far (truncated):
{context[:6000]}

Give a concise recap (3-5 paragraphs) of what has happened so far, focusing on:
- Key events and plot points (fiction) or main arguments (non-fiction)
- Important characters or concepts introduced
- Where the narrative/argument was heading when they stopped"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{settings.intello_url}/v1/chat/completions",
                json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3},
            )
            if r.status_code == 200:
                return {"recap": r.json()["choices"][0]["message"]["content"], "percentage": int(pct * 100)}
    except Exception as e:
        return {"error": str(e)}
    return {"error": "LLM unavailable"}


# ── Chapter Summaries ─────────────────────────────────────────────────────
@router.post("/books/{book_id}/summarize-chapters")
async def summarize_chapters(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Generate bulleted summaries for each chapter."""
    from uuid import UUID

    import httpx

    from brainycat.config import settings

    row = await db.fetch_one(
        "SELECT bf.file_path, bf.format, b.title FROM book_files bf JOIN books b ON b.id = bf.book_id WHERE bf.book_id = $1 AND bf.format = 'epub' LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "epub not found"}

    # Extract chapters from EPUB
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    book = epub.read_epub(row["file_path"], options={"ignore_ncx": True})
    chapters = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        text = soup.get_text()
        if len(text.split()) > 100:  # Skip short items (TOC, copyright)
            title = soup.find(["h1", "h2", "h3"])
            chapters.append({"title": title.get_text() if title else f"Section {len(chapters) + 1}", "text": text})

    if not chapters:
        return {"error": "no chapters found"}

    # Summarize first 10 chapters
    summaries = []
    async with httpx.AsyncClient(timeout=30) as client:
        for ch in chapters[:10]:
            words = ch["text"].split()[:1500]
            prompt = f'Summarize this chapter in 3-5 bullet points. Chapter: "{ch["title"]}"\n\n{" ".join(words)}'
            try:
                r = await client.post(
                    f"{settings.intello_url}/v1/chat/completions",
                    json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2},
                )
                if r.status_code == 200:
                    summaries.append({"chapter": ch["title"], "summary": r.json()["choices"][0]["message"]["content"]})
            except Exception:
                pass

    return {"book": row["title"], "chapters": len(chapters), "summaries": summaries}


# ── Similar Passages Finder ───────────────────────────────────────────────
@router.post("/search/similar-passages")
async def similar_passages(body: dict[str, Any], user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Find similar passages across your library using full-text search."""
    query = body.get("text", "")
    if not query or len(query) < 10:
        return {"error": "provide at least 10 characters of text"}

    # Use PostgreSQL full-text search across annotations and clippings
    results = await db.fetch_all(
        """(SELECT 'annotation' as source, a.text, b.title, b.id as book_id,
                   ts_rank(to_tsvector('english', a.text), websearch_to_tsquery('english', $1)) as rank
            FROM annotations a JOIN books b ON b.id = a.book_id
            WHERE to_tsvector('english', a.text) @@ websearch_to_tsquery('english', $1)
            ORDER BY rank DESC LIMIT 5)
           UNION ALL
           (SELECT 'clipping' as source, c.text, b.title, b.id as book_id,
                   ts_rank(to_tsvector('english', c.text), websearch_to_tsquery('english', $1)) as rank
            FROM clippings c JOIN books b ON b.id = c.book_id
            WHERE to_tsvector('english', c.text) @@ websearch_to_tsquery('english', $1)
            ORDER BY rank DESC LIMIT 5)
           ORDER BY rank DESC LIMIT 10""",
        query,
    )
    return {"query": query, "results": [dict(r) for r in results]}


# ── Auto-tag from Content ─────────────────────────────────────────────────
@router.post("/books/{book_id}/auto-tag")
async def auto_tag(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """LLM reads first pages and suggests tags/genres."""
    from uuid import UUID

    import fitz
    import httpx

    from brainycat.config import settings

    row = await db.fetch_one(
        "SELECT bf.file_path, bf.format, b.title FROM book_files bf JOIN books b ON b.id = bf.book_id WHERE bf.book_id = $1 LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "no file"}

    text = ""
    if row["format"] == "pdf":
        doc = fitz.open(row["file_path"])
        for i in range(min(5, len(doc))):
            text += doc[i].get_text() + "\n"
        doc.close()
    elif row["format"] == "epub":
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub

        book = epub.read_epub(row["file_path"], options={"ignore_ncx": True})
        for item in list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))[:3]:
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text += soup.get_text() + "\n"

    if not text:
        return {"error": "no text"}

    prompt = f"""Based on the first pages of "{row["title"]}", suggest:
1. Genre (fiction/non-fiction + subgenre)
2. 5-8 tags (topics, themes, keywords)
3. Target audience
4. Mood/tone

Return JSON: {{"genre": "...", "tags": ["..."], "audience": "...", "mood": "..."}}

TEXT:
{" ".join(text.split()[:1000])}"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{settings.intello_url}/v1/chat/completions",
                json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2},
            )
            if r.status_code == 200:
                import json

                content = r.json()["choices"][0]["message"]["content"]
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    result = json.loads(content[start:end])
                    # Apply tags to book
                    for tag_name in result.get("tags", []):
                        tag = await db.fetch_one(
                            "INSERT INTO tags (name) VALUES ($1) ON CONFLICT (name) DO UPDATE SET name = $1 RETURNING id",
                            tag_name.lower(),
                        )
                        if tag:
                            await db.execute(
                                "INSERT INTO books_tags (book_id, tag_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                                UUID(book_id),
                                tag["id"],
                            )
                    return result
    except Exception as e:
        return {"error": str(e)}
    return {"error": "LLM unavailable"}


# ── Story Graph ───────────────────────────────────────────────────────────
@router.post("/books/{book_id}/story-graph")
async def create_story_graph(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Analyze a book's narrative arc (tension/action over time)."""
    from brainycat.story_graph import analyze_book

    return await analyze_book(book_id, str(user["id"]))


@router.get("/books/{book_id}/story-graph")
async def get_story_graph(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Get stored story graph for a book."""
    from uuid import UUID

    row = await db.fetch_one(
        "SELECT points, metadata FROM story_graphs WHERE book_id = $1 AND user_id = $2",
        UUID(book_id),
        user["id"],
    )
    if not row:
        return {"error": "no story graph — trigger analysis first"}
    return {"points": row["points"], "metadata": row["metadata"]}


@router.get("/books/{book_id}/story-graph.svg")
async def story_graph_svg(book_id: str, theme: str = "dark", user: Any = Depends(get_current_user)) -> Any:
    """Export story graph as SVG (printable)."""
    from uuid import UUID

    from fastapi.responses import Response

    from brainycat.story_graph import render_svg

    row = await db.fetch_one(
        "SELECT points, metadata FROM story_graphs WHERE book_id = $1 AND user_id = $2",
        UUID(book_id),
        user["id"],
    )
    if not row:
        return {"error": "no story graph"}

    title = (row["metadata"] or {}).get("title", "Book")
    svg = render_svg([{"title": title, "points": row["points"]}], theme=theme)
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/story-graphs/compare")
async def compare_story_graphs(ids: str, theme: str = "dark", user: Any = Depends(get_current_user)) -> Any:
    """Compare multiple story graphs overlaid. ids=comma-separated book IDs."""
    from uuid import UUID

    from fastapi.responses import Response

    from brainycat.story_graph import render_svg

    book_ids = [i.strip() for i in ids.split(",") if i.strip()]
    graphs = []
    for bid in book_ids[:6]:
        row = await db.fetch_one(
            "SELECT points, metadata FROM story_graphs WHERE book_id = $1 AND user_id = $2",
            UUID(bid),
            user["id"],
        )
        if row:
            graphs.append({"title": (row["metadata"] or {}).get("title", bid[:8]), "points": row["points"]})

    if not graphs:
        return {"error": "no graphs found"}

    svg = render_svg(graphs, theme=theme)
    return Response(content=svg, media_type="image/svg+xml")


@router.post("/story-graph/generate")
async def generate_story_graph(body: dict[str, Any], user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Generate a proposed narrative arc for a new story based on premise + inspiration books."""
    from brainycat.story_graph import generate_story_arc

    return await generate_story_arc(
        premise=body.get("premise", ""),
        genre=body.get("genre", "fiction"),
        length=body.get("length", "novel"),
        inspiration_ids=body.get("inspiration_book_ids", []),
    )
