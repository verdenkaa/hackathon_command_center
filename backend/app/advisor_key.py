"""Local protected input: python -m app.advisor_key [set|delete|status]."""
import getpass
import sys

from fastapi import HTTPException

from app.db.session import SessionLocal
from app.deps import project_roles
from app.db.models import Role
from app.security import hash_token
from app.services.auth_service import authenticate, revoke_session
from app.services import advisor_vault as vault


def main() -> int:
    action = sys.argv[1] if len(sys.argv) == 2 else 'set'
    if action not in ('set', 'delete', 'status'):
        print('Использование: python -m app.advisor_key [set|delete|status]')
        return 1
    if not vault.available() or not sys.stdin.isatty():
        print('Требуется интерактивная консоль Windows под учётной записью сервера.')
        return 1
    try:
        with SessionLocal() as db:
            user, token = authenticate(db, input('Логин администратора: '),
                getpass.getpass('Пароль администратора: '), '127.0.0.1', 'local-key-console')
            revoke_session(db, hash_token(token))
            if Role.admin not in project_roles(db, user.id, None):
                print('Требуется роль администратора.')
                return 1
        if action == 'set':
            vault.save(getpass.getpass('Ключ Gemini (ввод скрыт): '))
        elif action == 'delete':
            vault.delete()
        print('Ключ сохранён.' if vault.is_saved() else 'Ключ не задан.')
        return 0
    except (vault.VaultUnavailable, HTTPException, OSError):
        print('Операция не выполнена. Проверьте вход и доступ к хранилищу Windows.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
