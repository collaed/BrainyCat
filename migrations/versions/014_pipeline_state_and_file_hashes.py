"""book_pipeline_state (M1 per-pipeline retry state) + book_files original-bytes hashes (K6)

M1: one `processing_status` column can't express ~15 independent pipelines. This per-(book,pipeline)
table replaces the scattered JSONB "tried" markers with explicit status + backoff + a lease so a
crash mid-run doesn't strand rows in 'processing'. Claimed via a LEFT JOIN against a candidate view
(a missing row = pending), so new books are picked up without a seeding step.

K6: BrainyCat modifies files after ingest (fix_epub rewrites EPUBs; writeback rewrites OPF/PDF), so a
hash of the *stored* file won't match the LibGen/AA record (MD5 of the original download) or another
user's upload of the same original. Capture the ORIGINAL bytes' md5/sha256 at ingest, immutably, plus
the Anna's Archive MD5 parsed from the filename before the standardizing rename drops it.

Revision ID: 014
Revises: 013
Create Date: 2026-09-30
"""

from typing import Sequence, Union

from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS book_pipeline_state (
        book_id       UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        pipeline      TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending','processing','complete','failed','skipped')),
        attempts      INT  NOT NULL DEFAULT 0,
        last_error    TEXT,
        claimed_at    TIMESTAMPTZ,
        next_retry_at TIMESTAMPTZ,
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (book_id, pipeline)
    );
    CREATE INDEX IF NOT EXISTS bps_ready_idx ON book_pipeline_state (pipeline, status, next_retry_at);

    ALTER TABLE book_files
        ADD COLUMN IF NOT EXISTS original_md5    TEXT,   -- MD5 of the bytes as received (LibGen/AA key)
        ADD COLUMN IF NOT EXISTS original_sha256 TEXT,   -- SHA-256 of the bytes as received (immutable)
        ADD COLUMN IF NOT EXISTS current_sha256  TEXT,   -- of the stored file (integrity checks)
        ADD COLUMN IF NOT EXISTS anna_md5        TEXT;   -- MD5 parsed from an Anna's Archive filename
    -- Non-UNIQUE index on the original-bytes hash: fast "do we already have this file?" lookups at
    -- ingest and exact-duplicate grouping. It is deliberately NOT unique yet — a UNIQUE index with
    -- the current plain INSERTs makes an ordinary duplicate import fail halfway (orphan book row +
    -- stranded file; 190/399 same-size pairs on fides are byte-identical). Uniqueness is deferred to
    -- the multi-user milestone, where it arrives together with the ingest_dedup membership path and
    -- an ON CONFLICT branch. For now, ingest looks the hash up first and skips exact duplicates.
    CREATE INDEX IF NOT EXISTS book_files_original_sha256_idx
        ON book_files(original_sha256) WHERE original_sha256 IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("""
    DROP INDEX IF EXISTS book_files_original_sha256_idx;
    ALTER TABLE book_files
        DROP COLUMN IF EXISTS original_md5,
        DROP COLUMN IF EXISTS original_sha256,
        DROP COLUMN IF EXISTS current_sha256,
        DROP COLUMN IF EXISTS anna_md5;
    DROP TABLE IF EXISTS book_pipeline_state;
    """)
