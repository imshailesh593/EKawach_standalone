"""Saved-logins vault. Passwords are encrypted with Windows DPAPI, so the file
only decrypts for the same Windows user on the same PC (no master password needed)."""
import base64
import ctypes
import json
from ctypes import wintypes as w

import licensing

FILE = licensing.user_dir() / "accounts.json"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", w.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_crypt, _kernel = ctypes.windll.crypt32, ctypes.windll.kernel32
_kernel.LocalFree.argtypes = [ctypes.c_void_p]


def _run(fn, data: bytes) -> bytes:
    buf = ctypes.create_string_buffer(data, len(data))
    src = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("DPAPI failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _kernel.LocalFree(out.pbData)


def _enc(text: str) -> str:
    return base64.b64encode(_run(_crypt.CryptProtectData, text.encode())).decode()


def _dec(token: str) -> str:
    return _run(_crypt.CryptUnprotectData, base64.b64decode(token)).decode()


def _load() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"last": "", "accounts": {}}


def _save(d: dict):
    FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")


def usernames() -> list:
    return sorted(_load()["accounts"])


def last_user() -> str:
    d = _load()
    return d["last"] if d["last"] in d["accounts"] else ""


def get_password(user: str) -> str:
    tok = _load()["accounts"].get(user)
    try:
        return _dec(tok) if tok else ""
    except Exception:
        return ""


def save(user: str, password: str):
    d = _load()
    d["accounts"][user] = _enc(password)
    d["last"] = user
    _save(d)


def delete(user: str):
    d = _load()
    d["accounts"].pop(user, None)
    if d["last"] == user:
        d["last"] = ""
    _save(d)
