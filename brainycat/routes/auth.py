"""Routes: auth."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from brainycat import auth, db
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
    allowed = {"kindle_email", "email", "packt_email", "packt_password", "auto_send_kindle"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return {"error": "no valid fields"}
    sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(updates))
    await db.execute(f"UPDATE users SET {sets} WHERE id = $1", user["id"], *updates.values())
    return {"ok": True, **updates}


# ── Security: optional login, change password ───────────────────────────────
# "Optional login" is meant for a trusted home network with no reverse proxy in front — see
# brainycat.auth.get_current_user for exactly what it does and doesn't affect.


@router.get("/settings/security")
async def get_security_settings(_u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return {"auth_required": await auth.is_auth_required()}


@router.put("/settings/security")
async def update_security_settings(body: auth.AuthRequiredUpdate, _admin: Any = Depends(auth.require_admin)) -> dict[str, Any]:
    await db.execute(
        """INSERT INTO app_settings (key, value, updated_at) VALUES ('auth_required', $1::jsonb, now())
           ON CONFLICT (key) DO UPDATE SET value = $1::jsonb, updated_at = now()""",
        "true" if body.auth_required else "false",
    )
    return {"auth_required": body.auth_required}


@router.post("/user/password")
async def change_password(body: auth.PasswordChange, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    import bcrypt

    row = await db.fetch_one("SELECT password_hash FROM users WHERE id = $1", user["id"])
    if not row or not row["password_hash"] or not bcrypt.checkpw(body.current_password.encode(), row["password_hash"].encode()):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    new_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt()).decode()
    await db.execute("UPDATE users SET password_hash = $1 WHERE id = $2", new_hash, user["id"])
    return {"ok": True}


# ── Clippings ─────────────────────────────────────────────────────────────


# Add auto_send_kindle to allowed settings


# ── API Key Management ────────────────────────────────────────────────────
@router.get("/user/api-key")
async def get_api_key(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Get user's API key (for KOReader sync, MCP, etc.)."""
    row = await db.fetch_one("SELECT api_key FROM users WHERE id = $1", user["id"])
    return {"api_key": row["api_key"] if row else None}


@router.post("/user/api-key/regenerate")
async def regenerate_api_key(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Regenerate API key."""
    import secrets

    new_key = secrets.token_hex(16)
    await db.execute("UPDATE users SET api_key = $1 WHERE id = $2", new_key, user["id"])
    return {"api_key": new_key}


# ── Theme Preference ──────────────────────────────────────────────────────
# Note: these used to write/read a `users.preferences` JSONB column that has never existed in any
# migration (users has no such column — user_preferences is its own table, with a real `theme` column).
# Every call 500'd with UndefinedColumnError; the theme setting has never worked on a migrated DB.
@router.put("/user/theme")
async def set_theme(body: dict[str, Any], user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Set UI theme preference (dark/light/auto)."""
    theme = body.get("theme", "dark")
    await db.execute(
        """INSERT INTO user_preferences (user_id, theme) VALUES ($1, $2)
           ON CONFLICT (user_id) DO UPDATE SET theme = $2, updated_at = now()""",
        user["id"],
        theme,
    )
    return {"theme": theme}


@router.get("/user/theme")
async def get_theme(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    """Get UI theme preference."""
    row = await db.fetch_one("SELECT theme FROM user_preferences WHERE user_id = $1", user["id"])
    return {"theme": row["theme"] if row and row["theme"] else "dark"}
