"""Extract BnF catalogue via SPARQL into SQLite for French book lookup.

Queries data.bnf.fr SPARQL endpoint in batches of 10000, extracts:
ISBN, title, author, date, publisher → bnf_lookup.db
"""

import json
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.parse

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "/mnt/brainycat/data/ol_dump/bnf_lookup.db"
SPARQL_URL = "https://data.bnf.fr/sparql"
BATCH_SIZE = 10000
TOTAL_EXPECTED = 4703410

QUERY_TEMPLATE = """
SELECT ?isbn ?title ?author ?date ?publisher WHERE {{
  ?manif <http://data.bnf.fr/ontology/bnf-onto/isbn> ?isbn .
  ?manif <http://purl.org/dc/terms/title> ?title .
  OPTIONAL {{ ?manif <http://purl.org/dc/terms/date> ?date }}
  OPTIONAL {{ ?manif <http://purl.org/dc/terms/publisher> ?publisher }}
  OPTIONAL {{ ?manif <http://purl.org/dc/terms/creator> ?creator . ?creator <http://xmlns.com/foaf/0.1/name> ?author }}
}} OFFSET {offset} LIMIT {limit}
"""

def clean_isbn(raw: str) -> str:
    return re.sub(r"[^\dXx]", "", raw)

def extract_year(date_str: str) -> int | None:
    if not date_str:
        return None
    m = re.search(r"\b(1[5-9]\d{2}|20[0-2]\d)\b", date_str)
    return int(m.group(1)) if m else None

def sparql_query(query: str) -> list[dict]:
    data = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
    req = urllib.request.Request(SPARQL_URL, data=data, method="POST")
    req.add_header("Accept", "application/sparql-results+json")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())
                return result.get("results", {}).get("bindings", [])
        except Exception as e:
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
            else:
                print(f"  SPARQL error after 3 attempts: {e}")
                return []

def main():
    print(f"Extracting BnF catalogue → {DB_PATH}")
    start = time.time()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")

    conn.execute("DROP TABLE IF EXISTS bnf_isbn")
    conn.execute("""
        CREATE TABLE bnf_isbn (
            isbn TEXT PRIMARY KEY,
            title TEXT,
            author TEXT,
            year INTEGER,
            publisher TEXT
        )
    """)

    offset = 0
    total_inserted = 0

    while offset < TOTAL_EXPECTED:
        query = QUERY_TEMPLATE.format(offset=offset, limit=BATCH_SIZE)
        bindings = sparql_query(query)

        if not bindings:
            print(f"  No results at offset {offset}, stopping.")
            break

        batch = []
        for b in bindings:
            isbn_raw = b.get("isbn", {}).get("value", "")
            isbn = clean_isbn(isbn_raw)
            if len(isbn) not in (10, 13):
                continue
            title = b.get("title", {}).get("value", "")
            author = b.get("author", {}).get("value", "")
            date = b.get("date", {}).get("value", "")
            publisher = b.get("publisher", {}).get("value", "")
            year = extract_year(date)
            # Clean publisher (often "Paris : Publisher , year")
            if ":" in publisher:
                publisher = publisher.split(":")[1].split(",")[0].strip()
            batch.append((isbn, title, author, year, publisher))

        if batch:
            conn.executemany("INSERT OR IGNORE INTO bnf_isbn VALUES (?,?,?,?,?)", batch)
            conn.commit()
            total_inserted += len(batch)

        offset += BATCH_SIZE
        elapsed = time.time() - start
        rate = total_inserted / elapsed if elapsed > 0 else 0
        print(f"  Offset {offset:,} / ~{TOTAL_EXPECTED:,} | Inserted: {total_inserted:,} | {rate:.0f}/s | {elapsed:.0f}s")

        # Be polite to the endpoint
        time.sleep(1)

    print("\nCreating index...")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bnf_title ON bnf_isbn(title)")
    conn.commit()

    count = conn.execute("SELECT count(*) FROM bnf_isbn").fetchone()[0]
    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.0f}s")
    print(f"  BnF ISBN entries: {count:,}")
    conn.close()

if __name__ == "__main__":
    main()
