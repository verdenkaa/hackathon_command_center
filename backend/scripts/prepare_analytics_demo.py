"""Run from backend: ../.venv/Scripts/python.exe -m scripts.prepare_analytics_demo."""
from app.db.session import SessionLocal
from app.db.models import User, RoleAssignment, Role
from app.main import run_migrations
from app.services.analytics_demo import prepare_analytics_demo


def main() -> None:
    run_migrations()
    with SessionLocal() as db:
        admin=db.query(User).join(RoleAssignment,RoleAssignment.user_id==User.id).filter(
            RoleAssignment.role==Role.admin,RoleAssignment.revoked_at.is_(None),User.active.is_(True)).order_by(User.id).first()
        if admin is None:
            raise RuntimeError('Нужен активный администратор')
        project=prepare_analytics_demo(db,admin.id)
        print(f'Демо аналитики: проект #{project.id}, {project.name}')


if __name__=='__main__':
    main()
