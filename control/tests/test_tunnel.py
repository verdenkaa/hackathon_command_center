from control.integrations import validate
from control.tunnel import Tunnel, configuration, public_link
from unittest.mock import Mock
import time


def test_tunnel_targets_only_platform_and_disables_inspector():
    config = configuration("team-hcc")
    assert config["inspect"]["enabled"] is False
    assert config["tunnels"] == [{"name": "hcc-platform", "type": "http", "local_port": 8000,
                                 "local_addr": "127.0.0.1", "subdomain": "team-hcc"}]
    assert config["reconnect"]["max_attempts"] == 5


def test_public_link_rejects_other_hosts_and_console_secret_values():
    assert public_link('HTTP: https://team-hcc.fxtun.ru') == 'https://team-hcc.fxtun.ru'
    assert public_link('HTTP: https://team-hcc.fxtun.dev') == 'https://team-hcc.fxtun.dev'
    assert public_link('https://evil.example password=secret') is None
    assert public_link('https://team.fxtun.ru.evil.example') is None
    assert public_link('https://team.fxtun.ru/path?token=secret') is None
    assert public_link('https://team.fxtun.dev.evil.example') is None


def test_launch_uses_current_tls_server(tmp_path, monkeypatch):
    spawn = Mock()
    monkeypatch.setattr('control.tunnel.tunnel_binary', lambda: 'fxtunnel')
    monkeypatch.setattr('control.tunnel.subprocess.Popen', spawn)
    monkeypatch.setattr('control.tunnel.psutil.Process', Mock(return_value=Mock(
        pid=123, create_time=Mock(return_value=1.0), exe=Mock(return_value='fxtunnel'))))
    monkeypatch.setattr('control.tunnel.threading.Thread', Mock())
    monkeypatch.setattr('control.tunnel.atomic_write', Mock())

    Tunnel(tmp_path).start('SYNTHETIC_TOKEN', 'team-hcc')

    args = spawn.call_args.args[0]
    assert args[args.index('--server') + 1] == 'tunnel.fxtun.dev:443'
    assert 'SYNTHETIC_TOKEN' not in args


def test_key_validation_lists_domains_on_current_server(monkeypatch):
    run = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr('control.integrations.tunnel_binary', lambda: 'fxtunnel')
    monkeypatch.setattr('control.integrations.subprocess.run', run)

    assert validate('fxtunnel', 'SYNTHETIC_TOKEN')[0] == 'valid'
    assert run.call_args.args[0] == ['fxtunnel', 'domains', 'list', '--server', 'tunnel.fxtun.dev:443']
    assert run.call_args.kwargs['env']['FXTUNNEL_TOKEN'] == 'SYNTHETIC_TOKEN'


def test_exited_child_is_released_for_retry(tmp_path):
    from control.tunnel import Tunnel
    tunnel = Tunnel(tmp_path)
    process = Mock()
    process.poll.return_value = 1
    tunnel.process = process
    tunnel.check()
    assert tunnel.process is None


def test_connection_without_address_has_deadline(tmp_path):
    from control.tunnel import Tunnel
    tunnel = Tunnel(tmp_path)
    process = Mock()
    process.poll.return_value = None
    tunnel.process = process
    tunnel.started = time.time() - 61
    tunnel.check()
    assert tunnel.process is None
    process.terminate.assert_called_once()
    assert '60' in tunnel.error
