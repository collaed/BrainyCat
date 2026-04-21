"""Collections/shelves and book linking."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from brainycat.auth import get_current_user
from brainycat.db import execute, fetch_all, fetch_one


class CollectionCreate(BaseModel):
    name: str
    description: str = ""
    is_public: bool = False


class BookLinkCreate(BaseModel):
    book_b_id: str
    link_type: str  # ebook_audiobook, translation, edition


async def create_collection(body: CollectionCreate, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    cid = uuid4()
    await execute(
        "INSERT INTO collections (id, user_id, name, description, is_public) VALUES ($1,$2,$3,$4,$5)",
        cid,
        user["id"],
        body.name,
        body.description,
        body.is_public,
    )
    return {"id": str(cid), "name": body.name}


async def list_collections(user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    rows = await fetch_all(
        """SELECT c.*, count(cb.book_id) as book_count
           FROM collections c LEFT JOIN collection_books cb ON cb.collection_id = c.id
           WHERE c.user_id = $1 GROUP BY c.id ORDER BY c.created_at""",
        user["id"],
    )
    return [dict(r) for r in rows]


async def add_book_to_collection(
    collection_id: str, book_id: str, user: Any = Depends(get_current_user)
) -> dict[str, bool]:
    col = await fetch_one("SELECT id FROM collections WHERE id = $1 AND user_id = $2", UUID(collection_id), user["id"])
    if not col:
        raise HTTPException(status_code=404, detail="Collection not found")
    max_pos = await fetch_one(
        "SELECT coalesce(max(position),0)+1 as next FROM collection_books WHERE collection_id = $1", UUID(collection_id)
    )
    await execute(
        "INSERT INTO collection_books (collection_id, book_id, position) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
        UUID(collection_id),
        UUID(book_id),
        max_pos["next"] if max_pos else 0,
    )
    return {"ok": True}


async def remove_book_from_collection(
    collection_id: str, book_id: str, user: Any = Depends(get_current_user)
) -> dict[str, bool]:
    await execute(
        "DELETE FROM collection_books WHERE collection_id = $1 AND book_id = $2", UUID(collection_id), UUID(book_id)
    )
    return {"ok": True}


async def link_books(book_id: str, body: BookLinkCreate, _user: Any = Depends(get_current_user)) -> dict[str, Any]:
    if body.link_type not in {"ebook_audiobook", "translation", "edition"}:
        raise HTTPException(status_code=400, detail="Invalid link type")
    lid = uuid4()
    await execute(
        "INSERT INTO book_links (id, book_a_id, book_b_id, link_type) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
        lid,
        UUID(book_id),
        UUID(body.book_b_id),
        body.link_type,
    )
    return {"id": str(lid)}


async def seed_default_collections(user_id: UUID) -> None:
    """Create default collections for a new user."""
    for name in ["Currently Reading", "Want to Read", "Finished"]:
        exists = await fetch_one(
            "SELECT id FROM collections WHERE user_id = $1 AND name = $2",
            user_id,
            name,
        )
        if not exists:
            await execute(
                "INSERT INTO collections (user_id, name, is_default) VALUES ($1,$2,true)",
                user_id,
                name,
            )
