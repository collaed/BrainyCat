"""Cover image optimization and generation."""

from __future__ import annotations

import os
from typing import Any

from brainycat.db import execute, fetch_all
from brainycat.storage import book_dir

MAX_WIDTH = 600
MAX_HEIGHT = 900
JPEG_QUALITY = 82

# Genre → color scheme for generated covers
GENRE_COLORS: dict[str, dict[str, str]] = {
    # Fiction genres — vertical stripe on left third
    "fiction": {"stripe": "#2563eb", "bg": "#f8fafc", "text": "#1e293b"},
    "romance": {"stripe": "#e11d48", "bg": "#fff1f2", "text": "#1e293b"},
    "thriller": {"stripe": "#0f172a", "bg": "#f8fafc", "text": "#1e293b"},
    "fantasy": {"stripe": "#7c3aed", "bg": "#faf5ff", "text": "#1e293b"},
    "sci-fi": {"stripe": "#0891b2", "bg": "#ecfeff", "text": "#1e293b"},
    "horror": {"stripe": "#450a0a", "bg": "#1c1917", "text": "#e2e8f0"},
    "mystery": {"stripe": "#854d0e", "bg": "#fefce8", "text": "#1e293b"},
    "literary": {"stripe": "#065f46", "bg": "#f0fdf4", "text": "#1e293b"},
    "erotica": {"stripe": "#9f1239", "bg": "#1c1917", "text": "#e2e8f0"},
    # Non-fiction — horizontal stripe across top
    "non-fiction": {"stripe": "#dc2626", "bg": "#ffffff", "text": "#1e293b", "layout": "horizontal"},
    "self-help": {"stripe": "#f59e0b", "bg": "#ffffff", "text": "#1e293b", "layout": "horizontal"},
    "business": {"stripe": "#1d4ed8", "bg": "#ffffff", "text": "#1e293b", "layout": "horizontal"},
    "science": {"stripe": "#059669", "bg": "#ffffff", "text": "#1e293b", "layout": "horizontal"},
    "history": {"stripe": "#92400e", "bg": "#fffbeb", "text": "#1e293b", "layout": "horizontal"},
    "philosophy": {"stripe": "#4338ca", "bg": "#ffffff", "text": "#1e293b", "layout": "horizontal"},
    "psychology": {"stripe": "#0d9488", "bg": "#ffffff", "text": "#1e293b", "layout": "horizontal"},
    "technology": {"stripe": "#475569", "bg": "#f1f5f9", "text": "#1e293b", "layout": "horizontal"},
    "cooking": {"stripe": "#ea580c", "bg": "#fff7ed", "text": "#1e293b", "layout": "horizontal"},
    "health": {"stripe": "#16a34a", "bg": "#f0fdf4", "text": "#1e293b", "layout": "horizontal"},
}


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _detect_genre(title: str, author: str, description: str) -> str:
    """Simple genre detection from metadata text."""
    text = f"{title} {description}".lower()
    checks = [
        ("erotica", ["erotica", "bdsm", "femdom", "erotic", "kink", "dominant", "submissive"]),
        ("romance", ["romance", "love story", "romantic"]),
        ("thriller", ["thriller", "suspense", "crime", "detective"]),
        ("fantasy", ["fantasy", "magic", "dragon", "wizard", "sword"]),
        ("sci-fi", ["sci-fi", "science fiction", "space", "robot", "cyberpunk"]),
        ("horror", ["horror", "ghost", "haunted", "zombie"]),
        ("mystery", ["mystery", "murder", "whodunit"]),
        ("self-help", ["self-help", "self help", "how to", "guide to", "workbook", "handbook"]),
        ("business", ["business", "entrepreneur", "startup", "marketing", "management", "investing"]),
        ("science", ["science", "physics", "biology", "chemistry", "mathematics"]),
        ("history", ["history", "historical", "war", "ancient", "medieval"]),
        ("philosophy", ["philosophy", "philosophical", "ethics", "existential"]),
        ("psychology", ["psychology", "psychological", "mental", "cognitive", "therapy", "anxiety"]),
        ("technology", ["programming", "software", "computer", "data science", "algorithm", "web"]),
        ("cooking", ["cooking", "recipe", "cuisine", "food", "kitchen"]),
        ("health", ["health", "fitness", "diet", "nutrition", "yoga", "meditation"]),
        ("non-fiction", ["dummies", "for beginners", "introduction to", "complete guide"]),
    ]
    for genre, keywords in checks:
        if any(kw in text for kw in keywords):
            return genre
    # Check if it looks like fiction
    if any(w in text for w in ["novel", "story", "tales", "fiction", "chapter 1"]):
        return "fiction"
    return "non-fiction"


def generate_cover(title: str, author: str, genre: str = "", description: str = "") -> bytes:
    """Generate a stylish book cover image. Returns JPEG bytes."""
    from PIL import Image, ImageDraw, ImageFont

    if not genre:
        genre = _detect_genre(title, author, description)

    colors = GENRE_COLORS.get(genre, GENRE_COLORS["fiction"])
    is_horizontal = colors.get("layout") == "horizontal"
    w, h = 600, 900

    bg = _hex_to_rgb(colors["bg"])
    stripe = _hex_to_rgb(colors["stripe"])
    text_color = _hex_to_rgb(colors["text"])

    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)

    if is_horizontal:
        # Non-fiction: horizontal stripe across top 15%
        draw.rectangle([0, 0, w, int(h * 0.12)], fill=stripe)
        # Thin accent line below
        draw.rectangle([0, int(h * 0.12), w, int(h * 0.12) + 4], fill=stripe)
        # Genre label in stripe
        try:
            small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        except OSError:
            small_font = ImageFont.load_default()
        draw.text((30, int(h * 0.04)), genre.upper(), fill=(255, 255, 255), font=small_font)
        title_y = int(h * 0.20)
    else:
        # Fiction: vertical stripe on left third
        stripe_w = int(w * 0.08)
        draw.rectangle([0, 0, stripe_w, h], fill=stripe)
        # Subtle gradient effect — lighter stripe
        lighter = tuple(min(255, c + 40) for c in stripe)
        draw.rectangle([stripe_w, 0, stripe_w + 3, h], fill=lighter)
        title_y = int(h * 0.25)

    # Load font
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 42)
        author_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
        small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except OSError:
        title_font = ImageFont.load_default()
        author_font = title_font
        small_font = title_font

    # Title — word wrap
    margin = int(w * 0.15) if not is_horizontal else 30
    max_text_w = w - margin - 30
    words = title.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=title_font)
        if bbox[2] - bbox[0] > max_text_w and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    lines = lines[:5]  # max 5 lines

    for i, line in enumerate(lines):
        draw.text((margin, title_y + i * 52), line, fill=text_color, font=title_font)

    # Author
    author_y = title_y + len(lines) * 52 + 40
    draw.text((margin, author_y), author, fill=(*text_color[:2], min(text_color[2] + 60, 200)), font=author_font)

    # Bottom accent — publisher-style line
    draw.rectangle([margin, h - 80, w - 30, h - 77], fill=stripe)

    # Small "BrainyCat" watermark
    draw.text((margin, h - 60), "BrainyCat Library", fill=(180, 180, 180), font=small_font)

    import io

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


def optimize_cover(path: str) -> int:
    """Resize and compress a cover image. Returns bytes saved."""
    from PIL import Image

    original_size = os.path.getsize(path)
    try:
        img = Image.open(path)
    except Exception:
        return 0

    # Skip if already small
    if original_size < 100_000 and max(img.size) <= MAX_WIDTH:
        return 0

    # Resize maintaining aspect ratio
    img.thumbnail((MAX_WIDTH, MAX_HEIGHT), Image.LANCZOS)

    # Convert to RGB if needed (RGBA/P modes)
    if img.mode not in ("RGB",):
        img = img.convert("RGB")

    img.save(path, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    new_size = os.path.getsize(path)
    return max(0, original_size - new_size)


async def optimize_all_covers() -> dict[str, Any]:
    """Optimize all existing cover images."""
    rows = await fetch_all("SELECT id, cover_path FROM books WHERE cover_path IS NOT NULL")
    total_saved = 0
    optimized = 0
    for r in rows:
        if r["cover_path"] and os.path.isfile(r["cover_path"]):
            saved = optimize_cover(r["cover_path"])
            if saved > 0:
                total_saved += saved
                optimized += 1
    return {"optimized": optimized, "saved_mb": round(total_saved / 1024 / 1024, 1)}


async def generate_missing_covers() -> dict[str, Any]:
    """Generate covers for books that don't have one."""
    rows = await fetch_all("""
        SELECT b.id, b.title, b.description,
               array_agg(DISTINCT a.name) FILTER (WHERE a.name IS NOT NULL) as authors,
               array_agg(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) as tags
        FROM books b
        LEFT JOIN books_authors ba ON ba.book_id = b.id LEFT JOIN authors a ON a.id = ba.author_id
        LEFT JOIN books_tags bt ON bt.book_id = b.id LEFT JOIN tags t ON t.id = bt.tag_id
        WHERE b.cover_path IS NULL OR b.cover_path = ''
        GROUP BY b.id
    """)
    generated = 0
    for r in rows:
        title = r["title"] or "Untitled"
        author = (r["authors"] or ["Unknown"])[0] if r["authors"] else "Unknown"
        desc = r["description"] or ""
        tags = " ".join(r["tags"] or [])

        cover_data = generate_cover(title, author, description=f"{desc} {tags}")
        cover_path = os.path.join(book_dir(str(r["id"])), "cover.jpg")
        with open(cover_path, "wb") as f:
            f.write(cover_data)
        await execute("UPDATE books SET cover_path = $1 WHERE id = $2", cover_path, r["id"])
        generated += 1

    return {"generated": generated}
