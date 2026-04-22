"""Book Genome — taste-based recommendation engine ported from CineCross.

Maps CineCross's Movie Genome to books:
  keywords → tags/themes     directors → authors
  actors → publishers        genres → genres/Thema codes
  cast → series              writers → translators

5 recommendation categories:
  DNA: weighted taste profile match
  Author: re-ranked by author affinity
  Community: similar books from highly-rated ones (pgvector)
  Overlap: multi-source high ratings (Google Books + Open Library)
  Anti: books you'd probably hate
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from brainycat.db import fetch_all


async def build_taste_profile(user_id: str) -> dict[str, dict[str, float]]:
    """Build weighted taste profile from user's reading history + ratings."""
    rows = await fetch_all(
        """
        SELECT b.id, b.title, b.rating, b.description,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
               array_agg(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) as tags,
               array_agg(DISTINCT s.name) FILTER (WHERE s.name IS NOT NULL) as series,
               rp.percentage
        FROM books b
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        LEFT JOIN books_tags bt ON bt.book_id = b.id LEFT JOIN tags t ON t.id = bt.tag_id
        LEFT JOIN books_series bs ON bs.book_id = b.id LEFT JOIN series s ON s.id = bs.series_id
        LEFT JOIN reading_progress rp ON rp.book_id = b.id AND rp.user_id = $1
        WHERE rp.percentage > 0.1 OR b.rating IS NOT NULL
        GROUP BY b.id, rp.percentage
    """,
        UUID(user_id),
    )

    tag_scores: dict[str, float] = {}
    author_scores: dict[str, float] = {}
    series_scores: dict[str, float] = {}

    for r in rows:
        # Rating-based weight (like CineCross: (rating - 5) / 5)
        # Books without explicit rating: progress > 50% = implicit 7
        rating = r["rating"]
        if rating is None:
            rating = 7.0 if (r["percentage"] or 0) > 0.5 else 6.0
        if rating < 6:
            continue
        weight = (rating - 5) / 5.0

        for tag in r["tags"] or []:
            tag_scores[tag] = tag_scores.get(tag, 0) + weight
        for author in r["authors"] or []:
            author_scores[author] = author_scores.get(author, 0) + weight
        for s in r["series"] or []:
            series_scores[s] = series_scores.get(s, 0) + weight

    return {
        "tags": tag_scores,
        "authors": author_scores,
        "series": series_scores,
    }


def score_book(
    book: dict[str, Any],
    profile: dict[str, dict[str, float]],
) -> float:
    """Score a candidate book against user's taste profile.

    Weights (ported from CineCross):
      tags: 1.0x (like keywords — themes, moods)
      authors: 2.0x (like directors — strong signal)
      series: 1.5x (like cast — moderate signal)
      rating boost: multiply by (0.5 + avg_rating/20)
    """
    score = 0.0
    for tag in book.get("tags") or []:
        score += profile["tags"].get(tag, 0) * 1.0
    for author in book.get("authors") or []:
        score += profile["authors"].get(author, 0) * 2.0
    for s in book.get("series") or []:
        score += profile["series"].get(s, 0) * 1.5

    # Boost by aggregated rating (adjusted for 1-10 scale)
    if book.get("rating"):
        score *= 0.7 + book["rating"] / 10.0  # rating 5 = 1.2x, rating 10 = 1.7x
    elif book.get("quality_score"):
        score *= 0.5 + book["quality_score"] / 200.0

    return round(score, 2)


async def get_5cat_recommendations(
    user_id: str,
    n_per_cat: int = 8,
) -> dict[str, list[dict[str, Any]]]:
    """5-category recommendations (ported from CineCross)."""
    profile = await build_taste_profile(user_id)

    # Get all unread books
    candidates = await fetch_all(
        """
        SELECT b.id, b.title, b.rating, b.quality_score, b.description,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
               array_agg(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) as tags,
               array_agg(DISTINCT s.name) FILTER (WHERE s.name IS NOT NULL) as series
        FROM books b
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        LEFT JOIN books_tags bt ON bt.book_id = b.id LEFT JOIN tags t ON t.id = bt.tag_id
        LEFT JOIN books_series bs ON bs.book_id = b.id LEFT JOIN series s ON s.id = bs.series_id
        LEFT JOIN reading_progress rp ON rp.book_id = b.id AND rp.user_id = $1
        WHERE rp.id IS NULL
        GROUP BY b.id
    """,
        UUID(user_id),
    )

    scored = []
    for c in candidates:
        s = score_book(dict(c), profile)
        if s > 0:
            scored.append({**dict(c), "id": str(c["id"]), "score": s})
    scored.sort(key=lambda x: x["score"], reverse=True)

    # DNA: pure taste match
    dna = scored[: n_per_cat * 3]

    # Author: re-rank by author affinity
    author_ranked = sorted(scored, key=lambda x: sum(profile["authors"].get(a, 0) for a in (x.get("authors") or [])), reverse=True)

    # Community: pgvector similar to top-rated books
    community = []
    top_rated = await fetch_all(
        """
        SELECT book_id FROM reading_progress
        WHERE user_id = $1 ORDER BY progress DESC LIMIT 5
    """,
        UUID(user_id),
    )
    seen_ids = set()
    for tr in top_rated:
        similar = await fetch_all(
            """
            SELECT b.id, b.title,
                   array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
                   1 - (b.embedding <=> (SELECT embedding FROM books WHERE id = $1)) as sim
            FROM books b
            LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
            LEFT JOIN reading_progress rp ON rp.book_id = b.id AND rp.user_id = $2
            WHERE b.id != $1 AND b.embedding IS NOT NULL AND rp.id IS NULL
            GROUP BY b.id ORDER BY b.embedding <=> (SELECT embedding FROM books WHERE id = $1) LIMIT 5
        """,
            tr["book_id"],
            UUID(user_id),
        )
        for s in similar:
            if str(s["id"]) not in seen_ids:
                seen_ids.add(str(s["id"]))
                community.append({**dict(s), "id": str(s["id"]), "similarity": round(float(s["sim"] or 0), 3)})

    # Overlap: books with both high quality_score AND high rating
    overlap = [b for b in scored if (b.get("quality_score") or 0) > 70 and (b.get("rating") or 0) > 7]
    overlap.sort(key=lambda x: (x.get("rating") or 0) + (x.get("quality_score") or 0) / 10, reverse=True)

    # Anti: tags user consistently avoids
    anti = await _anti_recommendations(user_id, candidates)

    # Deduplicate across categories
    seen: set[str] = set()

    def dedup(lst: list[dict], n: int) -> list[dict]:
        result = []
        for item in lst:
            bid = item.get("id", str(item.get("id", "")))
            if bid not in seen:
                seen.add(bid)
                result.append(
                    {
                        "id": bid,
                        "title": item.get("title"),
                        "authors": item.get("authors", []),
                        "score": item.get("score", item.get("similarity", 0)),
                    }
                )
                if len(result) >= n:
                    break
        return result

    return {
        "dna": dedup(dna, n_per_cat),
        "author": dedup(author_ranked, n_per_cat),
        "community": dedup(community, n_per_cat),
        "overlap": dedup(overlap, n_per_cat),
        "anti": anti[:n_per_cat],
        "profile_summary": {
            "top_tags": sorted(profile["tags"], key=profile["tags"].get, reverse=True)[:10],
            "top_authors": sorted(profile["authors"], key=profile["authors"].get, reverse=True)[:5],
        },
    }


async def _anti_recommendations(
    user_id: str,
    candidates: list[Any],
) -> list[dict[str, Any]]:
    """Books you'd probably hate — highly rated in tags you consistently rate low."""
    low_rated = await fetch_all("""
        SELECT array_agg(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) as tags
        FROM books b
        JOIN books_tags bt ON bt.book_id = b.id JOIN tags t ON t.id = bt.tag_id
        WHERE b.rating IS NOT NULL AND b.rating < 5
    """)
    hated_tags: set[str] = set()
    for r in low_rated:
        for t in r["tags"] or []:
            hated_tags.add(t)
    if not hated_tags:
        return []

    anti = []
    for c in candidates:
        book_tags = set(c["tags"] or [])
        if book_tags & hated_tags and (c["quality_score"] or 0) > 60:
            anti.append({"id": str(c["id"]), "title": c["title"], "reason": f"tags: {', '.join(book_tags & hated_tags)}"})
    return anti
