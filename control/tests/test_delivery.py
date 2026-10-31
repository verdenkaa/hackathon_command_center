from unittest.mock import patch

from control.controller import Controller


def test_telegram_initial_send_is_immediate_and_latest_only(tmp_path):
    c = Controller(tmp_path)
    c.vault.windows = False
    c.vault.unlock("test-vault-passphrase")
    c.vault.put("telegram", "SYNTHETIC_TEST_TOKEN")
    c.config["telegram_chat"] = "-100123"
    folder = c.folder / "backups"
    folder.mkdir()
    c.history["records"] = [{"id": "old", "file": "old.hcc", "created": 100}, {"id": "new", "file": "new.hcc", "created": 200}]
    (folder / "new.hcc").write_bytes(b"ENCRYPTED_TEST_ARCHIVE")
    with patch("control.controller.send_backup") as sender:
        c.deliver()
        assert sender.call_count == 1
        assert sender.call_args.args[4]["id"] == "new"
        c.deliver()
        assert sender.call_count == 1
    assert c.history["telegram_id"] == "new"


def test_telegram_failure_keeps_local_copy_and_backs_off(tmp_path):
    from control.telegram import DeliveryError
    c = Controller(tmp_path)
    c.vault.windows = False
    c.vault.unlock("test-vault-passphrase")
    c.vault.put("telegram", "SYNTHETIC_TEST_TOKEN")
    c.config["telegram_chat"] = "-100123"
    folder = c.folder / "backups"
    folder.mkdir()
    record = {"id": "new", "file": "new.hcc", "created": 200}
    c.history["records"] = [record]
    path = folder / record["file"]
    path.write_bytes(b"ENCRYPTED_TEST_ARCHIVE")
    with patch("control.controller.send_backup", side_effect=DeliveryError("Безопасная ошибка")) as sender:
        c.deliver()
        c.deliver()
        assert sender.call_count == 1
    assert path.read_bytes() == b"ENCRYPTED_TEST_ARCHIVE"
    assert c.history["telegram_id"] == ""


def test_external_disk_disconnect_and_reconnect_copies_only_latest(tmp_path):
    c = Controller(tmp_path)
    folder = tmp_path / "external"
    folder.mkdir()
    (folder / "personal.txt").write_text("preserve")
    local = c.folder / "backups"
    local.mkdir()
    c.config["external_folder"] = str(folder)
    latest = {"id":"a" * 32,"file":f'hcc-{c.config["id"]}-' + 'a' * 32 + '.hcc',"created":200,"size":10}
    c.history["records"] = [latest]
    (local / latest["file"]).write_bytes(b"encrypted1")
    c.copy_external()
    assert (folder / latest["file"]).read_bytes() == b"encrypted1"
    # Simulate an unplugged drive without touching its existing files.
    c.config["external_folder"] = str(tmp_path / "unplugged")
    c.copy_external()
    assert c.history["external_error"]
    c.config["external_folder"] = str(folder)
    c.copy_external()
    assert c.history["external_error"] is None
    assert (folder / "personal.txt").read_text() == "preserve"


def test_due_telegram_delivery_refreshes_snapshot_before_sending(tmp_path, monkeypatch):
    import time
    c = Controller(tmp_path)
    c.vault.windows = False
    c.vault.unlock('test-vault-passphrase')
    c.vault.put('telegram','SYNTHETIC_TEST_TOKEN')
    c.config.update(configured=True, telegram_chat='-100123')
    folder = c.folder / 'backups'
    folder.mkdir()
    c.history['records'] = [{'id':'old','file':'old.hcc','created':time.time()-300}]
    (folder / 'old.hcc').write_bytes(b'older-encrypted')
    def refresh(*, force=False):
        record = {'id':'fresh','file':'fresh.hcc','created':time.time()}
        (folder / record['file']).write_bytes(b'fresh-encrypted')
        c.history['records'].append(record)
    monkeypatch.setattr(c,'backup',refresh)
    with patch('control.controller.send_backup') as sender:
        c.deliver()
        assert sender.call_args.args[4]['id'] == 'fresh'
