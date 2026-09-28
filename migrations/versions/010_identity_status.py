"""books.identity_status — protect manually-corrected books from automated re-clobbering.

Three states:
- 'auto' (default): normal behavior, background enrichment can freely update any field.
- 'protected': a user manually corrected title/author/isbn. Enrichment may still add data that
  isn't already present (description, cover, tags) but must not overwrite title/author/isbn with
  a conflicting value. Stays visible in review lists until the user marks it 'locked'.
- 'locked': fully finalized by the user — no automated writes to this book at all, ever.

Revision ID: 010
Revises: 009
Create Date: 2026-09-28
"""

from typing import Sequence, Union

from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE books ADD COLUMN IF NOT EXISTS identity_status TEXT NOT NULL DEFAULT 'auto'
        CHECK (identity_status IN ('auto', 'protected', 'locked'));
    CREATE INDEX IF NOT EXISTS books_identity_status_idx ON books (identity_status);
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE books DROP COLUMN IF EXISTS identity_status;")
