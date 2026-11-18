"""VENDOR ONLY - licence issuing tool. Never ship this folder or private_key.pem.
Run:  python license_manager.py
Keeps a register of every key you issue in issued_licenses.json (next to this file).
"""
import base64
import datetime
import json
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from cryptography.hazmat.primitives import serialization as S

HERE = Path(__file__).parent
REG = HERE / "issued_licenses.json"
PRIV = S.load_pem_private_key((HERE / "private_key.pem").read_bytes(), None)
b64 = lambda x: base64.urlsafe_b64encode(x).decode().rstrip("=")


def make_key(name, machine, expires):
    payload = json.dumps({"n": name, "m": machine, "e": expires}, separators=(",", ":")).encode()
    return b64(payload) + "." + b64(PRIV.sign(payload))


def load():
    return json.loads(REG.read_text(encoding="utf-8")) if REG.exists() else []


def save(rows):
    REG.write_text(json.dumps(rows, indent=2), encoding="utf-8")


root = tk.Tk()
root.title("eKavach Filler - Licence Manager (vendor)")
root.geometry("980x560")
f = ttk.Frame(root, padding=10)
f.pack(fill="both", expand=True)

name_v, mach_v, exp_v, any_v = tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.BooleanVar()
for i, (lbl, var) in enumerate((("Customer name", name_v), ("Machine ID", mach_v),
                                ("Expires (YYYY-MM-DD, blank = never)", exp_v))):
    ttk.Label(f, text=lbl).grid(row=i, column=0, sticky="w", pady=2)
    ttk.Entry(f, textvariable=var, width=50).grid(row=i, column=1, sticky="w", padx=6)
ttk.Checkbutton(f, text="Works on any PC (not locked to a Machine ID)", variable=any_v).grid(row=3, column=1, sticky="w")
out = tk.Text(f, height=5, wrap="char")
out.grid(row=5, column=0, columnspan=3, sticky="ew", pady=6)

cols = ("Issued", "Customer", "Machine ID", "Expires", "Status")
tree = ttk.Treeview(f, columns=cols, show="headings", height=10)
for c, w in zip(cols, (110, 220, 220, 110, 90)):
    tree.heading(c, text=c)
    tree.column(c, width=w)
tree.grid(row=6, column=0, columnspan=3, sticky="nsew")
f.rowconfigure(6, weight=1)
f.columnconfigure(2, weight=1)


def refresh():
    tree.delete(*tree.get_children())
    today = datetime.date.today().isoformat()
    for r in reversed(load()):
        st = "Expired" if r["expires"] and r["expires"] < today else "Active"
        tree.insert("", "end", iid=r["key"][-24:], values=(r["issued"], r["name"], r["machine"],
                                                           r["expires"] or "never", st))


def generate():
    name, exp = name_v.get().strip(), exp_v.get().strip()
    machine = "*" if any_v.get() else mach_v.get().strip().upper()
    if not name or not machine:
        return messagebox.showerror("Missing", "Enter a customer name and a Machine ID (or tick 'any PC').")
    if exp:
        try:
            datetime.date.fromisoformat(exp)
        except ValueError:
            return messagebox.showerror("Bad date", "Use YYYY-MM-DD.")
    key = make_key(name, machine, exp)
    rows = load()
    rows.append({"issued": datetime.date.today().isoformat(), "name": name, "machine": machine,
                 "expires": exp, "key": key})
    save(rows)
    out.delete("1.0", "end")
    out.insert("end", key)
    root.clipboard_clear()
    root.clipboard_append(key)
    refresh()
    messagebox.showinfo("Licence created", "Key copied to clipboard. Send it to the customer.")


def copy_selected():
    sel = tree.selection()
    if sel:
        key = next(r["key"] for r in load() if r["key"][-24:] == sel[0])
        root.clipboard_clear()
        root.clipboard_append(key)
        out.delete("1.0", "end")
        out.insert("end", key)


def delete_selected():
    sel = tree.selection()
    if sel and messagebox.askyesno("Remove", "Remove this record from the register?\n"
                                   "(The key itself still works until it expires.)"):
        save([r for r in load() if r["key"][-24:] != sel[0]])
        refresh()


bar = ttk.Frame(f)
bar.grid(row=4, column=0, columnspan=3, sticky="w", pady=6)
ttk.Button(bar, text="Generate licence", command=generate).pack(side="left", padx=4)
ttk.Button(bar, text="Copy selected key", command=copy_selected).pack(side="left", padx=4)
ttk.Button(bar, text="Remove record", command=delete_selected).pack(side="left", padx=4)
refresh()
root.mainloop()
