# eKavach CBAC Auto-Filler — Full Documentation

Version 1.0.0 · Windows 10/11 (64-bit) · Requires Google Chrome or Microsoft Edge

---

## 1. What it is

A Windows desktop app that automates data entry on the eKavach portal
(`https://ekavach.nhm.up.gov.in/imtecho-ui/`). It logs in, opens
**NCD → NCD Enrollment feature → Pending CBAC List**, clicks **Fill CBAC** for each patient, fills
the CBAC form (6 dropdowns, the "None" checkbox, 37 Yes/No questions), submits, and moves to the
next patient. Every entry is recorded in a local history.

**Important:** the app only types in the answers you give it. By default every Yes/No question is
**No**. Use the CSV (section 5) for patients whose real answers differ. You are responsible for the
accuracy of what is submitted.

---

## 2. Quick start (end user)

1. Run `EkavachFiller_Setup_1.0.0.exe` and follow the wizard (see section 7).
2. Start the app from the Start menu.
3. **License / About** → copy your **Machine ID** → send it to the vendor → paste the key you receive → **Activate**.
4. Enter portal username and password (tick *Remember* to save them), set **Max patients**, press **Start**.
5. Tip: run 1 patient first and confirm it in the portal.

### Main window

| Control | Purpose |
|---|---|
| Username (saved logins) | Dropdown of saved logins; picking one fills the password |
| Password / Remember (encrypted) | Saved on Start when ticked |
| Delete saved | Removes the selected saved login |
| Max patients | How many to process; `0` = all pending |
| Patient answers CSV | Optional per-patient answers (section 5) |
| Pause to review each form | Fill, then wait for you to press *Submit this form* or *Skip* |
| Dry run | Fill and screenshot, **never submit** |
| Start / Stop | Run / stop after the current step |
| License / About | Version, install folder, data folder, Machine ID, activate key |
| Admin | PIN-protected history (section 6) |
| Check for updates | Manual update check (section 9) |

Default behaviour is **auto-submit** (review box unticked).

---

## 3. How a run works

1. Launch Chrome (falls back to Edge) and log in (retries up to 3× if the portal is slow).
2. Open the Pending CBAC List and take the first patient (or the next one in your CSV).
3. Fill: dropdowns → "None" checkbox → address fields (if given) → all radios. Read the CBAC score.
4. Submit and wait for the page to return to the list. If it doesn't (validation error) the patient is marked **Failed** and skipped.
5. Repeat until Max patients is reached or no patients remain.
6. A problem with one patient never stops the run; it is logged and the next one is processed.

### Default answers

| Field | Default |
|---|---|
| All 37 Yes/No questions | No |
| "Do you have any problems?" | None (ticked) |
| Insurance scheme | No |
| Smoke / consume gutka | Never |
| Waist | Lowest bucket (`FIRST`; the list differs for male/female) |
| Physical activity | At least 150 min/week |
| Mobile owner, Education | Left blank |

These defaults give a CBAC score of 0 ("not at any risk"). Change them in `config.json` under `defaults`.

---

## 4. Saved logins (password manager)

* Stored in `%APPDATA%\EkavachFiller\accounts.json`.
* Passwords are encrypted with **Windows DPAPI** — they only decrypt for the same Windows user on the same PC. No master password.
* Passwords are never written to `config.json`.
* If the PC is shared, use separate Windows accounts or untick *Remember*.

---

## 5. Per-patient answers (CSV)

A CSV with a header row and an `ekavach_id` column, plus any columns you want to override.
Empty cells use the defaults. Only patients listed in the CSV are processed. See `patients_example.csv`.

**Yes/No columns** (accept `yes`/`no`/`true`/`false`/`1`/`0`):
`consumeAlcoholDaily, bpDiabetesHeartHistory, shortnessOfBreath, coughingMoreThan2Weeks, fever2weeks, weightLoss, nightSweats, currentlyTakingAntiTBDrugs, AnyoneInFamilyCurrentTB, historyOfTb, bloodInSputum, recurrentUlceration, recurrentTingling, cloudyVision, difficultyInReading, eyePain, eyeRedness, difficultyInHearing, fitsHistory, difficultyInOpeningMouth, anyMouthUlcers, anyMouthGrowth, anyPatch, voiceToneChange, painInChewing, skinDiscoloration, thickenedSkin, nodulesOnSkin, sensationLossPalm, clawingOfFingers, tinglingOrNumbness, inabilityToCloseEyelid, difficultyWalking, difficultyHoldingObjects, cropResidue, garbageLeaves, workingInIndustry`

**Dropdown columns** (value or visible label):

| Column | Values |
|---|---|
| `mobileOwner` | `SELF`, `FAMILY_MEMBER`, `OTHER` |
| `educationStatus` | e.g. `string:701` (Illiterate), `string:707` (Graduation), `string:702` (Primary)… |
| `insuranceScheme` | `true` (Yes) / `false` (No) |
| `smokeOrConsumeGutka` | `NEVER`, `IN_PAST`, `DAILY` |
| `waist` | `FIRST`, or `LT90`/`91TO100`/`GT100` (male), `LT80`/`81TO90`/`GT90` (female) |
| `physicalActivity150Min` | `ATLEAST_150`, `LESS_THAN_150` |

**Text columns:** `address1`, `address2`.

---


## 5b. Task 2 - Examination (NCD Screening)

Select **Task 2**. **No CSV is needed.** The app opens **NCD Screening -> Examine -> Perform Screening** (a new browser
tab) for every patient whose *Examine* button is enabled, and completes the steps the portal is waiting for, saving
each with **Save & Continue**. Steps, in the portal's order: **Personal History -> Hypertension -> Diabetes -> Oral ->
Breast -> Cervical -> COPD** (Breast/Cervical exist for female patients only; the app checks which tabs each patient shows).

**Set-up (once):** type your **Health infrastructure name** (e.g. `Sanwli`) under the login, then open
**Batch readings**, fill the values below, tick *Use these batch readings in Task 2* and Save.

| Batch readings field | Used for |
|---|---|
| Fasting / Post-prandial / Random sugar (defaults 82 / 82 / 82) | Diabetes tab. **Random is mandatory on the portal even when the test is marked No**, so these are always entered |
| "Blood glucose test done?" answer (default **No**) | Passed on exactly as you choose |
| Systolic / Diastolic BP, Heart rate (optional) | Hypertension tab - only done if all three are given |
| Height cm / Weight kg (optional) | Personal History - used **only** if the portal shows N.A for that patient |

Applied automatically (all statuses "No Abnormality Detected"): Personal History radios = No; Oral = no issues,
"Restricted mouth opening" not ticked; Breast = nothing ticked; Cervical = all No; COPD = cough No, severity
"Dyspnoea only with strenuous exercise"; HbA1C left empty. The portal's "Information for Patient" pop-up (shown
after cough = No) is closed automatically before saving.

**Resumable.** The app reads which step the portal is on and only does the unfinished steps from there. Steps the
portal never offers (e.g. Oral already screened earlier) are simply not needed; when the portal returns to the patient
list the examination is complete.

**Nothing is invented.** Values come from the portal (height/weight), your Batch readings window, or an optional
per-patient CSV (which overrides the batch for that patient). If there are no values for a step the app stops there and
says so. The Admin history records every value entered. Use **Dry run** first: it fills everything and saves nothing.

**Optional CSV** (`exam_example.csv`) - one row per patient, columns `ekavach_id` plus any of:
`height, weight`, the nine personal-history Yes/No columns, `systolicBloodPressure, diastolicBloodPressure, heartRate,
hypertensionStatus`, `bloodSugar, diabetesStatus, fastingBloodSugar, postPrandialBloodSugar, hba1c, isRdk`,
`oralStatus, anyIssuesInMouth, restrictedMouthOpening`, `breastStatus` + 7 ticks, `cervicalStatus` + 7 Yes/No,
`cough, copdSeverity`, `healthInfrastructure`. Status values: `Suspected` / `No Abnormality Detected` (Oral, Breast,
Cervical also `Confirmed`).

**Not automated:** the 16 numbered findings checkboxes inside the Oral tab.

---

## 6. History & Admin panel

Every patient processed is recorded in `%APPDATA%\EkavachFiller\history.db` (SQLite):

| Field | Meaning |
|---|---|
| Time | When it was processed |
| Ekavach ID / Patient | From the pending list |
| Status | **Submitted**, **Failed** (submit didn't complete), **Error** (exception), **Skipped** (skipped at review), **Dry run** |
| Score | CBAC score read from the form |
| Portal user | Which portal login was used |
| Details | Error text, if any |
| Answers | Every value entered (dropdown values and Yes/No) |

**Admin** button → PIN required. First use asks you to create a PIN (4+ characters; stored hashed with PBKDF2).
Inside: filter by status, search by ID/name/user, double-click a row to see its answers, **Export CSV**, **Clear history**.

Limits: the PIN deters casual access but doesn't protect against someone who can open the files directly.
A forgotten PIN is reset by deleting `%APPDATA%\EkavachFiller\admin.json`. Run-level settings (which CSV file,
Max patients) are not stored — only per-patient entries.

---

## 7. Installer

`installer\output\EkavachFiller_Setup_<version>.exe` (Inno Setup 6)

* **System check page:** Windows version, 64-bit, free disk (needs 200 MB), Chrome/Edge detection. If no browser is found it offers to open the Chrome download page.
* **Nothing else to install** — Python, Playwright and libraries are bundled.
* **Install location:** default `C:\Program Files\eKavach CBAC Auto-Filler`; you can change it. The Ready and Finish pages show the exact folder, and the app's License/About window shows it again.
* Shortcuts: Start menu (app + "Open install folder"), optional desktop icon.
* Uninstall via Windows *Apps*. A normal uninstall asks whether to delete saved settings; a **silent** uninstall always keeps them.
* Registry: `HKLM\Software\EkavachFiller\InstallPath` (or HKCU for per-user installs).
* Silent install for scripts: `EkavachFiller_Setup_1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES`.
* Not code-signed, so Windows SmartScreen may warn on other PCs.

### Where files live

| What | Location |
|---|---|
| Program | install folder (Program Files) |
| Settings, saved logins, licence, history, admin PIN, dry-run screenshots | `%APPDATA%\EkavachFiller\` |

---

## 8. Licensing

Offline, signed licence keys (Ed25519). Controlled by `ENFORCE_LICENSE` in `licensing.py` (currently **True**).
Without a valid key the app disables Start and refuses to run.

**Issuing a key**
1. Customer sends the **Machine ID** (License / About window).
2. Vendor runs `python vendor_tools\license_manager.py`, enters name, Machine ID, optional expiry (or tick *any PC*), clicks **Generate licence**. The key is copied to the clipboard and logged in `vendor_tools\issued_licenses.json`.
3. Customer pastes it in License / About → **Activate**.

Command-line alternative: `python vendor_tools\keygen.py --name "X" --machine <ID> [--expires 2027-12-31]`.

**What is checked:** signature, Machine ID (unless `*`), expiry date.

**Limits:** no revocation (the app never phones home) — use expiry dates (e.g. 1 year) to control access.
A determined person could patch the program itself; the signature only prevents forging keys.

**Secrets — vendor only, never ship `vendor_tools\`:**
`private_key.pem` (licence signing) and `update_private.pem` (update signing). Back them up; if lost, you cannot issue
new keys/updates for already-distributed copies (their public keys are baked in).

---

## 9. Over-the-air updates

**How it works**
1. You publish two files to any static **HTTPS** host: the new installer and `<channel>.json`.
2. At launch (after 2 s) and on **Check for updates**, the app downloads `<channel>.json`.
3. It verifies the manifest's Ed25519 signature, and only offers versions **newer** than the installed one.
4. On accept it downloads the installer, checks its **SHA-256**, then runs it silently (`/SILENT`), closes, and the installer relaunches the app. Windows will show a UAC prompt if the app was installed for all users.
5. A tampered manifest, wrong hash, or non-HTTPS URL is rejected. (`http://127.0.0.1` is allowed for testing.)

**Update host**
From v1.0.1, `UPDATE_BASE_URL` in `updater.py` points at this repo's GitHub Releases
(`https://github.com/imshailesh593/EKawach_standalone/releases/latest/download`), so clients read
`stable.json` from the **latest** release and download the installer attached to that same release.
A machine can override it in `%APPDATA%\EkavachFiller\config.json` as `"update_base_url"`.
v1.0.0 was built with an empty URL, so v1.0.0 clients must install v1.0.1 by hand once.

**Publishing an update**
1. Edit `APP_VERSION` in `licensing.py` (e.g. `1.0.2`).
2. Build: `powershell -ExecutionPolicy Bypass -File build_installer.ps1`, or push to `main` and download the
   `EkavachFiller-installer` artifact from the **Build Windows installer** GitHub Actions run.
3. Sign:
   `python vendor_tools\publish_update.py --installer installer\output\EkavachFiller_Setup_1.0.2.exe --version 1.0.2 --notes "What changed" [--channel stable|beta] [--mandatory]`
4. Create a GitHub Release (tag `v1.0.2`) and attach **both** files from `vendor_tools\release\`
   (the installer and `stable.json`). Mark it as the latest release.

**Channels:** `"update_channel": "beta"` in a client's `config.json` makes it read `beta.json` instead of `stable.json` — use for testers.
**Mandatory:** `--mandatory` removes the "later" choice; if the download fails, Start is disabled until it succeeds.
**Rollback:** publish a newer version number containing the old code (clients never accept lower versions).

---

## 10. Configuration reference (`%APPDATA%\EkavachFiller\config.json`)

| Key | Default | Meaning |
|---|---|---|
| `username` | "" | Last username (password is in the vault, not here) |
| `max_patients` | 5 | Patients per run (0 = all) |
| `review_before_submit` | false | Pause before each submit |
| `headless` | false | Hide the browser window |
| `browser` | "chrome" | Preferred browser; falls back to Edge |
| `defaults` | see §3 | Default answers (`radio`, `selects`, `issues_none`, `address1/2`) |
| `update_base_url` | "" | Overrides `UPDATE_BASE_URL` |
| `update_channel` | "stable" | Which manifest to read |

---

## 11. Project layout (developer)

```
E-Kawach/
  ekavach_filler.py     Main app: automation engine + GUI (Tkinter)
  licensing.py          Licence verification, Machine ID, APP_VERSION, ENFORCE_LICENSE, data paths
  vault.py              Saved logins (DPAPI-encrypted)
  history.py            SQLite history + admin PIN
  updater.py            OTA update client
  build_installer.ps1   Builds the exe (PyInstaller) then the installer (Inno Setup)
  installer/            installer.iss, eula.txt, readme.txt, output/
  patients_example.csv  CSV template
  requirements.txt      playwright (+ cryptography, pyinstaller installed by the build script)
  vendor_tools/         VENDOR ONLY - never distribute
    license_manager.py  GUI to issue/track licence keys
    keygen.py           CLI licence generator
    publish_update.py   Sign + stage an update release
    private_key.pem     Licence signing key (secret)
    update_private.pem  Update signing key (secret)
```

**Build requirements (developer PC):** Python 3.12, `pip install playwright cryptography pyinstaller`,
Inno Setup 6 (`winget install JRSoftware.InnoSetup`).

**Run from source:** `python ekavach_filler.py` (GUI) ·
`python ekavach_filler.py --cli --dry-run --headless --max 1 --user <name>` (CLI; uses the saved password).

**Portal selectors:** the form fields are addressed by their `name` attributes (e.g. `insuranceScheme`,
`shortnessOfBreath`). If the portal changes its form, update `RADIO_FIELDS` / `SELECT_DEFAULTS` in `ekavach_filler.py`.

---

## 12. Troubleshooting

| Symptom | Fix |
|---|---|
| "Not activated" / Start greyed out | Activate a licence key (section 8) |
| "licence issued for a different computer" | Key was generated for another Machine ID |
| "Could not reach the eKavach login page" | Check internet / portal availability; the app retries 3× |
| Login failed | Check username/password; delete and re-save the login. If the message says the portal is having trouble, wait a few minutes (the app already retries 3x) |
| Task 2 stops at Diabetes | Open **Batch readings**, enter Random sugar, tick *Use these batch readings* and Save (the app logs a note when it is empty) |
| "no height/weight on the portal (N.A)" | Enter Height/Weight in Batch readings (used only for such patients) or use a CSV |
| Patient marked **Failed** | Portal rejected the form (validation); open it manually to see the message |
| Patient marked **Error** | See the Details column in Admin |
| No browser launches | Install Chrome or Edge |
| "Update server not configured" | Set `UPDATE_BASE_URL` / `update_base_url` (section 9) |
| Forgot admin PIN | Delete `%APPDATA%\EkavachFiller\admin.json` |

---

## 13. Security & compliance notes

* Patient data is handled only in the browser session and in the local history (names, IDs, answers). Protect the PC and the history file; export/delete per your data-protection rules.
* The history file is **not encrypted** (only the saved passwords are).
* You must be authorised to use the portal and each account you enter.
* Keep `vendor_tools\` and both `.pem` files off customer machines and out of any shared drive.
