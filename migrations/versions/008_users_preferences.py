"""users.preferences JSONB column

8+ call sites across 4 files (routes/auth.py: catalog languages; social.py: public-profile hash/key;
cover_settings.py; routes/reader.py: reading speed) all consistently read/write this column via the
same COALESCE(preferences, '{}'::jsonb) / jsonb_set(...) pattern, but it has never existed in any
migration — every one of those features 500s on a fresh install. Distinct from the properly-migrated
`user_preferences` table (theme, font_size, etc. — fixed for theme in migration-less iteration 1); this
is a second, genuinely-intended flexible-JSONB column that was simply never added, same class of gap as
word_count/rating/page_count in migrations 006-007. Found while redesigning the UI (2026-09-26).

Revision ID: 008
Revises: 007
Create Date: 2026-09-26
"""

from typing import Sequence, Union

from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS preferences JSONB DEFAULT '{}'::jsonb;")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS preferences;")
