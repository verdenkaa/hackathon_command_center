"""Populated pre-advisor SQLite upgrades preserve existing recommendation history."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_populated_database_upgrade(tmp_path):
    path = tmp_path / 'migration.db'
    env = {**os.environ, 'DATABASE_URL': f'sqlite:///{path.as_posix()}', 'APP_DATA_DIR': str(tmp_path)}
    backend = Path(__file__).resolve().parents[1]
    def upgrade(revision):
        process = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', revision],
                                 cwd=backend, env=env, capture_output=True, text=True, timeout=60)
        assert process.returncode == 0, process.stderr
    upgrade('20261028_project_start')
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO projects (id,name,state,settings,incident_counter,created_at) VALUES (1,'Preserved','active','{}',0,CURRENT_TIMESTAMP)")
        db.execute("INSERT INTO ai_settings (project_id,enabled,priority_provider,prompt,interval_minutes,triggers,created_at,updated_at) VALUES (1,1,'gemini','Keep prompt',30,'{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        db.execute("INSERT INTO ai_recommendations (project_id,provider,trigger,summary,content,excluded,created_at) VALUES (1,'gemini','manual','Keep summary','Keep history',1,CURRENT_TIMESTAMP)")
    upgrade('head')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT summary,content,excluded,status FROM ai_recommendations').fetchone() == ('Keep summary','Keep history',1,'unreviewed')
        assert db.execute('SELECT prompt,enabled,auto_enabled FROM ai_settings').fetchone() == ('Keep prompt',1,0)
        assert db.execute('SELECT rpd FROM advisor_provider_settings').fetchone() == (500,)
