import json
import time

from app.config import settings
from app.services.portable import current_public_url


def test_managed_link_expires_and_never_falls_back_to_old_project_url(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'app_managed', True)
    monkeypatch.setattr(settings, 'app_data_dir', str(tmp_path))
    path = tmp_path / '.public-url.json'
    assert current_public_url() == ''
    path.write_text(json.dumps({'url':'https://team.fxtun.ru','expires':time.time()+60}))
    assert current_public_url() == 'https://team.fxtun.ru'
    path.write_text(json.dumps({'url':'https://old.fxtun.ru','expires':time.time()-1}))
    assert current_public_url() == ''
