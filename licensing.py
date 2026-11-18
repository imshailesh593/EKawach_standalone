"""Offline licence verification for eKavach CBAC Filler.

A licence key is  base64url(JSON payload) + "." + base64url(Ed25519 signature).
Payload: {"n": customer name, "m": machine id or "*", "e": "YYYY-MM-DD" or ""}
Only the vendor holds the private key (vendor_tools/), so keys cannot be forged.
"""
import base64
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

APP_NAME = "EkavachFiller"
APP_VERSION = "1.0.0"
PUBLIC_KEY_B64 = "+g145/3eOo582/QbarfwqO2oaTzdlaikxZSxI9j8DRY="


def install_dir() -> Path:
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent


def user_dir() -> Path:
    """Writable per-user folder for config, licence and screenshots."""
    d = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def license_path() -> Path:
    return user_dir() / "license.key"


def machine_id() -> str:
    guid = ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            guid = winreg.QueryValueEx(k, "MachineGuid")[0]
    except Exception:
        guid = os.environ.get("COMPUTERNAME", "unknown")
    h = hashlib.sha256(("ekavach-filler|" + guid).encode()).hexdigest()[:20].upper()
    return "-".join(h[i:i + 5] for i in range(0, 20, 5))


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify(key_text: str):
    """Return (ok, message, payload)."""
    try:
        key_text = "".join(key_text.split())
        body, sig = key_text.split(".")
        Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY_B64)).verify(_b64d(sig), _b64d(body))
        p = json.loads(_b64d(body))
    except (InvalidSignature, ValueError, Exception):
        return False, "Invalid licence key.", None
    if p.get("m", "*") not in ("*", machine_id()):
        return False, "This licence was issued for a different computer.", p
    exp = p.get("e", "")
    if exp:
        try:
            if datetime.date.today() > datetime.date.fromisoformat(exp):
                return False, f"Licence expired on {exp}.", p
        except ValueError:
            return False, "Invalid licence key.", None
    who = p.get("n", "")
    return True, f"Licensed to {who}" + (f" (valid until {exp})" if exp else " (perpetual)"), p


# TEMPORARY: set to True before distributing to enforce licence keys.
ENFORCE_LICENSE = True


def status():
    if not ENFORCE_LICENSE:
        return True, "Licensing disabled (development mode)", None
    path = license_path()
    if not path.exists():
        return False, "Not activated.", None
    return verify(path.read_text(encoding="utf-8"))


def activate(key_text: str):
    ok, msg, p = verify(key_text)
    if ok:
        license_path().write_text("".join(key_text.split()), encoding="utf-8")
    return ok, msg
