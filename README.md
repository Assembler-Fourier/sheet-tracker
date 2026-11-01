# Sheet Tracker - Weekly Timesheet Tracker for Security Control Rooms

Every week, each site a security company covers sends in a photo of its signed timesheet. Some always
arrive late, and someone in the control room has to work out which ones are missing and who to call.

**Sheet Tracker does that for you.** Open it and you see straight away which timesheets are still
missing this week, which guard has each one, and the best time to ring them, usually just as their
shift ends. One click copies the list so you can send it on.

![Sheet Tracker showing this week's missing timesheets](docs/screenshots/this-week.png)

![Sheet Tracker in dark mode showing last week](docs/screenshots/last-week-dark.png)

*Everything in the screenshots is made up. The people, venues and timesheets are invented demo data.*

## Why it helps

- **No more counting photos by hand.** It looks in the week's folder and ticks off every venue that has
  sent its sheet, even when the photo is named something odd like `k9 (2).png` or `voltmart westgate signed.png`.
- **It tells you who to call.** For every missing sheet it shows the guard who worked that venue last.
- **It tells you when to call.** "On now, until 21:30", "finished - ring him", or "not on until 21:00 (in 1h)".
- **It remembers.** Mark a venue as "asked" and it stays marked. The *Often late* list shows which venues
  keep missing the deadline.
- **Easy on the eyes.** A clean window with light and dark mode, made for a busy control-room desk.
- **Safe.** It only ever *reads* the roster. It never changes it.

## Try it in 1 minute

You need Windows and Python 3.11 or newer. Nothing else needs installing.

```bash
git clone https://github.com/Assembler-Fourier/sheet-tracker.git
cd sheet-tracker
python tool/app.pyw
```

It opens in **demo mode** with a made-up roster and ten weeks of sample timesheets, so you can click
around straight away.

Prefer the command line?

```bash
python tool/timesheets.py             # this week
python tool/timesheets.py last        # last week
python tool/timesheets.py 04/10       # the week containing a date
python tool/timesheets.py --late 12   # venues most often late over 12 weeks
```

## Use it with your own roster

1. Share your roster Google Sheet as *anyone with the link can view*.
2. Tell Sheet Tracker the sheet's id, either with an environment variable:

   ```bash
   setx ROSTER_SHEET_ID "your-google-sheet-id"
   ```

   or with a small file, `tool/config.json` (git ignores it):

   ```json
   { "roster_id": "your-google-sheet-id", "desktop": "C:/Users/you/Desktop" }
   ```

3. Save each week's photos in a Desktop folder named for the Sunday, for example `Timesheets 01.11.26`.
4. Double-click `Sheet Tracker.bat`, or put a shortcut to it on your Desktop.

## Who it is for

Security companies, guarding and door-staff firms, facilities teams, cleaning contractors, event staffing
agencies: anyone who rosters staff across many sites and has to collect a timesheet from each one every week.

**Keywords:** timesheet tracker, missing timesheet checker, staff roster tool, security guard rostering,
control room software, door staff timesheets, shift roster Google Sheets, weekly timesheet collection,
workforce management, Python desktop app, tkinter GUI, Windows tool.

---

## Technical details

**Stack:** Python 3 (standard library only), tkinter GUI, PowerShell + `Windows.Media.Ocr` for OCR, no
third-party dependencies and no install step.

**Roster ingestion.** The roster is a wide Google Sheet pulled as a read-only `.xlsx` export over HTTPS.
`xl.py` is a ~100-line OOXML reader (zip + `xml.etree`) that resolves shared strings, cell styles,
fills and strike-through without openpyxl. `timesheets.py` parses each week block (a venue label column
plus seven day columns of alternating shift-time and name rows) into venues, shifts and people. It
tolerates notes in the label column, labels typed into day columns, duplicated or missing date headers,
merged weeks and per-venue closed days. Fill colours carry state: green confirmed, yellow provisional,
struck-through cancelled.

**Fuzzy file-to-venue matching.** File stems are canonicalised (NFKD accent folding, apostrophe and
punctuation stripping, noise-word removal, trailing page numbers dropped), then matched against per-venue
alias sets with whole-word and `difflib` similarity rules. Short aliases must match whole words, so camera
numbers like `IMG_3125` never false-match. Manual assignments persist in `names.json`.

**Shift-end inference and closing times.** Shift strings (`20:00-close`, `21:00-03-00`, `18.00-close`) are
parsed with regex into start/end minutes, including overnight spans. For open-ended "close" shifts,
`ocrscan.ps1` batch-OCRs the archive of timesheet photos with the built-in Windows OCR engine (about 5 sheets
a second, positional word output to JSONL), and `ocrclose.py` derives each venue's closing time by
column-position filtering (`RIGHT = 0.82`) and majority voting across hundreds of noisy readings, with a
`ROSTER_SHARE` threshold deciding when the roster's own end times outweigh the OCR evidence.

**Contact selection.** Who to ask is ranked from the venue's last rostered shift, explicit contacts and a
12-week "regulars" window. A live countdown re-times every row (*not yet → on now → finished*) without
re-reading the roster.

**Deterministic demo mode.** With no sheet id configured, `demo/make_demo.py` rebases an anonymised roster
template's date serials by whole weeks to the current week and synthesises PNG placeholder timesheets
(pure-stdlib zlib/PNG encoder) with seeded randomness and realistic modification times. The demo is
reproducible across dates, which lets the test suite pin exact expectations.

**Testing.** Five standard-library suites:

| Suite | What it covers |
|---|---|
| `selftest.py --window` | week arithmetic, folder-name parsing, filename matching, pinned demo weeks, headless GUI run |
| `faketest.py` | edge cases on a synthetic roster generated by `fakeroster.py` |
| `flowtest.py` | drives every GUI control off-screen with `report_callback_exception` hooked, since tkinter swallows callback errors, and flags any step slower than 2 s |
| `sweep.py 2026` | every week of a year through the full check |
| `audit.py` | property/invariant checks on every week (in + missing = rostered, each file counted once, monotonic clock-winding in 20-minute steps) |

**Project layout**

```
Sheet Tracker.bat      launcher (no console window)
tool/
  app.pyw              tkinter GUI
  timesheets.py        roster parsing, venue matching, scheduling logic, CLI
  xl.py                minimal read-only xlsx reader
  ocrscan.ps1          Windows OCR over the photo archive
  ocrclose.py          OCR words -> per-venue closing times
  makeicon.py          multi-resolution .ico generator, pure stdlib
  selftest.py faketest.py flowtest.py sweep.py audit.py fakeroster.py closing.py
demo/
  roster-template.xlsx anonymised roster in the real layout
  make_demo.py         date-rebased demo roster + synthetic timesheet photos
docs/screenshots/
```

Sister project: [check-call-log](https://github.com/Assembler-Fourier/check-call-log), which reads the same roster.

## Licence

MIT. See [LICENSE](LICENSE).
