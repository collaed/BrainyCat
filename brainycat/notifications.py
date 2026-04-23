"""Signal notifications via signal-api container."""

from __future__ import annotations

from typing import Any

from brainycat.config import settings
from brainycat.http_client import get_client


async def send_notification(message: str, recipient: str = "") -> dict[str, Any]:
    """Send a Signal notification."""
    try:
        client = get_client()
        resp = await client.post(
            f"{settings.signal_api_url}/v2/send",
            json={"message": message, "number": recipient, "recipients": [recipient] if recipient else []},
        )
        return {"ok": resp.status_code == 200}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def notify_book_added(title: str) -> None:
    await send_notification(f"📚 New book added to BrainyCat: {title}")


async def notify_job_complete(job_type: str, title: str) -> None:
    await send_notification(f"✅ {job_type} complete: {title}")
