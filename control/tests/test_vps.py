"""The VPS panel can control only Aion and only from its own HTTPS origin."""
from fastapi.testclient import TestClient

from control import vps


ORIGIN = "https://ops.example.com"
PROXY = {"X-Ouroboros-Operator": "operator"}


def test_panel_requires_authenticated_proxy_and_expected_host():
    app = vps.create_app(ORIGIN, "https://aion.example.com")
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/status").status_code == 401
        assert client.get("/", headers=PROXY).status_code == 200
        assert client.get("/", headers={**PROXY, "Host": "aion.example.com"}).status_code == 403
        assert client.get("/docs", headers=PROXY).status_code == 404


def test_status_and_allowed_actions(monkeypatch):
    calls = []
    monkeypatch.setattr(vps, "read_status", lambda _: {"service": "inactive", "ready": False})
    monkeypatch.setattr(vps, "queue_action", calls.append)
    app = vps.create_app(ORIGIN, "https://aion.example.com")
    with TestClient(app, base_url=ORIGIN, headers=PROXY) as client:
        assert client.get("/api/status").json()["service"] == "inactive"
        assert client.post("/api/action/start").status_code == 403
        headers = {"Origin": "https://aion.example.com", "X-Ouroboros-Action": "1"}
        assert client.post("/api/action/start", headers=headers).status_code == 403
        headers["Origin"] = ORIGIN
        assert client.post("/api/action/build", headers=headers).status_code == 422
        assert client.post("/api/action/start", headers=headers).status_code == 202
        assert client.post("/api/action/stop", headers=headers).status_code == 202
        assert calls == ["start", "stop"]


def test_action_never_accepts_a_caller_supplied_unit(monkeypatch):
    commands = []
    monkeypatch.setattr(vps, "run_command", lambda argv: commands.append(argv))
    vps.queue_action("restart")
    assert commands == [
        ["/usr/bin/sudo", "-n", "--", "/usr/bin/systemctl", "--no-block", "restart", "aion-web.service"]
    ]
