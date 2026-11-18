"""Submission history (SQLite) + admin PIN. Stored in %APPDATA%\\EkavachFiller."""
import csv
import hashlib
import hmac
import json
import os
import sqlite3
import time

import licensing

DB = licensing.user_dir() / "history.db"
PIN_FILE = licensing.user_dir() / "admin.json"

COLS = ["ts", "portal_user", "ekavach_id", "patient", "status", "score", "message", "answers"]


def _conn():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS entries(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, portal_user TEXT, ekavach_id TEXT,
        patient TEXT, status TEXT, score TEXT, message TEXT, answers TEXT)""")
    return c


def add(portal_user, ekavach_id, patient, status, score="", message="", answers=None):
    with _conn() as c:
        c.execute("INSERT INTO entries(ts,portal_user,ekavach_id,patient,status,score,message,answers) "
                  "VALUES(?,?,?,?,?,?,?,?)",
                  (time.strftime("%Y-%m-%d %H:%M:%S"), portal_user, ekavach_id, patient, status,
                   str(score), message, json.dumps(answers or {}, ensure_ascii=False)))


def rows(status="", text="", limit=10000):
    q, a = "SELECT id,ts,portal_user,ekavach_id,patient,status,score,message,answers FROM entries WHERE 1=1", []
    if status and status != "All":
        q += " AND status=?"
        a.append(status)
    if text:
        q += " AND (ekavach_id LIKE ? OR patient LIKE ? OR portal_user LIKE ?)"
        a += [f"%{text}%"] * 3
    q += " ORDER BY id DESC LIMIT ?"
    a.append(limit)
    with _conn() as c:
        return c.execute(q, a).fetchall()


def summary():
    with _conn() as c:
        return dict(c.execute("SELECT status, COUNT(*) FROM entries GROUP BY status").fetchall())


def clear():
    with _conn() as c:
        c.execute("DELETE FROM entries")


def export_csv(path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for r in reversed(rows()):
            w.writerow(r[1:])


# ---- admin PIN -----------------------------------------------------------
def _hash(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 200_000).hex()


def pin_is_set():
    return PIN_FILE.exists()


def set_pin(pin):
    salt = os.urandom(16)
    PIN_FILE.write_text(json.dumps({"salt": salt.hex(), "hash": _hash(pin, salt)}), encoding="utf-8")


def check_pin(pin):
    try:
        d = json.loads(PIN_FILE.read_text(encoding="utf-8"))
        return hmac.compare_digest(_hash(pin, bytes.fromhex(d["salt"])), d["hash"])
    except Exception:
        return False
