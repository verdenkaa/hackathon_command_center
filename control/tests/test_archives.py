from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

from control.archives import ArchiveError, create_snapshot, decrypt_archive, encrypt_archive, inspect_snapshot, restore_snapshot


def data_at(path: Path, text: str = "before") -> Path:
    path.mkdir()
    with closing(sqlite3.connect(path / "hackathon.db")) as db:
        db.execute("CREATE TABLE alembic_version (version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('test-schema')")
        db.execute("CREATE TABLE content (value TEXT)")
        db.execute("INSERT INTO content VALUES (?)", (text,))
        db.commit()
    (path / "documents").mkdir()
    (path / "documents" / "note.md").write_text(text)
    (path / "secret.dpapi").write_text("EXCLUDED_SECRET")
    (path / "backups").mkdir()
    (path / "backups" / "old.zip").write_text("EXCLUDED_BACKUP")
    return path


def test_encryption_authenticates_and_never_contains_key_or_plaintext(tmp_path):
    snapshot = create_snapshot(data_at(tmp_path / "source"), "installation-1")
    encrypted = encrypt_archive(snapshot, "operator-key" * 4)
    assert b"EXCLUDED_SECRET" not in snapshot
    assert b"operator-key" not in encrypted
    assert decrypt_archive(encrypted, "operator-key" * 4) == snapshot
    with pytest.raises(ArchiveError):
        decrypt_archive(encrypted, "wrong-key")
    with pytest.raises(ArchiveError):
        decrypt_archive(encrypted[:-1] + bytes([encrypted[-1] ^ 1]), "operator-key" * 4)


def test_change_detection_is_content_based_and_excludes_backup_metadata(tmp_path):
    data = data_at(tmp_path / "source")
    one = inspect_snapshot(create_snapshot(data, "installation-1"))
    two = inspect_snapshot(create_snapshot(data, "installation-1"))
    assert one["fingerprint"] == two["fingerprint"]
    (data / "documents" / "note.md").write_text("changed by background worker")
    three = inspect_snapshot(create_snapshot(data, "installation-1"))
    assert three["fingerprint"] != one["fingerprint"]
    assert one["schema"] == "test-schema"


def test_restore_round_trip_and_safety_copy(tmp_path):
    source = data_at(tmp_path / "source", "restored")
    target = data_at(tmp_path / "target", "current")
    snapshot = create_snapshot(source, "source-installation")
    safety = restore_snapshot(snapshot, target, {"test-schema"})
    assert (target / "documents" / "note.md").read_text() == "restored"
    with closing(sqlite3.connect(target / "hackathon.db")) as db:
        assert db.execute("SELECT value FROM content").fetchone()[0] == "restored"
    assert inspect_snapshot(safety)["schema"] == "test-schema"
    assert (target / "secret.dpapi").read_text() == "EXCLUDED_SECRET"


@pytest.mark.parametrize("name", ["../escape", "/absolute", "documents/../../escape", "C:/escape", "documents\\escape", "documents/link"])
def test_unsafe_or_unlisted_paths_are_rejected(name):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": 1, "files": {}}))
        info = zipfile.ZipInfo(name)
        if name.endswith("link"):
            info.external_attr = 0o120777 << 16
        archive.writestr(info, "bad")
    with pytest.raises(ArchiveError):
        inspect_snapshot(stream.getvalue())


def test_unknown_schema_does_not_touch_current_data(tmp_path):
    snapshot = create_snapshot(data_at(tmp_path / "source"), "installation-1")
    target = data_at(tmp_path / "target", "current")
    with pytest.raises(ArchiveError):
        restore_snapshot(snapshot, target, {"other-schema"})
    assert (target / "documents" / "note.md").read_text() == "current"


@pytest.mark.parametrize('field,value', [('created_at','invalid-date'),('schema',['invalid']),('id','../unsafe'),('installation',None)])
def test_manifest_metadata_is_validated_before_restore(tmp_path, field, value):
    snapshot = create_snapshot(data_at(tmp_path / 'source'), 'installation-1')
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(snapshot)) as original, zipfile.ZipFile(output,'w') as modified:
        for name in original.namelist():
            contents = original.read(name)
            if name == 'manifest.json':
                manifest = json.loads(contents)
                manifest[field] = value
                contents = json.dumps(manifest).encode()
            modified.writestr(name,contents)
    with pytest.raises(ArchiveError):
        inspect_snapshot(output.getvalue())


def test_failed_replace_rolls_back_database_and_documents(tmp_path, monkeypatch):
    snapshot = create_snapshot(data_at(tmp_path / "source", "restored"), "installation-1")
    target = data_at(tmp_path / "target", "current")
    original = Path.replace
    failed = False

    def fail_once(self, dst):
        nonlocal failed
        if Path(dst) == target / "documents" and not failed:
            failed = True
            raise OSError("simulated disk failure")
        return original(self, dst)

    monkeypatch.setattr(Path, "replace", fail_once)
    with pytest.raises(OSError):
        restore_snapshot(snapshot, target, {"test-schema"})
    assert (target / "documents" / "note.md").read_text() == "current"
    with closing(sqlite3.connect(target / "hackathon.db")) as db:
        assert db.execute("SELECT value FROM content").fetchone()[0] == "current"
