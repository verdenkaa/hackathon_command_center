import sqlite3
from pathlib import Path

import bcrypt

from control.controller import Controller


def account(data: Path, password: str, login: str = 'real_admin') -> None:
    data.mkdir()
    with sqlite3.connect(data / 'hackathon.db') as db:
        db.executescript('CREATE TABLE users(id INTEGER PRIMARY KEY,login TEXT,password_hash TEXT,active BOOLEAN,deleted_identity BOOLEAN); CREATE TABLE role_assignments(id INTEGER PRIMARY KEY,user_id INTEGER,role TEXT,project_id INTEGER);')
        db.execute('INSERT INTO users VALUES(1,?,?,1,0)', (login,bcrypt.hashpw(password.encode(),bcrypt.gensalt(rounds=4)).decode()))
        db.execute("INSERT INTO role_assignments VALUES(1,1,'admin',NULL)")


def test_attached_archive_key_is_never_presented_as_password(tmp_path):
    c = Controller(tmp_path)
    account(tmp_path/'data', 'actual-password')
    c.config.update(configured=True, mode='attach', data_dir=str(tmp_path/'data'), login='real_admin')
    c.vault.put('operator','archive-key-only')
    c.source_root = tmp_path
    result = c.credentials()
    assert result['password'] is None
    assert result['key'] == 'archive-key-only'
    assert 'неизвестен' in result['password_message']


def test_legacy_password_is_displayed_only_after_hash_verification(tmp_path):
    c = Controller(tmp_path)
    account(tmp_path/'data', 'actual-password')
    c.config.update(configured=True, mode='attach', data_dir=str(tmp_path/'data'), login='wrong-login')
    c.vault.put('operator','archive-key-only')
    c.source_root = tmp_path
    (tmp_path/'.env').write_text('APP_FIRST_ADMIN_PASSWORD=actual-password\n')
    result = c.credentials()
    assert result['login'] == 'real_admin'
    assert result['password'] == 'actual-password'
    assert result['password_verified'] is True
    # An account password change makes the displayed old password disappear.
    (tmp_path/'.env').write_text('APP_FIRST_ADMIN_PASSWORD=obsolete-password\n')
    assert c.credentials()['password'] is None


def test_new_installation_displays_actual_bootstrap_password(tmp_path):
    c = Controller(tmp_path)
    c.config.update(mode='new', configured=True)
    c.vault.put('operator','archive-key')
    c.vault.put('bootstrap_password','initial-password')
    result = c.credentials()
    assert result['password'] == 'initial-password'
    assert result['password_verified'] is False  # DB does not exist yet.
