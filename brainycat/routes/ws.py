"""WebSocket endpoint for real-time updates (enrichment progress, OCR status).

Auth: connect with ?token=api_key or session cookie.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from brainycat import db

router = APIRouter(tags=["websocket"])

_clients: dict[WebSocket, str] = {}  # ws → user_id


async def broadcast(event: str, data: Any) -> None:
    """Broadcast an event to all authenticated WebSocket clients."""
    msg = json.dumps({"event": event, "data": data})
    dead = set()
    for ws in _clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    for ws in dead:
        _clients.pop(ws, None)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(default="")) -> None:
    """WebSocket connection — requires ?token=api_key for auth."""
    # Authenticate
    user = None
    if token:
        user = await db.fetch_one("SELECT id FROM users WHERE api_key = $1", token)
    if not user:
        await websocket.close(code=4001, reason="Unauthorized — provide ?token=api_key")
        return

    await websocket.accept()
    _clients[websocket] = str(user["id"])
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.pop(websocket, None)
