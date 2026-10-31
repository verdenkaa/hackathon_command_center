import pytest

from control.vault import Vault, VaultError


def test_linux_vault_requires_unlock_and_authenticates(tmp_path):
    vault = Vault(tmp_path, windows=False)
    with pytest.raises(VaultError):
        vault.put("operator", "secret-operator")
    vault.unlock("a sufficiently long passphrase")
    vault.put("operator", "secret-operator")
    assert b"secret-operator" not in (tmp_path / "vault.bin").read_bytes()
    reopened = Vault(tmp_path, windows=False)
    with pytest.raises(VaultError):
        reopened.unlock("wrong password")
    reopened.unlock("a sufficiently long passphrase")
    assert reopened.get("operator") == "secret-operator"


def test_vault_atomic_update_preserves_other_secrets(tmp_path):
    vault = Vault(tmp_path, windows=False)
    vault.unlock("a sufficiently long passphrase")
    vault.put("operator", "old-archive-key")
    vault.put("telegram", "bot-token")
    assert vault.get("operator") == "old-archive-key"
    assert vault.get("telegram") == "bot-token"
