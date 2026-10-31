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
            entry = next(row for row in self.registry['items'] if row['id'] == self.registry['main'])
            self.current = Controller(Path(entry['root']))
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
                self.current.execute('start')

    def view(self) -> dict[str, Any]:
        # Monitoring must stay responsive during a build, a Docker stop or Telegram I/O.
        selected = self.current
        return {**selected.view(), 'installations': {**self.registry,
            'items': [dict(row) for row in self.registry['items']], 'active': selected.config['id']}}

    def execute(self, action: str) -> None:
        with self.gate:
            self.current.execute(action)

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
