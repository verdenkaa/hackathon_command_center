from unittest.mock import Mock

from control.controller import Controller


def test_start_enables_tunnel_and_tick_opens_once_api_ready(tmp_path, monkeypatch):
    c = Controller(tmp_path)
    c.config.update(configured=True)
    c.vault.put('fxtunnel', 'SYNTHETIC_TOKEN')
    monkeypatch.setattr(c,'stage_secrets',lambda:None)
    monkeypatch.setattr(c.docker,'compose',lambda *a,**k:b'')
    c.execute('start')
    assert c.config['tunnel_desired'] is True
    assert c.config['subdomain'] == 'dots-bots-hub'
    monkeypatch.setattr(c,'check',lambda:c.status.update(api=True))
    monkeypatch.setattr(c,'backup',lambda:None)
    c.tunnel.check=Mock()
    c.tunnel.start=Mock()
    c.tick()
    c.tunnel.start.assert_called_once_with('SYNTHETIC_TOKEN','dots-bots-hub')


def test_stop_blocks_tunnel_reopening_without_exiting_hub(tmp_path, monkeypatch):
    c = Controller(tmp_path)
    c.config.update(configured=True, desired=True, tunnel_desired=True)
    monkeypatch.setattr(c.docker,'compose',lambda *a,**k:b'')
    c.execute('stop')
    assert c.config['desired'] is False
    assert c.stop_event.is_set() is False


def test_default_domain_preserves_explicit_custom_domain(tmp_path):
    c = Controller(tmp_path)
    c.config['subdomain']='my-team'
    c.persist()
    assert Controller(tmp_path).config['subdomain']=='my-team'
