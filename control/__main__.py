"""Single-instance desktop launcher; --serve is reserved for diagnostics/tests."""
from __future__ import annotations

import argparse
import os
import secrets
import socket
import subprocess
import sys
import time
import json
import urllib.request
from pathlib import Path

from control.locking import FileLock
from control.vault import atomic_write, dpapi


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument('--desktop-child', action='store_true')
    parser.add_argument('--tray', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    folder = root / ".control"
    folder.mkdir(exist_ok=True, mode=0o700)
    token_file = folder / "launch.cap"
    if args.serve or args.desktop_child:
        import uvicorn
        from control.server import create_app
        with FileLock(folder / "panel.lock", blocking=False):
            raw = token_file.read_bytes()
            token = (dpapi(raw, decrypt=True) if os.name == "nt" else raw).decode()
            if args.desktop_child:
                from control.desktop import run_desktop
                run_desktop(root, token, hidden=args.tray or args.no_browser, resume=args.resume)
            else:
                app = create_app(root, token=token)
                server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8787, access_log=False, log_level='warning'))
                app.state.on_shutdown = lambda: setattr(server, 'should_exit', True)
                server.run()
        return
    with socket.socket() as probe:
        already_running = probe.connect_ex(("127.0.0.1", 8787)) == 0
    if not already_running:
        token = secrets.token_urlsafe(48)
        atomic_write(token_file, dpapi(token.encode()) if os.name == "nt" else token.encode())
        log = folder / "panel.log"
        if log.exists() and log.stat().st_size > 5 * 1024 * 1024:
            log.replace(folder / "panel.previous.log")
        python = str(Path(sys.executable).with_name("pythonw.exe")) if os.name == "nt" else sys.executable
        with log.open("ab") as output:
            child = [python, '-m', 'control', '--desktop-child', '--root', str(root)]
            if args.tray or args.no_browser:
                child.append('--tray')
            if args.resume:
                child.append('--resume')
            subprocess.Popen(child, cwd=Path(__file__).resolve().parents[1],
                             stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                             creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                             start_new_session=os.name != "nt")
        for _ in range(100):
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", 8787)) == 0:
                    break
            time.sleep(.1)
        else:
            raise SystemExit("Панель не запустилась. Проверьте .control/panel.log и занятость порта 8787.")
    else:
        try:
            raw = token_file.read_bytes()
            token = (dpapi(raw, decrypt=True) if os.name == "nt" else raw).decode()
        except OSError:
            raise SystemExit("Порт 8787 занят другой программой. Освободите его и повторите запуск.") from None
    if already_running and not (args.no_browser or args.tray):
        # Ask the existing native window to show; never spawn another host/window.
        import http.cookiejar
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        origin = 'http://127.0.0.1:8787'
        for route, data in [('session', {'token':token}), ('window/show', {})]:
            request = urllib.request.Request(origin + '/api/' + route, data=json.dumps(data).encode(),
                headers={'Content-Type':'application/json','Origin':origin})
            with opener.open(request, timeout=5):
                pass
    print('Хаб запущен. Крестик сворачивает окно в трей; выключение — в настройках или меню трея.')


if __name__ == "__main__":
    main()
