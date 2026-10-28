"""Additive advisor storage; preserve legacy mock history and settings."""
from alembic import op
import sqlalchemy as sa

revision = '20261028_advisor'
down_revision = '20261028_project_start'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ai_settings', sa.Column('auto_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('ai_settings', sa.Column('next_run_at', sa.DateTime(), nullable=True))
    for column in [
        sa.Column('structured', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='unreviewed'),
        sa.Column('status_by', sa.Integer(), nullable=True),
        sa.Column('status_at', sa.DateTime(), nullable=True),
        sa.Column('comment', sa.Text(), nullable=False, server_default=''),
        sa.Column('snapshot_at', sa.DateTime(), nullable=True),
        sa.Column('snapshot_version', sa.String(80), nullable=True),
        sa.Column('fingerprint', sa.String(64), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(), nullable=True),
    ]:
        op.add_column('ai_recommendations', column)
    op.create_index('ix_ai_recommendations_fingerprint', 'ai_recommendations', ['fingerprint'])
    from app.db.models import AdvisorProviderSettings, AdvisorJob, AdvisorAttempt
    for table in [AdvisorProviderSettings.__table__, AdvisorJob.__table__, AdvisorAttempt.__table__]:
        table.create(op.get_bind())
    op.execute(sa.text("INSERT INTO advisor_provider_settings (id,model,rpm,rpd,tpm,max_attempts,max_input_tokens,lock_version) VALUES (1,'gemini-3.5-flash-lite',15,500,200000,3,100000,0)"))


def downgrade() -> None:
    for table in ['advisor_attempts', 'advisor_jobs', 'advisor_provider_settings']:
        op.drop_table(table)
    op.drop_index('ix_ai_recommendations_fingerprint', table_name='ai_recommendations')
    for name in ['structured', 'status', 'status_by', 'status_at', 'comment', 'snapshot_at',
                 'snapshot_version', 'fingerprint', 'last_seen_at']:
        op.drop_column('ai_recommendations', name)
    op.drop_column('ai_settings', 'next_run_at')
    op.drop_column('ai_settings', 'auto_enabled')
