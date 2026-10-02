"""Audit script: identify books missing dedup signatures, text profiles, or ISBN metadata.

Connects to BrainyCat production database and generates a coverage gap report.
Output: reports/coverage_audit_gap.md
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

import asyncpg

# No default: a credential must never live in the source. Use the same URL the app uses, e.g.
#   export DATABASE_URL="postgresql://brainycat:$POSTGRES_PASSWORD@localhost:5432/brainycat"
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("BRAINYCAT_DATABASE_URL")
if not DATABASE_URL:
    sys.exit("ERROR: set DATABASE_URL (or BRAINYCAT_DATABASE_URL) to the database connection string.")


async def run_audit():
    try:
        conn = await asyncpg.connect(DATABASE_URL)
    except Exception as e:
        print(f"ERROR: Database connection failed: {e}", file=sys.stderr)
        sys.exit(1)

    report_lines = []
    report_lines.append("# BrainyCat Coverage Audit — Dedup & Identification Gaps")
    report_lines.append(f"\n**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    # Total counts
    total = await conn.fetchval("SELECT count(*) FROM books")
    report_lines.append(f"**Total books:** {total:,}\n")

    # --- ISBN Coverage ---
    isbn_stats = await conn.fetchrow("""
        SELECT
            count(*) FILTER (WHERE isbn IS NOT NULL AND isbn != '') as has_isbn,
            count(*) FILTER (WHERE isbn IS NULL OR isbn = '') as no_isbn
        FROM books
    """)
    report_lines.append("## 1. ISBN Coverage\n")
    report_lines.append(f"| Status | Count | % |")
    report_lines.append(f"|--------|-------|---|")
    report_lines.append(f"| Has ISBN | {isbn_stats['has_isbn']:,} | {100*isbn_stats['has_isbn']/total:.1f}% |")
    report_lines.append(f"| Missing ISBN | {isbn_stats['no_isbn']:,} | {100*isbn_stats['no_isbn']/total:.1f}% |")

    # ISBN gaps by storage volume
    isbn_by_storage = await conn.fetch("""
        SELECT
            CASE WHEN bf.file_path LIKE '/data/library/%' THEN '/data/library'
                 ELSE '/data/uuid-dirs' END as storage,
            count(DISTINCT b.id) FILTER (WHERE b.isbn IS NULL OR b.isbn = '') as no_isbn,
            count(DISTINCT b.id) as total
        FROM books b
        JOIN book_files bf ON bf.book_id = b.id
        GROUP BY 1 ORDER BY 2 DESC
    """)
    report_lines.append("\n### ISBN gaps by storage volume\n")
    report_lines.append("| Volume | Missing ISBN | Total | Gap % |")
    report_lines.append("|--------|-------------|-------|-------|")
    for row in isbn_by_storage:
        pct = 100 * row['no_isbn'] / row['total'] if row['total'] > 0 else 0
        report_lines.append(f"| `{row['storage']}` | {row['no_isbn']:,} | {row['total']:,} | {pct:.1f}% |")

    # ISBN gaps by format
    isbn_by_format = await conn.fetch("""
        SELECT bf.format,
            count(DISTINCT b.id) FILTER (WHERE b.isbn IS NULL OR b.isbn = '') as no_isbn,
            count(DISTINCT b.id) as total
        FROM books b
        JOIN book_files bf ON bf.book_id = b.id
        GROUP BY 1 ORDER BY 2 DESC
    """)
    report_lines.append("\n### ISBN gaps by format\n")
    report_lines.append("| Format | Missing ISBN | Total | Gap % |")
    report_lines.append("|--------|-------------|-------|-------|")
    for row in isbn_by_format:
        pct = 100 * row['no_isbn'] / row['total'] if row['total'] > 0 else 0
        report_lines.append(f"| {row['format']} | {row['no_isbn']:,} | {row['total']:,} | {pct:.1f}% |")

    # --- Fingerprint (LSH) Coverage ---
    fp_stats = await conn.fetchrow("""
        SELECT
            (SELECT count(*) FROM book_fingerprints) as has_fingerprint,
            (SELECT count(*) FROM books) - (SELECT count(*) FROM book_fingerprints) as no_fingerprint
        FROM (SELECT 1) x
    """)
    report_lines.append("\n## 2. Content Fingerprint (MinHash/LSH) Coverage\n")
    report_lines.append(f"| Status | Count | % |")
    report_lines.append(f"|--------|-------|---|")
    report_lines.append(f"| Has fingerprint | {fp_stats['has_fingerprint']:,} | {100*fp_stats['has_fingerprint']/total:.1f}% |")
    report_lines.append(f"| Missing fingerprint | {fp_stats['no_fingerprint']:,} | {100*fp_stats['no_fingerprint']/total:.1f}% |")

    # Fingerprint gaps by storage
    fp_by_storage = await conn.fetch("""
        SELECT
            CASE WHEN bf.file_path LIKE '/data/library/%' THEN '/data/library'
                 ELSE '/data/uuid-dirs' END as storage,
            count(DISTINCT b.id) FILTER (WHERE bfp.book_id IS NULL) as no_fp,
            count(DISTINCT b.id) as total
        FROM books b
        JOIN book_files bf ON bf.book_id = b.id
        LEFT JOIN book_fingerprints bfp ON bfp.book_id = b.id
        GROUP BY 1 ORDER BY 2 DESC
    """)
    report_lines.append("\n### Fingerprint gaps by storage volume\n")
    report_lines.append("| Volume | Missing FP | Total | Gap % |")
    report_lines.append("|--------|-----------|-------|-------|")
    for row in fp_by_storage:
        pct = 100 * row['no_fp'] / row['total'] if row['total'] > 0 else 0
        report_lines.append(f"| `{row['storage']}` | {row['no_fp']:,} | {row['total']:,} | {pct:.1f}% |")

    # --- Embedding Coverage ---
    emb_stats = await conn.fetchrow("""
        SELECT
            count(*) FILTER (WHERE embedding IS NOT NULL) as has_embedding,
            count(*) FILTER (WHERE embedding IS NULL) as no_embedding
        FROM books
    """)
    report_lines.append("\n## 3. Text Profile (Embedding) Coverage\n")
    report_lines.append(f"| Status | Count | % |")
    report_lines.append(f"|--------|-------|---|")
    report_lines.append(f"| Has embedding | {emb_stats['has_embedding']:,} | {100*emb_stats['has_embedding']/total:.1f}% |")
    report_lines.append(f"| Missing embedding | {emb_stats['no_embedding']:,} | {100*emb_stats['no_embedding']/total:.1f}% |")

    # Embeddable but not yet embedded
    embeddable = await conn.fetchval("""
        SELECT count(*) FROM books b
        WHERE b.embedding IS NULL
        AND (length(b.title) > 10 OR b.description IS NOT NULL
             OR EXISTS (SELECT 1 FROM books_authors ba WHERE ba.book_id = b.id))
    """)
    report_lines.append(f"\n**Embeddable (title>10 or has description/author) but not yet embedded:** {embeddable:,}")

    # --- Extra Metadata (incipit, LCCN, DOI, etc.) ---
    extra_stats = await conn.fetch("""
        SELECT
            count(*) FILTER (WHERE extra_metadata IS NOT NULL) as has_extra,
            count(*) FILTER (WHERE extra_metadata IS NOT NULL AND extra_metadata ? 'incipit') as has_incipit,
            count(*) FILTER (WHERE extra_metadata IS NOT NULL AND extra_metadata ? 'lccn') as has_lccn,
            count(*) FILTER (WHERE extra_metadata IS NOT NULL AND extra_metadata ? 'doi') as has_doi,
            count(*) FILTER (WHERE extra_metadata IS NOT NULL AND extra_metadata ? 'asin') as has_asin,
            count(*) FILTER (WHERE extra_metadata IS NOT NULL AND extra_metadata ? 'depot_legal') as has_depot_legal,
            count(*) FILTER (WHERE extra_metadata IS NOT NULL AND extra_metadata ? 'longest_words') as has_longest_words,
            count(*) FILTER (WHERE extra_metadata IS NOT NULL AND extra_metadata ? 'specific_words') as has_specific_words
        FROM books
    """)
    row = extra_stats[0]
    report_lines.append("\n## 4. Extended Identifiers & Text Profiles\n")
    report_lines.append("| Identifier | Books with data | % |")
    report_lines.append("|-----------|----------------|---|")
    for key in ('has_extra', 'has_incipit', 'has_lccn', 'has_doi', 'has_asin', 'has_depot_legal', 'has_longest_words', 'has_specific_words'):
        label = key.replace('has_', '').replace('_', ' ').title()
        report_lines.append(f"| {label} | {row[key]:,} | {100*row[key]/total:.1f}% |")

    # --- Cover and Description Coverage ---
    content_stats = await conn.fetchrow("""
        SELECT
            count(*) FILTER (WHERE cover_path IS NOT NULL AND cover_path != '' AND cover_path != 'none') as has_cover,
            count(*) FILTER (WHERE description IS NOT NULL AND description != '') as has_description
        FROM books
    """)
    report_lines.append("\n## 5. Content Completeness\n")
    report_lines.append("| Field | Has data | % |")
    report_lines.append("|-------|----------|---|")
    report_lines.append(f"| Cover | {content_stats['has_cover']:,} | {100*content_stats['has_cover']/total:.1f}% |")
    report_lines.append(f"| Description | {content_stats['has_description']:,} | {100*content_stats['has_description']/total:.1f}% |")

    # --- Priority Queue ---
    report_lines.append("\n## 6. Priority Gaps (books needing most work)\n")
    priority = await conn.fetchval("""
        SELECT count(*) FROM books b
        WHERE (b.isbn IS NULL OR b.isbn = '')
          AND b.embedding IS NULL
          AND NOT EXISTS (SELECT 1 FROM book_fingerprints bfp WHERE bfp.book_id = b.id)
    """)
    report_lines.append(f"**Books missing ALL three (ISBN + fingerprint + embedding):** {priority:,}\n")
    report_lines.append("These should be prioritized in the ingestion pipeline.\n")

    await conn.close()

    # Write report
    os.makedirs("reports", exist_ok=True)
    report_path = "reports/coverage_audit_gap.md"
    with open(report_path, "w") as f:
        f.write("\n".join(report_lines) + "\n")
    print(f"Report written to {report_path}")


if __name__ == "__main__":
    asyncio.run(run_audit())
