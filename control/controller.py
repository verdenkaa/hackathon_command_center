"""Installation state and bounded, independent operations behind the local UI."""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import socket
import threading
import time
import urllib.request
import urllib.error
import uuid
from pathlib import Path
from typing import Any

import psutil

from control import VERSION
from control.archives import ArchiveError, decrypt_archive, encrypt_archive, inspect_snapshot
from control.docker import Docker, DockerError
from control.supervision import RecoveryPolicy, retention_candidates
from control.telegram import DeliveryError, send_backup, send_alert
from control.vault import Vault, VaultError, atomic_write
from control.tunnel import Tunnel


def suggested_login() -> str:
    return re.sub(r"[^a-z0-9_-]", "-", socket.gethostname().lower()).strip("-")[:48] or "operator"


class Controller:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.source_root = Path(__file__).resolve().parents[1]
        self.folder = self.root / ".control"
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        config_path = self.folder / "config.json"
        self.config: dict[str, Any] = json.loads(config_path.read_text()) if config_path.exists() else {
            "id": uuid.uuid4().hex[:12], "configured": False, "desired": False,
            "data_dir": str(self.root / "data"), "login": suggested_login(),
            "distro": "Ubuntu-24.04", "external_folder": "", "telegram_chat": "", "telegram_thread": None,
            "transfer_pending": False, "external_resume_after": 0,
        }
        if not self.config.get('subdomain'):
            self.config['subdomain'] = 'dots-bots-hub'
        history = self.folder / "history.json"
        self.history: dict[str, Any] = json.loads(history.read_text()) if history.exists() else {
            "records": [], "telegram_at": 0, "telegram_attempt": 0, "telegram_id": "", "external_at": 0,
        }
        self.vault = Vault(self.folder)
        self.docker = Docker(self.root, self.config["id"], self.config["distro"])
        self.tunnel = Tunnel(self.folder, self.config["id"])
        self.policy = RecoveryPolicy()
        self.started = time.time()
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.state_lock = threading.RLock()
        self.busy = ""
        self.events: list[dict[str, Any]] = []
        event_file = self.folder / 'events.json'
        if event_file.exists():
            self.events = json.loads(event_file.read_text())[-100:]
        self.operation_error: str | None = None
        self.status: dict[str, Any] = {"checked_at": None, "engine": None, "container": None, "api": None,
                                       "ui": None, "metrics": [], "error": "Проверка ещё не выполнялась"}
        self.last_backup_check = 0.0
        self.last_engine: bool | None = None
        self.resume_pending = True
        if self.config['configured']:
            self.refresh_login()

    def refresh_login(self) -> None:
        """Display the actual global administrator login for attached databases."""
        import sqlite3
        from contextlib import closing
        database = Path(self.config['data_dir']) / 'hackathon.db'
        if not database.is_file():
            return
        try:
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
                row = db.execute("SELECT u.login FROM users u JOIN role_assignments r ON r.user_id=u.id WHERE r.role='admin' AND r.project_id IS NULL ORDER BY r.id LIMIT 1").fetchone()
                if row:
                    self.config['login'] = row[0]
        except sqlite3.Error:
            pass

    def credentials(self) -> dict[str, Any]:
        """Return a known password only if it belongs to an active administrator."""
        import sqlite3
        import bcrypt
        from contextlib import closing
        from dotenv import dotenv_values

        self.refresh_login()
        key = self.vault.get('operator')
        password: str | None = None
        verified = False
        candidates = [self.vault.get('bootstrap_password'), key]
        if self.config.get('mode') == 'attach':
            # Legacy source configuration is local; never assume its password is current.
            legacy = dotenv_values(self.source_root / '.env')
            candidates.append(legacy.get('APP_FIRST_ADMIN_PASSWORD') or 'change-me')
        database = Path(self.config['data_dir']) / 'hackathon.db'
        if database.is_file():
            try:
                with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
                    rows = db.execute("SELECT u.login,u.password_hash FROM users u JOIN role_assignments r ON r.user_id=u.id WHERE r.role='admin' AND r.project_id IS NULL AND u.active=1 AND coalesce(u.deleted_identity,0)=0 ORDER BY r.id").fetchall()
                for login, hashed in rows:
                    for candidate in dict.fromkeys(candidates):
                        if not candidate:
                            continue
                        try:
                            matches = bcrypt.checkpw(candidate.encode(), hashed.encode())
                        except (ValueError, TypeError):
                            matches = False
                        if matches:
                            self.config['login'], password, verified = login, candidate, True
                            break
                    if verified:
                        break
            except sqlite3.Error:
                pass
        elif self.config.get('mode') == 'new':
            password = self.vault.get('bootstrap_password') or None
        return {'login': self.config['login'], 'password': password, 'password_verified': verified,
            'password_message': 'Пароль проверен по текущей базе.' if verified else 'Первоначальный пароль; база ещё не создана.' if password else 'Текущий пароль неизвестен хабу. Используйте пароль этого аккаунта; ключ архива для входа не подходит.',
            'key': key, 'previous_keys': json.loads(self.vault.get('operator_history') or '[]'),
            'relationship': 'Это ключ шифрования архивов. Он хранится отдельно от пароля входа и не меняется при смене пароля аккаунта.',
            'existing': self.config.get('mode') == 'attach'}

    def persist(self) -> None:
        with self.state_lock:
            atomic_write(self.folder / "config.json", json.dumps(self.config).encode())
            atomic_write(self.folder / "history.json", json.dumps(self.history).encode())

    def event(self, message: str, level: str = "info") -> None:
        self.events.append({"at": time.time(), "message": message, "level": level})
        self.events = self.events[-100:]
        atomic_write(self.folder / "events.json", json.dumps(self.events).encode())

    def view(self) -> dict[str, Any]:
        return {**self.status, "version": VERSION, "config": self.config, "history": self.history,
                "services": self.service_states(), "operation_error": self.operation_error,
                "busy": self.busy, "events": self.events[-25:], "vault_unlocked": self.vault.unlocked,
                "recovery_attempts": len(self.policy.attempts), "recovery_exhausted": self.policy.exhausted,
                "host_platform": os.name, "local_url": "http://127.0.0.1:8000",
                "tunnel": {"url": self.tunnel.current_url, "checked_at": self.tunnel.checked_at, "error": self.tunnel.error}}

    def setup(self, data_dir: str, mode: str, login: str) -> None:
        data = Path(data_dir).expanduser().resolve()
        if data == self.root or data == self.folder or self.folder.is_relative_to(data) or data.is_relative_to(self.folder):
            raise ArchiveError("Выберите отдельную папку данных вне файлов панели")
        if (data / "hackathon.db").exists() and mode != "attach":
            raise FileExistsError("В папке уже есть база. Выберите явное подключение существующей установки.")
        if mode == "attach" and not (data / "hackathon.db").is_file():
            raise ArchiveError("Для подключения выберите папку с hackathon.db")
        if self.config["configured"]:
            raise ArchiveError("Установка уже настроена; смена папки требует отдельного переноса")
        data.mkdir(parents=True, exist_ok=True)
        probe = data / (".write-test-" + uuid.uuid4().hex)
        probe.write_bytes(b"ok")
        probe.unlink()
        if shutil.disk_usage(data).free < 512 * 1024 * 1024:
            raise ArchiveError("Для первоначальной подготовки нужно хотя бы 512 МиБ свободного места")
        if not (data / '.gitignore').exists():
            atomic_write(data / '.gitignore', b'*\n')
        if not self.vault.get("operator"):
            self.vault.put("operator", secrets.token_urlsafe(36))
        if mode == "new":
            self.vault.put("bootstrap_password", self.vault.get("operator"))
        else:
            # Read the actual account; the panel's suggested host login is not an existing DB login.
            import sqlite3
            from contextlib import closing
            try:
                with closing(sqlite3.connect((data / 'hackathon.db').as_uri() + '?mode=ro', uri=True)) as db:
                    row = db.execute("SELECT u.login FROM users u JOIN role_assignments r ON r.user_id=u.id WHERE r.role='admin' AND r.project_id IS NULL ORDER BY r.id LIMIT 1").fetchone()
                    if row:
                        login = row[0]
            except sqlite3.Error:
                pass
        self.config.update(configured=True, data_dir=str(data), login=login, mode=mode)
        self.write_compose()
        self.persist()
        self.event("Новая установка подготовлена" if mode == "new" else "Существующие данные подключены. Пароли аккаунтов не изменены.")

    def write_compose(self) -> None:
        runtime = "/run/hcc-" + self.config["id"] if os.name == "nt" else str(self.folder / "runtime")
        self.runtime = runtime
        document = {"services": {"app": {
            "image": "hcc-platform:" + VERSION,
            "build": {"context": self.docker.engine_path(self.source_root)},
            "restart": "on-failure:3",
            "ports": ["127.0.0.1:8000:8000"],
            "environment": {"APP_ENV": "production", "APP_MANAGED": "true", "APP_DATA_DIR": "/data",
                            "APP_INSTALLATION_ID": self.config["id"],
                            "APP_PROJECT_NAME": self.config.get("name", "Aion"),
                            "DATABASE_URL": "sqlite:////data/hackathon.db", "APP_SECRETS_DIR": "/run/secrets",
                            "APP_FIRST_ADMIN_LOGIN": self.config["login"]},
            "volumes": [{"type": "bind", "source": self.docker.engine_path(Path(self.config["data_dir"])), "target": "/data"},
                        {"type": "bind", "source": runtime, "target": "/run/secrets", "read_only": True}],
            "read_only": True, "tmpfs": ["/tmp:size=768m"], "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "labels": {"hcc.installation": self.config["id"]},
            "logging": {"driver": "json-file", "options": {"max-size": "5m", "max-file": "3"}},
            "healthcheck": {"test": ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)"],
                            "interval": "20s", "timeout": "5s", "retries": 3, "start_period": "90s"},
        }}}
        atomic_write(self.folder / "compose.json", json.dumps(document).encode())

    def discard_runtime(self) -> None:
        """Remove only the four staged secret files owned by this installation."""
        if not re.fullmatch(r'[a-f0-9]{1,32}', self.config['id']):
            raise ArchiveError('Неверный идентификатор проекта')
        names = ('operator', 'bootstrap_password', 'gemini', 'telegram')
        if os.name == 'nt':
            script = (f"from pathlib import Path; p=Path('/run/hcc-{self.config['id']}'); "
                      f"[(p/n).unlink(missing_ok=True) for n in {names!r}]; "
                      "p.rmdir() if p.exists() else None")
            self.docker.run(['python3', '-c', script])
        else:
            runtime = self.folder / 'runtime'
            for name in names:
                (runtime / name).unlink(missing_ok=True)
            if runtime.exists():
                runtime.rmdir()

    def stage_secrets(self) -> None:
        self.write_compose()
        values = {name: self.vault.get(name) for name in ("operator", "bootstrap_password", "gemini", "telegram")}
        # Values travel over stdin, never in command arguments, logs, Compose or environment.
        if os.name == "nt":
            script = ("import os,json,pathlib; os.umask(0o077); "
                      f"p=pathlib.Path({self.runtime!r}); p.mkdir(parents=True,exist_ok=True,mode=0o700); "
                      "[(p.joinpath(k).write_text(v),p.joinpath(k).chmod(0o600)) for k,v in json.load(__import__('sys').stdin).items()]")
            self.docker.run(["python3", "-c", script], data=json.dumps(values).encode())
        else:
            for name, value in values.items():
                atomic_write(Path(self.runtime) / name, value.encode())

    def execute(self, action: str) -> None:
        if action == "stop":
            self.config["desired"] = False
            self.persist()
        if not self.lock.acquire(timeout=90):
            raise ArchiveError("Другая операция ещё выполняется")
        self.busy = action
        self.operation_error = None
        try:
            if action == "check":
                self.check()
            elif action == "build":
                self.write_compose()
                self.docker.compose(["build", "--pull", "app"], timeout=900)
                self.event("Образ платформы собран")
            elif action in {"start", "restart"}:
                if not self.config["configured"]:
                    raise ArchiveError("Сначала завершите первоначальную настройку")
                if self.config["transfer_pending"]:
                    raise ArchiveError("Сначала завершите мастер переноса")
                self.stage_secrets()
                self.config["desired"] = True
                self.config['tunnel_desired'] = bool(self.vault.get('fxtunnel'))
                self.tunnel_attempts = 0
                self.last_tunnel_attempt = 0.0
                self.persist()
                try:
                    if action == "restart":
                        self.docker.compose(["stop", "-t", "130", "app"], timeout=150)
                    self.docker.compose(["up", "--detach", "--no-build", "--force-recreate", "app"])
                except DockerError:
                    self.config["desired"] = False
                    self.persist()
                    raise
                self.started, self.policy = time.time(), RecoveryPolicy()
                self.event("Платформа запущена" if action == "start" else "Платформа перезапущена")
            elif action == "stop":
                self.tunnel.stop()
                self.docker.compose(["stop", "-t", "130", "app"], timeout=150)
                self.status.update(api=False, ui=False, error=None,
                    container={**(self.status.get('container') or {}), 'State':'exited'})
                self.event("Платформа остановлена оператором; автоматический запуск отключён")
            elif action == "backup":
                self.backup(force=True)
            elif action == "telegram":
                self.deliver(manual=True)
            elif action == 'telegram-test':
                chat = self.config.get('telegram_alert_chat', '')
                if not chat or not self.vault.get('telegram'):
                    raise DeliveryError('Сначала сохраните токен бота и чат для оповещений')
                send_alert(self.vault.get('telegram'), chat, self.config.get('telegram_alert_thread'),
                    'Штаб: проверка канала оповещений. Связь работает.', self.config.get('administrator', ''))
                self.history.update(alert_error=None, alert_at=time.time())
                self.persist()
                self.event('Telegram подтвердил тестовое оповещение')
            elif action == "tunnel-start":
                if self.config["transfer_pending"] or not self.config["desired"]:
                    raise ArchiveError("Сначала завершите перенос и запустите платформу")
                try:
                    self.tunnel.start(self.vault.get("fxtunnel"), self.config.get("subdomain", ""))
                    self.config['tunnel_desired'] = True
                    self.persist()
                except ValueError as exc:
                    raise ArchiveError(str(exc)) from None
            elif action == "tunnel-stop":
                self.tunnel.stop()
                self.config['tunnel_desired'] = False
                self.persist()
            else:
                raise ArchiveError("Действие не предусмотрено")
            self.update_services()
        finally:
            self.busy = ""
            self.lock.release()

    def service_states(self) -> dict[str, dict[str, str]]:
        def state(status: str, detail: str) -> dict[str, str]:
            return {'status': status, 'detail': detail}
        desired = self.config['desired']
        engine = state('ok', 'Движок готов') if self.status['engine'] else state(
            'error' if self.status['checked_at'] else 'unknown', self.status.get('error') or 'Проверка ещё не завершена')
        api = state('ok', 'Платформа доступна') if self.status['api'] else state(
            'loading' if self.busy in {'start','restart','build'} or (desired and time.time()-self.started < 90) else 'error' if desired else 'waiting',
            self.status.get('error') or ('Ожидаем готовность API' if desired else 'Запускается на вкладке настроек'))
        tunnel = state('ok', self.tunnel.current_url) if self.tunnel.current_url else state(
            'loading' if self.tunnel.process and self.tunnel.process.poll() is None else 'error' if desired and self.config.get('tunnel_desired') else 'waiting',
            self.tunnel.error or 'Ожидает открытия')
        telegram = state('error', self.history['telegram_error']) if self.history.get('telegram_error') else state(
            'ok' if self.history.get('telegram_at') or self.history.get('alert_at') else 'unknown' if self.config.get('telegram_chat') or self.config.get('telegram_alert_chat') else 'waiting',
            'Последняя отправка подтверждена' if self.history.get('telegram_at') or self.history.get('alert_at') else 'Сохраните направления и отправьте тест')
        gemini = state('waiting', 'Ключ не задан')
        if self.vault.unlocked and self.vault.get('gemini'):
            gemini = state('unknown', 'Ключ сохранён. Проверка запросом не выполнялась; ИИ включается в платформе')
        return {'docker': engine, 'platform': api, 'fxtunnel': tunnel, 'telegram': telegram, 'gemini': gemini}

    def update_services(self) -> None:
        states = self.service_states()
        previous = self.history.setdefault('service_states', {})
        queue = self.history.setdefault('alert_outbox', [])
        labels = {'ok':'работает','error':'сбой','loading':'подготовка','unknown':'не проверено','waiting':'ожидает запуска'}
        names = {'docker':'Docker','platform':'Платформа','fxtunnel':'fxTunnel','telegram':'Telegram','gemini':'Gemini'}
        for name, value in states.items():
            old = previous.get(name)
            if old != value['status']:
                message = f"{names[name]}: {labels.get(old, 'неизвестно')} → {labels[value['status']]}. {value['detail']}"
                self.event(message, 'error' if value['status'] == 'error' else 'info')
                if self.config.get('telegram_alert_chat'):
                    queue.append({'at': time.time(), 'text': message})
                previous[name] = value['status']
        self.persist()

    def deliver_alerts(self) -> None:
        queue = self.history.setdefault('alert_outbox', [])
        if not queue or not self.config.get('telegram_alert_chat') or not self.vault.unlocked or self.config.get('transfer_pending'):
            return
        if time.time() < self.history.get('alert_retry_at', 0):
            return
        token = self.vault.get('telegram')
        if not token:
            return
        # Persist each acknowledged transition; failures retain the remaining queue.
        try:
            while queue:
                send_alert(token, self.config['telegram_alert_chat'], self.config.get('telegram_alert_thread'),
                    f"{self.config.get('name', 'Штаб')} · {time.strftime('%d.%m %H:%M:%S', time.localtime(queue[0]['at']))}\n{queue[0]['text']}",
                    self.config.get('administrator', ''))
                queue.pop(0)
                self.history.update(alert_at=time.time(), alert_error=None)
                self.persist()
        except DeliveryError as exc:
            self.history.update(alert_error=str(exc), alert_retry_at=time.time()+60)
            self.persist()

    def check(self) -> None:
        now = time.time()
        metrics: dict[str, Any] = {"at": now, "host_cpu": psutil.cpu_percent(), "host_memory": psutil.virtual_memory().percent,
                                   "panel_memory_bytes": psutil.Process().memory_info().rss, "container_cpu": None, "container_memory": None}
        result = {**self.status, "error": None, "api": None, "ui": None, "storage_error": False}
        try:
            result["engine"] = self.docker.ready()
            result["container"] = self.docker.container() if self.config["configured"] else None
            container = result["container"]
            if (self.config["desired"] and (self.resume_pending or self.last_engine is False)
                    and container and container.get("State") in {"exited", "created"}
                    and self.vault.unlocked and not self.config["transfer_pending"] and not self.policy.exhausted
                    and (not self.policy.attempts or now - self.policy.attempts[-1] >= self.policy.delay)):
                self.policy.attempts.append(now)
                self.stage_secrets()
                self.docker.compose(["up", "--detach", "--no-build", "app"])
                self.started = time.time()
                container = self.docker.container()
                result["container"] = container
                self.event("Платформа возобновлена после запуска панели или возвращения движка")
            self.resume_pending = False
            self.last_engine = True
            if container and container.get("State") == "exited" and self.config["desired"]:
                if int(container.get("ExitCode", 0)) != 0:
                    result["error"] = "Контейнер завершился с ошибкой после попыток Docker. Проверьте версию, миграции и свободное место, затем запустите вручную."
                    self.policy.attempts = [now] * self.policy.limit
                elif self.policy.should_restart(now=now, desired=True, started=self.started, healthy=False, running=True):
                    self.stage_secrets()
                    self.docker.compose(["up", "--detach", "--no-build", "app"])
                    self.started = time.time()
                    self.event("Остановившийся при перезапуске движка контейнер возобновлён; попытка учтена в лимите")
            if container and container.get("State") == "running":
                try:
                    raw = self.docker.run(["docker", "stats", "--no-stream", "--format", "{{json .}}", container["Name"]])
                    stats = json.loads(raw)
                    metrics.update(container_cpu=float(stats["CPUPerc"].rstrip("%")), container_memory=stats["MemUsage"])
                except (DockerError, KeyError, ValueError):
                    pass
                for route, key in (("/health", "api"), ("/", "ui")):
                    try:
                        with urllib.request.urlopen("http://127.0.0.1:8000" + route, timeout=4) as response:
                            result[key] = response.status == 200
                    except urllib.error.HTTPError as exc:
                        result[key] = False
                        if key == "api" and exc.code == 503:
                            try:
                                result["storage_error"] = json.loads(exc.read(65536)).get("reason") == "storage"
                            except (ValueError, OSError):
                                pass
                    except OSError:
                        result[key] = False
                startup = Path(self.config["data_dir"]) / ".startup-state.json"
                try:
                    startup_state = json.loads(startup.read_text()) if startup.exists() else {}
                except (OSError, ValueError):
                    startup_state = {}
                result["startup"] = startup_state
                if result["storage_error"]:
                    result["error"] = "Папка данных недоступна для записи или диск заполнен. Исправьте хранение; автоматический перезапуск не выполняется."
                if self.policy.should_restart(now=now, desired=self.config["desired"], started=self.started,
                                              healthy=result["api"] is True or result["storage_error"] or startup_state.get("phase") == "migrations", running=True):
                    self.event("API не отвечает: ограниченная попытка перезапуска", "warning")
                    self.docker.compose(["restart", "-t", "130", "app"], timeout=150)
                    self.started = time.time()
        except DockerError as exc:
            result.update(engine=None, container=None, error=str(exc))
            self.last_engine = False
        data = Path(self.config["data_dir"])
        result["disk_free_bytes"] = shutil.disk_usage(data if data.exists() else self.root).free
        result["metrics"] = [*self.status["metrics"][-59:], metrics]
        result["checked_at"] = time.time()
        self.status = result

    def backup(self, *, force: bool = False) -> None:
        start = time.time()
        self.last_backup_check = start
        self.history["checked_at"] = start
        if not self.config["configured"]:
            return
        blob = self.docker.helper("snapshot")
        manifest = inspect_snapshot(blob)
        records = self.history["records"]
        if not force and records and records[-1]["fingerprint"] == manifest["fingerprint"]:
            self.history["message"] = "Изменений после последней копии нет"
            self.persist()
            return
        encrypted = encrypt_archive(blob, self.vault.get("operator"))
        if decrypt_archive(encrypted, self.vault.get("operator")) != blob:
            raise ArchiveError("Проверка шифрования не пройдена")
        record = {"id": manifest["id"], "file": f'hcc-{self.config["id"]}-{manifest["id"]}.hcc',
                  "created": start, "size": len(encrypted), "seconds": time.time() - start, "fingerprint": manifest["fingerprint"]}
        folder = self.folder / "backups"
        folder.mkdir(exist_ok=True)
        if shutil.disk_usage(folder).free < len(encrypted) * 2 + 64 * 1024 * 1024:
            raise ArchiveError("Недостаточно места для копии. Последняя пригодная копия сохранена.")
        atomic_write(folder / record["file"], encrypted)
        records.append(record)
        self.history["message"] = "Копия создана и проверена локально"
        self.persist()
        self.event("Резервная копия проверена локально")
        removable = retention_candidates(records, now=time.time())
        for old in list(records):
            if old["id"] in removable and re.fullmatch(r"hcc-" + self.config["id"] + r"-[a-f0-9]{32}\.hcc", old["file"]):
                try:
                    (folder / old["file"]).unlink(missing_ok=True)
                    records.remove(old)
                except OSError:
                    self.event("Не удалось очистить старую копию; проверьте права папки", "warning")
        self.persist()

    def copy_external(self) -> None:
        if not self.config["external_folder"] or not self.history["records"]:
            return
        latest = self.history["records"][-1]
        folder = Path(self.config["external_folder"])
        try:
            if not folder.is_dir() or shutil.disk_usage(folder).free < latest["size"] * 2:
                raise OSError
            destination = folder / latest["file"]
            if destination.is_symlink():
                raise OSError
            unchanged = (self.history.get("external_id") == latest["id"] and not self.history.get("external_error")
                         and destination.exists() and destination.stat().st_size == latest["size"]
                         and destination.stat().st_mtime_ns == self.history.get("external_mtime"))
            if not unchanged:
                encrypted = (self.folder / "backups" / latest["file"]).read_bytes()
                atomic_write(destination, encrypted)
                if destination.read_bytes() != encrypted:
                    raise OSError
                self.history.update(external_at=time.time(), external_id=latest["id"], external_mtime=destination.stat().st_mtime_ns)
            self.history.update(external_checked_at=time.time(), external_error=None)
            copies = self.history.setdefault("external_records", [])
            if not any(item["id"] == latest["id"] for item in copies):
                copies.append(dict(latest))
            for old in list(copies):
                if (old["id"] in retention_candidates(copies, now=time.time())
                        and re.fullmatch(r"hcc-" + self.config["id"] + r"-[a-f0-9]{32}\.hcc", old["file"])):
                    (folder / old["file"]).unlink(missing_ok=True)
                    copies.remove(old)
        except OSError:
            self.history["external_error"] = "Дополнительная папка недоступна или заполнена. Подключите диск; будет скопирована актуальная копия."
        self.persist()

    def deliver(self, *, manual: bool = False) -> None:
        records = self.history["records"]
        if not records or not self.config["telegram_chat"] or self.config["transfer_pending"]:
            if manual:
                raise DeliveryError('Сначала создайте локальную копию и сохраните чат для резервных копий')
            return
        latest = records[-1]
        if self.history["telegram_id"] == latest["id"]:
            if manual:
                self.event('Эта копия уже принята Telegram. Создайте новую копию, если нужен повторный экспорт.')
            return
        cooldown = 30 if self.history.get('telegram_error') else 1800
        if time.time() - self.history["telegram_attempt"] < cooldown:
            if manual:
                remaining = int(cooldown - (time.time() - self.history['telegram_attempt'])) + 1
                raise DeliveryError(f'Повторная отправка доступна через {remaining} с. Интервал после успешной отправки — 30 минут.')
            return
        if not self.vault.unlocked:
            return
        token = self.vault.get("telegram")
        if not token:
            if manual:
                raise DeliveryError('Сохраните токен Telegram на этапе настройки резервных копий')
            return
        if not manual and self.config["configured"] and time.time() - self.last_backup_check > 20:
            try:
                self.backup()
                latest = self.history["records"][-1]
            except (DockerError, ArchiveError, VaultError, OSError):
                self.event("Не удалось обновить снимок перед Telegram; отправляется последняя проверенная копия с её исходной датой.", "warning")
        self.history["telegram_attempt"] = time.time()
        self.persist()
        try:
            send_backup(token, self.config["telegram_chat"], self.config["telegram_thread"],
                        (self.folder / "backups" / latest["file"]).read_bytes(), latest, self.config.get('name', 'Штаб'))
            self.history.update(telegram_at=time.time(), telegram_snapshot_at=latest["created"], telegram_id=latest["id"], telegram_error=None)
            self.event("Telegram подтвердил приём зашифрованного архива. Восстановление проверяется отдельно.")
        except DeliveryError as exc:
            self.history["telegram_error"] = str(exc)
            self.event(str(exc), "warning")
        self.persist()

    def tick(self) -> None:
        if not self.lock.acquire(blocking=False):
            return
        try:
            self.check()
            self.tunnel.check()
            if (self.config.get('tunnel_desired') and self.config['desired'] and self.status['api'] and not self.tunnel.process
                    and self.vault.unlocked and self.vault.get('fxtunnel')
                    and time.time()-getattr(self,'last_tunnel_attempt',0) >= 60 and getattr(self,'tunnel_attempts',0) < 3):
                self.last_tunnel_attempt = time.time()
                self.tunnel_attempts = getattr(self,'tunnel_attempts',0)+1
                try:
                    self.tunnel.start(self.vault.get('fxtunnel'), self.config['subdomain'])
                except (ValueError, OSError) as exc:
                    self.tunnel.error = str(exc) if isinstance(exc, ValueError) else 'Не удалось открыть fxTunnel. Проверьте установленный CLI.'
            data_folder = Path(self.config["data_dir"])
            if self.config["configured"] and data_folder.is_dir():
                atomic_write(data_folder / ".public-url.json", json.dumps({"url": self.tunnel.current_url or "", "expires": time.time() + 60}).encode())
            try:
                if self.vault.unlocked and time.time() - self.last_backup_check >= 300:
                    self.backup()
                self.copy_external()
                self.deliver()
            except (DockerError, ArchiveError, VaultError, OSError) as exc:
                self.history['message'] = str(exc) if isinstance(exc, (DockerError, ArchiveError, VaultError)) else 'Папка копий недоступна. Проверьте диск и права записи.'
            self.update_services()
            self.deliver_alerts()
        except (DockerError, ArchiveError, VaultError, OSError):
            self.operation_error = 'Не удалось проверить установку. Проверьте движок, доступность папки данных и свободное место.'
        finally:
            self.lock.release()

    def loop(self) -> None:
        while not self.stop_event.is_set():
            self.tick()
            self.stop_event.wait(20)
