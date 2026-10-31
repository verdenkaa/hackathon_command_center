from control.controller import Controller


def test_old_state_remains_visible_until_entire_probe_finishes(tmp_path, monkeypatch):
    controller = Controller(tmp_path)
    controller.status.update(api=True, ui=True, checked_at=123)

    def engine():
        assert controller.status['api'] is True
        assert controller.status['checked_at'] == 123
        return {'engine':'test','compose':'test'}

    monkeypatch.setattr(controller.docker, 'ready', engine)
    controller.check()
    assert controller.status['checked_at'] > 123
