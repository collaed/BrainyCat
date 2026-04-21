"""Reading statistics, book notes, and library analytics."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one


async def get_stats(user_id: str) -> dict[str, Any]:
    """Comprehensive library and reading statistics."""
    # Reading stats
    finished = await fetch_all(
        """
        SELECT rp.updated_at, b.title, array_agg(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) as genres
        FROM reading_progress rp JOIN books b ON b.id = rp.book_id
        LEFT JOIN books_tags bt ON bt.book_id = b.id LEFT JOIN tags t ON t.id = bt.tag_id
        WHERE rp.user_id = $1 AND rp.is_finished = true GROUP BY rp.id, b.title ORDER BY rp.updated_at
    """,
        UUID(user_id),
    )

    genre_counts: dict[str, int] = {}
    monthly: dict[str, int] = {}
    for r in finished:
        for g in r["genres"] or []:
            genre_counts[g] = genre_counts.get(g, 0) + 1
        if r["updated_at"]:
            key = r["updated_at"].strftime("%Y-%m")
            monthly[key] = monthly.get(key, 0) + 1

    # Streak
    in_progress = await fetch_all(
        "SELECT DISTINCT DATE(updated_at) as d FROM reading_progress WHERE user_id = $1 ORDER BY d DESC",
        UUID(user_id),
    )
    streak = 0
    from datetime import date, timedelta

    today = date.today()
    for r in in_progress:
        if r["d"] == today - timedelta(days=streak):
            streak += 1
        else:
            break

    # Library-wide stats
    total_books = await fetch_one("SELECT count(*) as n FROM books")
    total_authors = await fetch_one("SELECT count(*) as n FROM authors")
    format_counts = await fetch_all("SELECT format, count(*) as n FROM book_files GROUP BY format ORDER BY n DESC")

    # Top 10 authors
    top_authors = await fetch_all("""
        SELECT a.name, count(*) as n FROM authors a
        JOIN books_authors ba ON ba.author_id = a.id
        GROUP BY a.name ORDER BY n DESC LIMIT 10
    """)

    # Genre/field detection from titles and descriptions
    genre_analysis = await _analyze_genres()

    # Personality analysis
    personality = _analyze_personality(genre_analysis, total_books["n"] if total_books else 0)

    return {
        "total_finished": len(finished),
        "books_per_month": monthly,
        "genre_distribution": genre_counts,
        "current_streak_days": streak,
        "library": {
            "total_books": total_books["n"] if total_books else 0,
            "total_authors": total_authors["n"] if total_authors else 0,
            "formats": {r["format"]: r["n"] for r in format_counts},
            "top_authors": [{"name": r["name"], "books": r["n"]} for r in top_authors],
        },
        "genre_analysis": genre_analysis,
        "personality": personality,
    }


async def _analyze_genres() -> dict[str, Any]:
    """Analyze the library by genre/field using title+description keywords."""
    rows = await fetch_all("SELECT title, description FROM books")

    fiction = 0
    nonfiction = 0
    genres: dict[str, int] = {}

    fiction_kw = {
        "romance": ["romance", "love story", "romantic", "passion"],
        "erotica": ["erotica", "erotic", "bdsm", "femdom", "kink", "dominant", "submissive", "fetish"],
        "thriller": ["thriller", "suspense", "crime"],
        "fantasy": ["fantasy", "magic", "dragon", "wizard"],
        "sci-fi": ["sci-fi", "science fiction", "space opera"],
        "horror": ["horror", "ghost", "haunted"],
        "mystery": ["mystery", "detective", "whodunit"],
        "literary": ["novel", "literary fiction"],
    }
    nonfiction_kw = {
        "self-help": ["self-help", "self help", "how to", "guide", "workbook", "handbook", "dummies"],
        "business": ["business", "entrepreneur", "startup", "marketing", "management"],
        "science": ["science", "physics", "biology", "chemistry", "mathematics"],
        "history": ["history", "historical", "war", "ancient"],
        "philosophy": ["philosophy", "ethics", "existential"],
        "psychology": ["psychology", "mental", "cognitive", "therapy", "anxiety", "hypnosis", "nlp"],
        "technology": ["programming", "software", "computer", "data science", "linux", "python"],
        "health": ["health", "fitness", "diet", "yoga", "meditation", "breathing"],
        "cooking": ["cooking", "recipe", "cuisine"],
        "language": ["french", "english", "german", "spanish", "language learning", "grammar"],
    }

    for r in rows:
        text = ((r["title"] or "") + " " + (r["description"] or "")).lower()
        matched = False
        for genre, kws in fiction_kw.items():
            if any(k in text for k in kws):
                genres[genre] = genres.get(genre, 0) + 1
                fiction += 1
                matched = True
                break
        if not matched:
            for field, kws in nonfiction_kw.items():
                if any(k in text for k in kws):
                    genres[field] = genres.get(field, 0) + 1
                    nonfiction += 1
                    matched = True
                    break
        if not matched:
            nonfiction += 1
            genres["unclassified"] = genres.get("unclassified", 0) + 1

    return {
        "fiction": fiction,
        "nonfiction": nonfiction,
        "genres": dict(sorted(genres.items(), key=lambda x: -x[1])),
    }


def _analyze_personality(genre_analysis: dict[str, Any], total: int) -> str:
    """Generate a fun personality description based on library composition."""
    if total < 10:
        return "Just getting started — your library is a blank canvas waiting to be filled! 🎨"

    genres = genre_analysis.get("genres", {})
    fiction = genre_analysis.get("fiction", 0)
    nonfiction = genre_analysis.get("nonfiction", 0)
    top = sorted(genres.items(), key=lambda x: -x[1])[:3]
    top_names = [t[0] for t in top]

    parts = []

    if fiction > nonfiction * 2:
        parts.append("A voracious fiction reader with a vivid imagination")
    elif nonfiction > fiction * 2:
        parts.append("A knowledge seeker who devours non-fiction")
    else:
        parts.append("A balanced reader who moves fluidly between fiction and non-fiction")

    if "erotica" in top_names:
        parts.append("with a boldly unapologetic taste for the sensual side of literature")
    if "self-help" in top_names or "psychology" in top_names:
        parts.append("on a journey of self-discovery and personal growth")
    if "technology" in top_names or "science" in top_names:
        parts.append("with a curious, analytical mind")
    if "philosophy" in top_names:
        parts.append("who ponders life's deepest questions")
    if "business" in top_names:
        parts.append("with entrepreneurial ambitions")
    if "history" in top_names:
        parts.append("fascinated by the stories of the past")
    if "fantasy" in top_names or "sci-fi" in top_names:
        parts.append("who escapes into worlds beyond imagination")

    if total > 500:
        parts.append(f"— and with {total} books, clearly someone who believes you can never have too many")
    elif total > 100:
        parts.append(f"— {total} books and counting, a serious collector")

    return ". ".join(parts) + ". 📚"


async def get_note(user_id: str, book_id: str) -> dict[str, Any] | None:
    row = await fetch_one("SELECT * FROM book_notes WHERE user_id = $1 AND book_id = $2", UUID(user_id), UUID(book_id))
    return dict(row) if row else None


async def save_note(user_id: str, book_id: str, content: str) -> dict[str, Any]:
    await execute(
        """INSERT INTO book_notes (user_id, book_id, content, updated_at)
           VALUES ($1,$2,$3,now())
           ON CONFLICT (user_id, book_id) DO UPDATE SET content = $3, updated_at = now()""",
        UUID(user_id),
        UUID(book_id),
        content,
    )
    return {"ok": True}


async def export_notes(user_id: str) -> list[dict[str, Any]]:
    rows = await fetch_all(
        """
        SELECT bn.content, bn.updated_at, b.title FROM book_notes bn
        JOIN books b ON b.id = bn.book_id WHERE bn.user_id = $1 ORDER BY bn.updated_at DESC
    """,
        UUID(user_id),
    )
    return [{"title": r["title"], "content": r["content"], "updated_at": r["updated_at"].isoformat()} for r in rows]
