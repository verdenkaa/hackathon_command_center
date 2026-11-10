"""Start a disposable application for browser tests, never a working database."""
from pathlib import Path
import os
import sys
import tempfile
import uuid

root = Path(__file__).resolve().parents[1]
temporary = root / '.tmp'
temporary.mkdir(exist_ok=True)
sys.path[:0] = [str(root / 'backend'), str(root)]

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='e2e-', dir=temporary) as data:
        os.environ.update(APP_DATA_DIR=data, DATABASE_URL='sqlite:///' + (Path(data) / 'test.db').as_posix(),
            APP_MANAGED='false', APP_ENV='test', APP_STATIC_DIR=str(root / 'frontend' / 'dist'),
            APP_FIRST_ADMIN_LOGIN='admin', APP_FIRST_ADMIN_PASSWORD='e2e-password',
            APP_SECRET_KEY=uuid.uuid4().hex, APP_SECRETS_DIR='')
        import uvicorn
        from app.db.session import engine
        try:
            uvicorn.run('app.main:app', host='127.0.0.1', port=8001, proxy_headers=False)
        finally:
            engine.dispose()
