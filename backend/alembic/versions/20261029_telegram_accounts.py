"""Durable Telegram outbox; preserve historical previews and user references."""
from alembic import op
import sqlalchemy as sa

revision = '20261029_telegram_accounts'
down_revision = '20261028_advisor'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('deleted_identity', sa.Boolean(), nullable=False, server_default=sa.false()))
    from app.db.models import TelegramSettings
    TelegramSettings.__table__.create(op.get_bind())
    for column in [
        sa.Column('chat_id', sa.String(32)), sa.Column('thread_id', sa.Integer()),
        sa.Column('state', sa.String(16), nullable=False, server_default='preview'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_attempt_at', sa.DateTime(), nullable=False, server_default='1970-01-01 00:00:00'),
        sa.Column('attempted_at', sa.DateTime()), sa.Column('sent_at', sa.DateTime()),
        sa.Column('lease_token', sa.String(40)), sa.Column('lease_until', sa.DateTime()),
        sa.Column('error_code', sa.String(40)),
        sa.Column('message_ids', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('event_key', sa.String(100)),
    ]:
        op.add_column('telegram_deliveries', column)
    op.create_index('ix_telegram_deliveries_state', 'telegram_deliveries', ['state'])
    op.create_index('uq_telegram_event_key', 'telegram_deliveries', ['event_key'], unique=True)


def downgrade() -> None:
    op.drop_index('uq_telegram_event_key', table_name='telegram_deliveries')
    op.drop_index('ix_telegram_deliveries_state', table_name='telegram_deliveries')
    with op.batch_alter_table('telegram_deliveries') as batch:
        for name in ['event_key','message_ids','error_code','lease_until','lease_token','sent_at',
                     'attempted_at','next_attempt_at','attempts','state','thread_id','chat_id']:
            batch.drop_column(name)
    op.drop_table('telegram_settings')
    with op.batch_alter_table('users') as batch:
        batch.drop_column('deleted_identity')
