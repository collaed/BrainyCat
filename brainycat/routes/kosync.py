"""KOReader position sync server — compatible with kosync protocol.

Endpoints:
  POST /api/v1/kosync/users/create — register
  GET  /api/v1/kosync/users/auth — authenticate
  PUT  /api/v1/kosync/syncs/progress — update progress
  GET  /api/v1/kosync/syncs/progress/{document} — get progress
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Request

from brainycat import db

router = APIRouter(prefix="/api/v1/kosync", tags=["kosync"])


async def _auth_kosync(x_auth_user: str | None, x_auth_key: str | None) -> dict | None:
    if not x_auth_user or not x_auth_key:
        return None
    user = await db.fetch_one(
        "SELECT id, username FROM users WHERE username = $1 AND api_key = $2",
        x_auth_user,
        x_auth_key,
    )
    return dict(user) if user else None


@router.post("/users/create")
async def kosync_register(request: Request) -> dict[str, Any]:
    """KOReader user registration (returns existing user's key)."""
    body = await request.json()
    username = body.get("username", "")
    _ = body.get("password", "")
    user = await db.fetch_one("SELECT api_key FROM users WHERE username = $1", username)
    if user:
        return {"username": username}
    return {"message": "Use BrainyCat web UI to create account"}


@router.get("/users/auth")
async def kosync_auth(
    x_auth_user: str | None = Header(None),
    x_auth_key: str | None = Header(None),
) -> dict[str, Any]:
    """KOReader authentication check."""
    user = await _auth_kosync(x_auth_user, x_auth_key)
    if user:
        return {"authorized": "OK"}
    return {"message": "Unauthorized"}


@router.put("/syncs/progress")
async def kosync_put_progress(
    request: Request,
    x_auth_user: str | None = Header(None),
    x_auth_key: str | None = Header(None),
) -> dict[str, Any]:
    """KOReader sends reading progress."""
    user = await _auth_kosync(x_auth_user, x_auth_key)
    if not user:
        return {"message": "Unauthorized"}

    body = await request.json()
    document = body.get("document", "")
    progress = body.get("progress", "")
    percentage = body.get("percentage", 0)
    device = body.get("device", "")
    device_id = body.get("device_id", "")

    await db.execute(
        """INSERT INTO kosync_progress (user_id, document, progress, percentage, device, device_id)
           VALUES ($1, $2, $3, $4, $5, $6)
           ON CONFLICT (user_id, document) DO UPDATE
           SET progress = $3, percentage = $4, device = $5, device_id = $6, updated_at = now()""",
        user["id"],
        document,
        progress,
        float(percentage),
        device,
        device_id,
    )
    return {"document": document, "timestamp": int(__import__("time").time())}


@router.get("/syncs/progress/{document:path}")
async def kosync_get_progress(
    document: str,
    x_auth_user: str | None = Header(None),
    x_auth_key: str | None = Header(None),
) -> dict[str, Any]:
    """KOReader fetches reading progress."""
    user = await _auth_kosync(x_auth_user, x_auth_key)
    if not user:
        return {"message": "Unauthorized"}

    row = await db.fetch_one(
        "SELECT progress, percentage, device, device_id FROM kosync_progress WHERE user_id = $1 AND document = $2",
        user["id"],
        document,
    )
    if not row:
        return {}
    return dict(row)
