"""Only fixed installation-scoped Docker operations. No shell or generic API."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


class DockerError(RuntimeError):
    pass


class Docker:
    def __init__(self, root: Path, identity: str, distro: str = "Ubuntu-24.04") -> None:
        self.root, self.identity, self.distro = root, identity, distro
        self.project = "hcc-" + identity
        self.keeper: subprocess.Popen | None = None

    def keep_alive(self) -> None:
        if os.name == "nt" and (self.keeper is None or self.keeper.poll() is not None):
            # EOF ends the Linux child even if the Windows panel crashes.
            self.keeper = subprocess.Popen(["wsl.exe", "--distribution", self.distro, "--user", "root", "--exec", "cat"],
                                           stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           creationflags=subprocess.CREATE_NO_WINDOW)

    def close(self) -> None:
        if self.keeper and self.keeper.poll() is None:
            if self.keeper.stdin:
                self.keeper.stdin.close()
            try:
                self.keeper.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.keeper.terminate()
                self.keeper.wait(timeout=10)
        self.keeper = None

    def run(self, args: list[str], *, data: bytes | None = None, timeout: int = 60) -> bytes:
        prefix = ["wsl.exe", "--distribution", self.distro, "--user", "root", "--exec"] if os.name == "nt" else []
        try:
            self.keep_alive()
            result = subprocess.run(prefix + args, input=data, capture_output=True, timeout=timeout,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except (OSError, subprocess.TimeoutExpired):
            raise DockerError("Движок не отвечает или превышено время операции. Проверьте WSL / Docker и повторите проверку.") from None
        if result.returncode:
            # Never surface raw command output: providers, Compose and Docker may echo credentials.
            raise DockerError("Команда Docker не завершена. Проверьте готовность движка, место на диске и образ установки.")
        return result.stdout

    def engine_path(self, path: Path) -> str:
        absolute = path.resolve()
        if os.name == "nt":
            return "/mnt/" + absolute.drive[0].lower() + absolute.as_posix()[2:]
        return str(absolute)

    def compose(self, args: list[str], *, data: bytes | None = None, timeout: int = 90) -> bytes:
        return self.run(["docker", "compose", "--project-name", self.project, "--file",
                         self.engine_path(self.root / ".control" / "compose.json"), *args], data=data, timeout=timeout)

    def ready(self) -> dict[str, str]:
        return {"engine": self.run(["docker", "version", "--format", "{{.Server.Version}}"]).decode().strip(),
                "compose": self.run(["docker", "compose", "version", "--short"]).decode().strip()}

    def container(self) -> dict:
        raw = self.compose(["ps", "--all", "--format", "json", "app"]).decode().strip()
        if not raw:
            return {"State": "absent", "Health": "", "Name": "—"}
        parsed = json.loads(raw) if raw.startswith("[") else json.loads(raw.splitlines()[0])
        return parsed[0] if isinstance(parsed, list) and parsed else parsed

    def helper(self, operation: str, *, data: bytes | None = None) -> bytes:
        if operation not in {"snapshot", "restore", "schemas", "transfer"}:
            raise DockerError("Операция не предусмотрена")
        if operation == "snapshot" and self.container().get("State") == "running":
            return self.compose(["exec", "-T", "app", "python", "-m", "control.worker", operation, self.identity],
                                data=data, timeout=180)
        return self.compose(["run", "--rm", "--no-deps", "-T", "app", "python", "-m", "control.worker", operation, self.identity],
                            data=data, timeout=180)
