from app.config import settings


def test_managed_project_creation_requires_daemon(client, monkeypatch):
    monkeypatch.setattr(settings, 'app_managed', True)
    client.post('/api/v1/auth/login', json={'login': 'admin', 'password': 'admin-pass-123'})
    response = client.post('/api/v1/projects', json={'name': 'Other'})
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'LOCAL_PANEL_REQUIRED'


def test_delivery_identity():
    from app.services.telegram import sender_identity
    assert sender_identity('ai_report') == '👁 Argus'
    assert sender_identity('ai_recommendation') == '👁 Argus'
    assert sender_identity('task_assigned') == '✉️ Hermes'


def test_existing_managed_admin_gets_initial_project(client, monkeypatch):
    from tests.conftest import TestingSessionLocal
    from app.db.models import BoardColumn, Project
    from app.services.bootstrap import bootstrap
    with TestingSessionLocal() as db:
        db.query(BoardColumn).delete()
        db.query(Project).delete()
        db.commit()
        monkeypatch.setattr(settings, 'app_managed', True)
        bootstrap(db)
        assert db.query(Project).count() == 1
        assert db.query(BoardColumn).count() > 0


def test_split_real_schema_keeps_project_and_passwords(client, tmp_path):
    from pathlib import Path
    import sqlite3
    from tests.conftest import TestingSessionLocal
    from app.db.models import Project, ProjectState
    from control.projects import split_database
    with TestingSessionLocal() as db:
        project = Project(name='Second', state=ProjectState.preparation)
        db.add(project)
        db.commit()
        source = Path(db.get_bind().url.database).resolve()
    target = tmp_path / 'project.db'
    split_database(source, target, 1)
    with sqlite3.connect(target) as db:
        assert db.execute('SELECT count(*) FROM projects').fetchone()[0] == 1
        assert db.execute('SELECT login FROM users').fetchone()[0] == 'admin'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_manager_splits_complete_schema(client, tmp_path, monkeypatch):
    from pathlib import Path
    import sqlite3
    from tests.conftest import TestingSessionLocal
    from app.db.models import Project, ProjectState
    from control.manager import PlatformManager
    monkeypatch.setattr('control.controller.Controller.write_compose', lambda self: None)
    monkeypatch.setattr(PlatformManager, '_stop_current', lambda self: None)
    source = tmp_path / 'legacy'
    source.mkdir()
    with TestingSessionLocal() as db:
        db.add(Project(name='Second', state=ProjectState.preparation))
        db.commit()
        with sqlite3.connect(Path(db.get_bind().url.database)) as original, sqlite3.connect(source / 'hackathon.db') as target:
            original.backup(target)
    manager = PlatformManager(tmp_path / 'hub')
    manager.setup(str(source), 'attach', 'admin')
    identities = manager.split_projects()
    assert len(identities) == 2
    assert len(manager.registry['legacy_sources']) == 1
    for entry in manager.registry['items']:
        with sqlite3.connect(Path(entry['data_dir']) / 'hackathon.db') as db:
            assert db.execute('SELECT count(*) FROM projects').fetchone()[0] == 1
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert (Path(entry['data_dir']) / '.transfer-pending').exists()
