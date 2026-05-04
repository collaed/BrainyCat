"""LLM consistency check — validates enriched metadata makes sense together.

After enrichment, submit the complete entry to LLM and ask:
"Does this title + author + description + ISBN belong to the same book?"

Catches: wrong descriptions, wrong authors, mismatched ISBNs.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from brainycat import db
from brainycat.config import settings


async def check_consistency(book_id: str) -> dict[str, Any]:
    """Validate that a book's metadata is internally consistent."""
    book = await db.fetch_one(
        """SELECT b.title, b.description, b.isbn, b.language, b.pubdate,
                  a.name as author
           FROM books b
           LEFT JOIN books_authors ba ON ba.book_id = b.id
           LEFT JOIN authors a ON a.id = ba.author_id
           WHERE b.id = $1 LIMIT 1""",
        UUID(book_id),
    )
    if not book:
        return {"error": "not found"}

    # Only check if we have enough data to validate
    if not book.get("description") or not book.get("title"):
        return {"skip": True, "reason": "insufficient data"}

    prompt = f"""You are a librarian validating book catalog entries. Check if this metadata is internally consistent (all fields describe the SAME book):

Title: {book["title"]}
Author: {book.get("author") or "Unknown"}
ISBN: {book.get("isbn") or "None"}
Language: {book.get("language") or "Unknown"}
Description: {(book.get("description") or "")[:500]}

Answer with JSON:
{{"consistent": true/false, "issues": ["list of problems if any"], "confidence": 0.0-1.0}}

Examples of inconsistencies:
- Description is about a completely different topic than the title
- Author is a company name that publishes books, not writes them
- Language doesn't match the title's language
- Description mentions a different book title"""

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{settings.intello_url}/v1/chat/completions",
                json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1},
            )
            if r.status_code == 200:
                import json

                content = r.json()["choices"][0]["message"]["content"]
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    result = json.loads(content[start:end])
                    # If inconsistent, flag the book
                    if not result.get("consistent", True):
                        await db.execute(
                            "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'), '{consistency_issues}', $1::jsonb) WHERE id = $2",
                            json.dumps(result.get("issues", [])),
                            UUID(book_id),
                        )
                    return result
    except Exception as e:
        return {"error": str(e)}

    return {"error": "LLM unavailable"}


async def batch_check(limit: int = 10) -> dict[str, Any]:
    """Check consistency for recently enriched books."""
    books = await db.fetch_all(
        """SELECT b.id FROM books b
           WHERE b.quality_score >= 50
           AND b.description IS NOT NULL
           AND NOT (b.extra_metadata ? 'consistency_checked')
           ORDER BY b.updated_at DESC LIMIT $1""",
        limit,
    )

    results = {"checked": 0, "consistent": 0, "inconsistent": 0, "issues": []}
    for book in books:
        r = await check_consistency(str(book["id"]))
        results["checked"] += 1
        if r.get("consistent"):
            results["consistent"] += 1
        elif r.get("consistent") is False:
            results["inconsistent"] += 1
            results["issues"].append({"book_id": str(book["id"]), "issues": r.get("issues", [])})

        # Mark as checked
        await db.execute(
            "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'), '{consistency_checked}', 'true'::jsonb) WHERE id = $1",
            book["id"],
        )

    return results
