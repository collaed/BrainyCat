"""Intello async job client — handles long-running tasks (OCR, TTS, STT).

Pattern: submit job → poll status → retrieve result.
Survives Intello unavailability by persisting job IDs in the database.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import httpx

from brainycat.config import settings
from brainycat.db import execute, fetch_all, fetch_one
from brainycat.http_client import get_client


async def submit_job(
    book_id: str,
    job_type: str,
    endpoint: str,
    payload: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit an async job to Intello and track it."""
    try:
        client = get_client()
        if files:
            resp = await client.post(
                f"{settings.intello_url}{endpoint}",
                files=files,
                data=payload or {},
                headers={"Authorization": f"Bearer {settings.intello_api_key}"} if settings.intello_api_key else {},
            )
        else:
            resp = await client.post(
                f"{settings.intello_url}{endpoint}",
                json=payload or {},
                headers={"Authorization": f"Bearer {settings.intello_api_key}"} if settings.intello_api_key else {},
            )
        if resp.status_code in (200, 201, 202):
            data = resp.json()
            job_id = data.get("job_id") or data.get("id") or str(uuid4())
            await execute(
                """
                INSERT INTO async_jobs (id, book_id, job_type, remote_job_id, status)
                VALUES ($1, $2, $3, $4, 'submitted')
            """,
                uuid4(),
                UUID(book_id),
                job_type,
                job_id,
            )
            return {"ok": True, "job_id": job_id, "status": "submitted"}
        return {"error": f"Intello returned {resp.status_code}", "body": resp.text[:200]}
    except httpx.ConnectError:
        # Intello unavailable — queue for retry
        await execute(
            """
            INSERT INTO async_jobs (id, book_id, job_type, remote_job_id, status)
            VALUES ($1, $2, $3, $4, 'queued')
        """,
            uuid4(),
            UUID(book_id),
            job_type,
            "pending",
        )
        return {"ok": True, "job_id": "pending", "status": "queued", "note": "Intello unavailable, queued for retry"}
    except Exception as e:
        return {"error": str(e)[:200]}


async def check_job(job_id: str, status_endpoint: str) -> dict[str, Any]:
    """Check status of an async job on Intello."""
    try:
        client = get_client()
        resp = await client.get(
            f"{settings.intello_url}{status_endpoint}/{job_id}",
            headers={"Authorization": f"Bearer {settings.intello_api_key}"} if settings.intello_api_key else {},
        )
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status", "unknown")
            await execute(
                "UPDATE async_jobs SET status=$1 WHERE remote_job_id=$2",
                status,
                job_id,
            )
            return data
    except Exception as e:
        return {"status": "unreachable", "error": str(e)[:100]}
    return {"status": "unknown"}


async def get_job_result(job_id: str, result_endpoint: str) -> bytes | dict | None:
    """Retrieve the result of a completed async job."""
    try:
        client = get_client()
        resp = await client.get(
            f"{settings.intello_url}{result_endpoint}/{job_id}/result",
            headers={"Authorization": f"Bearer {settings.intello_api_key}"} if settings.intello_api_key else {},
        )
        if resp.status_code == 200:
            await execute(
                "UPDATE async_jobs SET status='completed' WHERE remote_job_id=$1",
                job_id,
            )
            ct = resp.headers.get("content-type", "")
            if ct.startswith("application/json"):
                return resp.json()
            return resp.content
    except Exception:
        pass
    return None


async def retry_queued_jobs() -> dict[str, Any]:
    """Retry jobs that were queued because Intello was unavailable."""
    queued = await fetch_all("SELECT * FROM async_jobs WHERE status='queued' LIMIT 10")
    retried = 0
    for job in queued:
        # Re-submit based on job_type
        if job["job_type"] == "ocr":
            row = await fetch_one(
                "SELECT file_path FROM book_files WHERE book_id=$1 AND format='pdf' LIMIT 1",
                job["book_id"],
            )
            if row:
                with open(row["file_path"], "rb") as fh:
                    result = await submit_job(str(job["book_id"]), "ocr", "/api/v1/ocr/jobs", files={"file": fh})
                if result.get("ok") and result.get("status") != "queued":
                    await execute("DELETE FROM async_jobs WHERE id=$1", job["id"])
                    retried += 1
    return {"retried": retried, "remaining": len(queued) - retried}


async def list_jobs(book_id: str | None = None) -> list[dict[str, Any]]:
    """List async jobs, optionally filtered by book."""
    if book_id:
        rows = await fetch_all(
            "SELECT * FROM async_jobs WHERE book_id=$1 ORDER BY created_at DESC",
            UUID(book_id),
        )
    else:
        rows = await fetch_all("SELECT * FROM async_jobs ORDER BY created_at DESC LIMIT 50")
    return [dict(r) for r in rows]
