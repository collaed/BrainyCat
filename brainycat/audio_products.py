"""Audio product generation — full, summary, and reinforcement versions.

Three modes:
1. Full: TTS of entire book (existing)
2. Summary: LLM condenses to 15-min Blinkist-style key points
3. Reinforcement: Spaced repetition audio flashcards (key takeaways)

Delivered via podcast RSS feed with scheduling metadata.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import httpx

from brainycat import db
from brainycat.config import settings


async def generate_summary_script(book_id: str) -> dict[str, Any]:
    """Generate a Blinkist-style summary script (10-15 min read-aloud)."""
    row = await db.fetch_one(
        "SELECT b.title, b.description, bf.file_path, bf.format FROM books b JOIN book_files bf ON bf.book_id = b.id WHERE b.id = $1 LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "not found"}

    # Extract key text
    import fitz

    text = ""
    if row["format"] == "pdf":
        doc = fitz.open(row["file_path"])
        for i in range(min(50, len(doc))):
            text += doc[i].get_text() + "\n"
        doc.close()

    words = text.split()[:6000]
    context = " ".join(words)

    prompt = f"""Create a Blinkist/Headway-style audio summary of "{row["title"]}".

Book text (excerpt):
{context[:5000]}

Generate a script for a 12-15 minute narration that covers:
1. Opening hook (why this book matters) — 1 min
2. Core idea #1 with example — 3 min
3. Core idea #2 with example — 3 min
4. Core idea #3 with example — 3 min
5. Practical takeaways (what to do differently) — 2 min
6. Closing (one sentence to remember) — 30 sec

Write in a conversational, engaging tone. Use "you" to address the listener.
Return the full script text (no JSON, no formatting instructions)."""

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{settings.intello_url}/v1/chat/completions",
            json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.4},
        )
        if r.status_code == 200:
            script = r.json()["choices"][0]["message"]["content"]
            # Store
            await db.execute(
                """INSERT INTO audio_products (book_id, product_type, script, status)
                   VALUES ($1, 'summary', $2, 'ready')
                   ON CONFLICT (book_id, product_type) DO UPDATE SET script = $2, status = 'ready'""",
                UUID(book_id),
                script,
            )
            return {"type": "summary", "script_length": len(script), "est_minutes": len(script.split()) // 150}

    return {"error": "LLM unavailable"}


async def generate_reinforcement_cards(book_id: str) -> dict[str, Any]:
    """Generate spaced repetition audio cards (key takeaways as short sentences)."""
    row = await db.fetch_one(
        "SELECT b.title, b.description, bf.file_path, bf.format FROM books b JOIN book_files bf ON bf.book_id = b.id WHERE b.id = $1 LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "not found"}

    import fitz

    text = ""
    if row["format"] == "pdf":
        doc = fitz.open(row["file_path"])
        for i in range(min(30, len(doc))):
            text += doc[i].get_text() + "\n"
        doc.close()

    prompt = f"""From the book "{row["title"]}", extract 10-15 key takeaways as short, memorable sentences.

Book text:
{" ".join(text.split()[:4000])}

Rules:
- Each takeaway should be 1-2 sentences (speakable in 10-15 seconds)
- Use active voice, present tense
- Make them actionable ("Do X when Y" not "The author says...")
- Include the "why" briefly
- Order from most important to least

Return as JSON array: ["takeaway 1", "takeaway 2", ...]"""

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{settings.intello_url}/v1/chat/completions",
            json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3},
        )
        if r.status_code == 200:
            content = r.json()["choices"][0]["message"]["content"]
            start = content.find("[")
            end = content.rfind("]") + 1
            if start >= 0 and end > start:
                cards = json.loads(content[start:end])
                await db.execute(
                    """INSERT INTO audio_products (book_id, product_type, script, status)
                       VALUES ($1, 'reinforcement', $2, 'ready')
                       ON CONFLICT (book_id, product_type) DO UPDATE SET script = $2, status = 'ready'""",
                    UUID(book_id),
                    json.dumps(cards),
                )
                return {"type": "reinforcement", "cards": cards, "count": len(cards)}

    return {"error": "LLM unavailable"}


def reinforcement_schedule(card_index: int, total_cards: int, start_date: date = None) -> list[date]:
    """Calculate spaced repetition schedule for a card.

    Frequency decreases: day 1, 3, 7, 14, 30, 60, 90
    Cards are staggered so you don't hear all on the same day.
    """
    if start_date is None:
        start_date = date.today()

    intervals = [0, 2, 4, 7, 14, 30, 60, 90]
    offset = card_index % 3  # Stagger cards across days
    return [start_date + timedelta(days=d + offset) for d in intervals]
