"""add missing tables

Revision ID: 002
Revises: 001
Create Date: 2026-04-22
"""

from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS enrichment_log (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        book_id UUID REFERENCES books(id) ON DELETE CASCADE,
        method TEXT NOT NULL,
        success BOOLEAN DEFAULT false,
        details JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS enrichment_log_time_idx ON enrichment_log(created_at);
    CREATE INDEX IF NOT EXISTS enrichment_log_method_idx ON enrichment_log(method);

    CREATE TABLE IF NOT EXISTS book_fingerprints (
        book_id UUID PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
        samples TEXT[] NOT NULL DEFAULT '{}',
        sample_count INTEGER DEFAULT 0,
        total_chars INTEGER DEFAULT 0,
        computed_at TIMESTAMPTZ DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS duplicate_matches (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        book_a_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        book_b_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        overlap_pct REAL NOT NULL,
        matching_samples INTEGER DEFAULT 0,
        total_samples INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending' CHECK (status IN ('pending','confirmed','dismissed','linked')),
        detected_at TIMESTAMPTZ DEFAULT now(),
        UNIQUE (book_a_id, book_b_id)
    );

    -- Add is_workbook column if missing
    DO $$ BEGIN
        ALTER TABLE books ADD COLUMN IF NOT EXISTS is_workbook BOOLEAN DEFAULT false;
    EXCEPTION WHEN duplicate_column THEN NULL;
    END $$;
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS duplicate_matches CASCADE;
    DROP TABLE IF EXISTS book_fingerprints CASCADE;
    DROP TABLE IF EXISTS enrichment_log CASCADE;
    ALTER TABLE books DROP COLUMN IF EXISTS is_workbook;
    """)
