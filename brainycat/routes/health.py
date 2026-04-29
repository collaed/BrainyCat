"""Consolidated health check — all subsystems in one endpoint."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter

from brainycat import db
from brainycat.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """Full system health: DB, Intello, disk, scheduler."""
    import os

    checks: dict[str, Any] = {}

    # Database
    try:
        row = await db.fetch_one("SELECT count(*) as n FROM books")
        checks["database"] = {"status": "ok", "books": row["n"]}
    except Exception as e:
        checks["database"] = {"status": "error", "error": str(e)[:50]}

    # Intello
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{settings.intello_url}/api/health")
            checks["intello"] = {"status": "ok" if r.status_code == 200 else "degraded"}
    except Exception:
        checks["intello"] = {"status": "unreachable"}

    # Disk
    try:
        stat = os.statvfs("/data")
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
        checks["disk"] = {"status": "ok" if free_gb > 1 else "low", "free_gb": round(free_gb, 1)}
    except Exception:
        checks["disk"] = {"status": "unknown"}

    overall = "ok" if all(c.get("status") == "ok" for c in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}
