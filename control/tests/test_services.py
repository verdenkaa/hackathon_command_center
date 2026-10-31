from unittest.mock import patch

from control.controller import Controller


def test_status_changes_are_durable_and_send_once_to_alert_chat(tmp_path):
    c = Controller(tmp_path)
    c.vault.windows = False
    c.vault.unlock('synthetic-passphrase')
    c.vault.put('telegram', 'SYNTHETIC_TOKEN')
    c.config.update(telegram_alert_chat='-200', administrator='server_admin')
    c.update_services()
    count = len(c.history['alert_outbox'])
    assert count >= 4
    c.update_services()
    assert len(c.history['alert_outbox']) == count
    with patch('control.controller.send_alert') as sender:
        c.deliver_alerts()
        assert sender.call_count == count
        assert sender.call_args.args[1] == '-200'
        assert sender.call_args.args[-1] == 'server_admin'
        c.deliver_alerts()
        assert sender.call_count == count
    assert c.history['alert_outbox'] == []


def test_alert_failure_keeps_queue_and_does_not_interrupt_backups(tmp_path):
    from control.telegram import DeliveryError
    c = Controller(tmp_path)
    c.vault.windows = False
    c.vault.unlock('synthetic-passphrase')
    c.vault.put('telegram','SYNTHETIC_TOKEN')
    c.config.update(telegram_alert_chat='-200')
    c.update_services()
    with patch('control.controller.send_alert', side_effect=DeliveryError('Нет прав')):
        c.deliver_alerts()
    assert c.history['alert_outbox']
    assert c.history['alert_error'] == 'Нет прав'
