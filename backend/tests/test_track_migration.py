"""Legacy task modules win over conflicting lane assignments."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_track_migration_preserves_start_and_prefers_module():
    path=Path(__file__).resolve().parents[1]/'alembic/versions/20261028_tracks.py'
    spec=importlib.util.spec_from_file_location('tracks',path)
    migration=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine=create_engine('sqlite://')
    with engine.begin() as db:
        for sql in [
            'CREATE TABLE projects(id INTEGER PRIMARY KEY)',
            'CREATE TABLE modules(id INTEGER PRIMARY KEY,project_id INTEGER,name TEXT,traffic_status TEXT,created_at DATETIME)',
            'CREATE TABLE tasks(id INTEGER PRIMARY KEY,module_id INTEGER,estimate_seconds INTEGER,deadline DATETIME)',
            'CREATE TABLE planning_lanes(id INTEGER PRIMARY KEY,project_id INTEGER,name TEXT,position INTEGER)',
            'CREATE TABLE task_placements(task_id INTEGER PRIMARY KEY,lane_id INTEGER,start DATETIME,pinned BOOLEAN)',
            'INSERT INTO projects VALUES(1)',
            "INSERT INTO modules VALUES(3,1,'Semantic track','green',CURRENT_TIMESTAMP)",
            "INSERT INTO planning_lanes VALUES(7,1,'Other lane',0)",
            'INSERT INTO tasks VALUES(1,3,3600,NULL),(2,3,NULL,NULL),(3,NULL,1800,NULL)',
            "INSERT INTO task_placements VALUES(1,7,'2026-10-28 08:00:00',0),(3,7,'2026-10-28 10:00:00',1)",
        ]:
            db.execute(text(sql))
        with Operations.context(MigrationContext.configure(db)):
            migration.upgrade()
        assert db.execute(text('SELECT lane_id,start FROM task_placements WHERE task_id=1')).one()==(3,'2026-10-28 08:00:00')
        assert db.execute(text('SELECT module_id,estimate_seconds FROM tasks WHERE id=2')).one()==(3,3600)
        assert db.execute(text('SELECT deadline FROM tasks WHERE id=1')).scalar_one()=='2026-10-28 09:00:00'
        assert db.execute(text('SELECT lane_id FROM task_placements WHERE task_id=3')).scalar_one()!=3
        assert not db.execute(text('PRAGMA foreign_key_check')).all()
    engine.dispose()
