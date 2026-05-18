"""metadata operations log with validation workflow

Revision ID: 004
Revises: 003
Create Date: 2026-05-18
"""

from typing import Sequence, Union

from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS metadata_history (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        field TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT,
        source TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'validated', 'flagged')),
        flag_reason TEXT,
        created_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS metadata_history_book_idx ON metadata_history(book_id);
    CREATE INDEX IF NOT EXISTS metadata_history_status_idx ON metadata_history(status);
    CREATE INDEX IF NOT EXISTS metadata_history_created_idx ON metadata_history(created_at DESC);

    CREATE TABLE IF NOT EXISTS bug_candidates (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        book_id UUID REFERENCES books(id) ON DELETE SET NULL,
        history_ids UUID[] NOT NULL DEFAULT '{}',
        description TEXT NOT NULL,
        operations JSONB NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'reviewed', 'fixed', 'wontfix')),
        created_at TIMESTAMPTZ DEFAULT now()
    );
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS bug_candidates CASCADE;
    DROP TABLE IF EXISTS metadata_history CASCADE;
    """)
