"""Index Open Library editions dump into SQLite for instant lookup.

Creates two lookup tables:
1. isbn_lookup: ISBN → title, author, language, publisher, year, subjects, OL key, work key
2. title_lookup: normalized(title+author) → ISBN (for reverse lookup)

Usage: python3 ol_indexer.py /path/to/ol_dump_editions_latest.txt.gz /path/to/isbn_lookup.db
"""

import gzip
import json
import re
import sqlite3
import sys
import time
import unicodedata

DUMP_PATH = sys.argv[1] if len(sys.argv) > 1 else "/mnt/brainycat/ol_dump/ol_dump_editions_latest.txt.gz"
DB_PATH = sys.argv[2] if len(sys.argv) > 2 else "/mnt/brainycat/ol_dump/isbn_lookup.db"

def normalize_title(title: str) -> str:
    """Normalize title for fuzzy matching."""
    t = title.lower()
    t = unicodedata.normalize("NFKD", t)
    t = re.sub(r"[\u0300-\u036f]", "", t)  # strip diacritics
    t = re.sub(r"[^a-z0-9 ]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def extract_year(publish_date: str) -> int | None:
    """Extract 4-digit year from various date formats."""
    if not publish_date:
        return None
    m = re.search(r"\b(1[5-9]\d{2}|20[0-2]\d)\b", publish_date)
    return int(m.group(1)) if m else None

def main():
    print(f"Indexing {DUMP_PATH} → {DB_PATH}")
    start = time.time()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-2000000")  # 2GB cache

    conn.execute("DROP TABLE IF EXISTS isbn_lookup")
    conn.execute("DROP TABLE IF EXISTS title_lookup")

    conn.execute("""
        CREATE TABLE isbn_lookup (
            isbn TEXT PRIMARY KEY,
            title TEXT,
            authors TEXT,
            language TEXT,
            publisher TEXT,
            year INTEGER,
            subjects TEXT,
            pages INTEGER,
            ol_key TEXT,
            work_key TEXT,
            cover_id INTEGER
        )
    """)

    conn.execute("""
        CREATE TABLE title_lookup (
            norm_title TEXT,
            isbn TEXT,
            ol_key TEXT
        )
    """)

    batch_isbn = []
    batch_title = []
    count = 0
    indexed = 0
    skipped = 0

    with gzip.open(DUMP_PATH, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            count += 1
            if count % 500000 == 0:
                # Commit batch
                if batch_isbn:
                    conn.executemany("INSERT OR IGNORE INTO isbn_lookup VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch_isbn)
                    conn.executemany("INSERT INTO title_lookup VALUES (?,?,?)", batch_title)
                    conn.commit()
                    batch_isbn.clear()
                    batch_title.clear()
                elapsed = time.time() - start
                rate = count / elapsed
                print(f"  {count:,} lines, {indexed:,} indexed, {rate:.0f} lines/s, {elapsed:.0f}s elapsed")

            parts = line.split("\t", 4)
            if len(parts) < 5:
                continue

            try:
                data = json.loads(parts[4])
            except (json.JSONDecodeError, IndexError):
                skipped += 1
                continue

            # Extract ISBNs
            isbns = data.get("isbn_13", []) + data.get("isbn_10", [])
            if not isbns:
                skipped += 1
                continue

            title = data.get("title", "")
            if not title:
                skipped += 1
                continue

            # Extract fields
            authors_list = []
            for a in data.get("authors", []):
                if isinstance(a, dict) and "key" in a:
                    authors_list.append(a["key"])
            authors = ",".join(authors_list)

            languages = data.get("languages", [])
            lang = ""
            if languages and isinstance(languages[0], dict):
                lang = languages[0].get("key", "").replace("/languages/", "")

            publishers = data.get("publishers", [])
            publisher = publishers[0] if publishers else ""

            year = extract_year(data.get("publish_date", ""))

            subjects = data.get("subjects", [])
            subjects_str = "|".join(subjects[:10]) if subjects else ""

            pages = data.get("number_of_pages")
            ol_key = data.get("key", "")

            works = data.get("works", [])
            work_key = works[0]["key"] if works and isinstance(works[0], dict) else ""

            covers = data.get("covers", [])
            cover_id = covers[0] if covers else None

            norm_title = normalize_title(title)

            # Index each ISBN
            for isbn in isbns:
                isbn = isbn.strip().replace("-", "")
                if len(isbn) not in (10, 13):
                    continue
                batch_isbn.append((isbn, title, authors, lang, publisher, year, subjects_str, pages, ol_key, work_key, cover_id))
                if norm_title:
                    batch_title.append((norm_title, isbn, ol_key))
                indexed += 1

    # Final batch
    if batch_isbn:
        conn.executemany("INSERT OR IGNORE INTO isbn_lookup VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch_isbn)
        conn.executemany("INSERT INTO title_lookup VALUES (?,?,?)", batch_title)
        conn.commit()

    print(f"Creating indexes...")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_title_norm ON title_lookup(norm_title)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_isbn_lang ON isbn_lookup(language)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_isbn_year ON isbn_lookup(year)")
    conn.commit()

    # Stats
    isbn_count = conn.execute("SELECT count(*) FROM isbn_lookup").fetchone()[0]
    title_count = conn.execute("SELECT count(*) FROM title_lookup").fetchone()[0]
    elapsed = time.time() - start

    print(f"\nDone in {elapsed:.0f}s")
    print(f"  ISBN entries: {isbn_count:,}")
    print(f"  Title entries: {title_count:,}")
    print(f"  Lines processed: {count:,}")
    print(f"  Skipped (no ISBN/title): {skipped:,}")

    conn.close()

if __name__ == "__main__":
    main()
