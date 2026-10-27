"""Child-process probe: real backup/restore APIs with isolated settings and storage."""
from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any


def main() -> None:
    directory = Path(sys.argv[1]).resolve()
    from app.config import settings
    if (settings.data_dir.resolve() != directory or directory.parent.parent.name != 'sandbox-checks'
            or not directory.parent.name.startswith('run-')
            or settings.sqlalchemy_url != f"sqlite:///{(directory / 'database.db').as_posix()}"):
        raise RuntimeError('Отказ: проверка допускается только в собственной временной папке')
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as client:
        def request(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
            response = client.request(method, '/api/v1' + path, json=body)
            if response.status_code != 200:
                raise RuntimeError(f'{method} {path}: HTTP {response.status_code}')
            return response.json()

        request('POST','/auth/login',{'login':'sandbox-admin','password':'sandbox-pass'})
        request('POST','/projects/1/tasks',{'title':'Before backup'})
        document = request('POST','/projects/1/documents',{'path':'probe.md','content':'original'})
        backup = request('POST','/admin/backups')
        request('POST','/projects/1/tasks',{'title':'After backup'})
        request('PUT',f"/documents/{document['id']}/content",{'content':'changed','base_checksum':document['checksum']})
        if len(request('GET','/projects/1/tasks')) != 2:
            raise RuntimeError('Не удалось подготовить изменения после резервной копии')
        request('POST',f"/admin/backups/{backup['id']}/restore",{'confirm':True})
        tasks = request('GET','/projects/1/tasks')
        if [task['title'] for task in tasks] != ['Before backup']:
            raise RuntimeError('API restore не восстановил исходные задачи')
        if request('GET',f"/documents/{document['id']}/content")['content'] != 'original':
            raise RuntimeError('API restore не восстановил содержимое файла')
        with closing(sqlite3.connect(directory / 'database.db')) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('Нарушена целостность восстановленной базы')
    print(json.dumps({'status':'passed','detail':'API резервного копирования и восстановления: задачи и файл восстановлены; целостность SQLite проверена. Отдельный процесс и собственная папка данных.'}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status':'failed','detail':f'{type(exc).__name__}: {exc}'[:500]},ensure_ascii=False))
        raise SystemExit(1)
