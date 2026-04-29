"""Kobo Sync API — allows Kobo e-readers to sync with BrainyCat.

Implements a subset of the Kobo API that Komga uses.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header

from brainycat import db

router = APIRouter(prefix="/api/v1/kobo", tags=["kobo"])


async def _auth_kobo(authorization: str | None) -> dict | None:
    """Authenticate via Bearer token (api_key)."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    user = await db.fetch_one("SELECT id, username FROM users WHERE api_key = $1", token)
    return dict(user) if user else None


@router.get("/v1/initialization")
async def kobo_init(authorization: str | None = Header(None)) -> dict[str, Any]:
    """Kobo initialization — returns sync capabilities."""
    return {
        "Resources": {
            "image_host": "",
            "image_url_quality_template": "",
            "image_url_template": "",
        }
    }


@router.get("/v1/library/sync")
async def kobo_library_sync(authorization: str | None = Header(None)) -> list[dict[str, Any]]:
    """Return books available for Kobo sync."""
    user = await _auth_kobo(authorization)
    if not user:
        return []

    books = await db.fetch_all(
        """SELECT b.id, b.title, bf.format FROM books b
           JOIN book_files bf ON bf.book_id = b.id
           WHERE bf.format IN ('epub', 'kepub')
           ORDER BY b.updated_at DESC LIMIT 100"""
    )
    return [
        {
            "EntitlementId": str(r["id"]),
            "BookEntitlement": {
                "Title": r["title"],
                "ContentType": "application/epub+zip",
            },
        }
        for r in books
    ]


@router.put("/v1/library/{book_id}/state")
async def kobo_update_state(
    book_id: str,
    authorization: str | None = Header(None),
) -> dict[str, Any]:
    """Kobo sends reading state update."""
    user = await _auth_kobo(authorization)
    if not user:
        return {"error": "unauthorized"}
    # Accept the state update (Kobo sends progress here)
    return {"StatusInfos": []}
