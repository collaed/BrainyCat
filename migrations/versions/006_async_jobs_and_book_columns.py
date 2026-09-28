"""async_jobs table + books.word_count/rating columns

Both were referenced by code (brainycat/async_jobs.py; routes/admin.py's stats_dashboard) but never
defined in any migration, so `/api/v1/jobs` and `/api/v1/stats/dashboard` 500'd on every fresh install.
Found while exercising these pages for the first time as part of the UI redesign (2026-09-26).

Revision ID: 006
Revises: 005
Create Date: 2026-09-26
"""

from typing import Sequence, Union

from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS async_jobs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        job_type TEXT NOT NULL,
        remote_job_id TEXT,
        status TEXT NOT NULL DEFAULT 'submitted',
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS async_jobs_book_idx ON async_jobs(book_id);
    CREATE INDEX IF NOT EXISTS async_jobs_status_idx ON async_jobs(status);

    ALTER TABLE books ADD COLUMN IF NOT EXISTS word_count INTEGER;
    ALTER TABLE books ADD COLUMN IF NOT EXISTS rating REAL;
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE books DROP COLUMN IF EXISTS rating;
    ALTER TABLE books DROP COLUMN IF EXISTS word_count;
    DROP TABLE IF EXISTS async_jobs CASCADE;
    """)
