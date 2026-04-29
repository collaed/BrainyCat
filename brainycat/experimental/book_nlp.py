"""Book NLP — extract characters, key quotes, and themes via LLM."""

from __future__ import annotations

from typing import Any


async def extract_characters(book_id: str) -> dict[str, Any]:
    """Extract characters and their relationships from a book using LLM."""
    from uuid import UUID

    import fitz
    import httpx

    from brainycat.config import settings
    from brainycat.db import fetch_one

    row = await fetch_one(
        "SELECT bf.file_path, b.title FROM book_files bf JOIN books b ON b.id = bf.book_id WHERE bf.book_id = $1 AND bf.format = 'pdf' LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "no pdf"}

    doc = fitz.open(row["file_path"])
    text = " ".join(doc[i].get_text() for i in range(min(30, len(doc))))[:6000]
    doc.close()

    prompt = f"""Analyze this text from "{row["title"]}" and extract:
1. Characters (name, role/description, importance: major/minor)
2. Key themes (3-5 themes)
3. Notable quotes (2-3 memorable lines)

Return JSON: {{"characters": [{{"name": "...", "role": "...", "importance": "major"}}], "themes": ["..."], "quotes": ["..."]}}

TEXT:
{text}"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{settings.intello_url}/v1/chat/completions",
                json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2},
            )
            if r.status_code == 200:
                import json

                content = r.json()["choices"][0]["message"]["content"]
                # Try to parse JSON
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    return json.loads(content[start:end])
                return {"raw": content}
    except Exception as e:
        return {"error": str(e)}
    return {"error": "LLM unavailable"}
