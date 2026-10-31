"""Maintenance entrypoint executed in the platform image, without API or schedulers."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path

from control.archives import create_snapshot, restore_snapshot, inspect_snapshot, encrypt_archive
from control.locking import FileLock
from control.vault import atomic_write


def schemas() -> set[str]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    backend = Path(__file__).resolve().parents[1] / "backend"
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    return {revision.revision for revision in ScriptDirectory.from_config(cfg).walk_revisions()}


def suspend_external_actions(data: Path, snapshot_at: str) -> None:
    """Snapshot state cannot prove delivery or provider usage after its timestamp."""
    with closing(sqlite3.connect(data / "hackathon.db")) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "advisor_jobs" in tables:
            db.execute("UPDATE advisor_jobs SET state='failed', error_code='RESTORED_INSTALLATION', lease_token=NULL, lease_until=NULL WHERE state IN ('queued','running','retry','waiting')")
        if "telegram_deliveries" in tables:
            db.execute("UPDATE telegram_deliveries SET state='uncertain', error_code='RESTORED_INSTALLATION', lease_token=NULL, lease_until=NULL WHERE state IN ('pending','sending')")
        if "ai_settings" in tables:
            db.execute("UPDATE ai_settings SET enabled=0, auto_enabled=0")
        if "sessions" in tables:
            db.execute("DELETE FROM sessions")
        cutoff = datetime.fromisoformat(snapshot_at).astimezone(timezone.utc).replace(tzinfo=None)
        if "task_timers" in tables:
            for timer_id, accumulated, started in db.execute("SELECT id,accumulated_seconds,last_started_at FROM task_timers WHERE state='running'").fetchall():
                start = datetime.fromisoformat(started).replace(tzinfo=None) if started else cutoff
                elapsed = max(0, int((cutoff - start).total_seconds()))
                db.execute("UPDATE task_timers SET state='paused', accumulated_seconds=?, last_started_at=NULL WHERE id=?", (accumulated + elapsed, timer_id))
        if "timer_segments" in tables:
            db.execute("UPDATE timer_segments SET ended_at=? WHERE ended_at IS NULL", (cutoff.isoformat(sep=" "),))
        db.commit()
    # Requires explicit activation AND quota reconciliation in the local panel.
    (data / ".transfer-pending").write_text("External actions suspended after restore\n", encoding="utf-8")
    (data / ".ai-not-before").write_text(str(time.time() + 86400), encoding="ascii")


def main() -> None:
    data = Path(os.environ.get("APP_DATA_DIR", "/data"))
    operation, identity = sys.argv[1:3]
    if operation == "schemas":
        print(json.dumps(sorted(schemas())))
        return
    with FileLock(data / ".hcc-operation.lock"):
        if operation == "snapshot":
            sys.stdout.buffer.write(create_snapshot(data, identity))
        elif operation == "restore":
            with FileLock(data / ".server.lock", blocking=False):
                blob = sys.stdin.buffer.read(512 * 1024 * 1024 + 1)
                manifest = inspect_snapshot(blob)
                if (data / "hackathon.db").exists():
                    key = (Path(os.environ["APP_SECRETS_DIR"]) / "operator").read_text()
                    if not key:
                        raise ValueError("A recovery key is required for the safety copy")
                    safety = create_snapshot(data, identity)
                    atomic_write(data / "restore-safety" / f"before-{time.time_ns()}.hcc", encrypt_archive(safety, key))
                restore_snapshot(blob, data, schemas())
                suspend_external_actions(data, manifest["created_at"])
        elif operation == "transfer":
            with FileLock(data / ".server.lock", blocking=False):
                (data / ".transfer-pending").unlink(missing_ok=True)
        else:
            raise ValueError("Unsupported maintenance operation")


if __name__ == "__main__":
    main()
