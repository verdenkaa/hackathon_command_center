from control.dependencies import next_step


def test_install_plan_does_not_replace_existing_engine():
    assert next_step({"wsl": True, "distro": True, "docker": True, "compose": True}, windows=True) == "ready"
    assert next_step({"docker": True, "compose": False}, windows=False) == "compose"
    assert next_step({"wsl": False}, windows=True) == "wsl"
    assert next_step({"wsl": True, "distro": False}, windows=True) == "distro"
    assert next_step({"wsl": True, "distro": True, "docker": False}, windows=True) == "docker"


def test_broken_or_conflicting_engine_requires_manual_resolution():
    assert next_step({"docker": True, "engine_error": True}, windows=False) == "manual"
    assert next_step({"docker": False, "conflict": True}, windows=False) == "manual"
