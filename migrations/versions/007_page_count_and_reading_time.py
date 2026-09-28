"""books.page_count + books.estimated_reading_minutes

Both are written by books.py's own count-pages endpoint and read by opds.py, routes/reader.py and
routes/books.py, but neither has ever existed in any migration — 10+ files reference page_count alone.
Found while fixing the taste-engine recommendation endpoints (2026-09-26).

Revision ID: 007
Revises: 006
Create Date: 2026-09-26
"""

from typing import Sequence, Union

from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE books ADD COLUMN IF NOT EXISTS page_count INTEGER;
    ALTER TABLE books ADD COLUMN IF NOT EXISTS estimated_reading_minutes INTEGER;
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE books DROP COLUMN IF EXISTS estimated_reading_minutes;
    ALTER TABLE books DROP COLUMN IF EXISTS page_count;
    """)
