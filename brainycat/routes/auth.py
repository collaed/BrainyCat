"""Routes: auth."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from brainycat import db
from brainycat.auth import get_current_user

router = APIRouter(prefix="/api/v1", tags=["auth"])


@router.post("/api-keys")
async def create_api_key(name: str = Query("default"), user: Any = Depends(get_current_user)) -> dict[str, str]:
    """Generate a new API key for the current user."""
    import hashlib
    import secrets

    token = f"bc_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    await db.execute(
        "INSERT INTO api_keys (key_hash, user_id, name) VALUES ($1, $2, $3)",
        key_hash,
        user["id"],
        name,
    )
    return {"api_key": token, "name": name, "note": "Save this key — it cannot be retrieved later"}


@router.get("/api-keys")
async def list_api_keys(user: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    """List API keys for the current user (hashes only, not the actual keys)."""
    rows = await db.fetch_all("SELECT id, name, created_at FROM api_keys WHERE user_id = $1", user["id"])
    return [dict(r) for r in rows]


@router.delete("/api-keys/{key_id}")
async def delete_api_key(key_id: str, user: Any = Depends(get_current_user)) -> dict[str, bool]:
    from uuid import UUID as _UUID

    await db.execute("DELETE FROM api_keys WHERE id = $1 AND user_id = $2", _UUID(key_id), user["id"])
    return {"ok": True}


# ── EPUB Quality Check ───────────────────────────────────────────────────


@router.get("/settings/languages")
async def get_language_prefs(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    row = await db.fetch_one("SELECT preferences FROM users WHERE id = $1", user["id"])
    prefs = (row["preferences"] or {}) if row else {}
    return {"languages": prefs.get("catalog_languages", ["en", "fr"])}


@router.post("/settings/languages")
async def set_language_prefs(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    body = await request.json()
    langs = body.get("languages", ["en", "fr"])
    import json

    await db.execute(
        "UPDATE users SET preferences = jsonb_set(COALESCE(preferences, '{}'), '{catalog_languages}', $1::jsonb) WHERE id = $2",
        json.dumps(langs),
        user["id"],
    )
    return {"languages": langs}


# ── Book summaries (getAbstract-style) ────────────────────────────────────


@router.get("/settings")
async def get_settings(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    row = await db.fetch_one("SELECT kindle_email, email, role FROM users WHERE id = $1", user["id"])
    return dict(row) if row else {}


@router.patch("/settings")
async def update_settings(body: dict[str, Any], user: Any = Depends(get_current_user)) -> dict[str, Any]:
    allowed = {"kindle_email", "email", "packt_email", "packt_password"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return {"error": "no valid fields"}
    sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(updates))
    await db.execute(f"UPDATE users SET {sets} WHERE id = $1", user["id"], *updates.values())
    return {"ok": True, **updates}


# ── Clippings ─────────────────────────────────────────────────────────────
