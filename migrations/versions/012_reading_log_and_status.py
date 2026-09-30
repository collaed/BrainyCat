"""reading_log table + reading_progress status columns (M2 — P0 bug fix)

The status/streak/reading-log routes already exist in brainycat/routes/reader.py and
brainycat/experimental/book_dna.py but 500 today because no migration ever created what they read/write.
This migration ships EXACTLY the shape the code already uses (verified against main):
  - status value 'library' (routes/reader.py set_book_status default + valid set) — NOT 'library_only'
  - reading_log columns `minutes` + `logged_at` (reader.py POST /reading/log; book_dna.py) — NOT minutes_read/date
  - reading_log.book_id NULLable ("read 30 pages on paper" with no book), multiple sessions/day → no UNIQUE

Revision ID: 012
Revises: 011
Create Date: 2026-09-30
"""

from typing import Sequence, Union

from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE reading_progress
        ADD COLUMN IF NOT EXISTS status       TEXT DEFAULT 'library'
            CHECK (status IN ('want_to_read','reading','finished','abandoned','library')),
        ADD COLUMN IF NOT EXISTS started_at   TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS finished_at  TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS abandoned_at TIMESTAMPTZ;

    CREATE TABLE IF NOT EXISTS reading_log (
        id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        book_id    UUID REFERENCES books(id) ON DELETE CASCADE,   -- NULLable on purpose
        minutes    INT,
        pages_read INT,
        logged_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS reading_log_user_time_idx ON reading_log (user_id, logged_at);
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS reading_log;
    ALTER TABLE reading_progress
        DROP COLUMN IF EXISTS status,
        DROP COLUMN IF EXISTS started_at,
        DROP COLUMN IF EXISTS finished_at,
        DROP COLUMN IF EXISTS abandoned_at;
    """)
