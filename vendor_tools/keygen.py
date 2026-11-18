"""VENDOR ONLY - never ship this folder or private_key.pem.

Usage:
  python keygen.py --name "Customer Name" --machine ABCDE-12345-FGHIJ-67890 [--expires 2027-12-31]
  python keygen.py --name "Customer Name" --any-machine            (works on any PC)
The customer sends you the Machine ID shown in the app's License window.
"""
import argparse
import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization as S

ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True)
g = ap.add_mutually_exclusive_group(required=True)
g.add_argument("--machine")
g.add_argument("--any-machine", action="store_true")
ap.add_argument("--expires", default="", help="YYYY-MM-DD, blank = perpetual")
a = ap.parse_args()

priv = S.load_pem_private_key((Path(__file__).parent / "private_key.pem").read_bytes(), None)
payload = json.dumps({"n": a.name, "m": "*" if a.any_machine else a.machine.strip().upper(),
                      "e": a.expires}, separators=(",", ":")).encode()
b = lambda x: base64.urlsafe_b64encode(x).decode().rstrip("=")
print(b(payload) + "." + b(priv.sign(payload)))
