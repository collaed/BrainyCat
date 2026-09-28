"""Unit tests for authentication."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from brainycat.auth import (
    COOKIE_NAME,
    _signer,
    _user_dict,
    get_current_user,
    seed_users,
)


def _mock_user(username: str = "admin", role: str = "admin") -> MagicMock:
    uid = uuid4()
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "id": uid,
        "username": username,
        "role": role,
        "email": None,
        "kindle_email": None,
        "password_hash": None,
        "created_at": None,
        "updated_at": None,
        "oauth_accounts": {},
    }[key]
    return row


def test_user_dict() -> None:
    """_user_dict converts a record to a dict."""
    assert _user_dict(None) == {}
    row = _mock_user("test", "reader")
    d = _user_dict(row)
    assert d["username"] == "test"
    assert d["role"] == "reader"


@pytest.mark.asyncio
async def test_get_current_user_from_header() -> None:
    """User resolved from X-Auth-User header."""
    mock_req = MagicMock()
    mock_req.headers = {"X-Auth-User": "admin"}
    mock_req.cookies = {}
    user = _mock_user()
    with patch("brainycat.auth._upsert_user", new_callable=AsyncMock, return_value=user):
        result = await get_current_user(mock_req)
    assert result["username"] == "admin"


@pytest.mark.asyncio
async def test_get_current_user_from_cookie() -> None:
    """User resolved from session cookie."""
    uid = str(uuid4())
    token = _signer.dumps(uid)
    mock_req = MagicMock()
    mock_req.headers = {}
    mock_req.cookies = {COOKIE_NAME: token}
    user = _mock_user("reader1", "reader")
    with patch("brainycat.auth._get_user_by_id", new_callable=AsyncMock, return_value=user):
        result = await get_current_user(mock_req)
    assert result["username"] == "reader1"


@pytest.mark.asyncio
async def test_get_current_user_unauthenticated() -> None:
    """Unauthenticated request raises 401 when auth is required (the default/secure state)."""
    from fastapi import HTTPException

    mock_req = MagicMock()
    mock_req.headers = {}
    mock_req.cookies = {}
    with patch("brainycat.auth.is_auth_required", new_callable=AsyncMock, return_value=True), pytest.raises(HTTPException) as exc_info:
        await get_current_user(mock_req)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_falls_back_when_auth_not_required() -> None:
    """No credentials presented, but auth_required is off: resolve to the default account instead of
    401ing — this is the entire point of the toggle (a trusted home network, no reverse proxy)."""
    mock_req = MagicMock()
    mock_req.headers = {}
    mock_req.cookies = {}
    default_user = _mock_user("admin", "admin")
    with (
        patch("brainycat.auth.is_auth_required", new_callable=AsyncMock, return_value=False),
        patch("brainycat.auth._default_user_when_auth_disabled", new_callable=AsyncMock, return_value=default_user),
    ):
        result = await get_current_user(mock_req)
    assert result["username"] == "admin"


@pytest.mark.asyncio
async def test_get_current_user_real_credentials_win_even_when_auth_not_required() -> None:
    """A real session cookie still resolves to its own actual user when auth_required is off — the
    toggle only removes the *requirement* to present something, it doesn't override real credentials."""
    uid = str(uuid4())
    token = _signer.dumps(uid)
    mock_req = MagicMock()
    mock_req.headers = {}
    mock_req.cookies = {COOKIE_NAME: token}
    user = _mock_user("reader1", "reader")
    with (
        patch("brainycat.auth._get_user_by_id", new_callable=AsyncMock, return_value=user),
        patch("brainycat.auth.is_auth_required", new_callable=AsyncMock, return_value=False) as mock_required,
    ):
        result = await get_current_user(mock_req)
    assert result["username"] == "reader1"
    mock_required.assert_not_called()  # never even needed to check — a real cookie resolved first


@pytest.mark.asyncio
async def test_seed_users() -> None:
    """seed_users creates the default admin account (only) — extra accounts are created via the
    setup wizard, not seeded."""
    with patch("brainycat.auth._upsert_user", new_callable=AsyncMock) as mock:
        await seed_users()
    assert mock.call_count == 1
    calls = [c.args[0] for c in mock.call_args_list]
    assert "admin" in calls


# ── Optional auth toggle + change password (app_settings, migration 009) ───


@pytest.mark.asyncio
async def test_is_auth_required_true_when_row_present() -> None:
    from brainycat.auth import is_auth_required

    row = MagicMock()
    row.__getitem__ = lambda self, key: True
    with patch("brainycat.auth.fetch_one", new_callable=AsyncMock, return_value=row):
        assert await is_auth_required() is True


@pytest.mark.asyncio
async def test_is_auth_required_false_when_disabled() -> None:
    from brainycat.auth import is_auth_required

    row = MagicMock()
    row.__getitem__ = lambda self, key: False
    with patch("brainycat.auth.fetch_one", new_callable=AsyncMock, return_value=row):
        assert await is_auth_required() is False


@pytest.mark.asyncio
async def test_is_auth_required_fails_secure_when_row_missing() -> None:
    """If the app_settings row is somehow absent, default to requiring auth, not the other way round."""
    from brainycat.auth import is_auth_required

    with patch("brainycat.auth.fetch_one", new_callable=AsyncMock, return_value=None):
        assert await is_auth_required() is True


@pytest.mark.asyncio
async def test_default_user_when_auth_disabled_prefers_admin() -> None:
    from brainycat.auth import _default_user_when_auth_disabled

    admin = _mock_user("admin", "admin")
    with patch("brainycat.auth.fetch_one", new_callable=AsyncMock, return_value=admin) as mock_fetch:
        result = await _default_user_when_auth_disabled()
    assert result["role"] == "admin"
    assert "role = 'admin'" in mock_fetch.call_args_list[0].args[0]
