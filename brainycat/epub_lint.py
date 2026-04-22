"""EPUB linter — CSS validation, image optimization, font check, accessibility."""

from __future__ import annotations

import re
import zipfile
from typing import Any
from uuid import UUID

from brainycat.db import fetch_one


async def lint_epub(book_id: str) -> dict[str, Any]:
    """Run lint checks on an EPUB file."""
    row = await fetch_one(
        "SELECT file_path FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "no epub"}

    issues: list[dict[str, str]] = []
    stats: dict[str, Any] = {}

    try:
        with zipfile.ZipFile(row["file_path"]) as zf:
            names = zf.namelist()

            # CSS analysis
            css_issues = 0
            total_css_rules = 0
            for n in names:
                if n.endswith(".css"):
                    css = zf.read(n).decode("utf-8", errors="replace")
                    rules = re.findall(r"([^{}]+)\{([^}]*)\}", css)
                    total_css_rules += len(rules)
                    for _selector, body in rules:
                        # Invalid properties
                        for prop in re.findall(r"([\w-]+)\s*:", body):
                            if prop.startswith("-webkit-") or prop.startswith("-moz-"):
                                css_issues += 1
                                issues.append({"severity": "info", "check": "css", "detail": f"Vendor prefix: {prop} in {n}"})
                        # !important abuse
                        if body.count("!important") > 2:
                            issues.append({"severity": "warning", "check": "css", "detail": f"Excessive !important in {n}"})

            stats["css_rules"] = total_css_rules
            stats["css_vendor_prefixes"] = css_issues

            # Image analysis
            total_img_size = 0
            oversized = []
            no_alt = 0
            for n in names:
                if n.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".svg")):
                    info = zf.getinfo(n)
                    total_img_size += info.file_size
                    if info.file_size > 500_000:
                        oversized.append({"file": n, "size_kb": info.file_size // 1024})

            # Check alt text in HTML
            for n in names:
                if n.endswith((".xhtml", ".html", ".htm")):
                    html = zf.read(n).decode("utf-8", errors="replace")
                    imgs = re.findall(r"<img[^>]*>", html, re.IGNORECASE)
                    for img in imgs:
                        if 'alt="' not in img and "alt='" not in img:
                            no_alt += 1

            stats["total_image_size_kb"] = total_img_size // 1024
            stats["oversized_images"] = len(oversized)
            stats["images_missing_alt"] = no_alt

            if oversized:
                issues.append(
                    {
                        "severity": "warning",
                        "check": "images",
                        "detail": f"{len(oversized)} images >500KB: {', '.join(i['file'] for i in oversized[:3])}",
                    }
                )
            if no_alt > 0:
                issues.append({"severity": "warning", "check": "accessibility", "detail": f"{no_alt} images missing alt text"})

            # Font analysis
            fonts = [n for n in names if n.lower().endswith((".ttf", ".otf", ".woff", ".woff2"))]
            total_font_size = sum(zf.getinfo(f).file_size for f in fonts)
            stats["embedded_fonts"] = len(fonts)
            stats["font_size_kb"] = total_font_size // 1024
            if total_font_size > 2_000_000:
                issues.append(
                    {
                        "severity": "warning",
                        "check": "fonts",
                        "detail": f"Large font payload: {total_font_size // 1024}KB ({len(fonts)} fonts). Consider subsetting.",
                    }
                )

            # Reading order check
            has_nav = any("nav" in n.lower() and n.endswith((".xhtml", ".html")) for n in names)
            if not has_nav:
                issues.append({"severity": "info", "check": "accessibility", "detail": "No nav document found (EPUB 3 accessibility)"})

            # Language declaration
            lang_found = False
            for n in names:
                if n.endswith((".xhtml", ".html")):
                    html = zf.read(n).decode("utf-8", errors="replace")[:500]
                    if "xml:lang=" in html or "lang=" in html:
                        lang_found = True
                        break
            if not lang_found:
                issues.append({"severity": "warning", "check": "accessibility", "detail": "No language declaration in HTML files"})

            stats["total_files"] = len(names)
            stats["total_size_kb"] = sum(zf.getinfo(n).file_size for n in names) // 1024

    except zipfile.BadZipFile:
        return {"error": "not a valid EPUB/ZIP"}

    return {"issues": issues, "stats": stats, "issue_count": len(issues)}
