"""Map free-text tags to BISAC and Thema subject codes."""

from __future__ import annotations

from typing import Any

# BISAC top-level mapping from Google Books categories and common free-text tags
# Format: free_text_lower → (bisac_code, bisac_name, thema_code)
BISAC_MAP: dict[str, tuple[str, str, str]] = {
    # Fiction
    "fiction": ("FIC000000", "Fiction / General", "F"),
    "literary fiction": ("FIC019000", "Fiction / Literary", "FB"),
    "romance": ("FIC027000", "Fiction / Romance / General", "FRD"),
    "mystery": ("FIC022000", "Fiction / Mystery & Detective / General", "FF"),
    "thriller": ("FIC031000", "Fiction / Thrillers / General", "FH"),
    "science fiction": ("FIC028000", "Fiction / Science Fiction / General", "FL"),
    "fantasy": ("FIC009000", "Fiction / Fantasy / General", "FM"),
    "horror": ("FIC015000", "Fiction / Horror", "FK"),
    "erotica": ("FIC005000", "Fiction / Erotica", "FP"),
    "historical fiction": ("FIC014000", "Fiction / Historical / General", "FV"),
    "literary criticism": ("LIT000000", "Literary Criticism / General", "DS"),
    # Non-fiction
    "biography & autobiography": ("BIO000000", "Biography & Autobiography / General", "DN"),
    "history": ("HIS000000", "History / General", "NH"),
    "philosophy": ("PHI000000", "Philosophy / General", "QD"),
    "psychology": ("PSY000000", "Psychology / General", "JM"),
    "science": ("SCI000000", "Science / General", "PD"),
    "political science": ("POL000000", "Political Science / General", "JP"),
    "art": ("ART000000", "Art / General", "A"),
    "architecture": ("ARC000000", "Architecture / General", "AM"),
    "music": ("MUS000000", "Music / General", "AV"),
    "popular music": ("MUS035000", "Music / Genres & Styles / Popular", "AVG"),
    # Business & Tech
    "business & economics": ("BUS000000", "Business & Economics / General", "K"),
    "computers": ("COM000000", "Computers / General", "U"),
    "technology & engineering": ("TEC000000", "Technology & Engineering / General", "TB"),
    # Education & Language
    "education": ("EDU000000", "Education / General", "JN"),
    "foreign language study": ("FOR000000", "Foreign Language Study / General", "CF"),
    "language arts & disciplines": ("LAN000000", "Language Arts & Disciplines / General", "CF"),
    # Health & Lifestyle
    "health & fitness": ("HEA000000", "Health & Fitness / General", "VF"),
    "cooking": ("CKB000000", "Cooking / General", "WB"),
    "self-help": ("SEL000000", "Self-Help / General", "VS"),
    "family & relationships": ("FAM000000", "Family & Relationships / General", "VF"),
    "travel": ("TRV000000", "Travel / General", "WT"),
    "sports & recreation": ("SPO000000", "Sports & Recreation / General", "S"),
    # Comics & Children
    "comics & graphic novels": ("CGN000000", "Comics & Graphic Novels / General", "X"),
    "juvenile fiction": ("JUV000000", "Juvenile Fiction / General", "YF"),
    "young adult fiction": ("YAF000000", "Young Adult Fiction / General", "YF"),
    # Other
    "antiques & collectibles": ("ANT000000", "Antiques & Collectibles / General", "WC"),
    "religion": ("REL000000", "Religion / General", "QR"),
    "mathematics": ("MAT000000", "Mathematics / General", "PB"),
    # Diving-specific (for our library)
    "diving": ("SPO016000", "Sports & Recreation / Water Sports", "SZG"),
    "scuba": ("SPO016000", "Sports & Recreation / Water Sports", "SZG"),
}


def map_tag_to_bisac(tag: str) -> tuple[str, str, str] | None:
    """Map a free-text tag to BISAC + Thema codes. Returns (code, name, thema) or None."""
    key = tag.lower().strip()
    if key in BISAC_MAP:
        return BISAC_MAP[key]
    # Fuzzy: check if any BISAC key is contained in the tag
    for k, v in BISAC_MAP.items():
        if k in key or key in k:
            return v
    return None


def map_google_category(category: str) -> tuple[str, str, str] | None:
    """Map a Google Books category to BISAC. Google uses BISAC-like names."""
    return map_tag_to_bisac(category)


async def backfill_bisac_codes(limit: int = 100) -> dict[str, Any]:
    """Map existing tags to BISAC codes and store in extra_metadata."""
    from brainycat.db import execute, fetch_all

    rows = await fetch_all(
        """
        SELECT b.id, array_agg(t.name) as tags
        FROM books b
        JOIN books_tags bt ON bt.book_id = b.id
        JOIN tags t ON t.id = bt.tag_id
        WHERE b.extra_metadata IS NULL OR NOT b.extra_metadata ? 'bisac_codes'
        GROUP BY b.id
        LIMIT $1
    """,
        limit,
    )

    mapped = 0
    for r in rows:
        codes = []
        for tag in r["tags"]:
            result = map_tag_to_bisac(tag)
            if result:
                codes.append({"bisac": result[0], "name": result[1], "thema": result[2]})
        if codes:
            import json

            await execute(
                "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || $1::jsonb WHERE id = $2",
                json.dumps({"bisac_codes": codes}),
                r["id"],
            )
            mapped += 1

    return {"mapped": mapped, "checked": len(rows)}
