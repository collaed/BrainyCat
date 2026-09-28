"""Translation linking — books.translation_of_book_id (self-referential, when the original is also
in the library) and books.wikidata_qid (cache of the resolved Wikidata entity, and the anchor for
finding sibling translations even when the original itself isn't in the library).

Revision ID: 011
Revises: 010
Create Date: 2026-09-28
"""

from typing import Sequence, Union

from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE books ADD COLUMN IF NOT EXISTS translation_of_book_id UUID REFERENCES books(id) ON DELETE SET NULL;
    ALTER TABLE books ADD COLUMN IF NOT EXISTS wikidata_qid TEXT;
    CREATE INDEX IF NOT EXISTS books_translation_of_idx ON books (translation_of_book_id);
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE books DROP COLUMN IF EXISTS translation_of_book_id;
    ALTER TABLE books DROP COLUMN IF EXISTS wikidata_qid;
    """)
