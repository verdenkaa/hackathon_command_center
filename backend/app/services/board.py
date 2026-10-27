"""Доска: стартовые колонки и их разрешение."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import BoardColumn

# Точный стартовый порядок колонок (docs/02, agents_plan).
DEFAULT_COLUMNS: list[tuple[str, str]] = [
    ("backlog", "Backlog"),
    ("todo", "To Do"),
    ("specification_review", "Specification Review"),
    ("in_progress", "In Progress"),
    ("testing", "Testing"),
    ("review", "Review"),
    ("done", "Done"),
    ("realised", "Realised"),
    ("trashed", "Trashed"),
]

COLUMN_KEYS = [k for k, _ in DEFAULT_COLUMNS]


def create_default_columns(db: Session, project_id: int) -> None:
    for position, (key, title) in enumerate(DEFAULT_COLUMNS):
        db.add(BoardColumn(project_id=project_id, key=key, title=title, position=position))
    db.flush()


def get_column_by_key(db: Session, project_id: int, key: str) -> BoardColumn:
    column = (
        db.query(BoardColumn)
        .filter(BoardColumn.project_id == project_id, BoardColumn.key == key)
        .first()
    )
    if column is None:
        raise api_error(404, "COLUMN_NOT_FOUND", f"Колонка {key} не найдена")
    return column
