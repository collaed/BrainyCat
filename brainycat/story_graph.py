"""Story Graph — narrative arc visualization and AI story generation."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import httpx

from brainycat import db
from brainycat.config import settings

COLORS = ["#4facfe", "#f093fb", "#43e97b", "#fa709a", "#fee140", "#a18cd1"]


async def analyze_book(book_id: str, user_id: str) -> dict[str, Any]:
    """Analyze a book's narrative arc by chunking text and scoring tension."""
    row = await db.fetch_one(
        "SELECT bf.file_path, bf.format, b.title FROM book_files bf JOIN books b ON b.id = bf.book_id WHERE bf.book_id = $1 LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "no file"}

    # Extract text in segments
    import fitz

    segments: list[str] = []

    if row["format"] == "pdf":
        doc = fitz.open(row["file_path"])
        total = len(doc)
        chunk_size = max(1, total // 10)
        for i in range(0, total, chunk_size):
            text = " ".join(doc[j].get_text() for j in range(i, min(i + chunk_size, total)))
            segments.append(text[:2000])
        doc.close()
    elif row["format"] == "epub":
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub

        book = epub.read_epub(row["file_path"], options={"ignore_ncx": True})
        items = [i for i in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)]
        chunk_size = max(1, len(items) // 10)
        for i in range(0, len(items), chunk_size):
            text = ""
            for item in items[i : i + chunk_size]:
                soup = BeautifulSoup(item.get_content(), "html.parser")
                text += soup.get_text() + " "
            segments.append(text[:2000])

    if not segments:
        return {"error": "no text"}

    # LLM scores each segment
    prompt = f"""Analyze the narrative arc of "{row["title"]}". For each of the following {len(segments)} text segments (representing ~10% of the book each), rate the tension/action level from 0-10 and identify the key event.

Return JSON array: [{{"position": 0, "tension": 5, "event": "brief description"}}]
Position should go from 0 to 100 in equal steps.

"""
    for i, seg in enumerate(segments[:10]):
        prompt += f"\n--- Segment {i + 1} ({(i * 10)}%-{(i + 1) * 10}%) ---\n{seg[:800]}\n"

    prompt += "\n\nReturn ONLY the JSON array."

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{settings.intello_url}/v1/chat/completions",
                json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2},
            )
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"]
                # Parse JSON
                start = content.find("[")
                end = content.rfind("]") + 1
                if start >= 0 and end > start:
                    points = json.loads(content[start:end])
                    # Store
                    await db.execute(
                        """INSERT INTO story_graphs (book_id, user_id, points, metadata)
                           VALUES ($1, $2, $3::jsonb, $4::jsonb)
                           ON CONFLICT (book_id, user_id) DO UPDATE SET points = $3::jsonb, created_at = now()""",
                        UUID(book_id),
                        UUID(user_id),
                        json.dumps(points),
                        json.dumps({"title": row["title"], "segments": len(segments)}),
                    )
                    return {"title": row["title"], "points": points}
    except Exception as e:
        return {"error": str(e)}

    return {"error": "analysis failed"}


async def generate_story_arc(premise: str, genre: str, length: str, inspiration_ids: list[str]) -> dict[str, Any]:
    """Generate a proposed narrative arc based on premise + inspiration books."""
    # Load inspiration arcs
    inspirations = []
    for bid in inspiration_ids[:3]:
        row = await db.fetch_one(
            "SELECT sg.points, sg.metadata FROM story_graphs sg WHERE sg.book_id = $1 LIMIT 1",
            UUID(bid),
        )
        if row:
            inspirations.append({"title": (row["metadata"] or {}).get("title", "Unknown"), "points": row["points"]})

    inspiration_text = ""
    for insp in inspirations:
        inspiration_text += f'\nInspiration: "{insp["title"]}" — arc: {json.dumps(insp["points"][:5])}\n'

    prompt = f"""You are a story structure expert. Generate a narrative arc for a new story.

PREMISE: {premise}
GENRE: {genre}
TARGET LENGTH: {length}
{inspiration_text}

Generate 10-12 plot points as a JSON array. Each point should have:
- position (0-100, representing % through the story)
- tension (0-10, action/conflict level)
- event (what happens at this beat)
- chapter_suggestion (suggested chapter title)

Follow classic story structure (setup → rising action → midpoint → crisis → climax → resolution) but adapt based on the inspiration arcs above.

Return ONLY the JSON array."""

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{settings.intello_url}/v1/chat/completions",
                json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.5},
            )
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"]
                start = content.find("[")
                end = content.rfind("]") + 1
                if start >= 0 and end > start:
                    points = json.loads(content[start:end])
                    return {"premise": premise, "genre": genre, "points": points, "inspirations": [i["title"] for i in inspirations]}
    except Exception as e:
        return {"error": str(e)}

    return {"error": "generation failed"}


def render_svg(graphs: list[dict[str, Any]], width: int = 800, height: int = 400, theme: str = "dark") -> str:
    """Render one or more story graphs as an SVG chart."""
    bg = "#0f1115" if theme == "dark" else "#ffffff"
    text_color = "#e2e8f0" if theme == "dark" else "#1a1d23"
    grid_color = "#2d333b" if theme == "dark" else "#e2e8f0"

    margin = {"top": 40, "right": 30, "bottom": 60, "left": 50}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n'
    svg += f'<rect width="{width}" height="{height}" fill="{bg}"/>\n'

    # Grid lines
    for i in range(11):
        y = margin["top"] + plot_h - (i / 10 * plot_h)
        svg += f'<line x1="{margin["left"]}" y1="{y}" x2="{margin["left"] + plot_w}" y2="{y}" stroke="{grid_color}" stroke-width="0.5"/>\n'
        if i % 2 == 0:
            svg += f'<text x="{margin["left"] - 8}" y="{y + 4}" fill="{text_color}" font-size="10" text-anchor="end">{i}</text>\n'

    # X axis labels
    for pct in [0, 25, 50, 75, 100]:
        x = margin["left"] + (pct / 100 * plot_w)
        svg += f'<text x="{x}" y="{height - 15}" fill="{text_color}" font-size="10" text-anchor="middle">{pct}%</text>\n'

    # Plot each graph
    for gi, graph in enumerate(graphs):
        color = COLORS[gi % len(COLORS)]
        title = graph.get("title", f"Book {gi + 1}")
        points = graph.get("points", [])
        if not points:
            continue

        # Draw line
        path_points = []
        for p in points:
            x = margin["left"] + (p.get("position", 0) / 100 * plot_w)
            y = margin["top"] + plot_h - (p.get("tension", 5) / 10 * plot_h)
            path_points.append(f"{x},{y}")

        svg += f'<polyline points="{" ".join(path_points)}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>\n'

        # Dots + labels for key events
        for p in points:
            x = margin["left"] + (p.get("position", 0) / 100 * plot_w)
            y = margin["top"] + plot_h - (p.get("tension", 5) / 10 * plot_h)
            svg += f'<circle cx="{x}" cy="{y}" r="3" fill="{color}"/>\n'

        # Legend
        ly = margin["top"] + 15 + gi * 18
        svg += f'<rect x="{margin["left"] + 10}" y="{ly - 8}" width="12" height="12" rx="2" fill="{color}"/>\n'
        svg += f'<text x="{margin["left"] + 28}" y="{ly + 2}" fill="{text_color}" font-size="11">{title[:30]}</text>\n'

    # Axis titles
    svg += (
        f'<text x="{width / 2}" y="{height - 2}" fill="{text_color}" font-size="11" text-anchor="middle">Progress through book (%)</text>\n'
    )
    svg += f'<text x="12" y="{height / 2}" fill="{text_color}" font-size="11" text-anchor="middle" transform="rotate(-90, 12, {height / 2})">Tension / Action</text>\n'

    svg += "</svg>"
    return svg
