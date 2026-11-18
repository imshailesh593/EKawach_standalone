r"""VENDOR ONLY - publish an update. Never ship this folder or update_private.pem.

  python publish_update.py --installer ..\installer\output\EkavachFiller_Setup_1.0.1.exe \
        --version 1.0.1 --notes "Fixed X, added Y" [--channel stable] [--mandatory]

Creates vendor_tools\release\<channel>.json and copies the installer next to it.
Upload BOTH files to your update folder (the URL you set as UPDATE_BASE_URL / update_base_url).
"""
import argparse
import base64
import datetime
import hashlib
import json
import shutil
from pathlib import Path

from cryptography.hazmat.primitives import serialization as S

ap = argparse.ArgumentParser()
ap.add_argument("--installer", required=True)
ap.add_argument("--version", required=True, help="e.g. 1.0.1 (must be higher than clients' version)")
ap.add_argument("--notes", default="")
ap.add_argument("--channel", default="stable", help="stable | beta | any name")
ap.add_argument("--mandatory", action="store_true", help="clients cannot skip this update")
a = ap.parse_args()

here = Path(__file__).parent
src = Path(a.installer)
out = here / "release"
out.mkdir(exist_ok=True)
shutil.copy2(src, out / src.name)
sha = hashlib.sha256(src.read_bytes()).hexdigest()

manifest = json.dumps({"version": a.version, "file": src.name, "sha256": sha, "notes": a.notes,
                       "mandatory": a.mandatory, "published": datetime.date.today().isoformat()},
                      separators=(",", ":"))
priv = S.load_pem_private_key((here / "update_private.pem").read_bytes(), None)
sig = base64.urlsafe_b64encode(priv.sign(manifest.encode())).decode().rstrip("=")
(out / f"{a.channel}.json").write_text(json.dumps({"manifest": manifest, "signature": sig}, indent=1),
                                       encoding="utf-8")
print(f"Published v{a.version} to {out}\n  upload: {src.name} and {a.channel}.json\n  sha256: {sha}")
