"""EPUB quality checker — validates structure, links, images, encoding."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID
from xml.etree import ElementTree as ET

from brainycat.db import execute, fetch_one


async def check_epub(book_id: str) -> dict[str, Any]:
    """Run quality checks on an EPUB file. Returns issues and a score."""
    row = await fetch_one(
        "SELECT file_path FROM book_files WHERE book_id = $1 AND format = 'epub' LIMIT 1",
        UUID(book_id),
    )
    if not row:
        return {"error": "no epub file"}

    import zipfile

    path = row["file_path"]
    issues: list[dict[str, str]] = []
    checks_passed = 0
    total_checks = 0

    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()

            # 1. mimetype file
            total_checks += 1
            if "mimetype" in names:
                mt = zf.read("mimetype").decode("utf-8", errors="replace").strip()
                if mt == "application/epub+zip":
                    checks_passed += 1
                else:
                    issues.append({"severity": "error", "check": "mimetype", "detail": f"Wrong mimetype: {mt}"})
            else:
                issues.append({"severity": "error", "check": "mimetype", "detail": "Missing mimetype file"})

            # 2. container.xml
            total_checks += 1
            container_path = "META-INF/container.xml"
            opf_path = None
            if container_path in names:
                checks_passed += 1
                try:
                    tree = ET.fromstring(zf.read(container_path))
                    ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
                    rf = tree.find(".//c:rootfile", ns)
                    if rf is not None:
                        opf_path = rf.get("full-path")
                except ET.ParseError:
                    issues.append({"severity": "error", "check": "container", "detail": "Malformed container.xml"})
            else:
                issues.append({"severity": "error", "check": "container", "detail": "Missing META-INF/container.xml"})

            # 3. OPF exists and parses
            total_checks += 1
            manifest_items: dict[str, str] = {}
            spine_ids: list[str] = []
            if opf_path and opf_path in names:
                try:
                    opf_xml = zf.read(opf_path)
                    opf_tree = ET.fromstring(opf_xml)
                    ns = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
                    checks_passed += 1

                    # 4. Title exists
                    total_checks += 1
                    title = opf_tree.find(".//dc:title", ns)
                    if title is not None and title.text:
                        checks_passed += 1
                    else:
                        issues.append({"severity": "warning", "check": "title", "detail": "Missing dc:title"})

                    # 5. Manifest items
                    total_checks += 1
                    for item in opf_tree.findall(".//opf:manifest/opf:item", ns):
                        iid = item.get("id", "")
                        href = item.get("href", "")
                        manifest_items[iid] = href
                    if manifest_items:
                        checks_passed += 1
                    else:
                        issues.append({"severity": "error", "check": "manifest", "detail": "Empty manifest"})

                    # 6. Spine references valid manifest items
                    total_checks += 1
                    for itemref in opf_tree.findall(".//opf:spine/opf:itemref", ns):
                        idref = itemref.get("idref", "")
                        spine_ids.append(idref)
                        if idref not in manifest_items:
                            issues.append({"severity": "error", "check": "spine", "detail": f"Spine references missing item: {idref}"})
                    if spine_ids:
                        checks_passed += 1
                    else:
                        issues.append({"severity": "error", "check": "spine", "detail": "Empty spine"})

                except ET.ParseError:
                    issues.append({"severity": "error", "check": "opf", "detail": "Malformed OPF file"})
            else:
                issues.append({"severity": "error", "check": "opf", "detail": f"OPF not found: {opf_path}"})

            # 7. Check for broken internal links in HTML content
            total_checks += 1
            import os
            opf_dir = os.path.dirname(opf_path) if opf_path else ""
            broken_links = 0
            for _iid, href in manifest_items.items():
                if href.endswith((".xhtml", ".html", ".htm")):
                    full = os.path.join(opf_dir, href).replace("\\", "/") if opf_dir else href
                    if full in names:
                        content = zf.read(full).decode("utf-8", errors="replace")
                        for m in re.finditer(r'(?:href|src)=["\']([^"\'#]+)', content):
                            ref = m.group(1)
                            if ref.startswith(("http:", "https:", "mailto:")):
                                continue
                            ref_full = os.path.normpath(os.path.join(os.path.dirname(full), ref)).replace("\\", "/")
                            if ref_full not in names:
                                broken_links += 1
            if broken_links == 0:
                checks_passed += 1
            else:
                issues.append({"severity": "warning", "check": "links", "detail": f"{broken_links} broken internal links"})

            # 8. NCX exists (EPUB 2 compat)
            total_checks += 1
            has_ncx = any(n.endswith(".ncx") for n in names)
            if has_ncx:
                checks_passed += 1
            else:
                issues.append({"severity": "info", "check": "ncx", "detail": "No NCX file (EPUB 3 may use nav.xhtml instead)"})

            # 9. Cover image exists
            total_checks += 1
            has_cover = any("cover" in n.lower() and n.lower().endswith((".jpg", ".jpeg", ".png")) for n in names)
            if has_cover:
                checks_passed += 1
            else:
                issues.append({"severity": "info", "check": "cover", "detail": "No embedded cover image"})

            # 10. Check for oversized images
            total_checks += 1
            large_images = []
            for n in names:
                if n.lower().endswith((".jpg", ".jpeg", ".png", ".gif")):
                    info = zf.getinfo(n)
                    if info.file_size > 2_000_000:
                        large_images.append(f"{n} ({info.file_size // 1024}KB)")
            if not large_images:
                checks_passed += 1
            else:
                issues.append({"severity": "warning", "check": "images", "detail": f"Oversized images: {', '.join(large_images[:5])}"})

    except zipfile.BadZipFile:
        return {"error": "Not a valid ZIP/EPUB file", "score": 0}

    score = round(checks_passed / max(total_checks, 1) * 100)
    await execute(
        "UPDATE books SET quality_score = $1 WHERE id = $2",
        score, UUID(book_id),
    )
    return {
        "score": score,
        "checks_passed": checks_passed,
        "total_checks": total_checks,
        "issues": issues,
    }
