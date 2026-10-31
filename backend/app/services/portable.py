"""Managed lifecycle safeguards; does not alter the legacy development launcher."""
from __future__ import annotations

import json
import shutil
import time
import os
import uuid
import re
from contextlib import nullcontext
from pathlib import Path

from app.config import settings

_storage_check: tuple[str, float, bool] = ("", 0, False)


def current_public_url() -> str:
    try:
        value = json.loads((settings.data_dir / '.public-url.json').read_text())
        url = value.get('url', '')
        return url if value.get('expires', 0) > time.time() and re.fullmatch(r'https://[a-z0-9-]+\.fxtun\.ru', url) else ''
    except (OSError, ValueError, TypeError):
        return ''


def storage_ready() -> bool:
    global _storage_check
    folder = settings.data_dir
    if _storage_check[0] == str(folder) and time.monotonic() - _storage_check[1] < 10:
        return _storage_check[2]
    probe = folder / (".health-" + uuid.uuid4().hex)
    ready = False
    try:
        if shutil.disk_usage(folder).free >= 64 * 1024 * 1024:
            descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(b"ok")
            probe.unlink()
            ready = True
    except OSError:
        pass
    _storage_check = (str(folder), time.monotonic(), ready)
    return ready


def operation_lock():
    if not settings.app_managed:
        return nullcontext()
    from control.locking import FileLock
    return FileLock(settings.data_dir / ".hcc-operation.lock")


def external_allowed() -> bool:
    if not settings.app_managed:
        return True
    return not (settings.data_dir / ".transfer-pending").exists()


def ai_allowed() -> bool:
    if not external_allowed():
        return False
    marker = settings.data_dir / ".ai-not-before"
    if settings.app_managed and marker.exists():
        try:
            return time.time() >= float(marker.read_text())
        except (OSError, ValueError):
            return False
    return True


def preflight_migrations() -> None:
    if not settings.app_managed:
        return
    from contextlib import closing
    import sqlite3
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from control.archives import create_snapshot, encrypt_archive, inspect_snapshot
    from control.vault import atomic_write

    database = settings.data_dir / "hackathon.db"
    if not database.exists() or database.stat().st_size == 0:
        return
    backend = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    scripts = ScriptDirectory.from_config(cfg)
    with closing(sqlite3.connect(database)) as db:
        try:
            rows = db.execute("SELECT version_num FROM alembic_version").fetchall()
        except sqlite3.Error:
            raise RuntimeError("Неизвестная схема базы; восстановите совместимую копию через локальную панель") from None
    if len(rows) != 1 or rows[0][0] not in {item.revision for item in scripts.walk_revisions()}:
        raise RuntimeError("Несовместимая версия базы; автоматическое изменение запрещено")
    if rows[0][0] == scripts.get_current_head():
        return
    key = settings.secret_value("operator")
    if not key:
        raise RuntimeError("Перед миграцией нужен ключ оператора для защитной копии")
    blob = create_snapshot(settings.data_dir, "migration-safety")
    inspect_snapshot(blob)
    if shutil.disk_usage(settings.data_dir).free < len(blob) * 3 + 64 * 1024 * 1024:
        raise RuntimeError("Недостаточно места для защитной копии и миграции")
    atomic_write(settings.data_dir / "migration-safety" / f"before-{time.time_ns()}.hcc", encrypt_archive(blob, key))
