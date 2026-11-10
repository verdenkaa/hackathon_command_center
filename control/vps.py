"""Ouroboros status and lifecycle API for the Linux service installation."""
from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import psutil
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

STATIC = Path(__file__).parent / "static"
UNIT = "aion-web.service"
SYSTEMCTL = "/usr/bin/systemctl"
APP_SOCKET = "/run/aion-web/aion.sock"
Action = Literal["start", "stop", "restart"]


def run_command(argv: list[str]) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=5, check=True)
    return result.stdout


def queue_action(action: Action) -> None:
    run_command(["/usr/bin/sudo", "-n", "--", SYSTEMCTL, "--no-block", action, UNIT])


def check_aion(host: str) -> dict:
    connection = http.client.HTTPConnection(host, timeout=2)
    try:
        connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.sock.settimeout(2)
        connection.sock.connect(APP_SOCKET)
        connection.request("GET", "/health")
        response = connection.getresponse()
        if response.status == 200:
            body = json.loads(response.read(4096))
            if body.get("status") == "ok":
                return {"ready": True, "version": body.get("version")}
    except (OSError, ValueError, http.client.HTTPException):
        pass
    finally:
        connection.close()
    return {"ready": False, "version": None}


def read_status(aion_host: str) -> dict:
    try:
        properties = run_command([SYSTEMCTL, "show", UNIT, "--property=ActiveState,SubState,Result,NRestarts"])
        state = dict(line.split("=", 1) for line in properties.splitlines() if "=" in line)
    except (OSError, subprocess.SubprocessError):
        state = {}
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage("/var/lib")
    return {
        "service": state.get("ActiveState", "unknown"),
        "phase": state.get("SubState"),
        "result": state.get("Result"),
        "restarts": state.get("NRestarts"),
        "memory_percent": memory.percent,
        "disk_free_bytes": disk.free,
        "load_1m": os.getloadavg()[0],
        **check_aion(aion_host),
    }


def create_app(panel_origin: str, aion_url: str) -> FastAPI:
    panel_host = urlsplit(panel_origin).netloc
    aion_host = urlsplit(aion_url).netloc
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.headers.get("host") != panel_host:
            return JSONResponse({"detail": "Недопустимый адрес панели"}, status_code=403)
        # The private socket is accessible to Caddy. Caddy sets this header after authentication.
        if request.headers.get("x-ouroboros-operator") != "operator":
            return JSONResponse({"detail": "Требуется вход оператора"}, status_code=401)
        if request.method not in {"GET", "HEAD"}:
            if (request.headers.get("origin") != panel_origin
                    or request.headers.get("x-ouroboros-action") != "1"):
                return JSONResponse({"detail": "Запрос со сторонней страницы отклонён"}, status_code=403)
        response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        })
        return response

    @app.get("/")
    def index():
        return FileResponse(STATIC / "vps.html")

    @app.get("/static/{name}")
    def asset(name: Literal["vps.js", "vps.css"]):
        return FileResponse(STATIC / name)

    @app.get("/api/status")
    def status():
        return {**read_status(aion_host), "aion_url": aion_url}

    @app.post("/api/action/{action}", status_code=202)
    def action(action: Action):
        try:
            queue_action(action)
        except (OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(503, "systemd не принял команду. Проверьте журнал Ouroboros.") from exc
        return {"status": "accepted"}

    return app


def from_env() -> FastAPI:
    return create_app("https://" + os.environ["OUROBOROS_HOST"], os.environ["APP_PUBLIC_URL"])
