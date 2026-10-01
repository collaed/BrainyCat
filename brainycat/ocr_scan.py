"""OCR + barcode scan for image-only PDFs that text extraction couldn't handle."""

import io
import json
import os
import re
import subprocess

import psycopg2
import psycopg2.extras

DB_URL = "postgresql://brainycat:brainycat@brainycat-db:5432/brainycat"

ISBN13_RE = re.compile(r"97[89][\d\s\-]{10,17}")
ISBN10_RE = re.compile(r"(?:ISBN[-:\s]*)?\d[-\s]?\d{2}[-\s]?\d{4,6}[-\s]?\d[-\s]?[\dXx]")
ISSN_RE = re.compile(r"ISSN\s*:?\s*(\d{4}[-\s]?\d{3}[\dXx])", re.IGNORECASE)


def _clean_isbn(raw):
    from brainycat.isbn import _clean_isbn
    return _clean_isbn(raw)


def run():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    found = 0
    tried = 0

    while True:
        cur.execute("""
            SELECT b.id, bf.file_path
            FROM books b
            JOIN book_files bf ON bf.book_id = b.id
            WHERE (b.isbn IS NULL OR b.isbn = '')
              AND bf.format = 'pdf'
              AND (b.extra_metadata ? 'isbn_extract_tried')
              AND NOT (COALESCE(b.extra_metadata, '{}'::jsonb) ? 'ocr_tried')
            LIMIT 1
        """)
        row = cur.fetchone()
        if not row:
            break

        book_id = row["id"]
        pdf_path = row["file_path"]
        tried += 1

        isbn = None
        issn = None

        if os.path.isfile(pdf_path):
            try:
                import fitz
                doc = fitz.open(pdf_path)
                num_pages = len(doc)

                # Scan first 5 + last 3 pages (copyright info, barcode on back)
                pages_to_scan = list(range(min(5, num_pages))) + list(range(max(0, num_pages - 3), num_pages))
                pages_to_scan = sorted(set(pages_to_scan))

                for page_idx in pages_to_scan:
                    if isbn:
                        break
                    page = doc[page_idx]
                    pix = page.get_pixmap(dpi=200)
                    img_bytes = pix.tobytes("png")

                    # Try barcode first (fast)
                    try:
                        from PIL import Image
                        from pyzbar.pyzbar import decode
                        img = Image.open(io.BytesIO(img_bytes))
                        barcodes = decode(img)
                        for bc in barcodes:
                            data = bc.data.decode("utf-8", errors="ignore")
                            cleaned = _clean_isbn(data)
                            if cleaned:
                                isbn = cleaned
                                break
                    except Exception:
                        pass

                    if isbn:
                        break

                    # OCR the page
                    try:
                        # Write temp PNG, run tesseract
                        tmp = f"/tmp/ocr_{book_id}_{page_idx}.png"
                        with open(tmp, "wb") as f:
                            f.write(img_bytes)
                        result = subprocess.run(
                            ["tesseract", tmp, "-", "--psm", "6", "-l", "eng+fra"],
                            capture_output=True, text=True, timeout=30,
                        )
                        os.unlink(tmp)
                        if result.returncode == 0:
                            text = result.stdout
                            # Look for ISBN
                            for m in ISBN13_RE.finditer(text):
                                cleaned = _clean_isbn(m.group())
                                if cleaned:
                                    isbn = cleaned
                                    break
                            if not isbn:
                                for m in ISBN10_RE.finditer(text):
                                    cleaned = _clean_isbn(m.group())
                                    if cleaned:
                                        isbn = cleaned
                                        break
                            # Look for ISSN
                            if not issn:
                                m = ISSN_RE.search(text)
                                if m:
                                    issn = re.sub(r"[^0-9Xx]", "", m.group(1))
                                    if len(issn) == 8:
                                        issn = issn[:4] + "-" + issn[4:]
                                    else:
                                        issn = None
                    except (subprocess.TimeoutExpired, FileNotFoundError):
                        pass

                doc.close()
            except Exception:
                pass

        # Write results
        meta = {"ocr_tried": True}
        if isbn:
            cur.execute("UPDATE books SET isbn = %s, updated_at = now() WHERE id = %s", (isbn, book_id))
            cur.execute("INSERT INTO enrichment_log (book_id, method, success) VALUES (%s, 'ocr_isbn', true)", (book_id,))
            found += 1
        if issn:
            meta["issn"] = issn

        cur.execute(
            "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || %s::jsonb WHERE id = %s",
            (json.dumps(meta), book_id),
        )

        if tried % 50 == 0:
            print(f"OCR scanned: {tried}, ISBNs found: {found}")

    print(f"Done. Scanned: {tried}, ISBNs found: {found}")
    conn.close()


if __name__ == "__main__":
    run()
