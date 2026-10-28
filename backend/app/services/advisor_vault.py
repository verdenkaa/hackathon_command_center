"""Current Windows account DPAPI; never falls back to plaintext or environment."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path

from app.config import settings


class VaultUnavailable(RuntimeError):
    pass


def available() -> bool:
    return os.name == 'nt'


def _path() -> Path:
    # Outside application data: excluded from application backups and exports.
    root = os.environ.get('LOCALAPPDATA')
    if not root or not available():
        raise VaultUnavailable('Защищённое хранилище Windows недоступно')
    import hashlib
    instance = hashlib.sha256(str(settings.data_dir.resolve()).encode()).hexdigest()[:16]
    return Path(root) / 'HackathonCommandCenter' / instance / 'gemini.dpapi'


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(value: bytes, *, decrypt: bool = False) -> bytes:
    if not available():
        raise VaultUnavailable('Требуется Windows DPAPI под учётной записью сервера')
    source = ctypes.create_string_buffer(value)
    incoming = Blob(len(value), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        ok = crypt32.CryptUnprotectData(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing))
    else:
        ok = crypt32.CryptProtectData(ctypes.byref(incoming), 'Gemini API', None, None, None, 1, ctypes.byref(outgoing))
    if not ok:
        raise VaultUnavailable('DPAPI не смог открыть хранилище для текущей учётной записи')
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel32.LocalFree(outgoing.data)


def is_saved() -> bool:
    try:
        return _path().is_file()
    except VaultUnavailable:
        return False


def save(secret: str) -> None:
    if not secret.strip() or len(secret) > 4096:
        raise VaultUnavailable('Ключ пустой или слишком длинный')
    encrypted = _crypt(secret.strip().encode('utf-8'))
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.pending')
    temp.write_bytes(encrypted)
    temp.replace(path)


def load() -> str:
    try:
        return _crypt(_path().read_bytes(), decrypt=True).decode('utf-8')
    except (OSError, UnicodeError) as exc:
        raise VaultUnavailable('Ключ не задан или хранилище недоступно') from None


def delete() -> None:
    _path().unlink(missing_ok=True)

