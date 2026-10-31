import sqlite3

from control.projects import split_database


def test_split_preserves_source_and_excludes_other_project(tmp_path):
    source = tmp_path / 'source.db'
    with sqlite3.connect(source) as db:
        db.executescript('''
        CREATE TABLE projects(id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE users(id INTEGER PRIMARY KEY, login TEXT, password_hash TEXT);
        CREATE TABLE role_assignments(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), project_id INTEGER REFERENCES projects(id), role TEXT);
        CREATE TABLE tasks(id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES projects(id));
        CREATE TABLE checklist_items(id INTEGER PRIMARY KEY, task_id INTEGER REFERENCES tasks(id));
        INSERT INTO projects VALUES(1,'One'),(2,'Two');
        INSERT INTO users VALUES(1,'admin','hash'),(2,'first','hash2'),(3,'second','hash3');
        INSERT INTO role_assignments VALUES(1,1,NULL,'admin'),(2,2,1,'participant'),(3,3,2,'participant');
        INSERT INTO tasks VALUES(1,1),(2,2);
        INSERT INTO checklist_items VALUES(1,1),(2,2);
        ''')
    target = tmp_path / 'target.db'
    split_database(source, target, 1)
    with sqlite3.connect(target) as db:
        assert db.execute('SELECT id FROM projects').fetchall() == [(1,)]
        assert db.execute('SELECT id FROM checklist_items').fetchall() == [(1,)]
        assert db.execute('SELECT login,password_hash FROM users ORDER BY id').fetchall() == [('admin','hash'),('first','hash2')]
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    with sqlite3.connect(source) as db:
        assert db.execute('SELECT count(*) FROM projects').fetchone()[0] == 2
