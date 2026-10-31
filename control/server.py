"""Loopback-only API. Local capability + HttpOnly session + strict Origin/Host."""
from __future__ import annotations

import json
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from control.archives import MAX_BYTES, ArchiveError, decrypt_archive, inspect_snapshot
from control.manager import PlatformManager
from control.docker import DockerError
from control.vault import VaultError
from control.telegram import DeliveryError
from control import autostart, dependencies

STATIC = Path(__file__).parent / "static"


class SessionRequest(BaseModel):
    token: str = Field(max_length=256)


class SetupRequest(BaseModel):
    data_dir: str = Field(min_length=1, max_length=2048)
    mode: Literal["new", "attach"]
    login: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")


class UnlockRequest(BaseModel):
    passphrase: str = Field(min_length=16, max_length=4096)


class SettingsRequest(BaseModel):
    external_folder: str = Field(default="", max_length=2048)
    telegram_chat: str = Field(default="", pattern=r"^-?\d{1,24}$|^$")
    telegram_thread: int | None = Field(default=None, gt=0)
    telegram_alert_chat: str = Field(default='', pattern=r'^-?\d{1,24}$|^$')
    telegram_alert_thread: int | None = Field(default=None, gt=0)
    administrator: str = Field(default='', pattern=r'^@?[A-Za-z0-9_]{5,32}$|^$')
    telegram: str = Field(default="", max_length=256)
    gemini: str = Field(default="", max_length=4096)


class TunnelRequest(BaseModel):
    fxtunnel: str = Field(default="", max_length=4096)
    subdomain: str = Field(default="", pattern=r"^[a-z0-9-]{0,63}$")


class RestoreRequest(BaseModel):
    ticket: str = Field(max_length=128)
    confirm: bool = False


class ActivationRequest(BaseModel):
    previous_server_stopped: bool = False
    accept_quota_pause: bool = False


class AutostartRequest(BaseModel):
    enabled: bool


class NewPlatformRequest(BaseModel):
    folder: str = Field(min_length=1, max_length=2048)
    name: str = Field(min_length=1, max_length=80)
    login: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')


class SelectPlatformRequest(BaseModel):
    identity: str = Field(pattern=r'^[a-f0-9]{1,32}$')
    start: bool = True


def create_app(root: Path, *, token: str, background: bool = True) -> FastAPI:
    controller = PlatformManager(root)
    sessions: set[str] = set()
    pending: dict[str, tuple[float, bytes, str]] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        worker = threading.Thread(target=controller.loop, daemon=True, name="hcc-control-monitor")
        if background:
            worker.start()
        try:
            yield
        finally:
            controller.stop_event.set()
            if background:
                worker.join(timeout=5)
            controller.docker.close()
            controller.tunnel.stop()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.controller = controller
    app.state.on_shutdown = lambda: None
    app.state.show_window = lambda: None

    @app.middleware("http")
    async def security(request: Request, call_next):
        host = request.headers.get("host", "")
        if host not in {"127.0.0.1:8787", "localhost:8787"}:
            return JSONResponse({"detail": "Недопустимый Host"}, status_code=403)
        if request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            return JSONResponse({"detail": "Панель доступна только локально"}, status_code=403)
        if request.method not in {"GET", "HEAD"}:
            if request.headers.get("origin") != "http://" + host:
                return JSONResponse({"detail": "Запрос со стороннего сайта отклонён"}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path != "/api/session":
            if request.cookies.get("hcc_control") not in sessions:
                return JSONResponse({"detail": "Откройте панель через start.bat / start.sh"}, status_code=401)
        length = request.headers.get("content-length")
        if length and (not length.isdecimal() or int(length) > MAX_BYTES + 1024 * 1024):
            return JSONResponse({"detail": "Превышен предел загрузки"}, status_code=413)
        if request.url.path == "/api/restore/inspect" and not length:
            return JSONResponse({"detail": "Требуется размер загружаемого файла"}, status_code=411)
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
        return response

    @app.exception_handler(RequestValidationError)
    async def validation(_: Request, __: RequestValidationError):
        return JSONResponse({"detail": "Проверьте формат введённых полей"}, status_code=422)

    for exception_type in (ArchiveError, VaultError, DockerError, DeliveryError):
        @app.exception_handler(exception_type)
        async def safe_error(_: Request, exc: Exception):
            return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/static/{name}")
    def asset(name: Literal["panel.js", "panel.css"]):
        return FileResponse(STATIC / name)

    @app.get('/static/icons/{name}')
    def icon(name: Literal['docker.png','fxtunnel.png','gemini.png','telegram.png']):
        return FileResponse(STATIC / 'icons' / name)

    @app.post("/api/session")
    def session(body: SessionRequest, response: Response):
        if not secrets.compare_digest(body.token, token):
            raise HTTPException(401, "Неверный локальный ключ панели")
        value = secrets.token_urlsafe(32)
        if len(sessions) >= 32:
            sessions.clear()
        sessions.add(value)
        response.set_cookie("hcc_control", value, httponly=True, samesite="strict", max_age=86400)
        return {"status": "ok"}

    @app.get("/api/status")
    def status():
        result = controller.view()
        result["autostart"] = autostart.enabled(controller.registry['host_id'])
        dependency_file = controller.folder / "dependencies.json"
        result["dependencies"] = json.loads(dependency_file.read_text()) if dependency_file.exists() else None
        return result

    @app.post("/api/autostart")
    def set_autostart(body: AutostartRequest):
        autostart.set_enabled(root, controller.registry['host_id'], body.enabled)
        controller.persist()
        return {"enabled": autostart.enabled(controller.registry['host_id'])}

    @app.post('/api/platforms/new')
    def new_platform(body: NewPlatformRequest):
        return {'identity': controller.create(body.folder, body.name, body.login)}

    @app.post('/api/platforms/select')
    def select_platform(body: SelectPlatformRequest):
        controller.select(body.identity, start=body.start)
        pending.clear()
        return {'status': 'ok'}

    @app.post('/api/window/show')
    def show_window():
        app.state.show_window()
        return {'status':'ok'}

    @app.post('/api/shutdown')
    def shutdown():
        controller.shutdown()
        threading.Timer(.3, app.state.on_shutdown).start()
        return {'status':'stopped'}

    @app.post("/api/dependencies/check")
    def check_dependencies():
        from control.vault import atomic_write
        result = dependencies.inspect(controller.docker)
        atomic_write(controller.folder / "dependencies.json", json.dumps(result).encode())
        return result

    @app.post("/api/dependencies/install", status_code=202)
    def install_dependencies():
        if controller.busy:
            raise ArchiveError("Другая операция ещё выполняется")
        def install():
            if not controller.lock.acquire(blocking=False):
                return
            controller.busy = "Установка компонентов"
            try:
                controller.event(dependencies.install_one_step(controller.docker, controller.folder / "dependencies.json"))
            except (DockerError, OSError) as exc:
                controller.event(str(exc) if isinstance(exc, DockerError) else "Установка не завершена. Проверьте системные права и свободное место.", "error")
            finally:
                controller.busy = ""
                controller.lock.release()
        threading.Thread(target=install, daemon=True).start()
        return {"status": "accepted"}

    @app.post("/api/unlock")
    def unlock(body: UnlockRequest):
        controller.vault.unlock(body.passphrase)
        controller.resume_pending = True
        return {"status": "ok"}

    @app.post("/api/setup")
    def setup(body: SetupRequest):
        try:
            controller.setup(body.data_dir, body.mode, body.login)
        except FileExistsError as exc:
            raise HTTPException(409, str(exc)) from None
        return {"status": "ok"}

    @app.post("/api/settings")
    def settings(body: SettingsRequest):
        if body.external_folder:
            folder = Path(body.external_folder).expanduser().resolve()
            if not folder.is_dir() or folder.is_relative_to(Path(controller.config["data_dir"]).resolve()) or folder.is_relative_to(controller.folder):
                raise ArchiveError("Выберите существующую отдельную папку внешних копий вне данных и панели")
        for name in ("telegram", "gemini"):
            value = getattr(body, name)
            if value:
                controller.vault.put(name, value)
        if (controller.config.get('telegram_chat'), controller.config.get('telegram_thread')) != (body.telegram_chat, body.telegram_thread):
            controller.history.update(telegram_id='', telegram_attempt=0, telegram_error=None)
        if body.telegram:
            controller.history.update(telegram_attempt=0, telegram_error=None)
        if (controller.config.get('telegram_alert_chat'), controller.config.get('telegram_alert_thread')) != (body.telegram_alert_chat, body.telegram_alert_thread):
            controller.history.update(alert_outbox=[], alert_retry_at=0, alert_error=None, service_states={})
        controller.config.update(external_folder=body.external_folder, telegram_chat=body.telegram_chat,
                                 telegram_thread=body.telegram_thread, telegram_alert_chat=body.telegram_alert_chat,
                                 telegram_alert_thread=body.telegram_alert_thread, administrator=body.administrator.lstrip('@'))
        controller.persist()
        return {"status": "ok", "message": "Секреты сохранены локально. Для обновления секретов контейнера выполните перезапуск."}

    @app.post("/api/tunnel/settings")
    def tunnel_settings(body: TunnelRequest):
        if body.fxtunnel:
            controller.vault.put("fxtunnel", body.fxtunnel)
        controller.config["subdomain"] = body.subdomain or 'dots-bots-hub'
        if controller.config['desired'] and controller.vault.get('fxtunnel'):
            controller.config['tunnel_desired'] = True
            controller.tunnel_attempts = 0
            controller.last_tunnel_attempt = 0.0
        controller.persist()
        return {"status": "ok"}

    @app.post("/api/operator")
    def operator():
        return controller.credentials()

    @app.post("/api/action/{action}", status_code=202)
    def action(action: Literal["start", "stop", "restart", "build", "check", "backup", "telegram", "telegram-test", "tunnel-start", "tunnel-stop"]):
        with controller.state_lock:
            if controller.busy:
                raise HTTPException(409, "Дождитесь завершения текущей операции")
            controller.busy = action
            if action == "stop":
                controller.config["desired"] = False
                controller.persist()

        def execute():
            try:
                controller.execute(action)
            except (ArchiveError, DockerError, VaultError, DeliveryError, OSError) as exc:
                message = str(exc) if isinstance(exc, (ArchiveError, DockerError, VaultError, DeliveryError)) else "Ошибка файловой системы. Проверьте место и права."
                controller.operation_error = message
                controller.event(message, "error")
            finally:
                controller.busy = ""
        threading.Thread(target=execute, daemon=True, name="hcc-control-action").start()
        return {"status": "accepted"}

    @app.get("/api/backup/{backup_id}")
    def download(backup_id: str):
        record = next((row for row in controller.history["records"] if row["id"] == backup_id), None)
        if record is None:
            raise HTTPException(404, "Копия не найдена")
        return FileResponse(controller.folder / "backups" / record["file"], filename=record["file"], media_type="application/octet-stream")

    @app.post("/api/restore/inspect")
    def inspect(file: UploadFile = File(), key: str = Form()):
        blob = decrypt_archive(file.file.read(MAX_BYTES + 1), key)
        manifest = inspect_snapshot(blob)
        if manifest["schema"] not in json.loads(controller.docker.helper("schemas")):
            raise ArchiveError("Несовместимая схема базы")
        pending.clear()
        ticket = secrets.token_urlsafe(32)
        pending[ticket] = (time.time() + 600, blob, key)
        return {"ticket": ticket, "manifest": manifest, "warning": "Архив содержит всю установку: все проекты и аккаунты. Восстановление заменит базу и документы. Интеграционные секреты нужно ввести отдельно."}

    @app.post("/api/restore/apply")
    def restore(body: RestoreRequest):
        item = pending.get(body.ticket)
        if not body.confirm or not item or item[0] < time.time():
            raise ArchiveError("Нужно проверить архив заново и подтвердить замену")
        if controller.busy or not controller.lock.acquire(timeout=90):
            raise ArchiveError("Дождитесь текущей операции")
        try:
            if pending.pop(body.ticket, None) is not item:
                raise ArchiveError("Этот архив уже использован; выполните проверку заново")
            controller.busy = "Восстановление"
            controller.config.update(desired=False, transfer_pending=True, restore_verified=False)
            controller.persist()
            controller.docker.compose(["stop", "-t", "130", "app"], timeout=150)
            if (Path(controller.config["data_dir"]) / "hackathon.db").exists():
                controller.backup(force=True)
            controller.docker.helper("restore", data=item[1])
            previous = controller.vault.get("operator")
            if previous and previous != item[2]:
                previous_keys = json.loads(controller.vault.get("operator_history") or "[]")
                if previous not in previous_keys:
                    previous_keys.append(previous)
                controller.vault.put("operator_history", json.dumps(previous_keys))
            controller.vault.put("operator", item[2])
            restored_login = inspect_snapshot(item[1]).get("operator_login")
            if isinstance(restored_login, str) and restored_login:
                controller.config["login"] = restored_login
            controller.config["external_resume_after"] = time.time() + 86400
            controller.config["restore_verified"] = True
            controller.persist()
            controller.event("Восстановление выполнено; внешние действия приостановлены. Завершите перенос и проверьте вход оператора.")
        finally:
            controller.busy = ""
            controller.lock.release()
        return {"status": "ok"}

    @app.post("/api/transfer/activate")
    def activate(body: ActivationRequest):
        if not body.previous_server_stopped or not body.accept_quota_pause:
            raise ArchiveError("Подтвердите остановку прежней установки и паузу ИИ на 24 часа")
        if not controller.config.get("restore_verified"):
            raise ArchiveError("Восстановление не завершилось успешно. Повторите проверку и восстановление архива перед активацией.")
        controller.docker.helper("transfer")
        controller.config["transfer_pending"] = False
        controller.persist()
        return {"status": "ok"}

    @app.get("/api/diagnostics")
    def diagnostics():
        safe = {"version": controller.view()["version"], "checked_at": controller.status["checked_at"],
                "engine": controller.status["engine"], "events": controller.events,
                "recovery_attempts": len(controller.policy.attempts)}
        return Response(json.dumps(safe, ensure_ascii=False), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="hcc-diagnostics.json"'})

    return app
