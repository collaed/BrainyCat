"""Federated reading profiles — privacy-preserving social layer.

Three visibility layers:
1. Your profile: full detail (books, ratings, reviews, shelves)
2. People you follow: cached daily (their activity, named)
3. Their network (2nd degree): anonymized aggregate only (genres, trending books)

Hash format: base64(bc://server_url|username|public_key)
"""

from __future__ import annotations

import base64
import json
import secrets
from collections import Counter
from typing import Any
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_all, fetch_one
from brainycat.http_client import get_client


def generate_profile_hash(server_url: str, username: str) -> dict[str, str]:
    """Generate a shareable profile hash."""
    public_key = secrets.token_hex(8)
    raw = f"bc://{server_url}|{username}|{public_key}"
    encoded = base64.urlsafe_b64encode(raw.encode()).decode()
    return {"hash": encoded, "public_key": public_key, "raw": raw}


def decode_profile_hash(hash_str: str) -> dict[str, str] | None:
    """Decode a profile hash into server_url, username, public_key."""
    try:
        raw = base64.urlsafe_b64decode(hash_str).decode()
        if not raw.startswith("bc://"):
            return None
        parts = raw[5:].split("|")
        if len(parts) != 3:
            return None
        return {"server_url": parts[0], "username": parts[1], "public_key": parts[2]}
    except Exception:
        return None


async def enable_public_profile(user_id: str, server_url: str) -> dict[str, Any]:
    """Enable public profile for a user and generate their hash."""
    user = await fetch_one("SELECT username FROM users WHERE id = $1", UUID(user_id))
    if not user:
        return {"error": "user not found"}

    info = generate_profile_hash(server_url, user["username"])
    await execute(
        """
        UPDATE users SET preferences = COALESCE(preferences, '{}'::jsonb)
        || jsonb_build_object('public_profile', 'true'::text, 'public_key', $1::text)
        WHERE id = $2
    """,
        info["public_key"],
        UUID(user_id),
    )

    return {"hash": info["hash"], "public_url": f"https://{server_url}/public/{user['username']}"}


async def get_public_feed(username: str) -> dict[str, Any]:
    """Generate the public feed for a user (polled by followers)."""
    user = await fetch_one("SELECT id, username, preferences FROM users WHERE username = $1", username)
    if not user:
        return {"error": "not found"}

    prefs = user["preferences"] if isinstance(user.get("preferences"), dict) else {}
    if prefs.get("public_profile") != "true":
        return {"error": "profile not public"}

    uid = user["id"]

    # Currently reading
    reading = await fetch_all(
        """
        SELECT b.title, array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
               rp.percentage
        FROM reading_progress rp
        JOIN books b ON b.id = rp.book_id
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        WHERE rp.user_id = $1 AND rp.is_finished = false AND rp.percentage > 0
        GROUP BY b.id, rp.percentage ORDER BY rp.updated_at DESC LIMIT 5
    """,
        uid,
    )

    # Recently finished
    finished = await fetch_all(
        """
        SELECT b.title, array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
               b.rating, rp.updated_at as finished_at
        FROM reading_progress rp
        JOIN books b ON b.id = rp.book_id
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        WHERE rp.user_id = $1 AND rp.is_finished = true
        GROUP BY b.id, rp.updated_at ORDER BY rp.updated_at DESC LIMIT 10
    """,
        uid,
    )

    # Want to read (books with no progress)
    # Use a "want_to_read" tag or shelf if exists
    want = await fetch_all(
        """
        SELECT b.title, array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors
        FROM books b
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        LEFT JOIN books_tags bt ON bt.book_id = b.id LEFT JOIN tags t ON t.id = bt.tag_id
        LEFT JOIN reading_progress rp ON rp.book_id = b.id AND rp.user_id = $1
        WHERE t.name IN ('want-to-read', 'to-read', 'wishlist') AND rp.id IS NULL
        GROUP BY b.id LIMIT 10
    """,
        uid,
    )

    # Reviews (annotations marked as reviews)
    reviews = await fetch_all(
        """
        SELECT b.title, ann.content, ann.created_at
        FROM annotations ann
        JOIN books b ON b.id = ann.book_id
        WHERE ann.user_id = $1 AND ann.is_shared = true AND ann.annotation_type = 'review'
        ORDER BY ann.created_at DESC LIMIT 10
    """,
        uid,
    )

    # Stats
    stats = await fetch_one(
        """
        SELECT count(*) FILTER (WHERE is_finished) as books_finished,
               count(*) FILTER (WHERE percentage > 0) as books_started
        FROM reading_progress WHERE user_id = $1
    """,
        uid,
    )

    # Genre distribution for network summary
    genres = await fetch_all(
        """
        SELECT t.name, count(*) as cnt FROM reading_progress rp
        JOIN books_tags bt ON bt.book_id = rp.book_id
        JOIN tags t ON t.id = bt.tag_id
        WHERE rp.user_id = $1 AND rp.is_finished = true
        GROUP BY t.name ORDER BY cnt DESC LIMIT 10
    """,
        uid,
    )

    # Network summary (anonymized aggregate of people THIS user follows)
    network = await _build_network_summary(uid)

    return {
        "username": username,
        "currently_reading": [
            {"title": r["title"], "authors": r["authors"] or [], "progress": round(r["percentage"] * 100)} for r in reading
        ],
        "recently_finished": [{"title": r["title"], "authors": r["authors"] or [], "rating": r["rating"]} for r in finished],
        "want_to_read": [{"title": r["title"], "authors": r["authors"] or []} for r in want],
        "reviews": [{"title": r["title"], "text": r["content"][:500]} for r in reviews],
        "stats": {"books_finished": stats["books_finished"] if stats else 0, "books_started": stats["books_started"] if stats else 0},
        "top_genres": [{"genre": r["name"], "count": r["cnt"]} for r in genres],
        "network_summary": network,
    }


async def follow_user(follower_id: str, hash_str: str) -> dict[str, Any]:
    """Follow a user by their profile hash."""
    info = decode_profile_hash(hash_str)
    if not info:
        return {"error": "invalid hash"}

    await execute(
        """
        INSERT INTO follows (id, follower_id, server_url, username, public_key)
        VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING
    """,
        uuid4(),
        UUID(follower_id),
        info["server_url"],
        info["username"],
        info["public_key"],
    )

    return {"ok": True, "following": info["username"], "server": info["server_url"]}


async def unfollow_user(follower_id: str, follow_id: str) -> dict[str, bool]:
    await execute("DELETE FROM follows WHERE id = $1 AND follower_id = $2", UUID(follow_id), UUID(follower_id))
    return {"ok": True}


async def list_following(user_id: str) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT id, server_url, username, cached_feed, last_fetched FROM follows WHERE follower_id = $1",
        UUID(user_id),
    )
    return [dict(r) for r in rows]


async def refresh_follows(user_id: str) -> dict[str, Any]:
    """Poll all followed profiles and cache their feeds."""
    follows = await fetch_all("SELECT * FROM follows WHERE follower_id = $1", UUID(user_id))
    refreshed = 0
    for f in follows:
        try:
            url = f"https://{f['server_url']}/public/{f['username']}/feed.json"
            client = get_client()
            resp = await client.get(url)
            if resp.status_code == 200:
                feed = resp.json()
                await execute(
                    "UPDATE follows SET cached_feed = $1, last_fetched = now() WHERE id = $2",
                    json.dumps(feed, default=str),
                    f["id"],
                )
                refreshed += 1
        except Exception:
            pass
    return {"refreshed": refreshed, "total": len(follows)}


async def _build_network_summary(user_id: UUID) -> dict[str, Any]:
    """Build anonymized aggregate of followed users' activity."""
    follows = await fetch_all("SELECT cached_feed FROM follows WHERE follower_id = $1 AND cached_feed IS NOT NULL", user_id)
    if not follows:
        return {"network_size": 0}

    genre_counter: Counter[str] = Counter()
    book_counter: Counter[str] = Counter()
    total_finished = 0

    for f in follows:
        feed = json.loads(f["cached_feed"]) if isinstance(f["cached_feed"], str) else (f["cached_feed"] or {})
        for g in feed.get("top_genres", []):
            genre_counter[g.get("genre", "")] += g.get("count", 1)
        for b in feed.get("recently_finished", []):
            book_counter[b.get("title", "")] += 1
            total_finished += 1

    return {
        "network_size": len(follows),
        "trending_genres": [{"genre": g, "count": c} for g, c in genre_counter.most_common(5)],
        "trending_books": [{"title": t, "readers": c} for t, c in book_counter.most_common(5) if c > 1],
        "total_books_finished": total_finished,
    }
