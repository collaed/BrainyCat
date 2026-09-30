"""Mass MOBI/AZW3 → EPUB converter. Runs as a dedicated thread."""

from __future__ import annotations

import json
import os
import subprocess
import time

import psycopg2
import psycopg2.extras


DB_URL = "postgresql://brainycat:brainycat@brainycat-db:5432/brainycat"
MIN_EPUB_SIZE = 1000  # minimum valid EPUB size in bytes


def run():
    """Convert all mobi/azw3 to epub, verify, delete source. Loops until done."""
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    converted = 0
    failed = 0

    while True:
        cur.execute("""
            SELECT bf.id as file_id, bf.book_id, bf.file_path, bf.format, bf.file_name
            FROM book_files bf
            JOIN books b ON b.id = bf.book_id
            WHERE bf.format IN ('mobi', 'azw3')
              AND NOT EXISTS (
                SELECT 1 FROM book_files bf2 
                WHERE bf2.book_id = bf.book_id AND bf2.format = 'epub'
              )
              AND NOT (COALESCE(b.extra_metadata, '{}'::jsonb) ? 'convert_failed')
            LIMIT 1
        """)
        row = cur.fetchone()
        if not row:
            break

        src = row["file_path"]
        book_id = row["book_id"]
        file_id = row["file_id"]

        if not os.path.isfile(src):
            # Source file missing — mark and skip
            cur.execute("DELETE FROM book_files WHERE id = %s", (file_id,))
            continue

        # Convert — try Rust converter first (fast), fall back to Calibre
        dst = os.path.splitext(src)[0] + ".epub"
        success = False
        rust_error = None
        try:
            result = subprocess.run(
                ["ebook-convert-rs", src, dst, "--lenient", "--json-summary"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) >= MIN_EPUB_SIZE:
                success = True
            else:
                rust_error = result.stderr.strip()[-200:] if result.stderr else result.stdout.strip()[-200:]
        except subprocess.TimeoutExpired:
            rust_error = "timeout_30s"
        except FileNotFoundError:
            rust_error = "binary_not_found"

        if not success:
            # Fallback to Calibre
            if os.path.isfile(dst):
                os.unlink(dst)
            try:
                result = subprocess.run(
                    ["ebook-convert", src, dst],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode == 0:
                    success = True
            except subprocess.TimeoutExpired:
                if os.path.isfile(dst):
                    os.unlink(dst)

            # Log Rust failure for learning (whether Calibre saved it or not)
            if rust_error:
                cur.execute(
                    "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'::jsonb), '{rust_convert_error}', %s::jsonb) WHERE id = %s",
                    (json.dumps({"error": rust_error, "calibre_saved": success, "format": row["format"]}), book_id),
                )

        # Verify output
        if not success or not os.path.isfile(dst) or os.path.getsize(dst) < MIN_EPUB_SIZE:
            # Conversion produced nothing or empty file
            if os.path.isfile(dst):
                os.unlink(dst)
            cur.execute(
                "UPDATE books SET extra_metadata = jsonb_set(COALESCE(extra_metadata, '{}'::jsonb), '{convert_failed}', 'true'::jsonb) WHERE id = %s",
                (book_id,),
            )
            failed += 1
            continue

        # Quick EPUB validity check — must be a zip with mimetype and well-formed XML
        try:
            import zipfile
            import xml.etree.ElementTree as ET
            with zipfile.ZipFile(dst) as zf:
                names = zf.namelist()
                if "mimetype" not in names and "META-INF/container.xml" not in names:
                    raise ValueError("not a valid epub")
                for name in names:
                    if name.endswith((".xhtml", ".html", ".htm")):
                        ET.fromstring(zf.read(name))
        except Exception:
            os.unlink(dst)
            failed += 1
            time.sleep(1)
            continue

        # Good EPUB — register in DB and delete source
        epub_size = os.path.getsize(dst)
        epub_name = os.path.basename(dst)

        cur.execute(
            "INSERT INTO book_files (book_id, format, file_path, file_name, file_size) VALUES (%s, 'epub', %s, %s, %s)",
            (book_id, dst, epub_name, epub_size),
        )

        # Delete source file and DB record
        if os.path.isfile(src):
            os.unlink(src)
        cur.execute("DELETE FROM book_files WHERE id = %s", (file_id,))

        converted += 1
        if converted % 100 == 0:
            print(f"Converted: {converted}, failed: {failed}")

    print(f"Done. Converted: {converted}, failed: {failed}")
    conn.close()


if __name__ == "__main__":
    run()
