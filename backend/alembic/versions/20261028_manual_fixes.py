"""Project column semantics and durable, independent incident numbering."""
from alembic import op
import sqlalchemy as sa

revision = '20261028_manual_fixes'
down_revision = '20261027_sandbox_checks'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('incident_counter', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('board_columns', sa.Column('semantic', sa.String(16), nullable=False, server_default='normal'))
    op.add_column('incidents', sa.Column('number', sa.Integer(), nullable=True))
    db = op.get_bind()
    db.execute(sa.text("UPDATE board_columns SET semantic=CASE WHEN key IN ('done','realised') THEN 'done' WHEN key='trashed' THEN 'trash' WHEN key IN ('in_progress','testing','review') THEN 'active' ELSE 'normal' END"))
    # All retained records, including resolved incidents, keep their internal IDs.
    rows = db.execute(sa.text('SELECT id,project_id FROM incidents ORDER BY created_at,id')).all()
    counters: dict[int, int] = {}
    for incident_id, project_id in rows:
        counters[project_id] = counters.get(project_id, 0) + 1
        db.execute(sa.text('UPDATE incidents SET number=:number WHERE id=:id'), {'number':counters[project_id], 'id':incident_id})
    for project_id, number in counters.items():
        db.execute(sa.text('UPDATE projects SET incident_counter=:number WHERE id=:id'), {'number':number, 'id':project_id})
    with op.batch_alter_table('incidents') as batch:
        batch.alter_column('number', existing_type=sa.Integer(), nullable=False)
        batch.create_unique_constraint('uq_incident_project_number', ['project_id', 'number'])


def downgrade() -> None:
    with op.batch_alter_table('incidents') as batch:
        batch.drop_constraint('uq_incident_project_number', type_='unique')
        batch.drop_column('number')
    op.drop_column('board_columns', 'semantic')
    op.drop_column('projects', 'incident_counter')
