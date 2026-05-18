"""content index + consumption rules

Revision ID: 005
Revises: 004
Create Date: 2026-05-18
"""

from typing import Sequence, Union

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS content_index (
        book_id UUID PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
        content TEXT NOT NULL DEFAULT '',
        search_vector tsvector,
        updated_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS content_index_search_idx ON content_index USING gin(search_vector);

    CREATE TABLE IF NOT EXISTS consumption_rules (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name TEXT NOT NULL,
        pattern TEXT NOT NULL,
        match_field TEXT NOT NULL DEFAULT 'filename' CHECK (match_field IN ('filename', 'title', 'author', 'path')),
        action TEXT NOT NULL CHECK (action IN ('tag', 'set_publisher', 'set_language', 'set_genre', 'skip')),
        action_value TEXT NOT NULL,
        priority INTEGER DEFAULT 0,
        enabled BOOLEAN DEFAULT true,
        created_at TIMESTAMPTZ DEFAULT now()
    );
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS consumption_rules CASCADE;
    DROP TABLE IF EXISTS content_index CASCADE;
    """)
