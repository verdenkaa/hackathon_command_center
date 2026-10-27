"""Резервное копирование и восстановление."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.config import settings
from app.db.models import BackupRecord
from app.db.session import engine
from app.timeutil import utcnow


def db_file_path() -> Path:
    url = settings.sqlalchemy_url
    if url.startswith("sqlite:///"):
        return Path(url[len("sqlite:///"):])
    return Path(url)


def backups_dir() -> Path:
    return settings.data_dir / "backups"


def _snapshot_db(dst: Path) -> None:
    src = sqlite3.connect(str(db_file_path()))
    try:
        d = sqlite3.connect(str(dst))
        with d:
            src.backup(d)
        d.close()
    finally:
        src.close()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def create_backup(db: Session, kind: str = "automatic") -> BackupRecord:
    backups_dir().mkdir(parents=True, exist_ok=True)
    tmp = backups_dir() / f".tmp_{utcnow().strftime('%Y%m%d%H%M%S%f')}"
    tmp.mkdir(parents=True, exist_ok=True)
    filename = f"backup_{utcnow().strftime('%Y%m%d%H%M%S%f')}_{kind}.zip"
    zip_path = backups_dir() / filename
    try:
        _snapshot_db(tmp / "database.sqlite")
        docs_src = settings.data_dir / "documents"
        if docs_src.exists():
            shutil.copytree(docs_src, tmp / "documents")
        (tmp / "manifest.json").write_text(
            json.dumps({"created_at": utcnow().isoformat(), "kind": kind}), encoding="utf-8"
        )
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in tmp.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(tmp))
        # Обновляем latest.zip только для обычных копий (не safety).
        if kind != "safety":
            latest = backups_dir() / "latest.zip"
            latest_tmp = backups_dir() / "latest.zip.tmp"
            shutil.copyfile(zip_path, latest_tmp)
            latest_tmp.replace(latest)
            # Хранится одна последняя копия: удаляем старые обычные.
            for old in backups_dir().glob("backup_*.zip"):
                if "_safety" not in old.name and old != zip_path:
                    old.unlink(missing_ok=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    checksum = _sha256(zip_path)
    record = BackupRecord(
        path=filename, checksum=checksum, size_bytes=zip_path.stat().st_size, kind=kind
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def restore_backup(db: Session, backup_id: int) -> BackupRecord:
    record = db.get(BackupRecord, backup_id)
    if record is None:
        raise api_error(404, "NOT_FOUND", "Резервная копия не найдена")
    latest = backups_dir() / record.path
    if not latest.exists():
        raise api_error(404, "NOT_FOUND", "Файл резервной копии не найден")
    if _sha256(latest) != record.checksum:
        raise api_error(409, "BACKUP_CORRUPT", "Резервная копия повреждена")

    # Защитная копия текущего состояния.
    create_backup(db, kind="safety")

    tmp = backups_dir() / f".restore_{utcnow().strftime('%Y%m%d%H%M%S%f')}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(latest) as zf:
            zf.extractall(tmp)

        # Закрываем все соединения с БД перед заменой файла.
        db.close()
        engine.dispose()

        db_path = db_file_path()
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(db_path) + suffix)
            if p.exists():
                p.unlink()
        shutil.copyfile(tmp / "database.sqlite", db_path)

        docs = settings.data_dir / "documents"
        if docs.exists():
            shutil.rmtree(docs, ignore_errors=True)
        if (tmp / "documents").exists():
            shutil.copytree(tmp / "documents", docs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    from app.main import stamp_head

    stamp_head()
    return record


def list_backups(db: Session) -> list[BackupRecord]:
    return db.query(BackupRecord).order_by(BackupRecord.created_at.desc()).all()
