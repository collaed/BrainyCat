"""app_settings — global (not per-user) key/value config

First use: an "auth_required" toggle so login can be made optional for a trusted home network,
requested directly rather than hardcoded into an env var (so it's changeable live from Settings without
a redeploy). Seeded `true` (secure default for any fresh install) — flipping it off is a deliberate,
explicit action taken via the Settings UI/API after this migration runs, not baked into the migration.

Revision ID: 009
Revises: 008
Create Date: 2026-09-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value JSONB NOT NULL,
        updated_at TIMESTAMPTZ DEFAULT now()
    );
    INSERT INTO app_settings (key, value) VALUES ('auth_required', 'true'::jsonb)
    ON CONFLICT (key) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app_settings CASCADE;")
