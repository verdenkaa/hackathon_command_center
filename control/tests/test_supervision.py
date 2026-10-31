from __future__ import annotations

from control.supervision import RecoveryPolicy, retention_candidates


def test_explicit_stop_and_startup_grace_are_respected():
    policy = RecoveryPolicy()
    assert not policy.should_restart(now=200, desired=False, started=0, healthy=False, running=True)
    assert not policy.should_restart(now=20, desired=True, started=0, healthy=False, running=True)
    assert not policy.should_restart(now=200, desired=True, started=0, healthy=False, running=False)
    assert not policy.should_restart(now=200, desired=True, started=0, healthy=True, running=True)


def test_recovery_is_bounded_and_waits_between_attempts():
    policy = RecoveryPolicy()
    for now in (100, 200, 300):
        assert policy.should_restart(now=now, desired=True, started=0, healthy=False, running=True)
    assert not policy.should_restart(now=301, desired=True, started=0, healthy=False, running=True)
    assert not policy.should_restart(now=500, desired=True, started=0, healthy=False, running=True)
    assert policy.exhausted


def test_retention_preserves_newest_and_daily_history():
    day = 86400
    records = [{"id": str(i), "created": i * 3600} for i in range(24 * 10)]
    remove = retention_candidates(records, now=10 * day)
    assert "239" not in remove
    assert all(str(i) not in remove for i in range(216, 240))
    assert len(set(str(i // 24) for i in range(24, 216) if str(i) not in remove)) == 7
