"""DPAPI on Windows; explicitly unlocked encrypted vault on Linux."""
from __future__ import annotations

import ctypes
import json
import os
import uuid
from pathlib import Path

from control.archives import ArchiveError, decrypt_archive, encrypt_archive


class VaultError(ValueError):
    pass


def atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    pending = path.with_name(path.name + "." + uuid.uuid4().hex + ".pending")
    try:
        descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def dpapi(value: bytes, *, decrypt: bool = False) -> bytes:
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    incoming_buffer = ctypes.create_string_buffer(value)
    incoming = Blob(len(value), ctypes.cast(incoming_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        ok = crypt.CryptUnprotectData(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing))
    else:
        ok = crypt.CryptProtectData(ctypes.byref(incoming), "HCC operator vault", None, None, None, 1, ctypes.byref(outgoing))
    if not ok:
        raise VaultError("DPAPI недоступен для текущей учётной записи Windows")
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel.LocalFree(outgoing.data)


class Vault:
    def __init__(self, folder: Path, *, windows: bool | None = None) -> None:
        self.folder = folder
        self.windows = os.name == "nt" if windows is None else windows
        self.password: str | None = None
        self.values: dict[str, str] | None = None

    @property
    def unlocked(self) -> bool:
        return self.windows or self.values is not None

    def unlock(self, password: str) -> None:
        if not self.windows and len(password) < 16:
            raise VaultError("Для хранилища Linux нужна отдельная фраза длиной от 16 символов")
        path = self.folder / "vault.bin"
        try:
            raw = path.read_bytes() if path.exists() else None
            value = dpapi(raw, decrypt=True) if self.windows and raw else decrypt_archive(raw, password) if raw else b"{}"
            values = json.loads(value)
            if not isinstance(values, dict):
                raise ValueError
        except (ArchiveError, ValueError, OSError):
            raise VaultError("Не удалось открыть хранилище: проверьте фразу и учётную запись") from None
        self.password, self.values = password, values

    def get(self, name: str) -> str:
        if self.values is None:
            if self.windows:
                self.unlock("")
            else:
                raise VaultError("Разблокируйте локальное хранилище Linux")
        assert self.values is not None
        return self.values.get(name, "")

    def put(self, name: str, value: str) -> None:
        self.get(name)
        assert self.values is not None
        next_values = {**self.values, name: value}
        raw = json.dumps(next_values).encode()
        encoded = dpapi(raw) if self.windows else encrypt_archive(raw, self.password or "")
        atomic_write(self.folder / "vault.bin", encoded)
        self.values = next_values
