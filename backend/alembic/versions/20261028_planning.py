"""Additive planning storage; shared task data and timer history stay in place."""
from alembic import op
import sqlalchemy as sa
import json

revision = '20261028_planning'
down_revision = '20261028_manual_fixes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('actual_started_at', sa.DateTime(), nullable=True))
    op.add_column('tasks', sa.Column('actual_completed_at', sa.DateTime(), nullable=True))
    op.create_table('planning_states', sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), primary_key=True), sa.Column('revision', sa.Integer(), nullable=False, server_default='0'))
    op.create_table('planning_lanes', sa.Column('id', sa.Integer(), primary_key=True), sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False), sa.Column('name', sa.String(120), nullable=False), sa.Column('position', sa.Integer(), nullable=False))
    op.create_index('ix_planning_lanes_project_id', 'planning_lanes', ['project_id'])
    op.create_table('task_placements', sa.Column('task_id', sa.Integer(), sa.ForeignKey('tasks.id'), primary_key=True), sa.Column('lane_id', sa.Integer(), sa.ForeignKey('planning_lanes.id'), nullable=True), sa.Column('start', sa.DateTime(), nullable=False), sa.Column('pinned', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('planning_baselines', sa.Column('id', sa.Integer(), primary_key=True), sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False), sa.Column('snapshot', sa.JSON(), nullable=False))
    op.create_index('ix_planning_baselines_project_id', 'planning_baselines', ['project_id'])
    db = op.get_bind()
    db.execute(sa.text('INSERT INTO planning_states (project_id,revision) SELECT id,0 FROM projects'))
    # Backfill only facts supported by retained evidence; never invent completion times.
    db.execute(sa.text('UPDATE tasks SET actual_started_at=(SELECT MIN(started_at) FROM timer_segments WHERE task_id=tasks.id)'))
    for task_id, data, created in db.execute(sa.text("SELECT entity_id,data,created_at FROM audit_entries WHERE entity_type='task' AND action='task.moved' ORDER BY created_at,id")).all():
        payload = json.loads(data) if isinstance(data, str) else data
        if not payload:
            continue
        semantic = payload.get('to_semantic')
        if semantic == 'done' or payload.get('key') in ('done', 'realised'):
            db.execute(sa.text('UPDATE tasks SET actual_completed_at=:at WHERE id=:id'), {'at': created, 'id': task_id})
        elif semantic != 'trash' and payload.get('key') != 'trashed':
            db.execute(sa.text('UPDATE tasks SET actual_completed_at=NULL WHERE id=:id'), {'id': task_id})


def downgrade() -> None:
    for table in ('planning_baselines', 'task_placements', 'planning_lanes', 'planning_states'):
        op.drop_table(table)
    op.drop_column('tasks', 'actual_completed_at')
    op.drop_column('tasks', 'actual_started_at')
