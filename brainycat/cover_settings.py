"""Cover customization settings — per-user cover generation preferences."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from brainycat.db import execute, fetch_one

# Default settings
DEFAULTS: dict[str, Any] = {
    "fiction_stripe": "vertical",
    "fiction_stripe_width": 20,
    "nonfiction_stripe": "horizontal",
    "nonfiction_stripe_height": 20,
    "font_family": "serif",
    "show_author": True,
    "show_genre_label": True,
    "background_style": "gradient",  # gradient, solid, dark
    "color_overrides": {},  # genre -> hex color
}


async def get_cover_settings(user_id: str) -> dict[str, Any]:
    """Get cover generation settings for a user."""
    row = await fetch_one(
        "SELECT preferences FROM users WHERE id = $1",
        UUID(user_id),
    )
    if row and row["preferences"]:
        prefs = row["preferences"] if isinstance(row["preferences"], dict) else {}
        cover_prefs = prefs.get("cover_settings", {})
        return {**DEFAULTS, **cover_prefs}
    return DEFAULTS


async def update_cover_settings(user_id: str, settings: dict[str, Any]) -> dict[str, Any]:
    """Update cover generation settings for a user."""
    # Validate
    valid_keys = set(DEFAULTS.keys())
    clean = {k: v for k, v in settings.items() if k in valid_keys}

    await execute(
        """
        UPDATE users SET preferences = COALESCE(preferences, '{}'::jsonb)
        || jsonb_build_object('cover_settings', $1::jsonb)
        WHERE id = $2
    """,
        str(clean).replace("'", '"').replace("True", "true").replace("False", "false"),
        UUID(user_id),
    )

    return {**DEFAULTS, **clean}
