"""Регрессия обновления заполненной базы без потери данных."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_column_timer_rules_preserve_existing_columns() -> None:
    path = Path(__file__).resolve().parents[1] / "alembic/versions/38bb310f4d87_column_timer_rules.py"
    spec = importlib.util.spec_from_file_location("column_timer_rules", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE board_columns (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO board_columns VALUES (1, 'Existing column')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        row = connection.execute(text("SELECT name, auto_start_timer, auto_stop_timer FROM board_columns")).one()
        assert tuple(row) == ("Existing column", 0, 0)
        connection.execute(text("INSERT INTO board_columns (id, name) VALUES (2, 'New column')"))
        assert connection.execute(text("SELECT auto_start_timer FROM board_columns WHERE id=2")).scalar_one() == 0
    engine.dispose()


def test_planning_upgrade_keeps_shared_data_and_backfills_only_evidence(tmp_path, monkeypatch) -> None:
    from alembic import command
    from alembic.config import Config
    from app.config import settings
    backend = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{(tmp_path / 'planning-upgrade.db').as_posix()}"
    monkeypatch.setattr(settings, 'database_url', url)
    cfg = Config(str(backend / 'alembic.ini'))
    cfg.set_main_option('script_location', str(backend / 'alembic'))
    command.upgrade(cfg, '20261028_manual_fixes')
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO projects (id,name,state,settings,created_at,incident_counter) VALUES (1,'Keep','active','{}',CURRENT_TIMESTAMP,0)"))
        db.execute(text("INSERT INTO board_columns (id,project_id,key,title,position,auto_start_timer,auto_stop_timer,semantic) VALUES (1,1,'done','Done',1,0,0,'done')"))
        db.execute(text("INSERT INTO tasks (id,project_id,column_id,title,priority,estimate_seconds,tags,version,created_at,updated_at) VALUES (1,1,1,'Keep A','medium',7200,'[]',7,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),(2,1,1,'Keep B','high',NULL,'[]',3,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        db.execute(text("INSERT INTO task_dependencies (task_id,predecessor_id,link_type) VALUES (2,1,'after')"))
        db.execute(text("INSERT INTO task_timers (task_id,state,accumulated_seconds,created_at,updated_at) VALUES (1,'stopped',1234,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        db.execute(text("INSERT INTO timer_segments (task_id,started_at,ended_at) VALUES (1,'2026-10-28 08:00:00','2026-10-28 09:00:00')"))
        db.execute(text("INSERT INTO audit_entries (project_id,action,entity_type,entity_id,data,created_at) VALUES (1,'task.moved','task','1','{\"to_semantic\":\"done\"}','2026-10-28 10:00:00')"))
    command.upgrade(cfg, 'head')
    with engine.connect() as db:
        assert db.execute(text('SELECT estimate_seconds,version FROM tasks ORDER BY id')).all() == [(7200,7),(None,3)]
        assert db.execute(text('SELECT accumulated_seconds FROM task_timers')).scalar_one() == 1234
        assert db.execute(text('SELECT count(*) FROM task_dependencies')).scalar_one() == 1
        assert db.execute(text('SELECT count(*) FROM task_placements')).scalar_one() == 0
        assert db.execute(text('SELECT name,start_msk FROM projects')).one() == ('Keep', None)
        assert db.execute(text('SELECT actual_completed_at FROM tasks WHERE id=1')).scalar_one().startswith('2026-10-28 10:00:00')
        assert db.execute(text('SELECT actual_completed_at FROM tasks WHERE id=2')).scalar_one() is None
        assert not db.execute(text('PRAGMA foreign_key_check')).all()
    engine.dispose()


def test_upgrade_preserves_legacy_access_and_adds_mock_storage(tmp_path, monkeypatch) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.orm import Session
    from app.config import settings
    from app.db.models import Project, RoleAssignment, User

    backend = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{(tmp_path / 'upgrade.db').as_posix()}"
    monkeypatch.setattr(settings, 'database_url', url)
    cfg = Config(str(backend / 'alembic.ini'))
    cfg.set_main_option('script_location', str(backend / 'alembic'))
    command.upgrade(cfg, '38bb310f4d87')
    engine = create_engine(url)
    with Session(engine) as db:
        db.execute(text("INSERT INTO users (login,display_name,password_hash,active,created_at) VALUES ('legacy','Legacy','unused',1,CURRENT_TIMESTAMP)"))
        # Insert using the old schema: the current ORM has new columns.
        db.execute(text("INSERT INTO projects (name,state,settings,created_at) VALUES ('A','preparation','{}',CURRENT_TIMESTAMP),('B','preparation','{}',CURRENT_TIMESTAMP)"))
        db.flush()
        db.add(RoleAssignment(user_id=1, role='participant', project_id=None))
        db.commit()
    command.upgrade(cfg, 'head')
    with engine.connect() as connection:
        active = connection.execute(text("SELECT project_id FROM role_assignments WHERE revoked_at IS NULL ORDER BY project_id")).scalars().all()
        assert active == [1, 2]
        assert connection.execute(text("SELECT count(*) FROM telegram_deliveries")).scalar_one() == 0
        assert 'request_context' in {r[1] for r in connection.execute(text('PRAGMA table_info(ai_recommendations)'))}
    engine.dispose()


def test_incident_numbers_backfill_retains_links(tmp_path, monkeypatch) -> None:
    from alembic import command
    from alembic.config import Config
    from app.config import settings
    backend = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{(tmp_path / 'number-upgrade.db').as_posix()}"
    monkeypatch.setattr(settings, 'database_url', url)
    cfg = Config(str(backend / 'alembic.ini'))
    cfg.set_main_option('script_location', str(backend / 'alembic'))
    command.upgrade(cfg, '20261027_sandbox_checks')
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO users (id,login,password_hash,display_name,active,created_at) VALUES (1,'u','unused','User',1,CURRENT_TIMESTAMP)"))
        db.execute(text("INSERT INTO projects (id,name,state,settings,created_at) VALUES (1,'A','active','{}',CURRENT_TIMESTAMP),(2,'B','active','{}',CURRENT_TIMESTAMP)"))
        db.execute(text("INSERT INTO incidents (id,project_id,level,status,title,author_id,created_at) VALUES (8,1,'red','resolved','Old',1,'2026-10-26'),(12,2,'yellow','open','Other',1,'2026-10-27'),(15,1,'yellow','open','New',1,'2026-10-27')"))
        db.execute(text("INSERT INTO incident_targets (incident_id,target_type,target_id) VALUES (8,'user',1)"))
    command.upgrade(cfg, 'head')
    with engine.connect() as db:
        assert db.execute(text('SELECT id,number FROM incidents ORDER BY id')).all() == [(8,1),(12,1),(15,2)]
        assert db.execute(text('SELECT incident_counter FROM projects ORDER BY id')).scalars().all() == [2,1]
        assert db.execute(text('SELECT incident_id FROM incident_targets')).scalar_one() == 8
        assert not db.execute(text('PRAGMA foreign_key_check')).all()
    engine.dispose()


def test_sandbox_upgrade_preserves_old_runs_and_marks_legacy_workspace(tmp_path, monkeypatch) -> None:
    from alembic import command
    from alembic.config import Config
    from app.config import settings

    backend = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{(tmp_path / 'sandbox-upgrade.db').as_posix()}"
    monkeypatch.setattr(settings, 'database_url', url)
    cfg = Config(str(backend / 'alembic.ini'))
    cfg.set_main_option('script_location', str(backend / 'alembic'))
    command.upgrade(cfg, '20261027_project_roles_mock')
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO projects (name,state,settings,created_at) VALUES ('Sandbox','active','{}',CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO sandbox_runs (scenario,status,logs,created_at) VALUES ('create_team','ok','[]',CURRENT_TIMESTAMP)"))
    command.upgrade(cfg, 'head')
    with engine.connect() as connection:
        assert connection.execute(text('SELECT checks,duration_ms FROM sandbox_runs')).one() == ('[]', 0)
        assert connection.execute(text("SELECT json_extract(settings,'$.sandbox') FROM projects")).scalar_one() == 1
    engine.dispose()
