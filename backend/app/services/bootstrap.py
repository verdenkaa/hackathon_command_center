"""Инициализация первого администратора и проекта по умолчанию."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Project, ProjectState, Role, RoleAssignment, User
from app.security import hash_password
from app.services.audit import write_audit
from app.services.board import create_default_columns


def bootstrap(db: Session) -> User | None:
    if db.query(User).count() > 0:
        return None
    admin = User(
        login=settings.app_first_admin_login,
        password_hash=hash_password(settings.app_first_admin_password),
        display_name=settings.app_first_admin_name,
        active=True,
    )
    db.add(admin)
    db.flush()
    project = Project(name="Hackathon", state=ProjectState.preparation)
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
        data={"login": admin.login, "project_id": project.id},
    )
    db.commit()
    return admin
