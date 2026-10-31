"""Инициализация первого администратора и проекта по умолчанию."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Project, ProjectState, Role, RoleAssignment, User
from app.security import hash_password
from app.services.audit import write_audit
from app.services.board import create_default_columns


def bootstrap(db: Session) -> User | None:
    if settings.app_managed and db.query(Project).count() > 1:
        raise RuntimeError('Разделите старую базу на проекты через Ouroboros Daemon')
    if db.query(User).count() > 0:
        if settings.app_managed and db.query(Project).count() == 0:
            project = Project(name=settings.app_project_name, state=ProjectState.preparation)
            db.add(project)
            db.flush()
            create_default_columns(db, project.id)
            db.commit()
        return None
    password = settings.secret_value("bootstrap_password") if settings.app_managed else settings.app_first_admin_password
    if settings.app_managed and len(password) < 32:
        raise RuntimeError("Задайте случайный ключ оператора через локальную панель; стандартный пароль запрещён")
    admin = User(
        login=settings.app_first_admin_login,
        password_hash=hash_password(password),
        display_name=settings.app_first_admin_name,
        active=True,
    )
    db.add(admin)
    db.flush()
    project = Project(name=settings.app_project_name if settings.app_managed else 'Hackathon', state=ProjectState.preparation)
    db.add(project)
    db.flush()
    create_default_columns(db, project.id)
    db.add(RoleAssignment(user_id=admin.id, role=Role.admin, project_id=None, granted_by=admin.id))
    write_audit(
        db,
        action="bootstrap.admin_created",
        actor_id=admin.id,
        entity_type="user",
        entity_id=admin.id,
        data={"login": admin.login, "project_id": project.id if project else None},
    )
    db.commit()
    return admin
