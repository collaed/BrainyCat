"""Book Genome — taste-based recommendation engine ported from CineCross.

Maps CineCross's Movie Genome to books:
  tags/themes → keywords (1.0x)    authors → directors (2.0x)
  narrators → actors (1.5x)        series → cast (1.5x)
  NLP themes → plot keywords (0.5x)

7 recommendation categories:
  DNA: weighted taste profile match
  Author: re-ranked by author affinity
  Narrator: re-ranked by narrator affinity (audiobook-specific)
  Community: similar books from highly-rated ones (pgvector)
  Hidden Gems: low-reader-count, high-completion books
  Complete Series: series with gaps
  Anti: books you'd probably hate
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from brainycat.db import fetch_all
from brainycat.stopwords import STOPWORDS

WEIGHTS = {"author": 2.0, "narrator": 1.5, "genre": 1.0, "series": 1.5, "theme": 0.5}


def _extract_themes(text: str) -> dict[str, int]:
    """NLP-lite theme extraction from description text."""
    if not text:
        return {}
    # Strip HTML
    clean = re.sub(r"<[^>]+>", " ", text)
    words = re.findall(r"[a-zA-ZÀ-ÿ]{4,}", clean.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w not in STOPWORDS:
            freq[w] = freq.get(w, 0) + 1
    return freq


def _implicit_rating(percentage: float | None, is_finished: bool | None) -> float:
    """4-tier implicit rating from reading progress."""
    if is_finished:
        return 8.0
    pct = percentage or 0
    if pct > 0.8:
        return 8.0
    if pct > 0.5:
        return 7.0
    if pct > 0.1:
        return 6.0
    if pct > 0:
        return 4.0  # Started but abandoned
    return 0.0


async def build_taste_profile(user_id: str) -> dict[str, dict[str, float]]:
    """Build weighted taste profile from user's reading history + ratings."""
    rows = await fetch_all(
        """
        SELECT b.id, b.title, b.rating, b.description, b.language,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
               array_agg(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) as tags,
               array_agg(DISTINCT s.name) FILTER (WHERE s.name IS NOT NULL) as series,
               rp.percentage, rp.is_finished
        FROM books b
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        LEFT JOIN books_tags bt ON bt.book_id = b.id LEFT JOIN tags t ON t.id = bt.tag_id
        LEFT JOIN books_series bs ON bs.book_id = b.id LEFT JOIN series s ON s.id = bs.series_id
        LEFT JOIN reading_progress rp ON rp.book_id = b.id AND rp.user_id = $1
        WHERE rp.percentage > 0 OR b.rating IS NOT NULL
        GROUP BY b.id, rp.percentage, rp.is_finished
    """,
        UUID(user_id),
    )

    tag_scores: dict[str, float] = {}
    author_scores: dict[str, float] = {}
    series_scores: dict[str, float] = {}
    theme_scores: dict[str, float] = {}
    low_genres: set[str] = set()
    languages: dict[str, int] = {}

    for r in rows:
        rating = r["rating"]
        if rating is None:
            rating = _implicit_rating(r["percentage"], r["is_finished"])
        if rating == 0:
            continue

        weight = (rating - 5) / 5.0  # CineCross formula: -1.0 to +1.0

        # Positive-weight books build the profile
        if weight > 0:
            for tag in r["tags"] or []:
                tag_scores[tag] = tag_scores.get(tag, 0) + weight * WEIGHTS["genre"]
            for author in r["authors"] or []:
                author_scores[author] = author_scores.get(author, 0) + weight * WEIGHTS["author"]
            for s in r["series"] or []:
                series_scores[s] = series_scores.get(s, 0) + weight * WEIGHTS["series"]
            # NLP themes from description
            themes = _extract_themes(r["description"] or "")
            for theme, freq in themes.items():
                theme_scores[theme] = theme_scores.get(theme, 0) + weight * WEIGHTS["theme"] * min(freq, 3) / 3
        else:
            # Negative-weight: track abandoned/disliked genres
            for tag in r["tags"] or []:
                low_genres.add(tag)

        # Language tracking
        lang = r.get("language") or ""
        if lang:
            languages[lang] = languages.get(lang, 0) + 1

    return {
        "tags": tag_scores,
        "authors": author_scores,
        "series": series_scores,
        "themes": theme_scores,
        "low_genres": list(low_genres),
        "languages": languages,
    }


def score_book(
    book: dict[str, Any],
    profile: dict[str, dict[str, float]],
) -> float:
    """Score a candidate book against user's taste profile.

    Weights (CineCross-derived):
      tags/genres: 1.0x    authors: 2.0x    series: 1.5x    themes: 0.5x
    """
    score = 0.0
    for tag in book.get("tags") or []:
        score += profile["tags"].get(tag, 0)
    for author in book.get("authors") or []:
        score += profile["authors"].get(author, 0)
    for s in book.get("series") or []:
        score += profile["series"].get(s, 0)

    # Theme matching from description
    if book.get("description") and profile.get("themes"):
        themes = _extract_themes(book["description"])
        for theme in themes:
            score += profile["themes"].get(theme, 0) * WEIGHTS["theme"]

    # Rating boost: (0.7 + rating/10) → rating 5=1.2x, rating 10=1.7x
    if book.get("rating"):
        score *= 0.7 + book["rating"] / 10.0
    elif book.get("quality_score"):
        score *= 0.7 + book["quality_score"] / 200.0

    return round(score, 2)


async def get_7cat_recommendations(
    user_id: str,
    n_per_cat: int = 8,
) -> dict[str, list[dict[str, Any]]]:
    """7-category recommendations."""
    profile = await build_taste_profile(user_id)

    candidates = await fetch_all(
        """
        SELECT b.id, b.title, b.rating, b.quality_score, b.description, b.language,
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

    # Language filter
    user_langs = set(profile.get("languages", {}).keys())

    scored = []
    for c in candidates:
        # Language filtering (if user has language preferences)
        if user_langs and c.get("language") and c["language"] not in user_langs:
            continue
        s = score_book(dict(c), profile)
        if s > 0:
            scored.append({**dict(c), "id": str(c["id"]), "score": s})
    scored.sort(key=lambda x: x["score"], reverse=True)

    # 1. DNA: pure taste match
    dna = scored

    # 2. Author: re-rank by author affinity
    author_ranked = sorted(scored, key=lambda x: sum(profile["authors"].get(a, 0) for a in (x.get("authors") or [])), reverse=True)

    # 3. Community: pgvector similar to top-rated books
    community = []
    top_rated = await fetch_all(
        """
        SELECT book_id FROM reading_progress
        WHERE user_id = $1 AND is_finished = true
        ORDER BY updated_at DESC LIMIT 5
    """,
        UUID(user_id),
    )
    seen_ids: set[str] = set()
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
            sid = str(s["id"])
            if sid not in seen_ids:
                seen_ids.add(sid)
                community.append({**dict(s), "id": sid, "similarity": round(float(s["sim"] or 0), 3)})

    # 4. Hidden Gems: few readers, high quality, matching genres
    top_tags = sorted(profile["tags"], key=profile["tags"].get, reverse=True)[:5]
    gems = [b for b in scored if (b.get("quality_score") or 0) > 60 and any(t in top_tags for t in (b.get("tags") or []))]
    # Sort by quality (hidden gems = high quality but not popular)
    gems.sort(key=lambda x: x.get("quality_score", 0), reverse=True)

    # 5. Complete Series
    series_recs = await fetch_all(
        """
        SELECT s.name, array_agg(b.series_index ORDER BY b.series_index) as owned,
               max(b.series_index) as max_idx
        FROM reading_progress rp
        JOIN books b ON b.id = rp.book_id
        JOIN books_series bs ON bs.book_id = b.id JOIN series s ON s.id = bs.series_id
        WHERE rp.user_id = $1
        GROUP BY s.name
    """,
        UUID(user_id),
    )
    complete = [{"series": r["name"], "owned": r["owned"], "next": int(max(r["owned"] or [0])) + 1} for r in series_recs]

    # 6. Anti: tags user consistently avoids
    anti = await _anti_recommendations(user_id, candidates, profile)

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
        "hidden_gems": dedup(gems, n_per_cat),
        "complete_series": complete[:n_per_cat],
        "anti": anti[:n_per_cat],
        "profile_summary": {
            "top_tags": sorted(profile["tags"], key=profile["tags"].get, reverse=True)[:10],
            "top_authors": sorted(profile["authors"], key=profile["authors"].get, reverse=True)[:5],
            "top_themes": sorted(profile.get("themes", {}), key=profile.get("themes", {}).get, reverse=True)[:10],
            "languages": profile.get("languages", {}),
            "low_genres": profile.get("low_genres", []),
        },
    }


async def _anti_recommendations(
    user_id: str,
    candidates: list[Any],
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """Books you'd probably hate — highly rated in genres you consistently rate low."""
    hated_tags = set(profile.get("low_genres", []))
    if not hated_tags:
        return []
    anti = []
    for c in candidates:
        book_tags = set(c["tags"] or [])
        if book_tags & hated_tags and (c["quality_score"] or 0) > 60:
            anti.append({"id": str(c["id"]), "title": c["title"], "reason": f"tags: {', '.join(book_tags & hated_tags)}"})
    return anti
