"""
eKavach CBAC Auto-Filler
------------------------
Logs in to eKavach, opens NCD > NCD Enrollment feature > Pending CBAC List,
and fills the CBAC form for each pending patient (dropdowns, checkboxes and
Yes/No radio buttons), then optionally submits.

Run the GUI:      python ekavach_filler.py
Headless dry run: python ekavach_filler.py --cli --dry-run --max 1
"""
import argparse
import csv
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

import history
import licensing
import updater
import vault

BASE = licensing.user_dir()          # writable per-user data folder (config, screenshots)
CONFIG_FILE = BASE / "config.json"
TASKS = ["1. CBAC form  (Pending CBAC List)",
         "2. Personal history + height/weight  (NCD Screening - needs CSV)"]
LOGIN_URL = "https://ekavach.nhm.up.gov.in/imtecho-ui/"

# Examination tabs opened after Personal History is saved. ALL values come from the CSV - never invented.
#   num    : number inputs {column: (min, max)}      radios : Yes/No questions (default No when the tab is used)
#   checks : tick-boxes (ticked only if the CSV says yes)   status : CSV column holding the clinical status
_S2 = ("SUSPECTED", "NO_ABNORMALITY")
_S3 = ("SUSPECTED", "CONFIRMED", "NO_ABNORMALITY")
CLINICAL = [
    {"label": "Hypertension", "pane": "hypertension-main", "dto": "hypertensionDto", "ok": _S2,
     "num": {"systolicBloodPressure": (40, 300), "diastolicBloodPressure": (20, 200), "heartRate": (20, 250)},
     "radios": [], "checks": [], "status": "hypertensionStatus",
     "required": ["systolicBloodPressure", "diastolicBloodPressure", "heartRate", "hypertensionStatus"]},
    {"label": "Diabetes", "pane": "diabetes-main", "dto": "diabetesDto", "ok": _S2,
     "num": {"fastingBloodSugar": (20, 800), "postPrandialBloodSugar": (20, 800),
             "bloodSugar": (20, 800), "hba1c": (0, 100)},
     "radios": [], "checks": [], "status": "diabetesStatus", "required": ["bloodSugar", "diabetesStatus"]},
    {"label": "Oral", "pane": "oral-main", "dto": "oralDto", "ok": _S3, "num": {},
     "radios": ["anyIssuesInMouth"], "checks": ["restrictedMouthOpening"], "status": "oralStatus",
     "required": ["oralStatus"]},
    {"label": "Breast", "pane": "breast-main", "dto": "breastDto", "ok": _S3, "num": {}, "radios": [],
     "checks": ["sizeChange", "colorChange", "painInBreast", "nippleNotOnSameLevel", "anyRetractionOfNipple",
                "lymphadenopathy", "dischargeFromNipple"],
     "status": "breastStatus", "required": ["breastStatus"]},
    {"label": "Cervical", "pane": "cervical-main", "dto": "cervicalDto", "ok": _S3, "num": {},
     "radios": ["excessiveBleedingDuringPeriods", "bleedingBetweenPeriods", "postmenopausalBleeding",
                "bleedingAfterIntercourse", "excessiveSmellingVaginalDischarge", "trainedViaExamination",
                "excessiveDischarge"],
     "checks": [], "status": "cervicalStatus", "required": ["cervicalStatus"]},
]


ORDER = ["Personal History", "Hypertension", "Diabetes", "Oral", "Breast", "Cervical", "COPD"]


def norm_status(v):
    low = str(v).strip().lower().replace("_", " ")
    if "suspect" in low:
        return "SUSPECTED"
    if "confirm" in low:
        return "CONFIRMED"
    if "no abnormal" in low or low in ("normal", "no", "none", "nad"):
        return "NO_ABNORMALITY"
    return None


# Yes/No questions on the form (radio `name` attribute). Default answer = No.
RADIO_FIELDS = [
    "consumeAlcoholDaily", "bpDiabetesHeartHistory",
    # Early detection
    "shortnessOfBreath", "coughingMoreThan2Weeks", "fever2weeks", "weightLoss",
    "nightSweats", "currentlyTakingAntiTBDrugs", "AnyoneInFamilyCurrentTB",
    "historyOfTb", "bloodInSputum", "recurrentUlceration", "recurrentTingling",
    "cloudyVision", "difficultyInReading", "eyePain", "eyeRedness",
    "difficultyInHearing", "fitsHistory", "difficultyInOpeningMouth",
    "anyMouthUlcers", "anyMouthGrowth", "anyPatch", "voiceToneChange",
    "painInChewing", "skinDiscoloration", "thickenedSkin", "nodulesOnSkin",
    "sensationLossPalm", "clawingOfFingers", "tinglingOrNumbness",
    "inabilityToCloseEyelid", "difficultyWalking", "difficultyHoldingObjects",
    # Occupational exposure
    "cropResidue", "garbageLeaves", "workingInIndustry",
]

# Dropdowns: name -> default option *value*. "" = leave untouched.
SELECT_DEFAULTS = {
    "mobileOwner": "",              # SELF | FAMILY_MEMBER | OTHER
    "educationStatus": "",          # e.g. string:701 (Illiterate)
    "insuranceScheme": "false",     # true = Yes, false = No
    "smokeOrConsumeGutka": "NEVER", # NEVER | IN_PAST | DAILY
    "waist": "FIRST",               # FIRST = lowest bucket (gender-specific list); or LT90 | 91TO100 | GT100 | LT80 | 81TO90 | GT90
    "physicalActivity150Min": "ATLEAST_150",  # ATLEAST_150 | LESS_THAN_150
}

DEFAULT_CONFIG = {
    "username": "",
    "password": "",
    "review_before_submit": False,
    "max_patients": 5,
    "headless": False,
    "defaults": {
        "radio": "no",
        "selects": SELECT_DEFAULTS,
        "issues_none": True,
        "address1": "",
        "address2": "",
    },
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if CONFIG_FILE.exists():
        user = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def to_bool_str(v):
    return "true" if str(v).strip().lower() in ("yes", "y", "true", "1") else "false"


def load_overrides(csv_path):
    """CSV with column `ekavach_id` plus any field names (radio / select names).
    Returns {ekavach_id: {field: value}} in file order (dict preserves order)."""
    rows = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            eid = (r.get("ekavach_id") or "").strip()
            if eid:
                rows[eid] = {k: v.strip() for k, v in r.items()
                             if k != "ekavach_id" and v is not None and v.strip() != ""}
    return rows


class Runner:
    def __init__(self, cfg, log, overrides=None, dry_run=False, confirm=None, stop=None):
        self.cfg, self.log = cfg, log
        self.overrides = overrides or {}
        self.dry_run = dry_run
        self.confirm = confirm          # callable(patient_label) -> "submit" | "skip" | "stop"
        self.stop = stop or threading.Event()
        self.pg = None

    # ---- navigation -------------------------------------------------------
    def login(self):
        pg = self.pg
        for attempt in range(3):  # the portal is sometimes slow / resets connections
            try:
                pg.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
                pg.wait_for_selector("[data-test=username]", timeout=60000)
                break
            except Exception:
                if attempt == 2:
                    raise RuntimeError("Could not reach the eKavach login page. Check your internet connection.")
                self.log("  Portal slow - retrying…")
        pg.fill("[data-test=username]", self.cfg["username"])
        pg.fill("[data-test=password]", self.cfg["password"])
        pg.click("[data-test=login-btn]")
        try:
            pg.wait_for_url("**/dashboard/**", timeout=30000)
        except PWTimeout:
            raise RuntimeError("Login failed - check username/password.")
        pg.wait_for_timeout(2500)
        self.log("Logged in.")

    def open_pending_list(self, tab="Pending CBAC List", wait_sel="button:visible:has-text('Fill CBAC')"):
        pg = self.pg
        if "/ncd/members" not in pg.url:
            pg.get_by_text("NCD", exact=True).first.click()
            pg.wait_for_timeout(700)
            pg.get_by_text("NCD Reports").first.click()
            pg.wait_for_timeout(700)
            pg.get_by_text("NCD Enrollment feature").first.click()
            pg.wait_for_timeout(3500)
        pg.mouse.move(900, 500)  # close the flyout menu
        pg.locator("a:visible", has_text=tab).first.click()
        pg.wait_for_selector(wait_sel, timeout=30000)
        pg.wait_for_timeout(500)

    def pending_rows(self):
        """[(ekavach_id, patient_name)] for visible rows in the pending tab."""
        return self.pg.evaluate("""()=>[...document.querySelectorAll('tbody tr')]
            .filter(r=>r.offsetParent && /Fill CBAC/.test(r.innerText))
            .map(r=>{const c=r.querySelectorAll('td');return [c[1].innerText.trim(), c[0].innerText.trim()]})""")

    def click_fill(self, eid):
        row = self.pg.locator("tbody tr:visible", has_text=eid).first
        row.locator("button:has-text('Fill CBAC')").click()
        self.pg.wait_for_selector("select[name=insuranceScheme]", timeout=30000)
        self.pg.wait_for_timeout(1500)

    # ---- form filling -----------------------------------------------------
    def rec(self, eid, name, status, score="", msg="", answers=None):
        try:
            history.add(self.cfg.get("username", ""), eid, name, status, score, msg, answers)
        except Exception as e:  # history must never break a run
            self.log(f"  (could not write history: {e})")

    def fill_form(self, eid):
        pg, d = self.pg, self.cfg["defaults"]
        ov = self.overrides.get(eid, {})
        answers = {}

        # selects
        for name, default in d["selects"].items():
            val = ov.get(name, default)
            if val == "":
                continue
            sel = pg.locator(f"select[name={name}]")
            answers[name] = val
            if val.upper() == "FIRST":  # first real option (e.g. waist differs by gender)
                val = sel.locator("option").nth(1).get_attribute("value")
                sel.select_option(value=val, timeout=3000)
                continue
            try:
                sel.select_option(value=val, timeout=3000)
            except Exception:  # allow the visible label too ("Never", "Yes", ...)
                sel.select_option(label=val, timeout=3000)

        # "Do you have any of the following problems?" -> None
        if d.get("issues_none", True):
            box = pg.locator("input[type=checkbox][ng-model='ncdmd.cbac.issues.none']")
            if not box.is_checked():
                box.evaluate("e => e.click()")  # styled label overlays the real input
                if not box.is_checked():
                    raise RuntimeError("could not tick 'None' checkbox")

        # text fields
        for key, model in (("address1", "ncdmd.cbac.address1"), ("address2", "ncdmd.cbac.address2")):
            v = ov.get(key, d.get(key, ""))
            if v:
                pg.locator(f"input[ng-model='{model}']").fill(v)

        # radios
        default_radio = to_bool_str(d.get("radio", "no"))
        # Discover every Yes/No group actually on the page (female patients get extra breast /
        # gynae questions; the form may add more later), not just the known list.
        page_radios = pg.evaluate("()=>[...new Set([...document.querySelectorAll('input[type=radio]')]"
                                  ".map(r=>r.name).filter(n=>n))]")
        for name in list(dict.fromkeys(RADIO_FIELDS + page_radios)):
            if name not in page_radios:
                continue  # question not shown for this patient
            val = to_bool_str(ov[name]) if name in ov else default_radio
            answers[name] = "Yes" if val == "true" else "No"
            r = pg.locator(f"input[type=radio][name='{name}'][value='{val}']")
            r.evaluate("e => e.click()")  # DOM click: immune to overlapping labels
            if not r.is_checked():
                raise RuntimeError(f"could not set radio '{name}'")

        # Safety net: refuse to submit if any Yes/No group is still unanswered.
        missing = pg.evaluate("""()=>{const g={};document.querySelectorAll('input[type=radio]').forEach(r=>{
            if(r.name){g[r.name]=g[r.name]||r.checked}; if(r.checked)g[r.name]=true});
            return Object.keys(g).filter(k=>!g[k])}""")
        if missing:
            raise RuntimeError("unanswered questions: " + ", ".join(missing))
        pg.wait_for_timeout(400)
        score = pg.locator("input[name=cbacScore]").input_value()
        return score, answers

    def submit(self, eid):
        pg = self.pg
        pg.locator("button:has-text('Submit')").first.click()
        try:
            pg.wait_for_url("**/ncd/members*", timeout=20000)
            return True
        except PWTimeout:
            return False


    # ---- task 2: Personal history + examination (NCD Screening list) ------------
    def screening_rows(self):
        """[(ekavach_id, name)] of NCD Screening rows whose Examine button is enabled."""
        return self.pg.evaluate("""()=>[...document.querySelectorAll('tbody tr')]
            .filter(r=>r.offsetParent && r.querySelector('button.dropdown-toggle:not(.disabled)'))
            .map(r=>{const c=r.querySelectorAll('td');return [c[1].innerText.trim(), c[0].innerText.trim()]})""")

    def open_exam_tab(self, eid):
        pg = self.pg
        row = pg.locator("tbody tr:visible", has_text=eid).first
        row.locator("button.dropdown-toggle").click()
        pg.wait_for_timeout(500)
        with pg.context.expect_page(timeout=30000) as info:
            row.locator("a.dropdown-item", has_text="Perform Screening").first.evaluate("e => e.click()")
        tab = info.value
        tab.set_default_timeout(30000)
        tab.wait_for_function("()=>!!(document.querySelector('.nav-tabs a.active')||document.querySelector('.nav-tabs li.active'))",
                              timeout=45000)
        try:  # wait until the patient summary (right-hand panel) has loaded
            tab.wait_for_function("()=>/Score/.test(document.body.innerText)", timeout=25000)
        except Exception:
            pass
        tab.wait_for_timeout(1500)
        return tab

    def fill_exam(self, tab, eid):
        d, ov = self.cfg["defaults"], self.overrides.get(eid, {})
        answers = {}
        # measurements must be supplied - they are never invented
        try:
            h, w = float(ov.get("height", "")), float(ov.get("weight", ""))
        except ValueError:
            raise RuntimeError("no height/weight supplied in the CSV for this patient")
        if not (60 <= h <= 250 and 10 <= w <= 150):
            raise RuntimeError(f"height {h} / weight {w} outside the form's allowed range (60-250 cm, 10-150 kg)")
        # Health Infrastructure (hidden 'chosen' select): first real option unless the CSV names one
        sel = tab.locator("select[ng-model='ncdmd.member.cbac.referredFromInstitute']")
        want = ov.get("healthInfrastructure", "")
        try:  # options are loaded asynchronously
            sel.evaluate("e => new Promise(res => { const t = setInterval(() => { if (e.options.length > 1) "
                         "{ clearInterval(t); res(true) } }, 200); setTimeout(() => { clearInterval(t); res(false) }, 20000) })")
        except Exception:
            pass
        picked = sel.evaluate("""(e, want) => {
            let i = [...e.options].findIndex((o, k) => k > 0 && (!want || o.text.trim() === want));
            if (i < 1) return null;
            e.selectedIndex = i; e.dispatchEvent(new Event('change', {bubbles: true}));
            return e.options[i].text.trim()}""", want)
        if not picked:
            raise RuntimeError("could not choose Health Infrastructure")
        answers["healthInfrastructure"] = picked
        # Personal history radios (default No, overridable by column name)
        default_radio = to_bool_str(d.get("radio", "no"))
        names = tab.evaluate("()=>[...new Set([...document.querySelectorAll('input[type=radio]')]"
                             ".filter(r=>r.offsetParent).map(r=>r.name).filter(n=>n))]")
        for name in names:
            val = to_bool_str(ov[name]) if name in ov else default_radio
            answers[name] = "Yes" if val == "true" else "No"
            r = tab.locator(f"input[type=radio][name='{name}'][value='{val}']")
            r.evaluate("e => e.click()")
            if not r.is_checked():
                raise RuntimeError(f"could not set radio '{name}'")
        tab.fill("input[name=height]", str(ov["height"]))
        tab.fill("input[name=weight]", str(ov["weight"]))
        answers["height"], answers["weight"] = ov["height"], ov["weight"]
        tab.wait_for_timeout(500)
        bmi = tab.evaluate("()=>{const i=document.querySelector('input[name=bmi]')||"
                           "[...document.querySelectorAll('input')].find(x=>x.offsetParent&&x.readOnly&&x.type=='text'&&!x.placeholder);"
                           "return i?i.value:''}")
        answers["bmi_shown"] = bmi
        return bmi, answers

    def save_exam(self, tab):
        """Click Save & Continue. Returns (ok, message)."""
        tab.locator("button:visible:has-text('Save & Continue')").first.click()
        tab.wait_for_timeout(4000)
        invalid = tab.evaluate("()=>[...document.querySelectorAll('.is-invalid')].filter(e=>e.offsetParent).length")
        toast = tab.evaluate("()=>[...document.querySelectorAll('.toast, .toast-message, [class*=toast]')]"
                             ".map(e=>e.innerText.trim()).filter(Boolean).join(' | ')")
        if invalid:
            return False, f"{invalid} field(s) still invalid"
        return True, toast or "Saved (no validation errors)"


    # ---- Hypertension / Diabetes / Oral / Breast / Cervical tabs --------------
    @staticmethod
    def _keys(sp):
        return list(sp["num"]) + sp["radios"] + sp["checks"] + [sp["status"]]

    def active_clinical(self, eid):
        ov = self.overrides.get(eid, {})
        return [sp for sp in CLINICAL if any(k in ov for k in self._keys(sp))]

    def check_clinical(self, eid):
        """Validate CSV data for the tabs BEFORE anything is saved. Returns a list of problems."""
        ov, problems = self.overrides.get(eid, {}), []
        for sp in self.active_clinical(eid):
            miss = [k for k in sp["required"] if k not in ov]
            if miss:
                problems.append(f"{sp['label']}: CSV is missing {', '.join(miss)}")
            for k, (lo, hi) in sp["num"].items():
                if k in ov:
                    try:
                        if not lo <= float(ov[k]) <= hi:
                            problems.append(f"{sp['label']}: {k}={ov[k]} outside {lo}-{hi}")
                    except ValueError:
                        problems.append(f"{sp['label']}: {k}='{ov[k]}' is not a number")
            if sp["status"] in ov and norm_status(ov[sp["status"]]) not in sp["ok"]:
                nice = " / ".join(x.replace("_", " ").title() for x in sp["ok"])
                problems.append(f"{sp['label']}: {sp['status']} must be one of: {nice}")
        return problems

    def fill_pane(self, tab, sp, eid):
        """Fill one tab's fields (works even while the tab is hidden). Returns (answers, invalid_field_names)."""
        ov = self.overrides.get(eid, {})
        vals = {k: str(ov[k]) for k in sp["num"] if k in ov}
        yn = {k: to_bool_str(ov.get(k, "no")) for k in sp["radios"]}
        cb = {k: to_bool_str(ov.get(k, "no")) == "true" for k in sp["checks"]}
        status = norm_status(ov[sp["status"]])
        rdk = to_bool_str(ov.get("isRdk", "yes")) if sp["dto"] == "diabetesDto" else ""
        tab.evaluate("""([dto, vals, yn, cb, status, want, rdk]) => {
            const fire = (e, t) => e.dispatchEvent(new Event(t, {bubbles: true}));
            const q = m => document.querySelector(`[ng-model='${dto}.${m}']`);
            const need = m => { const e = q(m); if (!e) throw new Error('field not found: ' + m); return e };
            for (const [k, v] of Object.entries(vals)) { const e = need(k); e.value = v; fire(e, 'input'); fire(e, 'change'); }
            for (const [k, v] of Object.entries(yn)) {
                const r = document.querySelector(`input[type=radio][ng-model='${dto}.${k}'][value='${v}']`);
                if (!r) throw new Error('radio not found: ' + k); r.click(); }
            for (const [k, v] of Object.entries(cb)) { const e = need(k); if (e.checked !== v) e.click(); }
            const pick = (e, f) => { const i = [...e.options].findIndex((o, k) => k > 0 && f(o));
                if (i < 1) throw new Error('option not found'); e.selectedIndex = i; fire(e, 'change'); };
            pick(need('status'), o => o.value === status);
            pick(need('referredFromInstitute'), o => !want || o.text.trim() === want);
            if (rdk) { const r = document.querySelector(`input[type=radio][ng-model='${dto}.isRdk'][value='${rdk}']`);
                       if (r) r.click(); }
        }""", [sp["dto"], vals, yn, cb, status, ov.get("healthInfrastructure", ""), rdk])
        tab.wait_for_timeout(500)
        invalid = tab.evaluate("(p)=>[...document.querySelectorAll('#'+p+' input.ng-invalid, #'+p+' select.ng-invalid')]"
                               ".map(e=>e.name||e.getAttribute('ng-model'))", sp["pane"])
        L = sp["label"]
        ans = {f"{L}.{k}": v for k, v in vals.items()}
        ans.update({f"{L}.{k}": ("Yes" if v == "true" else "No") for k, v in yn.items()})
        ans.update({f"{L}.{k}": ("Yes" if v else "No") for k, v in cb.items()})
        ans[f"{L}.status"] = status
        if rdk:
            ans[f"{L}.bloodGlucoseTestDone"] = "Yes" if rdk == "true" else "No"
        return ans, invalid

    def active_tab(self, tab):
        # the portal puts 'active' on the <a> for some patients and on the <li> for others
        return tab.evaluate("()=>{const a=document.querySelector('.nav-tabs a.active')||"
                            "document.querySelector('.nav-tabs li.active a')||document.querySelector('.nav-tabs li.active');"
                            "return a?a.innerText.trim():''}")

    def wait_active_change(self, tab, cur, timeout=25):
        end = time.time() + timeout
        while time.time() < end:
            now = self.active_tab(tab)
            if now and now != cur:
                return now
            tab.wait_for_timeout(500)
        return cur

    def todo_tabs(self, eid, cur):
        """CSV-supplied tabs that still need doing, given the portal's current step."""
        i0 = ORDER.index(cur) if cur in ORDER else 0
        todo, skipped = [], []
        for sp in self.active_clinical(eid):
            (todo if ORDER.index(sp["label"]) >= i0 else skipped).append(sp["label"])
        return todo, skipped

    def dry_exam(self, tab, eid):
        """Dry run: fill what the portal currently shows (and the supplied later tabs, hidden). Saves nothing."""
        answers, bmi = {}, ""
        cur = self.active_tab(tab)
        self.log(f"  Portal is at step: {cur}")
        todo, skipped = self.todo_tabs(eid, cur)
        for l in skipped:
            self.log(f"  {l}: already recorded in the portal - would be skipped")
        if cur == "Personal History":
            bmi, a = self.fill_exam(tab, eid)
            answers.update(a)
            self.log(f"  Personal history filled (BMI {bmi})")
        for sp in self.active_clinical(eid):
            if sp["label"] in skipped:
                continue
            ans, invalid = self.fill_pane(tab, sp, eid)
            answers.update(ans)
            self.log(f"  {sp['label']} tab: filled, invalid fields: {invalid or 'none'}")
            if invalid:
                raise RuntimeError(f"{sp['label']}: fields still invalid: {invalid}")
        return bmi, answers

    def drive_exam(self, tab, eid):
        """Resumable: complete each unfinished step the portal asks for, in its own order.
        Returns (ok, message, answers, bmi)."""
        answers, parts, bmi = {}, [], ""
        cur = self.active_tab(tab)
        pending, skipped = self.todo_tabs(eid, cur)
        for l in skipped:
            parts.append(f"{l} already recorded")
            self.log(f"  {l}: already recorded in the portal - skipped")

        def result(ok, extra=""):
            return ok, "; ".join(parts + ([extra] if extra else [])), answers, bmi

        for _ in range(10):
            cur = self.active_tab(tab)
            if cur == "Personal History":
                bmi, a = self.fill_exam(tab, eid)
                answers.update(a)
                self.log(f"  Personal history filled (BMI {bmi})")
                ok, msg = self.save_exam(tab)
                if not ok:
                    return result(False, f"Personal History FAILED: {msg}")
                parts.append("Personal history saved")
                self.log("  Personal history saved")
                if self.wait_active_change(tab, cur) == cur:
                    return result(False, "portal did not move on after Personal History")
                continue
            if not pending:
                break
            sp = next((x for x in CLINICAL if x["label"] == cur), None)
            if sp is None or sp["label"] not in pending:
                why = "not automated" if sp is None else "no data for it in the CSV"
                return result(False, f"stopped at {cur} ({why}); still to do: {', '.join(pending)}")
            ans, invalid = self.fill_pane(tab, sp, eid)
            answers.update(ans)
            if invalid:
                return result(False, f"{cur} FAILED: invalid fields {invalid}")
            btn = tab.locator(f"#{sp['pane']} button:visible").filter(has_text=re.compile("save|submit|continue", re.I))
            if not btn.count():
                return result(False, f"{cur} FAILED: save button not found")
            btn.first.click()
            tab.wait_for_timeout(3000)
            bad = tab.evaluate("(p)=>[...document.querySelectorAll('#'+p+' .is-invalid')].filter(e=>e.offsetParent).length",
                               sp["pane"])
            if bad:
                return result(False, f"{cur} FAILED: {bad} field(s) invalid")
            parts.append(f"{cur} saved")
            self.log(f"  {cur} saved")
            pending.remove(cur)
            if pending:
                self.wait_active_change(tab, cur)
        if pending:
            return result(False, f"incomplete; still to do: {', '.join(pending)}")
        return result(True)

    def run_exam(self):
        done, failed = [], []
        if not self.overrides:
            raise RuntimeError("This task needs a CSV with columns ekavach_id,height,weight (real measurements).")
        limit = int(self.cfg.get("max_patients") or 0) or 10**9
        self.open_pending_list("NCD Screening", "button.dropdown-toggle:visible")
        eligible = dict(self.screening_rows())
        for eid in self.overrides:
            if len(done) >= limit or self.stop.is_set():
                break
            if eid not in eligible:
                self.log(f"{eid}: not in the NCD Screening list (or already examined) - skipped.")
                self.rec(eid, "", "Skipped", "", "Not available for examination")
                continue
            name = eligible[eid]
            label = f"{name} ({eid})"
            self.log(f"Opening examination form: {label}")
            tab, bmi, answers = None, "", {}
            try:
                problems = self.check_clinical(eid)
                if problems:
                    raise RuntimeError("; ".join(problems))
                tab = self.open_exam_tab(eid)
                if self.dry_run:
                    bmi, answers = self.dry_exam(tab, eid)
                    shot = BASE / f"dryrun_exam_{eid}.png"
                    tab.screenshot(path=str(shot))
                    self.log(f"  DRY RUN - not saved. Screenshot: {shot.name}")
                    self.rec(eid, name, "Dry run", bmi, "Examination filled, not saved", answers)
                    done.append(eid)
                    continue
                action = "submit"
                if self.cfg.get("review_before_submit") and self.confirm:
                    action = self.confirm(label)
                if action == "stop":
                    self.log("Stopped by user.")
                    break
                if action == "skip":
                    self.log("  Skipped (not saved).")
                    self.rec(eid, name, "Skipped", "", "Skipped at review")
                    continue
                ok, msg, answers, bmi = self.drive_exam(tab, eid)
                if ok:
                    self.log(f"  Done. {msg}")
                    self.rec(eid, name, "Submitted", bmi, msg, answers)
                    done.append(eid)
                else:
                    self.log(f"  Not completed: {msg}")
                    self.rec(eid, name, "Failed", bmi, msg, answers)
                    failed.append(eid)
            except Exception as e:
                self.log(f"  ERROR for {label}: {e}")
                self.rec(eid, name, "Error", bmi, str(e).splitlines()[0][:200], answers)
                failed.append(eid)
            finally:
                if tab:
                    try:
                        tab.close()
                    except Exception:
                        pass
        self.log(f"Finished. Saved/filled: {len(done)}, failed: {len(failed)}.")
        return done, failed

    # ---- main loop --------------------------------------------------------
    def run(self):
        ok, msg, _ = licensing.status()
        if not ok:
            raise RuntimeError(f"{msg} Open the License window and enter a valid key.")
        done, failed = [], []
        with sync_playwright() as p:
            browser = None
            for ch in (self.cfg.get("browser", "chrome"), "chrome", "msedge"):
                try:
                    browser = p.chromium.launch(channel=ch, headless=self.cfg.get("headless", False))
                    self.log(f"Using browser: {ch}")
                    break
                except Exception:
                    continue
            if browser is None:
                raise RuntimeError("Neither Google Chrome nor Microsoft Edge could be started.")
            self.pg = browser.new_page(viewport={"width": 1600, "height": 900})
            self.pg.set_default_timeout(30000)
            try:
                self.login()
                if self.cfg.get("task") == "exam":
                    return self.run_exam()
                skip = set()
                limit = int(self.cfg.get("max_patients") or 0) or 10**9
                targets = list(self.overrides) if self.overrides else None
                while len(done) < limit and not self.stop.is_set():
                    self.open_pending_list()
                    rows = [r for r in self.pending_rows() if r[0] not in skip]
                    if targets is not None:
                        rows = [r for r in rows if r[0] in targets and r[0] not in done]
                    if not rows:
                        self.log("No more matching pending patients.")
                        break
                    eid, name = rows[0]
                    label = f"{name} ({eid})"
                    self.log(f"Opening form: {label}")
                    score, answers = "", {}
                    try:
                        self.click_fill(eid)
                        score, answers = self.fill_form(eid)
                        self.log(f"  Filled. CBAC score on form = {score}")
                        if self.dry_run:
                            shot = BASE / f"dryrun_{eid}.png"
                            self.pg.screenshot(path=str(shot), full_page=True)
                            self.log(f"  DRY RUN - not submitted. Screenshot: {shot.name}")
                            self.rec(eid, name, "Dry run", score, "Filled, not submitted", answers)
                            skip.add(eid)
                            done.append(eid)
                            continue
                        action = "submit"
                        if self.cfg.get("review_before_submit") and self.confirm:
                            action = self.confirm(label)
                        if action == "stop":
                            self.log("Stopped by user.")
                            break
                        if action == "skip":
                            self.log("  Skipped (not submitted).")
                            self.rec(eid, name, "Skipped", score, "Skipped at review", answers)
                            skip.add(eid)
                            continue
                        if self.submit(eid):
                            self.log("  Submitted OK.")
                            self.rec(eid, name, "Submitted", score, "", answers)
                            done.append(eid)
                        else:
                            self.log("  Submit did not complete (validation error?). Skipping.")
                            self.rec(eid, name, "Failed", score, "Submit did not complete", answers)
                            failed.append(eid)
                            skip.add(eid)
                    except Exception as e:  # keep going with the next patient
                        self.log(f"  ERROR for {label}: {e}")
                        self.rec(eid, name, "Error", score, str(e).splitlines()[0][:200], answers)
                        failed.append(eid)
                        skip.add(eid)
            finally:
                browser.close()
        self.log(f"Finished. Submitted/filled: {len(done)}, failed: {len(failed)}.")
        return done, failed


# ---------------------------------------------------------------------------
def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    cfg = load_config()
    root = tk.Tk()
    root.title(f"eKavach CBAC Auto-Filler  v{licensing.APP_VERSION}")
    root.geometry("720x560")

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="both", expand=True)

    def row(label, widget, r):
        ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=3)
        widget.grid(row=r, column=1, sticky="ew", pady=3, padx=6)

    last = vault.last_user()
    user_v, pw_v = tk.StringVar(value=last), tk.StringVar(value=vault.get_password(last) if last else "")
    remember_v = tk.BooleanVar(value=True)
    max_v = tk.StringVar(value=str(cfg["max_patients"]))
    review_v = tk.BooleanVar(value=cfg["review_before_submit"])
    dry_v = tk.BooleanVar(value=False)
    csv_v = tk.StringVar()

    acct_row = ttk.Frame(frm)
    user_cb = ttk.Combobox(acct_row, textvariable=user_v, values=vault.usernames())
    user_cb.pack(side="left", fill="x", expand=True)

    def on_pick(*_):
        pw_v.set(vault.get_password(user_v.get()))

    def del_account():
        u = user_v.get().strip()
        if u in vault.usernames() and messagebox.askyesno("Delete", f"Delete saved login '{u}'?"):
            vault.delete(u)
            user_cb.config(values=vault.usernames())
            user_v.set("")
            pw_v.set("")

    user_cb.bind("<<ComboboxSelected>>", on_pick)
    user_cb.bind("<FocusOut>", on_pick)
    ttk.Button(acct_row, text="Delete saved", command=del_account).pack(side="left", padx=4)
    row("Username (saved logins)", acct_row, 0)
    pw_row = ttk.Frame(frm)
    pw_e = ttk.Entry(pw_row, textvariable=pw_v, show="*")
    pw_e.pack(side="left", fill="x", expand=True)
    ttk.Checkbutton(pw_row, text="Remember (encrypted)", variable=remember_v).pack(side="left", padx=6)
    row("Password", pw_row, 1)
    task_v = tk.StringVar(value=TASKS[0])
    mt = ttk.Frame(frm)
    ttk.Entry(mt, textvariable=max_v, width=8).pack(side="left")
    ttk.Label(mt, text="   Task:").pack(side="left")
    ttk.Combobox(mt, textvariable=task_v, values=TASKS, state="readonly", width=48).pack(side="left", padx=4)
    row("Max patients (0 = all)", mt, 2)
    csv_row = ttk.Frame(frm)
    ttk.Entry(csv_row, textvariable=csv_v).pack(side="left", fill="x", expand=True)
    ttk.Button(csv_row, text="Browse…", command=lambda: csv_v.set(
        filedialog.askopenfilename(filetypes=[("CSV", "*.csv")]) or csv_v.get())).pack(side="left", padx=4)
    row("Patient answers CSV (optional)", csv_row, 3)
    ttk.Checkbutton(frm, text="Pause to review each form before submitting",
                    variable=review_v).grid(row=4, column=1, sticky="w")
    ttk.Checkbutton(frm, text="Dry run (fill + screenshot, never submit)",
                    variable=dry_v).grid(row=5, column=1, sticky="w")
    frm.columnconfigure(1, weight=1)

    logbox = scrolledtext.ScrolledText(frm, height=18, state="disabled")
    logbox.grid(row=7, column=0, columnspan=2, sticky="nsew", pady=8)
    frm.rowconfigure(7, weight=1)

    def log(msg):
        def _w():
            logbox.configure(state="normal")
            logbox.insert("end", time.strftime("%H:%M:%S ") + msg + "\n")
            logbox.see("end")
            logbox.configure(state="disabled")
        root.after(0, _w)

    lic_lbl = ttk.Label(frm)
    lic_lbl.grid(row=8, column=0, columnspan=2, sticky="w")

    def refresh_license():
        ok, msg, _ = licensing.status()
        lic_lbl.config(text=f"License: {msg}   |   Installed in: {licensing.install_dir()}",
                       foreground="#1a7f37" if ok else "#c62828")
        start_btn.config(state="normal" if ok else "disabled")
        return ok

    def license_window():
        w = tk.Toplevel(root)
        w.title("License & About")
        w.geometry("640x420")
        w.transient(root)
        f = ttk.Frame(w, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=f"eKavach CBAC Auto-Filler  v{licensing.APP_VERSION}",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")

        def info(label, value, folder=None):
            r = ttk.Frame(f)
            r.pack(fill="x", pady=2)
            ttk.Label(r, text=label, width=16).pack(side="left")
            e = ttk.Entry(r)
            e.insert(0, str(value))
            e.config(state="readonly")
            e.pack(side="left", fill="x", expand=True)
            if folder:
                ttk.Button(r, text="Open", command=lambda: os.startfile(folder)).pack(side="left", padx=4)
            else:
                ttk.Button(r, text="Copy", command=lambda: (root.clipboard_clear(),
                           root.clipboard_append(str(value)))).pack(side="left", padx=4)

        info("Install folder", licensing.install_dir(), licensing.install_dir())
        info("Data folder", licensing.user_dir(), licensing.user_dir())
        info("Machine ID", licensing.machine_id())
        status_l = ttk.Label(f, wraplength=600)
        status_l.pack(anchor="w", pady=8)
        ttk.Label(f, text="Paste licence key:").pack(anchor="w")
        key_t = tk.Text(f, height=6, wrap="char")
        key_t.pack(fill="x")

        def show():
            ok, msg, _ = licensing.status()
            status_l.config(text=f"Status: {msg}", foreground="#1a7f37" if ok else "#c62828")

        def do_activate():
            ok, msg = licensing.activate(key_t.get("1.0", "end"))
            if not ok:
                messagebox.showerror("Activation failed", msg, parent=w)
            show()
            refresh_license()

        ttk.Button(f, text="Activate", command=do_activate).pack(anchor="w", pady=6)
        ttk.Label(f, text="To buy/renew a licence, send your Machine ID to the vendor.",
                  foreground="#666").pack(anchor="w")
        show()

    def admin_window():
        from tkinter import simpledialog
        if not history.pin_is_set():
            pin = simpledialog.askstring("Admin", "First use: create an admin PIN (4+ characters):",
                                         show="*", parent=root)
            if not pin or len(pin) < 4:
                return
            history.set_pin(pin)
        else:
            pin = simpledialog.askstring("Admin", "Enter admin PIN:", show="*", parent=root)
            if pin is None:
                return
            if not history.check_pin(pin):
                return messagebox.showerror("Admin", "Wrong PIN.")
        w = tk.Toplevel(root)
        w.title("Admin - submission history")
        w.geometry("1100x560")
        top = ttk.Frame(w, padding=8)
        top.pack(fill="x")
        stat_v, find_v = tk.StringVar(value="All"), tk.StringVar()
        ttk.Label(top, text="Status:").pack(side="left")
        ttk.Combobox(top, textvariable=stat_v, width=11, state="readonly",
                     values=["All", "Submitted", "Failed", "Error", "Skipped", "Dry run"]).pack(side="left", padx=4)
        ttk.Label(top, text="Search:").pack(side="left", padx=(10, 0))
        ttk.Entry(top, textvariable=find_v, width=24).pack(side="left", padx=4)
        sum_l = ttk.Label(top)
        sum_l.pack(side="right")
        cols = ("Time", "Ekavach ID", "Patient", "Status", "Score", "Portal user", "Details")
        tree = ttk.Treeview(w, columns=cols, show="headings")
        for c_, wd in zip(cols, (140, 120, 170, 85, 55, 120, 380)):
            tree.heading(c_, text=c_)
            tree.column(c_, width=wd, anchor="w")
        sb = ttk.Scrollbar(w, command=tree.yview)
        tree.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True, padx=8)
        data = {}

        def refresh(*_):
            tree.delete(*tree.get_children())
            data.clear()
            for r in history.rows(stat_v.get(), find_v.get().strip()):
                iid = tree.insert("", "end", values=(r[1], r[3], r[4], r[5], r[6], r[2], r[7]))
                data[iid] = r
            s_ = history.summary()
            sum_l.config(text="   ".join(f"{k}: {v}" for k, v in s_.items()) or "No entries yet")

        def show_answers(_=None):
            sel = tree.selection()
            if not sel:
                return
            r = data[sel[0]]
            a = json.loads(r[8] or "{}")
            d = tk.Toplevel(w)
            d.title(f"Answers - {r[4]} ({r[3]})")
            t = scrolledtext.ScrolledText(d, width=60, height=30)
            t.pack(fill="both", expand=True)
            t.insert("end", f"{r[1]}  |  {r[5]}  |  score {r[6]}\n\n" +
                     "\n".join(f"{k:32} {v}" for k, v in a.items()))
            t.config(state="disabled")

        def export():
            f = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                             initialfile="ekavach_history.csv", parent=w)
            if f:
                history.export_csv(f)
                messagebox.showinfo("Export", f"Saved to {f}", parent=w)

        def clear_all():
            if messagebox.askyesno("Clear", "Permanently delete ALL history?", parent=w):
                history.clear()
                refresh()

        tree.bind("<Double-1>", show_answers)
        stat_v.trace_add("write", refresh)
        find_v.trace_add("write", refresh)
        bar = ttk.Frame(w, padding=8)
        bar.pack(fill="x")
        for t_, cmd in (("Refresh", refresh), ("View answers", show_answers),
                        ("Export CSV", export), ("Clear history", clear_all)):
            ttk.Button(bar, text=t_, command=cmd).pack(side="left", padx=4)
        ttk.Label(bar, text="Double-click a row to see the answers that were entered.",
                  foreground="#666").pack(side="left", padx=10)
        refresh()

    def do_update(m):
        mandatory = bool(m.get("mandatory"))
        msg = (f"Version {m['version']} is available (you have {licensing.APP_VERSION}).\n\n"
               f"{m.get('notes', '')}\n\n")
        if mandatory:
            messagebox.showinfo("Update required", msg + "This update is required and will install now.")
            go = True
        else:
            go = messagebox.askyesno("Update available", msg + "Install now? The app will close and restart.")
        if not go:
            return
        log(f"Downloading update {m['version']}…")

        def _dl():
            try:
                last = [-10]

                def prog(pct):
                    if pct >= last[0] + 10:
                        last[0] = pct
                        log(f"  download {pct}%")

                path = updater.download(m, prog)
                log("Update verified. Installing and restarting…")
                updater.apply(path)
                root.after(1500, root.destroy)
            except Exception as e:
                log(f"Update failed: {e}")
                if mandatory:
                    root.after(0, lambda: start_btn.config(state="disabled"))
                    log("This update is mandatory - Start is disabled until it installs.")

        threading.Thread(target=_dl, daemon=True).start()

    def check_updates(manual=False):
        if manual and str(stop_btn["state"]) == "normal":
            return messagebox.showinfo("Updates", "Stop the current run before updating.")

        def _chk():
            try:
                m = updater.check(load_config())
                if m:
                    root.after(0, lambda: do_update(m))
                elif manual:
                    log(f"You are on the latest version ({licensing.APP_VERSION}).")
            except Exception as e:
                if manual:
                    log(f"Update check failed: {e}")

        threading.Thread(target=_chk, daemon=True).start()

    stop_evt = threading.Event()
    decision = {"v": None}
    decision_evt = threading.Event()

    btns = ttk.Frame(frm)
    btns.grid(row=6, column=0, columnspan=2, sticky="ew")
    start_btn = ttk.Button(btns, text="Start")
    stop_btn = ttk.Button(btns, text="Stop", state="disabled")
    ok_btn = ttk.Button(btns, text="Submit this form", state="disabled")
    skip_btn = ttk.Button(btns, text="Skip", state="disabled")
    lic_btn = ttk.Button(btns, text="License / About", command=lambda: license_window())
    admin_btn = ttk.Button(btns, text="Admin", command=admin_window)
    upd_btn = ttk.Button(btns, text="Check for updates", command=lambda: check_updates(True))
    for b in (start_btn, ok_btn, skip_btn, stop_btn, lic_btn, admin_btn, upd_btn):
        b.pack(side="left", padx=4)

    def decide(v):
        decision["v"] = v
        ok_btn.config(state="disabled")
        skip_btn.config(state="disabled")
        decision_evt.set()

    ok_btn.config(command=lambda: decide("submit"))
    skip_btn.config(command=lambda: decide("skip"))

    def confirm(label):
        decision_evt.clear()
        root.after(0, lambda: (ok_btn.config(state="normal"), skip_btn.config(state="normal")))
        log(f"  >> Check the browser window for {label}, then press 'Submit this form' or 'Skip'.")
        while not decision_evt.wait(0.3):
            if stop_evt.is_set():
                return "stop"
        return decision["v"]

    def worker(c, overrides):
        try:
            Runner(c, log, overrides, dry_run=dry_v.get(), confirm=confirm, stop=stop_evt).run()
        except Exception as e:
            log(f"FATAL: {e}")
        finally:
            root.after(0, lambda: (start_btn.config(state="normal"), stop_btn.config(state="disabled")))

    def start():
        c = load_config()
        c.update(username=user_v.get().strip(), password=pw_v.get(),
                 review_before_submit=review_v.get())
        try:
            c["max_patients"] = int(max_v.get() or 0)
        except ValueError:
            return messagebox.showerror("Error", "Max patients must be a number")
        if not c["username"] or not c["password"]:
            return messagebox.showerror("Error", "Enter username and password")
        save_config({**c, "password": ""})   # never store the password in config.json
        if remember_v.get():
            vault.save(c["username"], c["password"])
            user_cb.config(values=vault.usernames())
        overrides = load_overrides(csv_v.get()) if csv_v.get() else None
        c["task"] = "exam" if task_v.get() == TASKS[1] else "cbac"
        if c["task"] == "exam" and not overrides:
            return messagebox.showerror("CSV needed", "Task 2 needs a CSV with columns:\n"
                                        "ekavach_id, height, weight\n(real measurements for each patient)")
        stop_evt.clear()
        start_btn.config(state="disabled")
        stop_btn.config(state="normal")
        threading.Thread(target=worker, args=(c, overrides), daemon=True).start()

    start_btn.config(command=start)
    stop_btn.config(command=lambda: (stop_evt.set(), log("Stopping after current step…")))
    if not refresh_license():
        root.after(300, license_window)
    root.after(2000, check_updates)   # silent background check at launch
    root.mainloop()


def run_cli(args):
    cfg = load_config()
    if args.user:
        cfg["username"] = args.user
    if args.password:
        cfg["password"] = args.password
    elif cfg["username"] and not cfg["password"]:
        cfg["password"] = vault.get_password(cfg["username"])
    cfg["task"] = args.task
    cfg["max_patients"] = args.max
    cfg["headless"] = args.headless
    cfg["review_before_submit"] = False
    ov = load_overrides(args.csv) if args.csv else None
    Runner(cfg, print, ov, dry_run=args.dry_run).run()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--max", type=int, default=1)
    ap.add_argument("--csv")
    ap.add_argument("--task", choices=["cbac", "exam"], default="cbac")
    ap.add_argument("--user")
    ap.add_argument("--password")
    a = ap.parse_args()
    run_cli(a) if a.cli else run_gui()
