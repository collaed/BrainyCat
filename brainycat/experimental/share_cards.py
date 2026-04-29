"""Shareable note cards — export highlights as designed images.

Generates SVG cards from annotations for social sharing.

Config: BRAINYCAT_EXP_SHARE_CARDS=1
"""

from __future__ import annotations


def generate_card_svg(text: str, book_title: str, author: str = "", theme: str = "dark") -> str:
    """Generate an SVG card for a highlight/annotation."""
    bg = "#1a1d23" if theme == "dark" else "#fefefe"
    fg = "#e2e8f0" if theme == "dark" else "#1a1d23"
    accent = "#4facfe" if theme == "dark" else "#2563eb"
    muted = "#94a3b8" if theme == "dark" else "#64748b"

    # Wrap text at ~45 chars
    words = text.split()
    lines = []
    current = ""
    for w in words:
        if len(current) + len(w) + 1 > 45:
            lines.append(current)
            current = w
        else:
            current = f"{current} {w}".strip()
    if current:
        lines.append(current)
    lines = lines[:8]  # Max 8 lines

    text_y = 80
    text_elements = "\n".join(
        f'<text x="40" y="{text_y + i * 28}" fill="{fg}" font-size="16" font-family="Georgia, serif">{line}</text>'
        for i, line in enumerate(lines)
    )

    height = 120 + len(lines) * 28 + 60
    meta_y = height - 40

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="500" height="{height}" viewBox="0 0 500 {height}">
  <rect width="500" height="{height}" rx="12" fill="{bg}"/>
  <rect x="30" y="40" width="4" height="{len(lines) * 28 + 10}" rx="2" fill="{accent}"/>
  {text_elements}
  <text x="40" y="{meta_y}" fill="{muted}" font-size="12" font-family="Inter, sans-serif">— {book_title}</text>
  <text x="40" y="{meta_y + 18}" fill="{muted}" font-size="11" font-family="Inter, sans-serif">{author}</text>
  <text x="430" y="{meta_y + 18}" fill="{muted}" font-size="10" font-family="Inter, sans-serif" text-anchor="end">🐱 BrainyCat</text>
</svg>'''
