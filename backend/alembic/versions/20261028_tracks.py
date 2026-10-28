"""Unify planning lanes with modules (tracks), preserving task module semantics."""
from datetime import datetime, timedelta, timezone

from alembic import op
import sqlalchemy as sa

revision = '20261028_tracks'
down_revision = '20261028_planning'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('modules', sa.Column('position', sa.Integer(), nullable=False, server_default='0'))
    db = op.get_bind()
    mapping: dict[int, int] = {}
    for lane in db.execute(sa.text('SELECT id,project_id,name,position FROM planning_lanes ORDER BY position,id')).mappings():
        module_id = db.execute(sa.text('SELECT id FROM modules WHERE project_id=:p AND name=:n ORDER BY id LIMIT 1'),
                               {'p':lane['project_id'],'n':lane['name']}).scalar()
        if module_id is None:
            module_id = db.execute(sa.text("INSERT INTO modules(project_id,name,traffic_status,created_at,position) VALUES(:p,:n,'green',CURRENT_TIMESTAMP,:pos) RETURNING id"),
                                   {'p':lane['project_id'],'n':lane['name'],'pos':lane['position']}).scalar_one()
        mapping[lane['id']] = module_id
    op.create_table('track_placements',sa.Column('task_id',sa.Integer(),sa.ForeignKey('tasks.id'),primary_key=True),
                    sa.Column('lane_id',sa.Integer(),sa.ForeignKey('modules.id'),nullable=True),
                    sa.Column('start',sa.DateTime(),nullable=False),sa.Column('pinned',sa.Boolean(),nullable=False))
    for p in db.execute(sa.text('SELECT p.*,t.module_id FROM task_placements p JOIN tasks t ON t.id=p.task_id')).mappings():
        track = p['module_id'] or mapping.get(p['lane_id'])
        db.execute(sa.text('INSERT INTO track_placements VALUES(:t,:l,:s,:p)'),{'t':p['task_id'],'l':track,'s':p['start'],'p':p['pinned']})
        db.execute(sa.text('UPDATE tasks SET module_id=:l WHERE id=:t'),{'l':track,'t':p['task_id']})
    current=datetime.now(timezone.utc).replace(tzinfo=None)
    start=current.replace(minute=current.minute//15*15,second=0,microsecond=0)+timedelta(minutes=15)
    db.execute(sa.text("UPDATE tasks SET estimate_seconds=3600 WHERE module_id IS NOT NULL AND (estimate_seconds IS NULL OR estimate_seconds<=0)"))
    db.execute(sa.text('INSERT INTO track_placements SELECT id,module_id,:s,0 FROM tasks WHERE module_id IS NOT NULL AND id NOT IN (SELECT task_id FROM track_placements)'),{'s':start})
    db.execute(sa.text("UPDATE tasks SET deadline=(SELECT datetime(p.start,'+' || tasks.estimate_seconds || ' seconds') FROM track_placements p WHERE p.task_id=tasks.id) WHERE id IN (SELECT task_id FROM track_placements WHERE lane_id IS NOT NULL)"))
    op.drop_table('task_placements')
    op.rename_table('track_placements','task_placements')


def downgrade() -> None:
    raise RuntimeError('Track consolidation cannot be reversed without a backup')
