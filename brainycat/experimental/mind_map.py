"""AI mind map — generate structured mind map from book content via LLM.

Config: BRAINYCAT_EXP_MIND_MAP=1
"""

from __future__ import annotations

from typing import Any


async def generate_mind_map(book_id: str) -> dict[str, Any]:
    """Generate a mind map JSON structure from a book's content."""
    from brainycat.db import fetch_one

    book = await fetch_one(
        "SELECT b.title, a.name as author, b.description FROM books b LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id WHERE b.id = $1 LIMIT 1",
        book_id,
    )
    if not book:
        return {"error": "not found"}

    # Use description + title for LLM prompt
    desc = book["description"] or book["title"]
    prompt = (
        f"Create a mind map for the book '{book['title']}' by {book['author'] or 'Unknown'}.\n"
        f"Description: {desc[:500]}\n\n"
        'Return JSON with this structure: {"title": "...", "branches": [{"label": "...", "children": [{"label": "..."}]}]}\n'
        "Include 4-6 main branches with 2-4 children each. Focus on key themes and concepts."
    )

    import httpx

    from brainycat.config import settings

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{settings.intello_url}/v1/chat/completions",
                json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3},
            )
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"]
                import json

                # Try to parse JSON from response
                for start in [content.find("{"), content.find("```json\n")]:
                    if start >= 0:
                        if "```" in content[start:]:
                            content = content[start:].split("```")[0] if start == 0 else content[start + 8 :].split("```")[0]
                        else:
                            content = content[start:]
                        try:
                            return json.loads(content)
                        except Exception:
                            continue
                return {"raw": content}
    except Exception as e:
        return {"error": str(e)}

    return {"error": "no response"}
