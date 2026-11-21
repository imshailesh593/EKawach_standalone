"""Over-the-air update client.

The vendor publishes <channel>.json (e.g. stable.json) + the installer on any static HTTPS host.
<channel>.json = {"manifest": "<JSON string>", "signature": "<Ed25519 over that exact string>"}
manifest = {version, file, sha256, notes, mandatory, published}
The client trusts nothing that isn't signed with the vendor's update key, and checks the
installer's SHA-256 before running it.
"""
import base64
import hashlib
import json
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

import licensing

# Where updates are published (folder URL, no trailing file). Can be overridden in config.json
# as "update_base_url". Empty = updates disabled.
UPDATE_BASE_URL = "https://github.com/imshailesh593/EKawach_standalone/releases/latest/download"
UPDATE_PUBLIC_KEY_B64 = "5MbbZBC+605WFxAFx4LW3FoBV4yKKviyvZ0OmgaI1MU="
MAX_INSTALLER_BYTES = 500 * 1024 * 1024


class UpdateError(Exception):
    pass


def _ver(v: str):
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except ValueError:
        raise UpdateError(f"bad version '{v}'")


def _check_url(url: str):
    u = urlparse(url)
    if u.scheme != "https" and not (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost")):
        raise UpdateError("update URL must be https")


def _get(url: str, timeout=20) -> bytes:
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": f"EkavachFiller/{licensing.APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check(cfg: dict, current: str = None):
    """Return the manifest dict (with 'installer_url') if a newer signed version exists, else None."""
    base = (cfg.get("update_base_url") or UPDATE_BASE_URL).strip()
    if not base:
        raise UpdateError("Update server not configured.")
    channel = cfg.get("update_channel", "stable")
    manifest_url = base.rstrip("/") + f"/{channel}.json"
    try:
        outer = json.loads(_get(manifest_url))
        body = outer["manifest"]
        sig = base64.urlsafe_b64decode(outer["signature"] + "=" * (-len(outer["signature"]) % 4))
        Ed25519PublicKey.from_public_bytes(base64.b64decode(UPDATE_PUBLIC_KEY_B64)).verify(sig, body.encode())
        m = json.loads(body)
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError(f"Could not read a valid signed update manifest ({type(e).__name__}).")
    if _ver(m["version"]) <= _ver(current or licensing.APP_VERSION):
        return None
    m["installer_url"] = urljoin(manifest_url, m["file"])
    _check_url(m["installer_url"])
    return m


def download(m: dict, progress=None) -> Path:
    """Download the installer to a temp folder and verify its SHA-256."""
    _check_url(m["installer_url"])
    dest = Path(tempfile.mkdtemp(prefix="ekupd_")) / Path(urlparse(m["installer_url"]).path).name
    h = hashlib.sha256()
    req = urllib.request.Request(m["installer_url"], headers={"User-Agent": "EkavachFiller"})
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(256 * 1024):
            done += len(chunk)
            if done > MAX_INSTALLER_BYTES:
                raise UpdateError("Installer too large.")
            h.update(chunk)
            f.write(chunk)
            if progress and total:
                progress(done * 100 // total)
    if h.hexdigest().lower() != m["sha256"].lower():
        dest.unlink(missing_ok=True)
        raise UpdateError("Downloaded file failed the integrity check (SHA-256 mismatch). Not installed.")
    return dest


def apply(installer: Path):
    """Launch the verified installer silently; the caller must exit the app right after."""
    subprocess.Popen([str(installer), "/SILENT", "/NOCANCEL", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
                     close_fds=True, creationflags=0x00000008)  # DETACHED_PROCESS
