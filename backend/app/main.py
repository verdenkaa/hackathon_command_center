"""Точка входа FastAPI-приложения."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    admin,
    ai,
    analytics,
    audit,
    auth,
    dashboard,
    documents,
    health,
    incidents,
    notifications,
    operations,
    projects,
    sandbox,
    tasks,
    timers,
)
from app.api.errors import register_error_handlers
from app.config import settings
from app.db.session import SessionLocal

BACKEND_DIR = Path(__file__).resolve().parents[1]


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


def stamp_head() -> None:
    """Помечает текущую схему как актуальную без запуска DDL (для восстановления)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.stamp(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    from app.services.bootstrap import bootstrap

    db = SessionLocal()
    try:
        bootstrap(db)
    finally:
        db.close()

    import threading

    stop = threading.Event()
    thread = threading.Thread(target=_scheduler_loop, args=(stop,), daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()


def _scheduler_loop(stop) -> None:
    import time

    from app.services import backup as backup_svc
    from app.services import jobs

    last_backup = time.time()  # первый автоматический бэкап — через 15 минут, не сразу
    while not stop.is_set():
        stop.wait(60)
        try:
            db = SessionLocal()
            try:
                jobs.run_all_jobs(db)
                now = time.time()
                if now - last_backup >= 900:  # 15 минут
                    backup_svc.create_backup(db, kind="automatic")
                    last_backup = now
            finally:
                db.close()
        except Exception:  # noqa: BLE001 — фоновая задача не должна ронять сервер
            pass


def create_app() -> FastAPI:
    app = FastAPI(title="Hackathon Command Center", lifespan=lifespan)
    register_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(audit.router, prefix="/api/v1")
    app.include_router(projects.router, prefix="/api/v1")
    app.include_router(tasks.router, prefix="/api/v1")
    app.include_router(timers.router, prefix="/api/v1")
    app.include_router(dashboard.router, prefix="/api/v1")
    app.include_router(incidents.router, prefix="/api/v1")
    app.include_router(notifications.router, prefix="/api/v1")
    app.include_router(documents.router, prefix="/api/v1")
    app.include_router(ai.router, prefix="/api/v1")
    app.include_router(operations.router, prefix="/api/v1")
    app.include_router(sandbox.router, prefix="/api/v1")
    app.include_router(analytics.router, prefix="/api/v1")
    return app


app = create_app()
