"""Hidden local input; no secret in API bodies, command arguments or stdout."""
import getpass
import sys

from fastapi import HTTPException
from alembic.util.exc import CommandError
from sqlalchemy.exc import SQLAlchemyError
from app.db.session import SessionLocal
from app.db.models import Role
from app.deps import project_roles
from app.security import hash_token
from app.services.auth_service import authenticate, revoke_session
from app.services import telegram_vault as vault


def main() -> int:
    action = sys.argv[1] if len(sys.argv) == 2 else 'set'
    if action not in ('set', 'delete', 'status') or not vault.available() or not sys.stdin.isatty():
        print('Требуется интерактивная консоль Windows: python -m app.telegram_key [set|delete|status]')
        return 1
    try:
        from app.main import run_migrations

        run_migrations()
    except (CommandError, SQLAlchemyError, OSError):
        print('Не удалось применить миграции базы данных. Проверьте доступ к базе и повторите запуск.')
        return 1
    try:
        with SessionLocal() as db:
            user, token = authenticate(db, input('Логин администратора: '),
                getpass.getpass('Пароль администратора: '), '127.0.0.1', 'local-telegram-console')
            revoke_session(db, hash_token(token))
            if Role.admin not in project_roles(db, user.id, None):
                print('Требуется роль администратора.')
                return 1
        if action == 'set':
            vault.save(getpass.getpass('Токен Telegram (ввод скрыт): '))
        elif action == 'delete':
            vault.delete()
        print('Бот подключён.' if vault.is_saved() else 'Бот не подключён.')
        return 0
    except (vault.VaultUnavailable, HTTPException, OSError):
        print('Операция не выполнена. Проверьте вход, формат токена и хранилище Windows.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
