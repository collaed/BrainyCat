"""Authentication middleware and user management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

import bcrypt
from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel

from brainycat.config import settings
from brainycat.db import execute, fetch_all, fetch_one

if TYPE_CHECKING:
    import asyncpg

_signer = URLSafeTimedSerializer(settings.secret_key)
COOKIE_NAME = "brainycat_session"


class UserOut(BaseModel):
    id: str
    username: str
    email: str | None = None
    kindle_email: str | None = None
    role: str


class LoginRequest(BaseModel):
    username: str
    password: str


class PreferencesUpdate(BaseModel):
    kindle_email: str | None = None
    theme: str | None = None
    font_size: int | None = None
    fluent_languages: list[str] | None = None
    secondary_languages: list[str] | None = None
    preferred_format: str | None = None


# ---------------------------------------------------------------------------
# User lookup / creation
# ---------------------------------------------------------------------------


async def _upsert_user(username: str, *, role: str = "reader") -> asyncpg.Record | None:
    """Create user if not exists, return the row."""
    row = await fetch_one("SELECT * FROM users WHERE username = $1", username)
    if row:
        return row
    await execute(
        "INSERT INTO users (username, role) VALUES ($1, $2) ON CONFLICT (username) DO NOTHING",
        username,
        role,
    )
    return await fetch_one("SELECT * FROM users WHERE username = $1", username)


async def _get_user_by_id(user_id: str) -> asyncpg.Record | None:
    return await fetch_one("SELECT * FROM users WHERE id = $1", UUID(user_id))


# ---------------------------------------------------------------------------
# Resolve current user from request
# ---------------------------------------------------------------------------


async def get_current_user(request: Request) -> asyncpg.Record:
    """Dependency: resolve user from X-Auth-User header, ECB auth cookie, or session cookie."""
    # 1) Trusted header from Caddy forward_auth
    header_user = request.headers.get("X-Auth-User")
    if header_user:
        first_admin = header_user == "ecb"
        user = await _upsert_user(header_user, role="admin" if first_admin else "reader")
        if user:
            return user

    # 2) ECB shared auth cookie (ecb_auth) — fallback when Caddy doesn't forward the header
    ecb_cookie = request.cookies.get("ecb_auth")
    if ecb_cookie:
        try:
            # Format: "username:timestamp:signature"
            parts = ecb_cookie.rsplit(":", 2)
            if len(parts) == 3:
                username = parts[0]
                user = await _upsert_user(username, role="admin" if username == "ecb" else "reader")
                if user:
                    return user
        except (ValueError, IndexError):
            pass

    # 3) BrainyCat session cookie
    token = request.cookies.get(COOKIE_NAME)
    if token:
        try:
            user_id = _signer.loads(token, max_age=settings.session_max_age)
            user = await _get_user_by_id(user_id)
            if user:
                return user
        except BadSignature:
            pass

    raise HTTPException(status_code=401, detail="Not authenticated")


async def require_admin(user: asyncpg.Record = Depends(get_current_user)) -> asyncpg.Record:
    """Dependency: require admin role."""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    return user


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def login(body: LoginRequest, response: Response) -> dict[str, Any]:
    """POST /api/v1/login — authenticate with username/password."""
    user = await fetch_one("SELECT * FROM users WHERE username = $1", body.username)
    if not user or not user["password_hash"]:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not bcrypt.checkpw(body.password.encode(), user["password_hash"].encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = _signer.dumps(str(user["id"]))
    response.set_cookie(COOKIE_NAME, token, max_age=settings.session_max_age, httponly=True, samesite="lax")
    return {"ok": True, "user": _user_dict(user)}


async def logout(response: Response) -> dict[str, bool]:
    """POST /api/v1/logout — clear session."""
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


async def me(user: asyncpg.Record = Depends(get_current_user)) -> dict[str, Any]:
    """GET /api/v1/me — current user info."""
    prefs = await fetch_one("SELECT * FROM user_preferences WHERE user_id = $1", user["id"])
    return {"user": _user_dict(user), "preferences": dict(prefs) if prefs else None}


async def list_users(_admin: asyncpg.Record = Depends(require_admin)) -> list[dict[str, Any]]:
    """GET /api/v1/users — list all users (admin only)."""
    rows = await fetch_all("SELECT * FROM users ORDER BY created_at")
    return [_user_dict(r) for r in rows]


async def update_user(user_id: str, body: dict[str, Any], _admin: asyncpg.Record = Depends(require_admin)) -> dict[str, Any]:
    """PATCH /api/v1/users/{user_id} — update user (admin only)."""
    allowed = {"role", "email", "kindle_email"}
    sets = []
    vals: list[Any] = []
    idx = 1
    for k, v in body.items():
        if k in allowed:
            sets.append(f"{k} = ${idx}")
            vals.append(v)
            idx += 1
    if not sets:
        raise HTTPException(status_code=400, detail="No valid fields")
    vals.append(UUID(user_id))
    await execute(f"UPDATE users SET {', '.join(sets)}, updated_at = now() WHERE id = ${idx}", *vals)
    user = await _get_user_by_id(user_id)
    return _user_dict(user) if user else {}


async def update_preferences(body: PreferencesUpdate, user: asyncpg.Record = Depends(get_current_user)) -> dict[str, Any]:
    """PATCH /api/v1/me/preferences — update user preferences."""
    await execute(
        """INSERT INTO user_preferences (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING""",
        user["id"],
    )
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        sets = []
        vals: list[Any] = []
        idx = 1
        for k, v in updates.items():
            sets.append(f"{k} = ${idx}")
            vals.append(v)
            idx += 1
        vals.append(user["id"])
        await execute(
            f"UPDATE user_preferences SET {', '.join(sets)}, updated_at = now() WHERE user_id = ${idx}",
            *vals,
        )
    prefs = await fetch_one("SELECT * FROM user_preferences WHERE user_id = $1", user["id"])
    return dict(prefs) if prefs else {}


def _user_dict(row: asyncpg.Record | None) -> dict[str, Any]:
    if not row:
        return {}
    return {
        "id": str(row["id"]),
        "username": row["username"],
        "email": row["email"],
        "kindle_email": row["kindle_email"],
        "role": row["role"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


# ---------------------------------------------------------------------------
# Seed default users
# ---------------------------------------------------------------------------


async def seed_users() -> None:
    """Create default users if they don't exist."""
    for username, role in [("ecb", "admin"), ("mafalda", "reader"), ("lilian", "reader")]:
        await _upsert_user(username, role=role)
