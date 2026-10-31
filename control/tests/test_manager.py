import json
from unittest.mock import Mock

import pytest

from control.archives import ArchiveError
from control.manager import PlatformManager


def test_existing_installation_is_registered_without_moving_data(tmp_path):
    folder = tmp_path / '.control'
    folder.mkdir()
    config = {'id': 'abc123', 'configured': True, 'desired': False, 'data_dir': str(tmp_path / 'data'),
              'login': 'original', 'distro': 'Ubuntu-24.04'}
    (folder / 'config.json').write_text(json.dumps(config))
    manager = PlatformManager(tmp_path)
    assert manager.installations()['items'][0]['id'] == 'abc123'
    assert manager.config['login'] == 'original'
    assert manager.folder == folder


def test_new_installation_requires_empty_unshared_folder(tmp_path):
    manager = PlatformManager(tmp_path)
    dirty = tmp_path / 'dirty'
    dirty.mkdir()
    (dirty / 'keep.txt').write_text('keep')
    with pytest.raises(ArchiveError, match='пуст'):
        manager.create(str(dirty), 'New', 'operator')
    assert (dirty / 'keep.txt').read_text() == 'keep'


def test_switch_stops_previous_and_keeps_independent_settings(tmp_path, monkeypatch):
    manager = PlatformManager(tmp_path)
    monkeypatch.setattr('control.controller.Controller.write_compose', lambda self: None)
    first = manager.create(str(tmp_path / 'first'), 'First', 'first_admin')
    old = manager.current
    old.execute = Mock()
    old.docker.close = Mock()
    second = manager.create(str(tmp_path / 'second'), 'Second', 'second_admin')
    old.execute.assert_called_once_with('stop')
    assert first != second
    manager.current.execute = Mock()
    manager.select(first, start=False)
    assert manager.config['login'] == 'first_admin'
    assert manager.installations()['main'] == first
    assert len(manager.installations()['items']) == 2


def test_duplicate_or_nested_data_folder_is_rejected(tmp_path, monkeypatch):
    manager = PlatformManager(tmp_path)
    monkeypatch.setattr('control.controller.Controller.write_compose', lambda self: None)
    manager.create(str(tmp_path / 'one'), 'One', 'admin')
    with pytest.raises(ArchiveError):
        manager.create(str(tmp_path / 'one' / 'nested'), 'Bad', 'admin')


def test_switch_rejected_while_operation_reserved(tmp_path):
    manager = PlatformManager(tmp_path)
    manager.current.busy = 'backup'
    with pytest.raises(ArchiveError, match='операц'):
        manager.select('missing', start=False)


def test_monitoring_does_not_wait_for_running_maintenance(tmp_path):
    import threading
    manager = PlatformManager(tmp_path)
    ready = threading.Event()
    release = threading.Event()
    def maintenance():
        with manager.gate:
            ready.set()
            release.wait(3)
    thread=threading.Thread(target=maintenance)
    thread.start()
    assert ready.wait(1)
    try:
        assert manager.view()['installations']['active'] == manager.config['id']
        assert thread.is_alive()
    finally:
        release.set()
        thread.join()
