"""Routes: ai."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from brainycat import companion
from brainycat.auth import get_current_user

router = APIRouter(prefix="/api/v1", tags=["ai"])


@router.get("/ai/recap/{book_id}")
async def ai_recap(book_id: str, user: Any = Depends(get_current_user)) -> dict[str, str]:
    return await companion.recap(book_id, str(user["id"]))


@router.post("/ai/ask/{book_id}")
async def ai_ask(book_id: str, question: str = Query(...), user: Any = Depends(get_current_user)) -> dict[str, str]:
    return await companion.ask(book_id, str(user["id"]), question)


@router.post("/ai/auto-tag/{book_id}")
async def ai_tag(book_id: str, _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    return await companion.auto_tag(book_id)


# Reviews: see aggregated endpoint below


# ── Stats & Notes ────────────────────────────────────────────────────────


@router.post("/ai/explain")
async def ai_explain(body: dict[str, Any], _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    text = body.get("text", "")[:1000]
    if not text:
        return {"error": "no text"}
    try:
        from brainycat.http_client import get_client

        client = get_client()
        resp = await client.post(
            "http://intello:8000/api/v1/llm/chat",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": f'Explain this passage briefly (2-3 sentences). If it\'s from a book, provide context:\n\n"{text}"',
                    }
                ],
                "max_tokens": 200,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {"explanation": data.get("choices", [{}])[0].get("message", {}).get("content", "")}
    except Exception:
        pass
    return {"error": "AI explanation unavailable — Intello not connected"}


@router.post("/ai/translate")
async def ai_translate(body: dict[str, Any], _u: Any = Depends(get_current_user)) -> dict[str, Any]:
    text = body.get("text", "")[:1000]
    if not text:
        return {"error": "no text"}
    try:
        from brainycat.http_client import get_client

        client = get_client()
        resp = await client.post(
            "http://intello:8000/api/v1/llm/chat",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": f'Translate this to English. If already English, translate to French. Just the translation, nothing else:\n\n"{text}"',
                    }
                ],
                "max_tokens": 300,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {"translation": data.get("choices", [{}])[0].get("message", {}).get("content", "")}
    except Exception:
        pass
    return {"error": "Translation unavailable — Intello not connected"}


# ── AI explain/translate already added above ──────────────────────────────
# (endpoints POST /api/v1/ai/explain and /api/v1/ai/translate)


# ── First-run setup ──────────────────────────────────────────────────────
