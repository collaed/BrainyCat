"""Async background job queue backed by the jobs table."""

from __future__ import annotations

import asyncio
import json
import traceback
from typing import Any
from uuid import UUID, uuid4

from brainycat.db import execute, fetch_one
from brainycat.logging import log


async def create_job(job_type: str, book_id: str | None = None, user_id: str | None = None, params: dict[str, Any] | None = None) -> str:
    """Create a new job and return its ID."""
    jid = uuid4()
    await execute(
        "INSERT INTO jobs (id, job_type, book_id, user_id, params) VALUES ($1,$2,$3,$4,$5::jsonb)",
        jid,
        job_type,
        UUID(book_id) if book_id else None,
        UUID(user_id) if user_id else None,
        json.dumps(params or {}),
    )
    return str(jid)


async def update_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: float | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Update job status/progress."""
    sets, vals = [], []
    idx = 1
    if status:
        sets.append(f"status = ${idx}")
        vals.append(status)
        idx += 1
    if progress is not None:
        sets.append(f"progress = ${idx}")
        vals.append(progress)
        idx += 1
    if result is not None:
        sets.append(f"result = ${idx}::jsonb")
        vals.append(json.dumps(result))
        idx += 1
    if error is not None:
        sets.append(f"error = ${idx}")
        vals.append(error)
        idx += 1
    if sets:
        vals.append(UUID(job_id))
        await execute(f"UPDATE jobs SET {', '.join(sets)}, updated_at = now() WHERE id = ${idx}", *vals)


async def get_job(job_id: str) -> dict[str, Any] | None:
    """Get job status."""
    row = await fetch_one("SELECT * FROM jobs WHERE id = $1", UUID(job_id))
    return dict(row) if row else None


async def run_in_background(job_id: str, coro: Any) -> None:
    """Run a coroutine as a background task, updating job status."""

    async def _wrapper() -> None:
        try:
            await update_job(job_id, status="running")
            await coro
            await update_job(job_id, status="complete", progress=100)
        except Exception as e:
            await log.aerror("job_failed", job_id=job_id, error=str(e))
            await update_job(job_id, status="failed", error=traceback.format_exc())

    asyncio.create_task(_wrapper())  # noqa: RUF006
