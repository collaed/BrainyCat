"""filename history — track before/after for every rename operation

Revision ID: 003
Revises: 002
Create Date: 2026-05-17
"""

from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE filename_history (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        operation TEXT NOT NULL,
        filename_before TEXT NOT NULL,
        filename_after TEXT NOT NULL,
        alignment_pct REAL NOT NULL DEFAULT 0,
        reverted BOOLEAN DEFAULT false,
        created_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX filename_history_book_idx ON filename_history(book_id);
    CREATE INDEX filename_history_alignment_idx ON filename_history(alignment_pct);
    CREATE INDEX filename_history_created_idx ON filename_history(created_at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS filename_history CASCADE")
