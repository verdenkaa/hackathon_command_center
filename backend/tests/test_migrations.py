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
        db.add(User(login='legacy', display_name='Legacy', password_hash='unused'))
        db.add_all([Project(name='A'), Project(name='B')])
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
