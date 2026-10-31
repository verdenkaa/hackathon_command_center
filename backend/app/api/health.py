"""Эндпоинт проверки работоспособности."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.deps import get_db
from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)):
    # 200 только если БД доступна и папка данных записываема.
    db.execute(text("SELECT 1"))
    if settings.app_managed:
        from app.services.portable import storage_ready
        if not storage_ready():
            return JSONResponse({"status": "degraded", "reason": "storage"}, status_code=503)
        workers = getattr(request.app.state, "workers", [])
        if any(not worker.is_alive() for worker in workers):
            return JSONResponse({"status": "degraded", "reason": "workers"}, status_code=503)
        return {"status": "ok", "installation": settings.app_installation_id}
    return {"status": "ok"}
