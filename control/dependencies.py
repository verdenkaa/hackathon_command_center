"""Resumable dependency checks. Every system-changing step needs a panel click."""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from control.docker import Docker, DockerError
from control.vault import atomic_write


def next_step(state: dict[str, Any], *, windows: bool) -> str:
    if state.get("engine_error") or state.get("conflict"):
        return "manual"
    if windows and not state.get("wsl"):
        return "wsl"
    if windows and not state.get("distro"):
        return "distro"
    if not state.get("docker"):
        return "docker"
    if not state.get("compose"):
        return "compose"
    return "ready"


def _run(args: list[str], *, data: bytes | None = None, timeout: int = 30) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(args, input=data, capture_output=True, timeout=timeout,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def inspect(docker: Docker) -> dict[str, Any]:
    state: dict[str, Any] = {"wsl": None, "distro": None, "docker": False, "compose": False,
                              "virtualization": "Проверяется фактическим запуском WSL 2", "supported": True}
    try:
        if os.name == "nt":
            state["supported"] = sys.getwindowsversion().build >= 19041
            state["wsl"] = _run(["wsl.exe", "--version"]).returncode == 0
            distro = _run(["wsl.exe", "--list", "--quiet"])
            names = distro.stdout.decode("utf-16-le", errors="replace").replace("\x00", "")
            state["distros"] = names.split()
            state["distro"] = docker.distro in state["distros"]
            if not state["wsl"] or not state["distro"]:
                state["next"] = next_step(state, windows=True)
                return state
        prefix = ["wsl.exe", "--distribution", docker.distro, "--user", "root", "--exec"] if os.name == "nt" else []
        result = _run(prefix + ["sh", "-c", "command -v docker"], timeout=30)
        state["docker"] = result.returncode == 0
        if state["docker"]:
            state["compose"] = _run(prefix + ["docker", "compose", "version"]).returncode == 0
            state["engine_error"] = _run(prefix + ["docker", "info"]).returncode != 0
        else:
            check = _run(prefix + ["sh", "-c", "dpkg -l docker.io containerd runc podman-docker 2>/dev/null || true"])
            state["conflict"] = any(line.startswith("ii ") for line in check.stdout.decode(errors="replace").splitlines())
    except (OSError, subprocess.TimeoutExpired):
        state["error"] = "Проверка не завершена: проверьте права и запуск WSL / Docker"
    state["next"] = next_step(state, windows=os.name == "nt")
    return state


def install_one_step(docker: Docker, state_path: Path) -> str:
    state = inspect(docker)
    step = state["next"]
    state["phase"] = "Выполняется: " + step
    atomic_write(state_path, json.dumps(state).encode())
    if not state["supported"]:
        raise DockerError("Для WSL 2 нужна поддерживаемая Windows; воспользуйтесь официальной инструкцией Microsoft")
    if step == "manual":
        raise DockerError("Обнаружен неисправный движок или существующие конфликтующие пакеты. Они сохранены. Запустите прежний движок или устраните конфликт вручную.")
    if step == "wsl":
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "wsl.exe", "--install --no-distribution", None, 0)
        if result <= 32:
            raise DockerError("Windows не подтвердила запуск установки. Нажмите кнопку заново и подтвердите UAC.")
        message = "Подтвердите UAC. После установки и возможной перезагрузки снова откройте панель и повторите проверку. Новые изменения потребуют отдельного нажатия."
    elif step == "distro":
        result = _run(["wsl.exe", "--install", "--distribution", docker.distro, "--no-launch", "--web-download"], timeout=900)
        if result.returncode:
            raise DockerError("Установка дистрибутива не завершена. Проверьте сеть и требования Windows, затем повторите шаг.")
        message = "Ubuntu установлена. Повторите проверку; следующий шаг — Docker Engine."
    elif step == "docker":
        script = (Path(__file__).parent / "install_docker_ubuntu.sh").read_bytes().replace(b"\r\n", b"\n")
        if os.name == "nt":
            docker.run(["bash", "-s"], data=script, timeout=900)
        elif os.geteuid() == 0:
            result = _run(["bash", "-s"], data=script, timeout=900)
            if result.returncode:
                raise DockerError("Установка не завершена. Поддерживаются Ubuntu 22.04/24.04; проверьте пакеты и официальный репозиторий.")
        else:
            elevated = shutil.which("pkexec")
            if not elevated:
                raise DockerError("Для Linux требуются системные права. Выполните sudo bash control/install_docker_ubuntu.sh в терминале, затем повторите проверку.")
            result = _run([elevated, "bash", "-s"], data=script, timeout=900)
            if result.returncode:
                raise DockerError("Системная установка не подтверждена или не завершена; повторите проверку")
        message = "Docker Engine и Compose установлены из подписанного репозитория Docker."
    elif step == "compose":
        raise DockerError("Движок сохранён. Установите Compose plugin по официальной инструкции для существующего Docker, затем повторите проверку.")
    else:
        docker.run(["docker", "run", "--rm", "hello-world"], timeout=120)
        message = "Docker, Compose и запуск тестового контейнера проверены."
    state["phase"] = message
    atomic_write(state_path, json.dumps(state).encode())
    return message
