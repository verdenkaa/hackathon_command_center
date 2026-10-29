from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app import telegram_key
from app.config import settings
from app.db.models import Role, User


def interactive_console(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telegram_key.sys, 'argv', ['telegram_key', 'status'])
    monkeypatch.setattr(telegram_key.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(telegram_key.vault, 'available', lambda: True)


def test_console_upgrades_old_database_before_authentication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    interactive_console(monkeypatch)
    url = f"sqlite:///{(tmp_path / 'old.db').as_posix()}"
    monkeypatch.setattr(settings, 'database_url', url)
    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / 'alembic.ini'))
    cfg.set_main_option('script_location', str(backend / 'alembic'))
    command.upgrade(cfg, '20261028_advisor')
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO users (login,password_hash,display_name,active,created_at) VALUES ('existing','unchanged','Admin',1,CURRENT_TIMESTAMP)"))
    monkeypatch.setattr(telegram_key, 'SessionLocal', sessionmaker(bind=engine))

    def login_prompt(prompt: str) -> str:
        # Prompting must happen only after the schema is ready.
        with engine.connect() as db:
            assert db.execute(text('SELECT deleted_identity FROM users')).scalar_one() == 0
        return 'existing'

    def authenticate(db, login: str, password: str, ip: str, agent: str):
        user = db.query(User).filter(User.login == login).one()
        assert user.password_hash == 'unchanged'
        return user, 'session'

    monkeypatch.setattr('builtins.input', login_prompt)
    monkeypatch.setattr(telegram_key.getpass, 'getpass', lambda prompt: 'password')
    monkeypatch.setattr(telegram_key, 'authenticate', authenticate)
    monkeypatch.setattr(telegram_key, 'revoke_session', lambda *args: None)
    monkeypatch.setattr(telegram_key, 'project_roles', lambda *args: {Role.admin})
    monkeypatch.setattr(telegram_key.vault, 'is_saved', lambda: False)
    try:
        assert telegram_key.main() == 0
        assert telegram_key.main() == 0  # Repeated launch is safe.
        with engine.connect() as db:
            assert db.execute(text('SELECT login,password_hash FROM users')).one() == ('existing', 'unchanged')
            assert not db.execute(text('PRAGMA foreign_key_check')).all()
    finally:
        engine.dispose()


def test_migration_failure_stops_before_credentials(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    interactive_console(monkeypatch)
    from app import main

    def fail() -> None:
        raise OperationalError('private database path', {}, Exception('locked'))

    monkeypatch.setattr(main, 'run_migrations', fail)
    monkeypatch.setattr('builtins.input', lambda prompt: pytest.fail('Credentials requested before migration'))
    assert telegram_key.main() == 1
    output = capsys.readouterr().out
    assert 'миграц' in output.lower()
    assert 'private database path' not in output
