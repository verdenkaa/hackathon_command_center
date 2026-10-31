"""Точка входа FastAPI-приложения."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event
from contextlib import nullcontext

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
    planning,
    realtime,
    timers,
    telegram,
)
from app.api.errors import register_error_handlers
from app.config import settings
from app.db.session import SessionLocal
from app.services import realtime as _realtime  # Register transactional change tracking.

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
    from app.services.portable import preflight_migrations
    if settings.app_managed:
        from control.locking import FileLock
        instance_lock = FileLock(settings.data_dir / ".server.lock", blocking=False)
    else:
        instance_lock = nullcontext()
    with instance_lock:
        def startup_state(phase: str) -> None:
            if settings.app_managed:
                import json
                import time
                from control.vault import atomic_write
                atomic_write(settings.data_dir / ".startup-state.json", json.dumps({"phase": phase, "at": time.time()}).encode())
        try:
            startup_state("migrations")
            preflight_migrations()
            run_migrations()
            async with _running_services(app):
                startup_state("ready")
                yield
        except Exception:
            startup_state("failed")
            raise


@asynccontextmanager
async def _running_services(app: FastAPI):
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
    advisor_thread = threading.Thread(target=_advisor_loop, args=(stop,), daemon=True)
    advisor_thread.start()
    telegram_thread = threading.Thread(target=_telegram_loop, args=(stop,), daemon=True)
    telegram_thread.start()
    app.state.workers = [thread, advisor_thread, telegram_thread]
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)
        advisor_thread.join(timeout=100)
        telegram_thread.join(timeout=25)


def _telegram_loop(stop: Event) -> None:
    from app.services.telegram import work_once
    from app.services.portable import external_allowed, operation_lock
    while not stop.is_set():
        try:
            with operation_lock():
                worked = work_once(SessionLocal) if external_allowed() else False
        except Exception:
            worked = False
        stop.wait(0.1 if worked else 3)


def _advisor_loop(stop) -> None:
    from app.services import advisor
    from app.services.portable import ai_allowed, operation_lock
    while not stop.is_set():
        try:
            with operation_lock():
                if ai_allowed():
                    with SessionLocal() as db:
                        advisor.schedule(db)
                    worked = advisor.work_once(SessionLocal)
                else:
                    worked = False
        except Exception:
            # No raw provider/credential exceptions in logs. Leases recover interrupted jobs.
            worked = False
        stop.wait(1 if worked else 5)


def _scheduler_loop(stop) -> None:
    import time

    from app.services import backup as backup_svc
    from app.services import jobs
    from app.services.portable import operation_lock

    last_backup = time.time()  # первый автоматический бэкап — через 15 минут, не сразу
    while not stop.is_set():
        stop.wait(60)
        if stop.is_set():
            break
        try:
            db = SessionLocal()
            try:
                with operation_lock():
                    jobs.run_all_jobs(db)
                now = time.time()
                if not settings.app_managed and now - last_backup >= 900:  # managed backups belong to the independent control plane
                    backup_svc.create_backup(db, kind="automatic")
                    last_backup = now
            finally:
                db.close()
        except Exception:  # noqa: BLE001 — фоновая задача не должна ронять сервер
            pass


def create_app() -> FastAPI:
    app = FastAPI(title="Hackathon Command Center", lifespan=lifespan,
                  docs_url=None if settings.app_managed else "/docs",
                  redoc_url=None if settings.app_managed else "/redoc",
                  openapi_url=None if settings.app_managed else "/openapi.json")
    if settings.app_managed:
        import anyio
        from app.services.portable import operation_lock

        @app.middleware("http")
        async def maintenance_fence(request, call_next):
            if request.method in {"GET", "HEAD", "OPTIONS"}:
                return await call_next(request)
            lock = operation_lock()
            await anyio.to_thread.run_sync(lock.__enter__)
            try:
                return await call_next(request)
            finally:
                lock.__exit__(None, None, None)
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
    app.include_router(planning.router, prefix="/api/v1")
    app.include_router(realtime.router, prefix="/api/v1")
    app.include_router(timers.router, prefix="/api/v1")
    app.include_router(dashboard.router, prefix="/api/v1")
    app.include_router(incidents.router, prefix="/api/v1")
    app.include_router(notifications.router, prefix="/api/v1")
    app.include_router(documents.router, prefix="/api/v1")
    app.include_router(ai.router, prefix="/api/v1")
    app.include_router(telegram.router, prefix="/api/v1")
    app.include_router(operations.router, prefix="/api/v1")
    app.include_router(sandbox.router, prefix="/api/v1")
    app.include_router(analytics.router, prefix="/api/v1")
    if settings.app_static_dir:
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=settings.app_static_dir, html=True), name="frontend")
    return app


app = create_app()
