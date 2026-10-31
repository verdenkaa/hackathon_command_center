from unittest.mock import Mock

import pytest

from control.archives import ArchiveError
from control.manager import PlatformManager


@pytest.fixture
def projects(tmp_path, monkeypatch):
    monkeypatch.setattr('control.controller.Controller.write_compose', lambda self: None)
    monkeypatch.setattr('control.controller.Controller.discard_runtime', lambda self: None)
    monkeypatch.setattr('control.docker.Docker.compose', lambda self, *args, **kwargs: b'')
    monkeypatch.setattr(PlatformManager, '_stop_current', lambda self: None)
    manager = PlatformManager(tmp_path / 'hub')
    first = manager.create(str(tmp_path / 'one'), 'One', 'admin')
    second = manager.create(str(tmp_path / 'two'), 'Two', 'admin')
    manager.current.execute = Mock()
    return manager, first, second


def test_delete_requires_exact_name_and_idle_state(projects):
    manager, _, second = projects
    with pytest.raises(ArchiveError):
        manager.delete(second, 'wrong', delete_data=True)
    manager.current.busy = 'backup'
    with pytest.raises(ArchiveError):
        manager.delete(second, 'Two', delete_data=True)
    assert len(manager.registry['items']) == 2


def test_forget_keeps_files_and_does_not_start_fallback(projects):
    manager, first, second = projects
    data = manager.current.config['data_dir']
    manager.delete(second, 'Two', delete_data=False)
    from pathlib import Path
    assert Path(data).exists()
    assert manager.registry['main'] == first
    assert manager.current.config['desired'] is False


def test_delete_last_project_can_restart_empty_manager(projects):
    manager, first, second = projects
    from pathlib import Path
    data = Path(manager.current.config['data_dir'])
    (data / 'keep.db').write_text('test')
    manager.delete(second, 'Two', delete_data=True)
    assert not data.exists()
    manager.current.execute = Mock()
    manager.delete(first, 'One', delete_data=True)
    restored = PlatformManager(manager.root)
    assert restored.registry['items'] == []
    assert not restored.current.config['configured']


def test_delete_rejects_source_or_shared_data(projects):
    manager, first, second = projects
    manager.current.config['data_dir'] = str(manager.root)
    manager.registry['items'][1]['data_dir'] = str(manager.root)
    with pytest.raises(ArchiveError):
        manager.delete(second, 'Two', delete_data=True)
    assert manager.root.exists()


def test_delete_rejects_legacy_source_overlap(projects):
    manager, _, second = projects
    manager.registry['legacy_sources'] = [dict(manager.registry['items'][1])]
    with pytest.raises(ArchiveError):
        manager.delete(second, 'Two', delete_data=True)


def test_deleting_inactive_project_keeps_current_selection(projects, monkeypatch):
    manager, first, second = projects
    monkeypatch.setattr('control.controller.Controller.execute', lambda self, action: None)
    manager.delete(first, 'One', delete_data=True)
    assert manager.current.config['id'] == second
    manager.current.execute.assert_not_called()


def test_new_project_folder_ignores_runtime_with_arbitrary_name(projects):
    manager, _, _ = projects
    from pathlib import Path
    assert (Path(manager.config['data_dir']) / '.gitignore').read_text().strip() == '*'
