"""Optional project start; existing dates and task history remain intact."""
from alembic import op
import sqlalchemy as sa

revision = '20261028_project_start'
down_revision = '20261028_tracks'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('start_msk', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'start_msk')
