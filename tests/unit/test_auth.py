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
    """Unauthenticated request raises 401."""
    from fastapi import HTTPException

    mock_req = MagicMock()
    mock_req.headers = {}
    mock_req.cookies = {}
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(mock_req)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_seed_users() -> None:
    """seed_users creates 3 default users."""
    with patch("brainycat.auth._upsert_user", new_callable=AsyncMock) as mock:
        await seed_users()
    assert mock.call_count == 3
    calls = [c.args[0] for c in mock.call_args_list]
    assert "admin" in calls
    assert "reader1" in calls
    assert "reader2" in calls
