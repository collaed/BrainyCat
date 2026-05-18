"""Consumption rules — auto-tag/classify books based on filename patterns."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_all, fetch_one


async def apply_rules(book_id: str, filename: str, title: str = "", author: str = "") -> list[str]:
    """Apply all enabled consumption rules to a book. Returns list of actions taken."""
    rules = await fetch_all(
        "SELECT * FROM consumption_rules WHERE enabled = true ORDER BY priority DESC"
    )
    actions_taken = []
    for rule in rules:
        field_value = {"filename": filename, "title": title, "author": author, "path": filename}.get(rule["match_field"], "")
        if not field_value:
            continue
        try:
            if not re.search(rule["pattern"], field_value, re.IGNORECASE):
                continue
        except re.error:
            continue

        action = rule["action"]
        value = rule["action_value"]

        if action == "tag":
            await execute("INSERT INTO tags (name) VALUES ($1) ON CONFLICT DO NOTHING", value)
            tag = await fetch_one("SELECT id FROM tags WHERE name = $1", value)
            if tag:
                await execute("INSERT INTO books_tags (book_id, tag_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                              UUID(book_id), tag["id"])
            actions_taken.append(f"tag:{value}")

        elif action == "set_publisher":
            await execute("INSERT INTO publishers (name) VALUES ($1) ON CONFLICT DO NOTHING", value)
            pub = await fetch_one("SELECT id FROM publishers WHERE name = $1", value)
            if pub:
                await execute("INSERT INTO books_publishers (book_id, publisher_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                              UUID(book_id), pub["id"])
            actions_taken.append(f"publisher:{value}")

        elif action == "set_language":
            await execute("INSERT INTO languages (code) VALUES ($1) ON CONFLICT DO NOTHING", value)
            lang = await fetch_one("SELECT id FROM languages WHERE code = $1", value)
            if lang:
                await execute("INSERT INTO books_languages (book_id, language_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                              UUID(book_id), lang["id"])
            actions_taken.append(f"language:{value}")

        elif action == "set_genre":
            await execute("INSERT INTO tags (name) VALUES ($1) ON CONFLICT DO NOTHING", value)
            tag = await fetch_one("SELECT id FROM tags WHERE name = $1", value)
            if tag:
                await execute("INSERT INTO books_tags (book_id, tag_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                              UUID(book_id), tag["id"])
            actions_taken.append(f"genre:{value}")

        elif action == "skip":
            actions_taken.append("skip")
            break

    return actions_taken


async def list_rules() -> list[dict[str, Any]]:
    rows = await fetch_all("SELECT * FROM consumption_rules ORDER BY priority DESC")
    return [dict(r) for r in rows]


async def create_rule(name: str, pattern: str, match_field: str, action: str, action_value: str, priority: int = 0) -> dict[str, Any]:
    row = await fetch_one(
        "INSERT INTO consumption_rules (name, pattern, match_field, action, action_value, priority) "
        "VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
        name, pattern, match_field, action, action_value, priority,
    )
    return {"id": str(row["id"])} if row else {"error": "failed"}


async def delete_rule(rule_id: str) -> dict[str, bool]:
    await execute("DELETE FROM consumption_rules WHERE id = $1", UUID(rule_id))
    return {"ok": True}
