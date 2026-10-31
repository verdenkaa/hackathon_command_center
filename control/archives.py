"""Versioned, authenticated whole-installation snapshots. No credentials included."""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from control import VERSION

MAX_BYTES = 512 * 1024 * 1024
MAX_FILES = 10000
MAGIC = b"HCCENC01"


class FileEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: int = Field(ge=0, le=MAX_BYTES)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal[1]
    application: str = Field(min_length=1, max_length=32)
    schema_revision: str = Field(alias="schema", pattern=r"^[A-Za-z0-9_-]{1,100}$", strict=True)
    installation: str = Field(min_length=1, max_length=128, strict=True)
    id: str = Field(pattern=r"^[a-f0-9]{32}$", strict=True)
    created_at: AwareDatetime
    files: dict[str, FileEntry] = Field(min_length=1, max_length=MAX_FILES)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)
    operator_login: str | None = Field(default=None, max_length=64, strict=True)


class ArchiveError(ValueError):
    """Safe error suitable for displaying locally."""


def _key(password: str, salt: bytes) -> bytes:
    if not password or len(password) > 4096:
        raise ArchiveError("Введите ключ архива")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())


def encrypt_archive(snapshot: bytes, password: str) -> bytes:
    salt, nonce = os.urandom(16), os.urandom(12)
    header = MAGIC + salt + nonce
    return header + AESGCM(_key(password, salt)).encrypt(nonce, snapshot, header)


def decrypt_archive(blob: bytes, password: str) -> bytes:
    if len(blob) > MAX_BYTES or len(blob) < 52 or blob[:8] != MAGIC:
        raise ArchiveError("Неверный формат или превышен предел архива 512 МиБ")
    try:
        return AESGCM(_key(password, blob[8:24])).decrypt(blob[24:36], blob[36:], blob[:36])
    except InvalidTag:
        raise ArchiveError("Неверный ключ или архив повреждён") from None


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _verify_db(path: Path) -> str:
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ArchiveError("Проверка целостности SQLite не пройдена")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ArchiveError("Нарушена целостность связей базы")
        try:
            versions = db.execute("SELECT version_num FROM alembic_version").fetchall()
        except sqlite3.Error:
            raise ArchiveError("В базе отсутствует версия схемы") from None
        if len(versions) != 1:
            raise ArchiveError("Неоднозначная версия схемы")
        return str(versions[0][0])


def create_snapshot(data: Path, installation: str) -> bytes:
    """Caller holds the application operation fence; SQLite uses its backup API."""
    database = data / "hackathon.db"
    if not database.is_file() or database.is_symlink():
        raise ArchiveError("База данных не найдена")
    if database.stat().st_size > MAX_BYTES:
        raise ArchiveError("База превышает предел снимка 512 МиБ")
    with tempfile.TemporaryDirectory(prefix=".hcc-snapshot-", dir=data) as temporary:
        snapshot = Path(temporary) / "database.sqlite"
        with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(snapshot)) as destination:
                source.backup(destination, pages=256, sleep=0.05)
        schema = _verify_db(snapshot)
        operator_login: str | None = None
        with closing(sqlite3.connect(snapshot)) as metadata_db:
            tables = {row[0] for row in metadata_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if {"users", "role_assignments"}.issubset(tables):
                original = metadata_db.execute("SELECT u.login FROM users u JOIN role_assignments r ON r.user_id=u.id WHERE r.role='admin' AND r.project_id IS NULL ORDER BY r.id LIMIT 1").fetchone()
                operator_login = original[0] if original else None
        content = {"database.sqlite": snapshot.read_bytes()}
        total = len(content["database.sqlite"])
        documents = data / "documents"
        if documents.is_symlink():
            raise ArchiveError("Ссылки в папке документов не поддерживаются")
        if documents.exists():
            for path in sorted(documents.rglob("*")):
                if path.is_symlink():
                    raise ArchiveError("Ссылки в документах не поддерживаются")
                if path.is_file():
                    total += path.stat().st_size
                    if total > MAX_BYTES or len(content) >= MAX_FILES:
                        raise ArchiveError("Превышен предел снимка: 512 МиБ / 10000 файлов")
                    content[path.relative_to(data).as_posix()] = path.read_bytes()
        files = {name: {"sha256": _hash(value), "size": len(value)} for name, value in content.items()}
        manifest = {
            "format": 1, "application": VERSION, "schema": schema, "installation": installation,
            "id": uuid.uuid4().hex, "created_at": datetime.now(timezone.utc).isoformat(), "files": files,
            "fingerprint": _hash(json.dumps(files, sort_keys=True).encode()),
            "operator_login": operator_login,
        }
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            for name, value in content.items():
                archive.writestr(name, value)
        result = stream.getvalue()
        inspect_snapshot(result)
        return result


def inspect_snapshot(blob: bytes) -> dict[str, Any]:
    if len(blob) > MAX_BYTES:
        raise ArchiveError("Архив превышает предел 512 МиБ")
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(infos) > MAX_FILES + 1 or len(set(names)) != len(names):
                raise ArchiveError("Повторяющиеся файлы или превышен предел количества файлов")
            if sum(info.file_size for info in infos) > MAX_BYTES:
                raise ArchiveError("Превышен предел распаковки 512 МиБ")
            for info in infos:
                path = PurePosixPath(info.filename)
                if (path.is_absolute() or ".." in path.parts or ":" in info.filename
                        or "\\" in info.filename or stat.S_ISLNK(info.external_attr >> 16)
                        or info.filename != path.as_posix() or info.is_dir()):
                    raise ArchiveError("Опасный путь или ссылка в архиве")
                if info.filename not in {"manifest.json", "database.sqlite"} and not info.filename.startswith("documents/"):
                    raise ArchiveError("Неизвестное содержимое архива")
            if archive.getinfo("manifest.json").file_size > 4 * 1024 * 1024:
                raise ArchiveError("Слишком большой манифест")
            manifest = json.loads(archive.read("manifest.json"))
            if not isinstance(manifest, dict):
                raise ArchiveError("Манифест должен быть объектом")
            if manifest.get("format") != 1 or manifest.get("application") != VERSION:
                raise ArchiveError("Несовместимая версия поставки; используйте версию из архива")
            manifest = Manifest.model_validate(manifest).model_dump(mode="json", by_alias=True)
            files = manifest["files"]
            if not isinstance(files, dict) or set(files) != set(names) - {"manifest.json"} or "database.sqlite" not in files:
                raise ArchiveError("Состав архива не соответствует манифесту")
            for name, metadata in files.items():
                value = archive.read(name)
                if len(value) != metadata["size"] or _hash(value) != metadata["sha256"]:
                    raise ArchiveError("Контрольная сумма не совпала")
            if manifest["fingerprint"] != _hash(json.dumps(files, sort_keys=True).encode()):
                raise ArchiveError("Контрольная сумма манифеста не совпала")
            return manifest
    except (zipfile.BadZipFile, KeyError, TypeError, ValueError, RuntimeError, OSError) as exc:
        if isinstance(exc, ArchiveError):
            raise
        raise ArchiveError("Повреждённый или неполный архив") from None


def restore_snapshot(blob: bytes, data: Path, compatible: set[str]) -> bytes:
    """Only called with the platform stopped. Roll back BOTH database and documents."""
    manifest = inspect_snapshot(blob)
    if manifest["schema"] not in compatible:
        raise ArchiveError("Несовместимая схема базы; нужна соответствующая версия приложения")
    data.mkdir(parents=True, exist_ok=True)
    if data.is_symlink() or (data / "documents").is_symlink():
        raise ArchiveError("Восстановление в символические ссылки запрещено")
    safety = create_snapshot(data, "safety") if (data / "hackathon.db").exists() else b""
    required = sum(item["size"] for item in manifest["files"].values())
    if shutil.disk_usage(data).free < required * 2 + 64 * 1024 * 1024:
        raise ArchiveError("Недостаточно места для безопасного восстановления")
    with tempfile.TemporaryDirectory(prefix=".hcc-restore-", dir=data) as temporary:
        staging = Path(temporary)
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            for name in manifest["files"]:
                destination = staging / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(name))
        if _verify_db(staging / "database.sqlite") != manifest["schema"]:
            raise ArchiveError("Версия схемы не соответствует манифесту")
        (staging / "documents").mkdir(exist_ok=True)
        # All displaced SQLite sidecars stay with the rollback database.
        displaced: list[tuple[Path, Path]] = []
        installed: list[Path] = []
        try:
            for name in ("hackathon.db", "hackathon.db-wal", "hackathon.db-shm", "documents"):
                current = data / name
                if current.exists():
                    saved = staging / ("old-" + name)
                    current.replace(saved)
                    displaced.append((saved, current))
            for source, destination in ((staging / "database.sqlite", data / "hackathon.db"),
                                        (staging / "documents", data / "documents")):
                source.replace(destination)
                installed.append(destination)
        except BaseException:
            for destination in installed:
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink(missing_ok=True)
            for saved, destination in reversed(displaced):
                saved.replace(destination)
            raise
    return safety
