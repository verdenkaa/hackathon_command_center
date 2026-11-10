"""Dedicated fxTunnel child. Inspector disabled; raw output is never logged."""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
import psutil
from pathlib import Path
from typing import Any

from control.vault import atomic_write
from control.integrations import FXTUNNEL_SERVER, tunnel_binary


def configuration(subdomain: str) -> dict[str, Any]:
    tunnel: dict[str, Any] = {"name": "hcc-platform", "type": "http", "local_port": 8000, "local_addr": "127.0.0.1"}
    if subdomain:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", subdomain):
            raise ValueError("Неверное имя адреса fxTunnel")
        tunnel["subdomain"] = subdomain
    return {"inspect": {"enabled": False}, "reconnect": {"enabled": True, "interval": "10s", "max_attempts": 5}, "tunnels": [tunnel]}


def public_link(line: str) -> str | None:
    match = re.search(r"https://[a-z0-9-]+\.fxtun\.(?:dev|ru)(?=[\s\"']|$)", line)
    return match.group(0) if match else None


class Tunnel:
    def __init__(self, folder: Path, identity: str = "") -> None:
        self.folder = folder
        self.identity = identity
        self.process: subprocess.Popen | None = None
        self.issued_url: str | None = None
        self.current_url: str | None = None
        self.checked_at: float | None = None
        self.error: str | None = "Не настроен"
        self.started = 0.0

    def start(self, token: str, subdomain: str) -> None:
        if not token:
            raise ValueError("Введите секрет fxTunnel в локальной панели")
        binary = tunnel_binary()
        if not binary:
            raise ValueError("Установите официальный CLI fxTunnel с fxtun.dev, затем повторите запуск")
        self.stop()
        path = self.folder / "fxtunnel.json"
        atomic_write(path, json.dumps(configuration(subdomain)).encode())
        environment = {**os.environ, "FXTUNNEL_TOKEN": token, "FXTUNNEL_INSPECT_ENABLED": "false"}
        self.process = subprocess.Popen([binary, "--config", str(path), "--server", FXTUNNEL_SERVER,
                                        "--no-inspect", "--log-level", "info"], cwd=self.folder,
                                        env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.error = "Подключаемся; публичный адрес ещё не проверен"
        self.started = time.time()
        try:
            child = psutil.Process(self.process.pid)
            atomic_write(self.folder / 'tunnel-process.json', json.dumps({
                'pid': child.pid, 'created': child.create_time(), 'executable': child.exe()
            }).encode())
        except psutil.Error:
            pass
        threading.Thread(target=self._read_output, args=(self.process,), daemon=True).start()

    def _read_output(self, process: subprocess.Popen) -> None:
        assert process.stdout is not None
        for raw in iter(process.stdout.readline, b""):
            if process is not self.process:
                break
            url = public_link(raw[:16384].decode(errors="replace"))
            if url:
                self.issued_url = url
        if process is self.process:
            self.current_url = None
            self.error = "Туннель завершился. Проверьте подключение и запустите его вручную."
            self.process = None

    def check(self) -> None:
        self.checked_at = time.time()
        self.current_url = None
        if self.process and (self.process.poll() is not None or
                             (not self.issued_url and time.time() - self.started > 60)):
            self.stop()
            self.error = 'fxTunnel не открыл адрес за 60 с. Проверьте ключ, сеть и занятость поддомена'
        if not self.process or not self.issued_url:
            return
        try:
            # No cookies or credentials leave the local panel. HTTPS validation stays enabled.
            with urllib.request.urlopen(self.issued_url + "/health", timeout=5) as response:
                if json.loads(response.read(65536)).get("installation") != self.identity:
                    raise OSError
            with urllib.request.urlopen(self.issued_url + "/", timeout=5) as response:
                if response.status != 200 or response.url.rstrip("/") != self.issued_url:
                    raise OSError
            try:
                urllib.request.urlopen(self.issued_url + "/api/v1/auth/me", timeout=5).close()
                raise ValueError("Проверка защиты входа не пройдена; остановите туннель")
            except urllib.error.HTTPError as exc:
                if exc.code not in {401, 403}:
                    raise OSError from None
            self.current_url, self.error = self.issued_url, None
        except (OSError, ValueError):
            self.error = "Публичный адрес или защита входа не прошли проверку. Ссылка не публикуется как действующая."

    def stop(self) -> None:
        # Recover only the exact child left by this installation after a hub crash.
        ownership = self.folder / 'tunnel-process.json'
        try:
            record = json.loads(ownership.read_text()) if ownership.exists() else None
            if record:
                child = psutil.Process(record['pid'])
                if (child.create_time() == record['created'] and child.exe() == record['executable']
                        and str(self.folder / 'fxtunnel.json') in child.cmdline()):
                    children = child.children(recursive=True)
                    child.terminate()
                    for descendant in children:
                        try:
                            descendant.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    _, alive = psutil.wait_procs([child, *children], timeout=10)
                    for remaining in alive:
                        remaining.kill()
                    psutil.wait_procs(alive, timeout=5)
        except (psutil.Error, OSError, ValueError, KeyError):
            pass
        ownership.unlink(missing_ok=True)
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None
        self.issued_url, self.current_url = None, None
        self.error = "Туннель остановлен"
