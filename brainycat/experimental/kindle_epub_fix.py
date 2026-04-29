"""Extended Kindle EPUB fixes (from kindle-epub-fix.netlify.app).

Adds checks beyond our existing epub_fix.py:
- Removes <img> tags with empty/missing src attribute
- Strips invalid XML characters (control chars)
- Fixes broken internal links (href="#" with no target)

Config: BRAINYCAT_EXP_KINDLE_FIX=1
"""

from __future__ import annotations

import re
import zipfile


def fix_epub_for_kindle(epub_path: str) -> dict:
    """Apply Kindle-specific fixes to an EPUB file. Returns dict of fixes applied."""
    fixes = []

    try:
        with zipfile.ZipFile(epub_path, "r") as zin:
            contents = {}
            for name in zin.namelist():
                contents[name] = zin.read(name)
    except Exception:
        return {"error": "cannot read epub"}

    for name, data in contents.items():
        if not name.endswith((".xhtml", ".html", ".htm", ".opf")):
            continue
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            continue

        original = text

        # Remove <img> with empty/missing src
        text = re.sub(r'<img[^>]*src\s*=\s*["\']["\'][^>]*/?\s*>', "", text)
        text = re.sub(r"<img(?![^>]*src)[^>]*/?\s*>", "", text)

        # Strip invalid XML characters (control chars except tab/newline/cr)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

        # Fix href="#" with no id target (Kindle rejects these)
        text = re.sub(r'href="#"', 'href=""', text)

        if text != original:
            contents[name] = text.encode("utf-8")
            fixes.append(name)

    if fixes:
        with zipfile.ZipFile(epub_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for name, data in contents.items():
                zout.writestr(name, data)

    return {"fixes_applied": fixes, "files_modified": len(fixes)}
