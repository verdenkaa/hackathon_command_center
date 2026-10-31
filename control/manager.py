"""One host, isolated installation state, and one selected platform at a time."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from control.archives import ArchiveError
from control.controller import Controller
from control.vault import atomic_write


class PlatformManager:
    # The server's existing maintenance routes delegate to the selected controller.
    _owned = {'root', 'registry_file', 'registry', 'current', 'gate', 'stop_event'}

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.registry_file = self.root / '.control' / 'installations.json'
        self.gate = threading.RLock()
        self.stop_event = threading.Event()
        if self.registry_file.exists():
            self.registry = json.loads(self.registry_file.read_text())
            entry = next((row for row in self.registry['items'] if row['id'] == self.registry['main']), None)
            self.current = Controller(Path(entry['root']) if entry else self.root / '.control' / 'empty')
        else:
            self.current = Controller(self.root)
            self.registry = {'main': self.current.config['id'], 'items': []}
            if self.current.config['configured']:
                self._register(self.current, 'Основная платформа')
        self.current.config.setdefault('telegram_alert_chat', '')
        self.registry.setdefault('host_id', self.current.config['id'])
        selected = next((row for row in self.registry['items'] if row['id'] == self.current.config['id']), None)
        if selected:
            self.current.config['name'] = selected['name']

    def __getattr__(self, name: str) -> Any:
        return getattr(self.current, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self._owned:
            object.__setattr__(self, name, value)
        else:
            setattr(self.current, name, value)

    def _persist(self) -> None:
        atomic_write(self.registry_file, json.dumps(self.registry).encode())

    def _register(self, controller: Controller, name: str) -> None:
        controller.config['name'] = name
        controller.persist()
        self.registry.setdefault('host_id', self.current.config['id'])
        self.registry['items'].append({'id': controller.config['id'], 'name': name,
            'root': str(controller.root), 'data_dir': controller.config['data_dir']})
        self.registry['main'] = controller.config['id']
        self._persist()

    def installations(self) -> dict[str, Any]:
        return {**self.registry, 'active': self.current.config['id']}

    def setup(self, data_dir: str, mode: str, login: str) -> None:
        with self.gate:
            self.current.setup(data_dir, mode, login)
            if not any(row['id'] == self.config['id'] for row in self.registry['items']):
                self._register(self.current, 'Основная платформа')

    def create(self, folder: str, name: str, login: str) -> str:
        data = Path(folder).expanduser().resolve()
        with self.gate, self.current.state_lock:
            if self.current.busy:
                raise ArchiveError('Дождитесь завершения текущей операции')
            if data.exists() and (not data.is_dir() or any(data.iterdir())):
                raise ArchiveError('Для новой платформы выберите пустую папку')
            for entry in self.registry['items']:
                existing = Path(entry['data_dir']).resolve()
                if data.is_relative_to(existing) or existing.is_relative_to(data):
                    raise ArchiveError('Папки платформ не должны совпадать или находиться друг внутри друга')
            if data == self.root or data.is_relative_to(self.root / '.control') or self.root.is_relative_to(data):
                raise ArchiveError('Выберите отдельную папку данных вне файлов хаба')
            import uuid
            state = self.root / '.control' / 'platforms' / uuid.uuid4().hex
            candidate = Controller(state)
            # Windows vault opens with the current account; Linux requires explicit unlock.
            if not candidate.vault.windows:
                if not self.current.vault.password:
                    raise ArchiveError('Сначала разблокируйте хранилище Linux')
                candidate.vault.unlock(self.current.vault.password)
            candidate.setup(str(data), 'new', login)
            self._stop_current()
            self.current = candidate
            self._register(candidate, name.strip() or 'Новая платформа')
            return candidate.config['id']

    def _stop_current(self) -> None:
        if self.current.config['configured']:
            self.current.execute('stop')
        self.current.tunnel.stop()
        self.current.docker.close()

    def select(self, identity: str, *, start: bool = True) -> None:
        with self.gate, self.current.state_lock:
            if self.current.busy:
                raise ArchiveError('Дождитесь завершения текущей операции')
            entry = next((row for row in self.registry['items'] if row['id'] == identity), None)
            if entry is None:
                raise ArchiveError('Платформа не найдена в списке')
            if identity != self.current.config['id']:
                self._stop_current()
                candidate = Controller(Path(entry['root']))
                candidate.config['name'] = entry['name']
                self.current = candidate
            self.registry['main'] = identity
            self._persist()
            if start:
                self._require_single_project()
                self.current.execute('start')

    def view(self) -> dict[str, Any]:
        # Monitoring must stay responsive during a build, a Docker stop or Telegram I/O.
        selected = self.current
        return {**selected.view(), 'installations': {**self.registry,
            'items': [dict(row) for row in self.registry['items']], 'active': selected.config['id']}}

    def delete(self, identity: str, confirmation: str, *, delete_data: bool = False) -> None:
        import shutil
        with self.gate, self.current.state_lock:
            if self.current.busy:
                raise ArchiveError('Дождитесь завершения текущей операции')
            entry = next((row for row in self.registry['items'] if row['id'] == identity), None)
            if entry is None or confirmation != entry['name']:
                raise ArchiveError('Для удаления введите точное название проекта')
            selected = self.current if identity == self.current.config['id'] else Controller(Path(entry['root']))
            if selected.busy:
                raise ArchiveError('Дождитесь завершения операции проекта')
            paths: list[Path] = []
            if delete_data:
                data = Path(entry['data_dir']).resolve()
                if (selected.config['id'] != identity or Path(selected.config['data_dir']).resolve() != data
                        or selected.root != Path(entry['root']).resolve()):
                    raise ArchiveError('Папка проекта не совпадает с его настройками')
                protected = [self.root, selected.source_root, Path.home()]
                protected += [selected.source_root / name for name in
                              ('.git', '.control', '.agents', '.codex', '.venv', 'backend', 'frontend', 'control', 'docs', 'specifications')]
                if data == Path(data.anchor) or any(p.resolve().is_relative_to(data) for p in protected):
                    raise ArchiveError('Нельзя удалять папку приложения, пользователя или её родителя')
                if any(data.is_relative_to(p.resolve()) for p in protected[3:]):
                    raise ArchiveError('Нельзя удалять служебные файлы приложения')
                others = [row for row in self.registry['items'] if row['id'] != identity]
                others += self.registry.get('legacy_sources', [])
                for row in others:
                    other = Path(row['data_dir']).resolve()
                    if data.is_relative_to(other) or other.is_relative_to(data):
                        raise ArchiveError('Папка пересекается с другим проектом или исходной базой')
                paths.append(Path(entry['data_dir']))
                state = Path(entry['root']).resolve()
                if state == self.root:
                    paths += [self.root / '.control' / name for name in
                              ('config.json', 'vault.bin', 'compose.json', 'history.json', 'events.json', 'backups', 'runtime', 'fxtunnel.json')]
                else:
                    if state.parent != (self.root / '.control' / 'platforms').resolve() and state != (self.root / '.control' / 'empty').resolve():
                        raise ArchiveError('Неизвестная папка состояния проекта')
                    paths.append(Path(entry['root']))
                # Validate every exact target before stopping services or deleting anything.
                for path in paths:
                    pending = [path]
                    while pending:
                        child = pending.pop()
                        if child.is_symlink() or child.is_junction():
                            raise ArchiveError('Удаление папок со ссылками запрещено; уберите проект из списка без удаления файлов')
                        if child.is_dir():
                            pending.extend(child.iterdir())
            if selected is self.current:
                self._stop_current()
            else:
                selected.execute('stop')
                selected.tunnel.stop()
                selected.docker.close()
            try:
                selected.docker.compose(['down', '--remove-orphans'], timeout=150)
                selected.discard_runtime()
            finally:
                selected.docker.close()
            for path in paths:
                if path.is_dir():
                    shutil.rmtree(path.resolve())
                elif path.exists():
                    path.resolve().unlink()
            remaining = [row for row in self.registry['items'] if row['id'] != identity]
            if selected is self.current:
                self.current = Controller(Path(remaining[0]['root']) if remaining else self.root / '.control' / 'empty')
                self.current.config['desired'] = False
                self.current.persist()
            self.registry['items'] = remaining
            self.registry['main'] = self.current.config['id'] if remaining else None
            self._persist()

    def execute(self, action: str) -> None:
        with self.gate:
            if action in {'start', 'restart'}:
                self._require_single_project()
            self.current.execute(action)

    def _require_single_project(self) -> None:
        import sqlite3
        from contextlib import closing
        database = Path(self.config['data_dir']) / 'hackathon.db'
        if database.is_file():
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
                if db.execute('SELECT count(*) FROM projects').fetchone()[0] > 1:
                    raise ArchiveError('Сначала разделите старую базу на проекты кнопкой в Ouroboros Daemon')

    def split_projects(self) -> list[str]:
        import sqlite3
        import shutil
        import uuid
        from contextlib import closing
        from control.projects import split_database
        from control.locking import FileLock
        with self.gate, self.current.state_lock:
            if self.current.busy:
                raise ArchiveError('Дождитесь завершения операции')
            original = self.current
            source = Path(original.config['data_dir'])
            self._stop_current()
            candidates: list[tuple[Controller, str]] = []
            with FileLock(source / '.hcc-operation.lock', blocking=False):
                with closing(sqlite3.connect((source / 'hackathon.db').as_uri() + '?mode=ro', uri=True)) as db:
                    projects = db.execute('SELECT id,name FROM projects ORDER BY id').fetchall()
                if len(projects) < 2:
                    raise ArchiveError('В базе уже один проект; разделение не требуется')
                for project_id, name in projects:
                    identity = uuid.uuid4().hex
                    data = source.parent / ('aion-project-' + identity)
                    data.mkdir()
                    split_database(source / 'hackathon.db', data / 'hackathon.db', project_id)
                    from control.worker import suspend_external_actions
                    from datetime import datetime, timezone
                    suspend_external_actions(data, datetime.now(timezone.utc).isoformat())
                    documents = source / 'documents' / str(project_id)
                    if documents.exists():
                        if documents.is_symlink() or any(p.is_symlink() for p in documents.rglob('*')):
                            raise ArchiveError('Ссылки в документах запрещены; исходник сохранён')
                        shutil.copytree(documents, data / 'documents' / str(project_id))
                    candidate = Controller(self.root / '.control' / 'platforms' / identity)
                    if not candidate.vault.windows:
                        candidate.vault.unlock(original.vault.password or '')
                    candidate.setup(str(data), 'attach', original.config['login'])
                    candidate.config['name'] = name
                    candidate.config.update(transfer_pending=True, restore_verified=True)
                    candidate.persist()
                    candidates.append((candidate, name))
            # Publish only when every copy passed validation. The source remains intact.
            self.registry.setdefault('legacy_sources', []).append(dict(next(row for row in self.registry['items'] if row['id'] == original.config['id'])))
            self.registry['items'] = [row for row in self.registry['items'] if row['id'] != original.config['id']]
            for candidate, name in candidates:
                self.registry['items'].append({'id': candidate.config['id'], 'name': name,
                    'root': str(candidate.root), 'data_dir': candidate.config['data_dir']})
            self.current = candidates[0][0]
            self.registry['main'] = self.current.config['id']
            self._persist()
            return [candidate.config['id'] for candidate, _ in candidates]

    def loop(self) -> None:
        while not self.stop_event.is_set():
            if self.gate.acquire(blocking=False):
                try:
                    self.current.tick()
                finally:
                    self.gate.release()
            self.stop_event.wait(20)

    def shutdown(self) -> None:
        with self.gate, self.current.state_lock:
            if self.current.busy:
                raise ArchiveError('Дождитесь завершения операции перед выключением хаба')
            self._stop_current()
            self.stop_event.set()

    def resume_main(self) -> None:
        """Login autostart explicitly follows the saved existing-platform scenario."""
        if self.registry['items']:
            self.select(self.registry['main'], start=True)
