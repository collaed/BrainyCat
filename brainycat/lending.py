"""Cross-Library Lending — federated book lending between BrainyCat instances.

Request/approve flow: no DRM, human decides.
Public domain books can be shared freely.
Non-PD books: request → owner approves → time-limited access link.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_all, fetch_one


async def request_lend(
    requester_id: str,
    book_id: str,
    server_url: str,
    owner_username: str,
    message: str = "",
) -> dict[str, Any]:
    """Request to borrow a book from another instance."""
    rid = uuid4()
    await execute(
        """
        INSERT INTO lend_requests (id, requester_id, book_id, remote_server, remote_user, message, status)
        VALUES ($1, $2, $3, $4, $5, $6, 'pending')
    """,
        rid,
        UUID(requester_id),
        UUID(book_id),
        server_url,
        owner_username,
        message,
    )
    return {"id": str(rid), "status": "pending"}


async def list_incoming_requests(user_id: str) -> list[dict[str, Any]]:
    """List lending requests others have made for your books."""
    rows = await fetch_all(
        """
        SELECT lr.id, lr.book_id, lr.remote_server, lr.remote_user, lr.message,
               lr.status, lr.created_at, b.title
        FROM lend_requests lr
        JOIN books b ON b.id = lr.book_id
        WHERE lr.requester_id != $1 AND lr.status = 'pending'
        ORDER BY lr.created_at DESC
    """,
        UUID(user_id),
    )
    return [dict(r) for r in rows]


async def list_my_requests(user_id: str) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT * FROM lend_requests WHERE requester_id = $1 ORDER BY created_at DESC",
        UUID(user_id),
    )
    return [dict(r) for r in rows]


async def approve_request(request_id: str, owner_id: str, days: int = 14) -> dict[str, Any]:
    """Approve a lending request — generates a time-limited access token."""
    import secrets
    from datetime import datetime, timedelta

    req = await fetch_one("SELECT * FROM lend_requests WHERE id = $1", UUID(request_id))
    if not req:
        return {"error": "not found"}

    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(days=days)

    await execute(
        """
        UPDATE lend_requests SET status = 'approved', access_token = $1, expires_at = $2
        WHERE id = $3
    """,
        token,
        expires,
        UUID(request_id),
    )

    return {"ok": True, "token": token, "expires": expires.isoformat(), "days": days}


async def deny_request(request_id: str) -> dict[str, Any]:
    await execute("UPDATE lend_requests SET status = 'denied' WHERE id = $1", UUID(request_id))
    return {"ok": True}


async def access_lent_book(token: str) -> dict[str, Any]:
    """Access a lent book via token (time-limited)."""
    from datetime import datetime

    req = await fetch_one(
        "SELECT * FROM lend_requests WHERE access_token = $1 AND status = 'approved'",
        token,
    )
    if not req:
        return {"error": "invalid or expired token"}
    if req["expires_at"] and req["expires_at"] < datetime.utcnow():
        await execute("UPDATE lend_requests SET status = 'expired' WHERE id = $1", req["id"])
        return {"error": "loan expired"}

    return {"book_id": str(req["book_id"]), "expires": req["expires_at"].isoformat()}
