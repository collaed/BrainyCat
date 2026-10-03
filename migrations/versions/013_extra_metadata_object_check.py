"""Clean up degraded extra_metadata and enforce it is always a JSON object (K3 / M1 corruption class)

Known issue (docs/known-issues.md): `books.extra_metadata` sometimes degrades from a JSON object into
a JSON array (Postgres `jsonb || jsonb` coerces to array concatenation when either side isn't an
object). Once that happens, `extra_metadata ? 'flag'` tests array-element membership, never matches an
object key, so the "already processed" guard fails open and background loops reprocess and re-append
to that row forever (one book had ~80 duplicate `{"title_parsed": true}` entries).

Fix: (1) reset every non-object row to '{}' (the array elements were duplicated processing flags with
no recoverable value); (2) add a guarded CHECK so the whole class becomes impossible going forward.
The CHECK is added only if absent (Postgres has no ADD CONSTRAINT IF NOT EXISTS) and validated
immediately (after step 1 there are no violating rows).

Revision ID: 013
Revises: 012
Create Date: 2026-09-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
    -- 1) Repair already-corrupted rows (arrays / non-objects) — flags were duplicated, nothing to keep.
    UPDATE books SET extra_metadata = '{}'::jsonb
    WHERE extra_metadata IS NOT NULL AND jsonb_typeof(extra_metadata) <> 'object';

    -- 2) Make the corruption class impossible. Guarded because ADD CONSTRAINT isn't idempotent.
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'extra_metadata_is_object'
        ) THEN
            ALTER TABLE books
                ADD CONSTRAINT extra_metadata_is_object
                CHECK (extra_metadata IS NULL OR jsonb_typeof(extra_metadata) = 'object');
        END IF;
    END $$;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE books DROP CONSTRAINT IF EXISTS extra_metadata_is_object;")
