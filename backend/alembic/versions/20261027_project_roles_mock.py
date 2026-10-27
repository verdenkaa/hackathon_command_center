"""Project roles and inspectable integration mocks."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '20261027_project_roles_mock'
down_revision = '38bb310f4d87'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ai_recommendations', sa.Column('request_context', sa.JSON(), nullable=True))
    op.create_table('telegram_deliveries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=True),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('mentions', sa.JSON(), nullable=False),
        sa.Column('mode', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_telegram_deliveries_project_id', 'telegram_deliveries', ['project_id'])
    # Preserve old access to current projects, without granting access to future projects.
    connection = op.get_bind()
    connection.execute(sa.text("""
        INSERT INTO role_assignments (user_id, role, project_id, granted_by, granted_at)
        SELECT r.user_id, r.role, p.id, r.granted_by, r.granted_at
        FROM role_assignments r CROSS JOIN projects p
        WHERE r.project_id IS NULL AND r.role != 'admin' AND r.revoked_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM role_assignments scoped
            WHERE scoped.user_id=r.user_id AND scoped.role=r.role
              AND scoped.project_id=p.id AND scoped.revoked_at IS NULL)
        GROUP BY r.user_id, r.role, p.id
        ON CONFLICT (user_id, project_id, role) DO UPDATE SET revoked_at=NULL
    """))
    connection.execute(sa.text("""UPDATE role_assignments SET revoked_at=CURRENT_TIMESTAMP
        WHERE project_id IS NULL AND role != 'admin' AND revoked_at IS NULL"""))


def downgrade() -> None:
    # Keep scoped assignments: restoring global privileges would broaden access.
    op.drop_table('telegram_deliveries')
    op.drop_column('ai_recommendations', 'request_context')
