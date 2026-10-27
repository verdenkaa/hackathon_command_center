"""Persist structured sandbox diagnostics without changing existing runs."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '20261027_sandbox_checks'
down_revision = '20261027_project_roles_mock'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('sandbox_runs', sa.Column('checks', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('sandbox_runs', sa.Column('duration_ms', sa.Integer(), nullable=False, server_default='0'))
    # Mark only a legacy workspace associated with an existing sandbox history.
    connection = op.get_bind()
    if connection.execute(sa.text('SELECT count(*) FROM sandbox_runs')).scalar():
        connection.execute(sa.text("UPDATE projects SET settings=json_set(settings, '$.sandbox', json('true')) WHERE id=(SELECT min(id) FROM projects WHERE name='Sandbox')"))


def downgrade() -> None:
    op.drop_column('sandbox_runs', 'duration_ms')
    op.drop_column('sandbox_runs', 'checks')
