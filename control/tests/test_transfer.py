from contextlib import closing
import sqlite3
from pathlib import Path

from control.worker import suspend_external_actions


def test_transfer_suspends_queues_disables_ai_and_pauses_timers_at_snapshot(tmp_path):
    with closing(sqlite3.connect(tmp_path / "hackathon.db")) as db:
        db.executescript("""
        CREATE TABLE advisor_jobs(state TEXT,error_code TEXT,lease_token TEXT,lease_until TEXT);
        INSERT INTO advisor_jobs VALUES('running',NULL,'lease',NULL);
        CREATE TABLE telegram_deliveries(state TEXT,error_code TEXT,lease_token TEXT,lease_until TEXT);
        INSERT INTO telegram_deliveries VALUES('pending',NULL,'lease',NULL);
        CREATE TABLE ai_settings(enabled INTEGER,auto_enabled INTEGER);
        INSERT INTO ai_settings VALUES(1,1);
        CREATE TABLE task_timers(id INTEGER,state TEXT,accumulated_seconds INTEGER,last_started_at TEXT);
        INSERT INTO task_timers VALUES(1,'running',20,'2026-10-29 08:00:00');
        CREATE TABLE timer_segments(ended_at TEXT);
        INSERT INTO timer_segments VALUES(NULL);
        """)
    suspend_external_actions(tmp_path, "2026-10-29T08:01:00+00:00")
    with closing(sqlite3.connect(tmp_path / "hackathon.db")) as db:
        assert db.execute("SELECT state FROM advisor_jobs").fetchone() == ('failed',)
        assert db.execute("SELECT state FROM telegram_deliveries").fetchone() == ('uncertain',)
        assert db.execute("SELECT enabled,auto_enabled FROM ai_settings").fetchone() == (0,0)
        assert db.execute("SELECT state,accumulated_seconds,last_started_at FROM task_timers").fetchone() == ('paused',80,None)
    assert (tmp_path / ".transfer-pending").exists()
    assert (tmp_path / ".ai-not-before").is_file()
