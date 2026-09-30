"""Verification API — confidence scores + human review endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from brainycat.auth import get_current_user

router = APIRouter(prefix="/api/v1/verify", tags=["verification"])


@router.get("/top")
async def top_confidence(limit: int = 20, _u: Any = Depends(get_current_user)) -> list[dict]:
    """Get top N high-confidence books ready for user confirmation."""
    from brainycat.confidence import get_top_confidence
    return await get_top_confidence(limit=limit)


@router.get("/conflicts")
async def conflicts(limit: int = 20, _u: Any = Depends(get_current_user)) -> list[dict]:
    """Get books with conflicting identification signals."""
    from brainycat.confidence import get_conflicts
    return await get_conflicts(limit=limit)


@router.get("/{book_id}")
async def book_confidence(book_id: str, _u: Any = Depends(get_current_user)) -> dict:
    """Get detailed confidence breakdown for a specific book."""
    from brainycat.confidence import compute_confidence
    return await compute_confidence(book_id)


@router.post("/{book_id}/confirm")
async def confirm_book(book_id: str, _u: Any = Depends(get_current_user)) -> dict:
    """Confirm a book's identity — pushes to 100% and triggers contribute-back."""
    from brainycat.confidence import verify_book
    return await verify_book(book_id, confirmed=True)


@router.post("/{book_id}/correct")
async def correct_book(book_id: str, body: dict[str, Any], _u: Any = Depends(get_current_user)) -> dict:
    """Correct a book's identity with user-provided data."""
    from brainycat.confidence import verify_book
    return await verify_book(book_id, confirmed=False, corrections=body)


@router.get("/stats")
async def verification_stats(_u: Any = Depends(get_current_user)) -> dict:
    """Overview of confidence distribution."""
    from brainycat.db import fetch_all
    dist = await fetch_all("""
        SELECT
            CASE
                WHEN (extra_metadata->>'confidence_score')::int >= 90 THEN '90-99'
                WHEN (extra_metadata->>'confidence_score')::int >= 70 THEN '70-89'
                WHEN (extra_metadata->>'confidence_score')::int >= 50 THEN '50-69'
                WHEN (extra_metadata->>'confidence_score')::int >= 30 THEN '30-49'
                ELSE '0-29'
            END as bracket,
            count(*) as cnt
        FROM books
        WHERE extra_metadata ? 'confidence_score'
        GROUP BY bracket ORDER BY bracket DESC
    """)
    verified = await fetch_all(
        "SELECT count(*) as cnt FROM books WHERE extra_metadata->>'human_verified' = 'true'"
    )
    return {
        "distribution": {r["bracket"]: r["cnt"] for r in dist},
        "human_verified": verified[0]["cnt"] if verified else 0,
    }
