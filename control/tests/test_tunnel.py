from control.tunnel import configuration, public_link


def test_tunnel_targets_only_platform_and_disables_inspector():
    config = configuration("team-hcc")
    assert config["inspect"]["enabled"] is False
    assert config["tunnels"] == [{"name": "hcc-platform", "type": "http", "local_port": 8000,
                                 "local_addr": "127.0.0.1", "subdomain": "team-hcc"}]
    assert config["reconnect"]["max_attempts"] == 5


def test_public_link_rejects_other_hosts_and_console_secret_values():
    assert public_link('HTTP: https://team-hcc.fxtun.ru') == 'https://team-hcc.fxtun.ru'
    assert public_link('https://evil.example password=secret') is None
    assert public_link('https://team.fxtun.ru.evil.example') is None
    assert public_link('https://team.fxtun.ru/path?token=secret') is None
