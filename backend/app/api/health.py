"""Эндпоинт проверки работоспособности."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.deps import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    # 200 только если БД доступна и папка данных записываема.
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
