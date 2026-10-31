"""Per-user opt-in startup. Never changes machine policies or power settings."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from control.vault import atomic_write


def command(root: Path) -> list[str]:
    python = str(Path(sys.executable).with_name("pythonw.exe")) if os.name == "nt" else sys.executable
    return [python, str(Path(__file__).with_name("launcher.py")), '--resume', '--root', str(root), "--no-browser"]


def enabled(identity: str) -> bool:
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                winreg.QueryValueEx(key, "HCC-" + identity)
            return True
        except OSError:
            return False
    return (Path.home() / ".config" / "autostart" / ("hcc-" + identity + ".desktop")).is_file()


def set_enabled(root: Path, identity: str, value: bool) -> None:
    if os.name == "nt":
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            if value:
                winreg.SetValueEx(key, "HCC-" + identity, 0, winreg.REG_SZ, subprocess.list2cmdline(command(root)))
            else:
                try:
                    winreg.DeleteValue(key, "HCC-" + identity)
                except FileNotFoundError:
                    pass
        return
    path = Path.home() / ".config" / "autostart" / ("hcc-" + identity + ".desktop")
    if not value:
        path.unlink(missing_ok=True)
        return
    def quote(item: str) -> str:
        return '"' + item.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
    contents = "[Desktop Entry]\nType=Application\nName=Hackathon Control\nTerminal=false\nExec=" + " ".join(map(quote, command(root))) + "\n"
    atomic_write(path, contents.encode())
