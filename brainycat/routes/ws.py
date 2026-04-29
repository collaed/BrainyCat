"""WebSocket endpoint for real-time updates (enrichment progress, OCR status)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket"])

# Connected clients
_clients: set[WebSocket] = set()


async def broadcast(event: str, data: Any) -> None:
    """Broadcast an event to all connected WebSocket clients."""
    msg = json.dumps({"event": event, "data": data})
    dead = set()
    for ws in _clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _clients -= dead


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket connection for real-time library updates."""
    await websocket.accept()
    _clients.add(websocket)
    try:
        while True:
            # Keep alive — client can send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)
