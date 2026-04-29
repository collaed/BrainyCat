"""Auto-fix common EPUB issues on ingest (inspired by CWA's EPUB Fixer)."""

from __future__ import annotations

import os
import re
import zipfile
from typing import Any


def fix_epub(epub_path: str) -> dict[str, Any]:
    """Fix common EPUB issues in-place. Returns list of fixes applied."""
    if not zipfile.is_zipfile(epub_path):
        return {"fixed": False, "error": "not a valid zip"}

    fixes = []
    tmp_path = epub_path + ".fixing"

    try:
        with zipfile.ZipFile(epub_path, "r") as zin, zipfile.ZipFile(tmp_path, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)

                if item.filename.endswith((".xhtml", ".html", ".htm", ".opf", ".ncx")):
                    text = data.decode("utf-8", errors="replace")

                    # Fix 1: Add UTF-8 XML declaration if missing
                    if item.filename.endswith((".xhtml", ".html", ".htm")) and "<?xml" not in text[:100]:
                        text = '<?xml version="1.0" encoding="utf-8"?>\n' + text
                        fixes.append("added_xml_declaration")

                    # Fix 2: Fix missing/invalid language tag in OPF
                    if item.filename.endswith(".opf"):
                        if "<dc:language" not in text:
                            text = text.replace("</metadata>", "  <dc:language>en</dc:language>\n  </metadata>")
                            fixes.append("added_language_tag")
                        # Fix malformed language tags
                        text = re.sub(r"<dc:language>\s*</dc:language>", "<dc:language>en</dc:language>", text)

                    # Fix 3: Remove stray img tags with no src
                    text = re.sub(r'<img[^>]*src\s*=\s*["\']["\'][^>]*/?\s*>', "", text)
                    text = re.sub(r"<img(?![^>]*src)[^>]*/?\s*>", "", text)
                    if "stray_img" not in fixes and re.search(r"<img(?![^>]*src)", data.decode("utf-8", errors="replace")):
                        fixes.append("removed_stray_img")

                    # Fix 4: Fix NCX links pointing to body with hash
                    if item.filename.endswith(".ncx"):
                        text = re.sub(r'src="([^"]+)#body"', r'src="\1"', text)
                        if "ncx_body_hash" not in fixes and "#body" in data.decode("utf-8", errors="replace"):
                            fixes.append("fixed_ncx_body_links")

                    data = text.encode("utf-8")

                zout.writestr(item, data)

        if fixes:
            os.replace(tmp_path, epub_path)
        else:
            os.unlink(tmp_path)

    except Exception as e:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return {"fixed": False, "error": str(e)[:100]}

    return {"fixed": bool(fixes), "fixes": fixes}
