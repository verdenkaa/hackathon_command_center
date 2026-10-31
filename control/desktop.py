"""Native pywebview window, Windows tray, and explicit graceful host shutdown."""
from __future__ import annotations

import os
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse


class DesktopLifecycle:
    def __init__(self, window: Any, shutdown: Callable[[], bool]) -> None:
        self.window = window
        self.shutdown = shutdown
        self.exiting = False
        self.lock = threading.Lock()
        self.tray: Any = None

    def on_closing(self) -> bool:
        if self.exiting:
            return True
        self.window.hide()
        return False

    def show(self) -> None:
        self.window.show()
        self.window.restore()

    def finish(self) -> None:
        self.exiting = True
        if self.tray:
            self.tray.stop()
        self.window.destroy()

    def quit(self) -> None:
        if not self.lock.acquire(blocking=False):
            return
        try:
            if self.shutdown():
                self.finish()
            else:
                self.show()
        finally:
            self.lock.release()


def run_desktop(root: Path, token: str, *, hidden: bool = False, resume: bool = False) -> None:
    import webview
    import pystray
    import uvicorn
    from PIL import Image
    from control.icon import ICON_DIR
    from control.archives import ArchiveError
    from control.docker import DockerError
    from control.server import create_app
    from control.vault import VaultError

    if os.name == 'nt':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('HCC.PlatformManager')
    app = create_app(root, token=token)
    manager = app.state.controller
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8787,
                                          access_log=False, log_level='warning'))
    server_thread = threading.Thread(target=server.run, daemon=True, name='hcc-local-api')
    server_thread.start()
    for _ in range(200):
        if server.started:
            break
        if not server_thread.is_alive():
            raise RuntimeError('Локальный API хаба не запустился; проверьте порт 8787 и panel.log')
        time.sleep(.05)
    else:
        raise RuntimeError('Истекло время запуска локального API хаба')

    class Bridge:
        def choose_folder(self) -> str | None:
            result = window.create_file_dialog(webview.FileDialog.FOLDER)
            return result[0] if result else None

        def open_external(self, url: str) -> None:
            parsed = urlparse(url)
            if (parsed.scheme == 'https' and parsed.hostname in {'fxtun.ru','docs.docker.com','learn.microsoft.com'}) or url == 'http://127.0.0.1:8000' or url == manager.tunnel.current_url:
                webbrowser.open(url)

    window = webview.create_window('Ouroboros Daemon',
        'http://127.0.0.1:8787/#token=' + token, js_api=Bridge(), width=1280, height=900,
        min_size=(900, 640), hidden=hidden, text_select=True)

    def shutdown() -> bool:
        try:
            manager.shutdown()
            server.should_exit = True
            return True
        except (ArchiveError, DockerError, VaultError, OSError) as exc:
            manager.operation_error = str(exc)
            manager.event('Хаб не выключен: ' + str(exc), 'error')
            return False

    lifecycle = DesktopLifecycle(window, shutdown)
    window.events.closing += lifecycle.on_closing
    app.state.show_window = lifecycle.show
    def finish_from_api() -> None:
        server.should_exit = True
        lifecycle.finish()
    app.state.on_shutdown = finish_from_api
    image = Image.open(ICON_DIR / 'hub.png')
    lifecycle.tray = pystray.Icon('hcc-manager', image, 'Ouroboros Daemon', menu=pystray.Menu(
        pystray.MenuItem('Открыть хаб', lambda *_: lifecycle.show(), default=True),
        pystray.MenuItem('Выключить хаб и платформу', lambda *_: threading.Thread(target=lifecycle.quit, daemon=True).start())))
    if os.name == 'nt':
        threading.Thread(target=lifecycle.tray.run, daemon=True, name='hcc-tray').start()
    else:
        lifecycle.tray.run_detached()
    if resume:
        def resume_platform() -> None:
            try:
                manager.resume_main()
            except (ArchiveError, DockerError, VaultError, OSError) as exc:
                manager.operation_error = str(exc)
                manager.event('Основная платформа не запущена: ' + str(exc), 'error')
        threading.Thread(target=resume_platform, daemon=True).start()
    webview.settings['ALLOW_DOWNLOADS'] = True
    try:
        webview.start(gui='edgechromium' if os.name == 'nt' else None, private_mode=True,
                      icon=str(ICON_DIR / ('hub.ico' if os.name == 'nt' else 'hub.png')))
    finally:
        lifecycle.tray.stop()
        manager.stop_event.set()
        server.should_exit = True
        server_thread.join(timeout=10)
