"""NORTHWIND Security - weekly timesheet check.

    python timesheets.py                  the week being collected now (Sat/Sun: this week, else last week)
    python timesheets.py last             the week that has just finished
    python timesheets.py this             the week ending this coming Sunday
    python timesheets.py next             the week after
    python timesheets.py 04/10            the week ending that Sunday (any day in the week will do)

Reads the roster (read-only, same sheet as the check call log), lists every venue that has
somebody rostered between the Monday and the Sunday of that week, finds the week's timesheet
folder (`Timesheets DD.MM.YY`, named for the Sunday) and says which venues have come in and
which are still missing, with the days and the guards' names so they can be chased.

The roster is only ever downloaded. Nothing here writes to it, and no other program is started.
app.pyw is the window on top of this.
"""
import argparse
import collections
import datetime
import difflib
import json
import os
import re
import shutil
import sys
import unicodedata
import urllib.request
import zipfile

from xl import Book, idx_to_col

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _config():
    """tool/config.json (optional, never committed): {"roster_id": "...", "desktop": "..."}."""
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


_CFG = _config()

# ---- settings ---------------------------------------------------------------
# The roster is a Google Sheet shared by link (view only). Its id comes from the ROSTER_SHEET_ID environment
# variable or tool/config.json. With no id the tool runs in DEMO mode on the made-up roster in demo/.
ROSTER_ID = os.environ.get("ROSTER_SHEET_ID") or _CFG.get("roster_id", "")
DEMO = not ROSTER_ID
ROSTER_EXPORT = "https://docs.google.com/spreadsheets/d/%s/export?format=xlsx" % ROSTER_ID
# Where the week's folder is looked for, in this order. The first is where it lives while it is
# being collected; the second is where finished weeks are filed (its year subfolders are searched too).
DESKTOP = (os.environ.get("SHEET_TRACKER_DESKTOP") or _CFG.get("desktop")
           or (os.path.join(ROOT, "demo", "Desktop") if DEMO else os.path.join(os.path.expanduser("~"), "Desktop")))
ARCHIVE = os.path.join(DESKTOP, "Important DATA", "Timesheets")
SHEET_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".tif", ".tiff", ".pdf"}
# -----------------------------------------------------------------------------

CACHE = os.path.join(HERE, "cache")
ROSTER_PATH = os.path.join(CACHE, "roster.xlsx")
NAMES = os.path.join(HERE, "names.json")        # file names taught by hand: canonical name -> venue label
CHASED = os.path.join(HERE, "chased.json")      # venues already asked for, per week: iso Sunday -> {venue: when}
CONTACTS = os.path.join(HERE, "contacts.json")  # who sends each venue's sheet: venue -> [names, best first]
REGULAR_WEEKS = 12                              # how far back "who is a regular here" looks
CONFIRMED = "FF92D050"                          # the roster's green: this shift is covered
#: A shift written "20:00-close" has no end on the roster. If the venue's closing time is not known
#: either, a door shift is taken to run this long - never the 24 hours that once had K9 "on now" at
#: half two on a Sunday afternoon, sixteen hours after the man went home.
DOOR_HOURS = 8
LONGEST_SHIFT = 14 * 60
EPOCH = datetime.date(1899, 12, 30)
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
# "20:00-close", "18.00-close", "21:00-03-00", "22:00hrs-close", "14:00- ??"
TIME_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*(?:hrs?)?\s*-|^\s*(\d{1,2})-(\d{2})\s*-")
# the end of a shift when it is written out: "21:00-03-00", "17:00-22:00", "18:00-01:30"
END_RE = re.compile(r"^\s*\d{1,2}\s*[:.\-]\s*\d{2}\s*(?:hrs?)?\s*-\s*(\d{1,2})\s*[:.\-]\s*(\d{2})")
SPACED_DASH = re.compile(r"\s*-\s*")
FOLDER_RE = re.compile(r"^\s*time\s*sheets?\s*(?:w\.?\s*e\.?)?\s*[-–]?\s*"
                       r"(\d{1,2})\s*[.\-_/ ]\s*(\d{1,2})\s*[.\-_/ ]\s*(\d{2,4})\s*$", re.I)
# words in a file name that say nothing about which venue it is
NOISE = {"timesheet", "timesheets", "time", "sheet", "sheets", "ts", "copy", "img", "image", "images",
         "scan", "scanned", "photo", "pic", "picture", "part", "pt", "p", "page", "pages", "of", "and",
         "new", "signed", "final", "week", "wk", "we", "whatsapp", "doc", "bar", "pub", "security", "sec"}


class Problem(Exception):
    """Something the user needs to know about; shown without a traceback."""


# ---- the week ---------------------------------------------------------------

def sunday_of(date):
    """The Sunday that ends the Mon-Sun week containing this date."""
    return date + datetime.timedelta(days=6 - date.weekday())


def week_dates(sunday):
    monday = sunday - datetime.timedelta(days=6)
    return [monday + datetime.timedelta(days=i) for i in range(7)]


def collected(sunday, places=None):
    """Has anything been collected for that week yet? (A folder with no sheets in it has not.)"""
    folders = known_folders(places)
    for d in week_dates(sunday):
        if d in folders and sheets_in(folders[d]):
            return True
    return False


def default_week(today):
    """The week to work on with nothing asked for.

    **On a Monday that is last week**: the week has just ended and Monday is when its stragglers get
    chased, so that is the one to open on. Every other day it is the week being collected now. The other
    week is never far away - the window keeps its outstanding count on the switcher.
    """
    this = sunday_of(today)
    return this - datetime.timedelta(days=7) if today.weekday() == 0 else this


def make_week_folder(sunday, where=None):
    """Make the week's folder on the Desktop if it is not there yet. Returns (path, made it just now).

    Done every time the tool is opened, so Saturday's sheets always have somewhere to go. If the folder
    already exists - on the Desktop or filed away - nothing happens at all.
    """
    path = os.path.join(where or DESKTOP, folder_name(sunday))
    if os.path.isdir(path):
        return path, False
    there, _ = find_folder(sunday)                     # already made, or already filed away
    if there:
        return there, False
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return None, False
    return path, True


def pick_week(token, today):
    """'last' / 'this' / 'next' / a date / a weekday -> the Sunday of that week."""
    t = (token or "last").strip().lower()
    if t in ("", "auto", "now"):
        t = "last"
    if t in ("this", "current", "thisweek"):
        return sunday_of(today)
    if t in ("last", "previous", "prev", "lastweek"):
        return sunday_of(today) - datetime.timedelta(days=7)
    if t in ("next", "nextweek"):
        return sunday_of(today) + datetime.timedelta(days=7)
    if t in ("today", "yesterday"):
        return sunday_of(today - datetime.timedelta(days=1 if t == "yesterday" else 0))
    low = [w.lower() for w in WEEKDAYS]
    if t.isalpha() and t[:3] in low:
        want = low.index(t[:3])
        return sunday_of(today - datetime.timedelta(days=(today.weekday() - want) % 7))
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", t)
    if m:
        y, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.match(r"^(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2}|\d{4}))?$", t)
        if not m:
            raise Problem("can't read the week %r - use last, this, next, or a date like 04/10" % token)
        dd, mo = int(m.group(1)), int(m.group(2))
        y = today.year if not m.group(3) else int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
    try:
        return sunday_of(datetime.date(y, mo, dd))
    except ValueError:
        raise Problem("%r is not a real date" % token)


def week_text(sunday):
    monday = sunday - datetime.timedelta(days=6)
    if monday.month == sunday.month:
        return "%s - %s" % (monday.strftime("%a %d"), sunday.strftime("%a %d %b %Y"))
    return "%s - %s" % (monday.strftime("%a %d %b"), sunday.strftime("%a %d %b %Y"))


def folder_name(sunday):
    return "Timesheets %s" % sunday.strftime("%d.%m.%y")


# ---- the roster -------------------------------------------------------------

def download_roster(dest=ROSTER_PATH):
    """Fetch a read-only .xlsx export of the roster. Falls back to the last copy."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if DEMO:
        sys.path.insert(0, os.path.join(ROOT, "demo"))
        import make_demo
        make_demo.build(dest, DESKTOP)
        return "DEMO roster (made-up people and venues) - set ROSTER_SHEET_ID to use a real one"
    part = dest + ".part"
    try:
        req = urllib.request.Request(ROSTER_EXPORT, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=90) as r, open(part, "wb") as f:
            shutil.copyfileobj(r, f)
        if not zipfile.is_zipfile(part):
            raise ValueError("the link did not return a spreadsheet (is it still shared by link?)")
        os.replace(part, dest)
        return "downloaded just now"
    except Exception as e:
        if os.path.exists(part):
            os.remove(part)
        if not os.path.exists(dest):
            raise Problem("could not download the roster and there is no saved copy: %s" % e)
        age = datetime.datetime.fromtimestamp(os.path.getmtime(dest))
        return "DOWNLOAD FAILED (%s) - using the copy saved %s" % (e, age.strftime("%a %d %b %H:%M"))


def looks_like_name(text):
    """Roster names always carry a capital letter; notes typed into the grid usually do not."""
    return any(ch.isupper() for ch in text)


def days_text(days):
    """Weekday numbers as something short to read: 'Mon-Sun', 'Thu-Sat', 'Tue Fri-Sat'."""
    runs = []
    for i in sorted(days):
        if runs and i == runs[-1][-1] + 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    return " ".join(WEEKDAYS[r[0]] if len(r) == 1 else "%s-%s" % (WEEKDAYS[r[0]], WEEKDAYS[r[-1]]) for r in runs)


def _dark(color):
    """A site label is filled black; names are green and time cells white."""
    if not color:
        return False
    if color.startswith("theme"):
        return color == "theme1"
    try:
        rgb = int(color[-6:], 16)
    except ValueError:
        return False
    return max(rgb >> 16, (rgb >> 8) & 255, rgb & 255) < 0x40


class Roster:
    """The live roster, read only. One sheet, weeks side by side, eight columns to a week:
    a site-label column then Mon..Sun. Row 1 is the weekday names and row 2 the dates, and that
    header pair repeats down the sheet. Under a site label, a time cell is followed by the names
    that share it, one row each, until the next time cell or the next site."""

    def __init__(self, path=ROSTER_PATH):
        self.book = Book(path)
        self.cells = self.book.cells(self.book.sheets[0])
        self.max_row = max(r for r, _ in self.cells)
        self._date_cols = collections.defaultdict(list)
        for (r, c), v in self.cells.items():
            if r == 2 and v[2] not in ("s", "str", "inlineStr"):
                try:
                    self._date_cols[float(v[0])].append(c)
                except ValueError:
                    pass

    def text(self, r, c):
        v = self.cells.get((r, c))
        return "" if v is None else v[0].strip()

    def style(self, r, c):
        v = self.cells.get((r, c))
        return self.book.style(v[1] if v else None)

    def is_text(self, r, c):
        v = self.cells.get((r, c))
        return v is not None and v[2] in ("s", "str", "inlineStr")

    def day_column(self, date):
        cols = self._date_cols.get(float((date - EPOCH).days), [])
        cols = [c for c in cols if self.text(1, c) == WEEKDAYS[date.weekday()]] or cols
        if not cols:
            raise Problem("%s is not on the roster (no such date in the header row)" % date.strftime("%a %d %b %Y"))
        if len(cols) > 1:
            raise Problem("%s appears %d times in the roster header (%s) - can't tell which column is right"
                          % (date.strftime("%d %b %Y"), len(cols), ", ".join(idx_to_col(c) for c in cols)))
        return cols[0]

    def week(self, sunday):
        """Every venue with somebody rostered in that Mon-Sun week, in roster order.

        Returns (venues, notes). A venue is {'label', 'row', 'days' {weekday: [people]}, 'people', 'shifts',
        'struck', 'live'}; a person is {'name', 'shift', 'day', 'ref', 'strike'}. Each day column keeps its
        own current time cell, because one row of times serves all seven days.
        """
        days = week_dates(sunday)
        cols, notes, missing = {}, [], []              # weekday index -> column, for the days this roster has
        for i, d in enumerate(days):
            try:
                cols[i] = self.day_column(d)
            except Problem as e:
                missing.append((i, d, str(e)))
        if not cols:
            raise Problem("the week %s is not on the roster" % week_text(sunday))
        # the week's own label column sits left of its Monday, which is the first day's column less its offset
        first = min(cols)
        monday_col = cols[first] - first
        label_col = monday_col - 1
        if label_col < 1:
            raise Problem("the week %s sits at the very left edge of the roster, with no venue-label column "
                          "beside it - check that week by hand" % week_text(sunday))
        for i, c in sorted(cols.items()):
            if c != monday_col + i:
                notes.append("%s is in column %s, not beside the rest of the week (%s) - read from its own column"
                             % (days[i].strftime("%a %d %b"), idx_to_col(c), idx_to_col(monday_col + i)))
        for i, d, why in missing:                      # a day the header row has lost: fall back to its place in the block
            where = monday_col + i
            if self.text(1, where) == WEEKDAYS[i]:
                cols[i] = where
                notes.append("%s is not in the header row (%s) - read from column %s, which is where the week puts it"
                             % (d.strftime("%a %d %b"), why, idx_to_col(where)))
            else:
                notes.append("%s left out: %s" % (d.strftime("%a %d %b"), why))

        found = collections.OrderedDict()             # label -> venue
        site = None
        when = {}                                     # column -> the time cell in force
        for r in range(3, self.max_row + 1):
            # A venue label is filled black. Anything else typed into the venue column is a note - the
            # roster has a white "IMPORTANT NOTE" cell directly under "Perch Kilcarran", and reading that
            # as a venue took Perch off the list and gave all its people to the note.
            label = ""
            head = self.text(r, label_col)
            if head and head not in WEEKDAYS and self.is_text(r, label_col):
                if _dark(self.style(r, label_col)["fill"]):
                    label = head
                else:
                    notes.append("%s%d: %r sits in the venue column but is not marked as a venue - taken as "
                                 "a note, and whatever is under it stays with %s"
                                 % (idx_to_col(label_col), r, head, site or "the venue above"))
            if not label:
                for c in sorted(cols.values()):       # a label is sometimes typed into a day column
                    v = self.text(r, c)
                    if v and v not in WEEKDAYS and self.is_text(r, c) and _dark(self.style(r, c)["fill"]):
                        label = v
                        break
            if label and label not in WEEKDAYS:
                site, when = label, {}
                found.setdefault(label, {"label": label, "row": r, "days": {}, "people": [],
                                         "shifts": [], "struck": 0, "open": set(), "covered": set()})
            for i, c in sorted(cols.items()):
                v = self.text(r, c)
                if not v or not self.is_text(r, c) or v in WEEKDAYS or v == label:
                    continue
                m = TIME_RE.match(v)
                if m:                       # the time cell these names sit under: when it starts, and ends
                    hh, mm = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
                    fin = END_RE.match(v)
                    when[c] = (tidy_shift(v), int(hh) * 60 + int(mm),
                               int(fin.group(1)) * 60 + int(fin.group(2)) if fin else None)
                    # A time on a day means the venue is open that day, whether or not anybody is
                    # confirmed for it yet. This is what tells us Lucky Bingo still runs on the Sunday
                    # when only Saturday has a green name under it.
                    if site:
                        found[site]["open"].add(i)
                    continue
                if v.lower().startswith("break"):
                    continue
                ref = "%s%d" % (idx_to_col(c), r)
                if not looks_like_name(v):            # "reminder", "cancelled" and the like
                    if site:
                        notes.append("%s: %r under %s is not a name - left out; check that part of the roster by hand"
                                     % (ref, v, site))
                    continue
                if any(ch.isdigit() for ch in v):
                    notes.append("%s: can't read %r as a time or a name - skipped, check it by hand" % (ref, v))
                    continue
                if site is None:
                    notes.append("%s: %r has no venue above it - skipped, check it by hand" % (ref, v))
                    continue
                st = self.style(r, c)
                shift, start, finish = when.get(c, ("", -1, None))
                # **The fill on a name cell cannot be trusted.** Green is `CONFIRMED`, but the export
                # does not reproduce it reliably on the last column of a week: Lucerne' Sunday man is
                # green in the sheet and comes out `FFFFFFFF`, Lucky Bingo's came out with no fill at
                # all. Reading "not green" as "not covered" dropped Carl Fielding, who was plainly there.
                # So a name is a name. The only coverage fact the export really carries is whether
                # there is a name on the day at all.
                who = {"name": v, "shift": shift, "start": start, "end": finish, "day": i, "ref": ref,
                       "strike": st["strike"], "fill": st["fill"], "confirmed": st["fill"] == CONFIRMED}
                venue = found[site]
                venue["days"].setdefault(i, []).append(who)
                venue["people"].append(who)
                venue["open"].add(i)
                if not st["strike"]:
                    venue["covered"].add(i)
                venue["struck"] += bool(st["strike"])
                if shift and shift not in venue["shifts"]:
                    venue["shifts"].append(shift)
        venues = [v for v in found.values() if v["people"]]
        idle = [v for v in found.values() if not v["people"]]   # on the roster, nobody on it this week
        if not venues:
            raise Problem("nobody is rostered at any venue in the week %s - the roster is probably not filled in "
                          "that far yet" % week_text(sunday))
        for v in venues:
            v["live"] = v["struck"] < len(v["people"])        # at least one name not struck through
            v["day_text"] = days_text(v["days"])
            v["names"] = sorted({p["name"] for p in v["people"]})
            # The last day is the last day the venue is **open**, not the last day somebody green is on
            # it. The roster marks an uncovered shift yellow, and that yellow does not survive the
            # export - but the time cell does, so a Sunday with a time and no confirmed name still
            # counts as a Sunday. Getting this wrong put Lucky Bingo and a dozen others on the Saturday
            # list when they were still running on the Sunday.
            v["open"] = sorted(v["open"]) or sorted(v["days"])
            v["covered"] = sorted(v["covered"])
            v["uncovered"] = [i for i in v["open"] if i not in v["covered"]]
            last = v["open"][-1] if v["open"] else max(v["days"])
            v["last_day"] = last
            v["last_covered"] = v["covered"][-1] if v["covered"] else None
            v["holders"] = sorted(v["days"].get(last, []), key=lambda p: -p["start"])
        if idle:
            notes.append("on the roster with nobody rostered this week, so no timesheet expected: "
                         + ", ".join(v["label"] for v in idle))
        return venues, idle, notes


# ---- venue names ------------------------------------------------------------

def canon(text):
    """A file or venue name boiled down to what is worth comparing.

    Lower case, accents and apostrophes gone, punctuation to spaces, words that only say
    "this is a timesheet" dropped, and a trailing page number ("K9 Part 2", "Perch (1)") dropped.
    """
    t = unicodedata.normalize("NFKD", text)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[‘’ʼ'`´]", "", t.lower())
    t = re.sub(r"[^a-z0-9]+", " ", t)
    words = [w for w in t.split() if w not in NOISE]
    while len(words) > 1 and words[-1].isdigit():
        words.pop()
    return " ".join(words)


# Extra spellings seen on the real file names, by the venue label on the roster. The label itself
# (and the label without a leading "the", and each side of a "/") is always matched as well.
ALIASES = {
    "WESTGATE": ["westgate", "voltmart westgate", "westgate"],
    "HILLCREST": ["voltmart hillcrest", "hillcres"],
    "ASHGROVE": ["voltmart ashgrove"],
    "BROOKVALE": ["voltmart brookvale"],
    "OAKRIDGE": ["voltmart oakridge"],
    "KILMORAN": ["voltmart kilmoran"],
    "BRIDGEPORT": ["voltmart bridgeport"],
    "SEAVIEW": ["voltmart seaview"],
    "STONEBRIDGE": ["voltmart stonebridge", "stonebridg"],
    "MEADOWBANK": ["voltmart meadowbank"],
    "ELMHURST": ["voltmart elmhurst", "elmhurs"],
    "QuickStop Elmfield": ["quickstop", "elmfield"],
    "Kilcarran": ["kilcarran business campus", "business campus", "campus", "kbc"],
    "Portlane": ["portlane dock view", "dock view"],
    "Brennans Mill st": ["brennans", "dabrowski", "brennans mill street", "mill st", "mill street"],
    "Elysium Ferncourt": ["elysium", "ferncourt"],
    "Orchard House": ["orchard", "orchards", "orchard hse"],
    "Hanlons": ["fenwick"],
    "O'Garvey": ["ogarvey", "ogarveys", "ogarvy", "ogarvys", "garvy", "ogarvey st", "ogarvey street"],
    "Ashbury": ["ashbury hotel"],
    "12 Harbour st": ["12 harbour street", "harbour st", "harbour street", "harbour", "12 harbour", "12"],
    "Glenmore": ["glenmore avenue"],
    "The Meadows": ["meadows", "paddock"],
    "Town Ballyrock": ["town", "ballyrock", "town bar ballyrock"],
    "Loft": ["the loft", "loft dublin"],
    "Lucerne": ["luce", "lucern"],
    "Lido": ["the lido"],
    "The Old Haunt": ["old haunt", "oldhaunt"],
    "Keystone": ["the keystone"],
    "Fogartys": ["fogarty", "fogartys pub"],
    "The Jug": ["jug"],
    "Costellos": ["costello", "costellos pub"],
    "Lucky Bingo": ["bingo", "luckybingo"],
    "K9 / Red Door": ["k9", "red door", "reddoor", "k9 red door", "k9 reddoor", "knine", "k nine"],
    "The Wharf": ["wharf", "wharf"],
    "Perch Kilcarran": ["perch", "the perch"],
    "Bullseye Club Darts / Pats": ["bullseye club", "bullseyeclub", "bullseye club darts", "pats", "pats bar", "darts"],
    "Nona's": ["nonas", "nona"],
    "Quinlans": ["quinlan", "quinlans pub"],
    # venues that come and go; the spellings below all turned up in folders during 2026
    "Column bar (Delacroix)": ["column bar", "column", "delacroix", "delacroix", "delacrox", "delacrix",
                                "delacrox column bar"],
    "Fox Inn": ["foxmoor inn", "foxmoor", "fox"],
    "Foxmoor Inn": ["fox inn", "foxmoor"],
    "Hugo Fairbrook Hotel": ["hugo fairbrook", "hugo fair", "hugo"],
    "Millbrook Lane Night": ["millbrook lane nights", "millbrook night", "millbrook lane n"],
    "Riverside Park": ["riverside"],
    "Merchants Green": ["merchants grn", "st merchants green"],
}


def aliases_for(label):
    """Everything a file might be called for this venue, canonical form, longest first."""
    out = {canon(label)}
    for part in label.split("/"):                     # "K9 / Red Door", "Bullseye Club Darts / Pats"
        out.add(canon(part))
    both = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", label)   # "Column bar (Delacroix)" - either name is used
    if both:
        out.add(canon(both.group(1)))
        out.add(canon(both.group(2)))
    bare = re.sub(r"^the\s+", "", canon(label))
    out.add(bare)
    for extra in ALIASES.get(label, []):
        out.add(canon(extra))
    return sorted((a for a in out if a), key=len, reverse=True)


def load_names():
    """File names taught by hand: canonical file name -> venue label."""
    try:
        with open(NAMES, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if isinstance(v, str)}
    except (OSError, ValueError):
        return {}


def save_name(name, label):
    """Remember that a file called this belongs to that venue; label None forgets it."""
    taught = load_names()
    key = canon(name)
    if label:
        taught[key] = label
    else:
        taught.pop(key, None)
    if taught:
        with open(NAMES, "w", encoding="utf-8") as f:
            json.dump(taught, f, indent=1, ensure_ascii=False, sort_keys=True)
    elif os.path.exists(NAMES):
        os.remove(NAMES)


#: The day a sheet can be collected is the last day anyone works there. Saturday comes first because it is
#: the deadline: those venues are shut on Sunday, so a sheet not caught on the Saturday night waits another
#: week, while a Sunday venue can still be got the next night. Groups are (key, heading, weekday index).
COLLECT = (("sat", "Get on Saturday", 5), ("sun", "Get on Sunday", 6), ("past", "Finished earlier", None))


def to_collect(report):
    """The missing venues grouped by the night they can be got: Sunday, Saturday, or finished before that.

    Returns [(key, heading, [venues])] in the order of COLLECT, groups with nobody in them left out.
    """
    groups = {k: [] for k, _, _ in COLLECT}
    for v in report["missing"]:
        last = v.get("last_day")
        groups["sun" if last == 6 else "sat" if last == 5 else "past"].append(v)
    return [(k, head, groups[k]) for k, head, _ in COLLECT if groups[k]]


def load_contacts():
    """Who sends each venue's sheet, as taught by hand: {venue: [names, best first]}."""
    try:
        with open(CONTACTS, encoding="utf-8-sig") as f:
            data = json.load(f)
        return {k: [n for n in v if isinstance(n, str)] for k, v in data.items() if isinstance(v, list)}
    except (OSError, ValueError, AttributeError):
        return {}


def save_contact(venue, name, on=True):
    """Remember that this person sends this venue's sheet (first in the list), or that they do not."""
    data = load_contacts()
    names = [n for n in data.get(venue, []) if n != name]
    if on:
        names.insert(0, name)
    data[venue] = names
    if not names:
        data.pop(venue, None)
    if data:
        with open(CONTACTS, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False, sort_keys=True)
    elif os.path.exists(CONTACTS):
        os.remove(CONTACTS)


def regulars(roster, today, weeks=REGULAR_WEEKS):
    """Who is a regular at each venue, worked out from the roster: {venue: [(name, shifts, weeks)]}.

    A head doorman is not something the roster says outright, so this is only ever a guess - it is the
    person who turns up there most. It is kept on the Roster object, because it costs a dozen week reads.
    """
    if getattr(roster, "_regulars", None) is not None:
        return roster._regulars
    shifts = collections.defaultdict(collections.Counter)
    seen = collections.defaultdict(lambda: collections.defaultdict(set))
    sunday = sunday_of(today)
    for _ in range(weeks):
        try:
            venues, _, _ = roster.week(sunday)
        except Problem:
            venues = []
        for v in venues:
            for p in v["people"]:
                shifts[v["label"]][p["name"]] += 1
                seen[v["label"]][p["name"]].add(sunday)
        sunday -= datetime.timedelta(days=7)
    out = {}
    for label, counter in shifts.items():
        out[label] = [(n, c, len(seen[label][n]))
                      for n, c in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]
    roster._regulars = out
    return out


def who_has_it(venue, contacts, regular):
    """Who to ask for this venue's sheet, best first, each with the reason.

    The sheet is held by the venue's main man, and the roster does not say who that is - "most shifts"
    gets Perch and K9 right but Hanlons and the Wharf wrong, so a name taught by hand always wins. What
    the roster can do is pick the stand-in when the usual one is off, which is the K9 case: Oscar is
    the sender, and when he is not on it is Dale Merrick, the next most regular there.

    Returns (candidates, away): candidates are rostered this week, away are taught senders who are not.
    """
    here = {}
    # The shift that matters is a person's **last** one of the week, not their first: that is the night
    # they are holding the sheet, and the night it is any use ringing the place for it.
    for p in venue["people"]:
        was = here.get(p["name"])
        if was is None or (p["day"], p["start"]) > (was["day"], was["start"]):
            here[p["name"]] = p
    taught = contacts.get(venue["label"], [])
    rank, away = [], []
    for i, name in enumerate(taught):
        if name in here:
            rank.append((0, i, name, "sends this one"))
        else:
            away.append(name)
    # Nobody to guess between: one man on the last day is the man who has it. That covers the Voltmart
    # stores, where one guard works the whole shift, and any night a big door happens to run on one.
    last = venue["days"].get(venue.get("last_day"), [])
    if len(last) == 1 and last[0]["name"] in here and not any(r[2] == last[0]["name"] for r in rank):
        rank.append((0, 99, last[0]["name"], "the only one on the last day - it has to be him"))
    # More than one on the last night: the head doorman is the one with the sheet, and the user's rule
    # for spotting him is that he **starts earliest** - "he is main as he starts early, doesnt mean he
    # is finishing early". So earliest start first, ahead of anyone whose only claim is working here a
    # lot. (A taught name still beats all of this.)
    # Each rule gets its **own** tier. They used to share one, and the second element of the key was
    # minutes for one rule and a list position for another, so a 23:00 start sorted behind index 2 and
    # K9 asked a man with three shifts instead of the one who opened the door.
    # The key here is the **position** in that sorted order, not the start time itself: the final
    # rank.sort() would otherwise re-sort on the raw minutes and undo this, and a man with no time at all
    # (start -1) would sort ahead of one who starts at 16:00. A blank on the roster is not evidence of an
    # early start - it is no evidence at all, so he goes last and anyone with a real time is asked first.
    for i, p in enumerate(sorted(last, key=lambda p: (p["start"] if p["start"] >= 0 else 9999))):
        if p["name"] in here and not any(r[2] == p["name"] for r in rank):
            rank.append((1, i, p["name"], "first on the last night, %s"
                         % (p["shift"] or "no time given")))
    counts = {n: (c, w) for n, c, w in regular.get(venue["label"], [])}
    for i, (name, c, w) in enumerate(regular.get(venue["label"], [])):
        if name in here and not any(r[2] == name for r in rank):
            rank.append((2, i, name, "most regular here - %d shifts over %d of the last %d weeks"
                         % (c, w, REGULAR_WEEKS)))
    for name in here:                                 # everyone else who was on, so the list is complete
        if not any(r[2] == name for r in rank):
            rank.append((3, counts.get(name, (0, 0))[0] * -1, name, "on this week"))
    rank.sort()
    out = [dict(here[name], why=why, taught=(tier == 0)) for tier, _, name, why in rank]
    return out, away


def tidy_shift(text):
    """The roster's own spelling of a shift, tidied enough to read: '15:00-  close' -> '15:00-close'.

    Only whitespace is touched - the times themselves are left exactly as the office typed them, because
    the tool quotes this string back at the user and should not be inventing a shift he never wrote.
    """
    return SPACED_DASH.sub("-", " ".join(text.split()))


def hhmm(mins):
    """A time of day, zero-padded, the way the roster itself writes one: 09:00, 21:30, 00:00.

    It used to drop the leading zero, so a list read "9:00" beside "11:00" and "1:30" beside "21:30",
    and midnight came out "0:00", which is the one nobody reads at a glance.
    """
    return "%02d:%02d" % (mins // 60, mins % 60)


def how_long(wait):
    """How long until he is on, in the words a person would use.

    It used to read "in 0h07m". The user's reaction was "what is 0 hours anyways" - and he was right:
    nobody says nought hours. Under an hour it is minutes, over an hour the minutes are dropped when
    there are none, and a whole day away is named by its day rather than counted in hours.
    """
    mins = int(wait.total_seconds() // 60)
    if mins < 1:
        return "any minute now"
    if mins == 1:
        return "in a minute"
    if mins < 60:
        return "in %d min" % mins
    hours, left = divmod(mins, 60)
    return "in %dh" % hours if not left else "in %dh %dm" % (hours, left)


CLOSING = os.path.join(HERE, "ocr", "closing.json")   # worked out by ocrclose.py; optional


def load_closing():
    """When each venue is reckoned to shut: {venue: (minutes, 'the roster'|'the sheets', how sure)}.

    Written by ocrclose.py from the roster's own end times where it has them, and otherwise from the
    handwritten "Time out" column read off hundreds of sheets. Missing file means no estimates, which is
    fine - everything still works, a shift just says "close" instead of a time.
    """
    try:
        with open(CLOSING, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for label, got in data.items():
        try:
            out[label] = (int(got["close_min"]), got.get("from", "?"), float(got.get("sure", 0)))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def when_to_ask(person, monday, now=None, closes=None):
    """When it is any use ringing this venue for the sheet - you cannot ask Brennans at three in the
    afternoon when the man is not on until five.

    Returns {'day', 'from', 'to', 'state', 'text'}; state is 'on' (he is there now), 'later' (not yet),
    'gone' (that shift has finished) or 'unknown' (no time on the roster).
    """
    now = now or datetime.datetime.now()
    if not person or person.get("start", -1) < 0:
        return {"state": "unknown", "text": ""}
    day = monday + datetime.timedelta(days=person["day"])
    midnight = datetime.datetime.combine(day, datetime.time())
    start = midnight + datetime.timedelta(minutes=person["start"])

    # Work out when the shift ends. The roster first; then the venue's reckoned closing time; and if
    # neither is known, a door shift of DOOR_HOURS. There is always an end - a shift that runs until
    # "close" still ends, and pretending otherwise is what made a Thursday-to-Saturday club look open
    # on Sunday afternoon.
    finish, how = person.get("end"), "roster"
    if finish is None and closes:
        finish, how = closes[0], "guess"
    if finish is None:
        end, how = start + datetime.timedelta(hours=DOOR_HOURS), "assumed"
    else:
        mins = finish + (1440 if finish <= person["start"] else 0)    # a close after midnight
        # The cap is for ends the tool **invented** - a "-close" shift reckoned from the venue's usual
        # closing time. It must not touch an end the roster states: the control room works 13.00-06.00,
        # seventeen hours, and capping that at fourteen had Kilcarran reading "finished Sun 13:00-6:00 -
        # ring him" at half three in the morning, three hours before the man went home, quoting the very
        # time it was ignoring. State and text now come from the same end and cannot disagree.
        if how != "roster":
            mins = min(mins, person["start"] + LONGEST_SHIFT)
        end = midnight + datetime.timedelta(minutes=mins)
    shut = {"roster": hhmm(finish) if finish is not None else "",
            "guess": "about %s" % hhmm(finish) if finish is not None else "",
            "assumed": "close"}[how]
    span = "%s %s-%s" % (day.strftime("%a"), hhmm(person["start"]), shut)

    if now < start:
        wait = start - now
        soon = how_long(wait) if wait.days == 0 else "on %s" % day.strftime("%a")
        return {"day": day, "from": start, "to": end, "state": "later", "span": span,
                "text": "not on until %s %s (%s)" % (day.strftime("%a"), hhmm(person["start"]), soon)}
    if now > end:
        return {"day": day, "from": start, "to": end, "state": "gone", "span": span,
                "text": "finished %s - ring him" % span}
    return {"day": day, "from": start, "to": end, "state": "on", "span": span,
            "text": "on now, until %s" % (shut if how != "assumed" else "close")}


def when_for(venue, monday, now=None):
    """The whole 'when is it any use asking' line for one venue, against the clock.

    Lifted out of check() so the window can work it out again on its own - all this needs is the time,
    and re-reading the roster and the folder every time "in 31 min" has to become "in 30 min" is waste.
    One definition, so the background re-time and the full check can never word the same venue
    differently.
    """
    ask = venue.get("ask") or []
    when = when_to_ask(ask[0] if ask else None, monday, now, closes=venue.get("closes"))
    if when.get("state") == "unknown" and ask:
        # The roster left his own hours blank, so there is nothing to time him by. Anyone else on that
        # same night does say when the place is open, and that is what actually decides whether ringing
        # is any use - so borrow their hours and mark them as the venue's, not his. The alternative is
        # the blank cell the user would otherwise be left reading.
        him = ask[0]
        mate = next((p for p in venue["days"].get(him["day"], [])
                     if p["start"] >= 0 and p["name"] != him["name"]), None)
        if mate:
            borrowed = when_to_ask(mate, monday, now, closes=venue.get("closes"))
            when = dict(borrowed, text="%s (venue's hours)" % borrowed["text"])
        else:
            when = dict(when, text="no hours on the roster")
    if venue.get("uncovered") and venue.get("last_day") in venue["uncovered"]:
        # Say what it is: the roster has nobody green on the venue's last night, so there is nobody to
        # ring for it yet. "not covered" meant nothing to the user - "nobody on the roster yet" is the
        # same fact in the words he would use.
        day = (monday + datetime.timedelta(days=venue["last_day"])).strftime("%A")
        usual = ask[0]["name"] if ask else ""
        when = dict(when, state="open", text="nobody on the roster for %s yet%s"
                    % (day, " - usually %s" % usual if usual else ""))
    return when


def retime(report, now=None):
    """Re-word every venue's clock line in the report already in hand. Touches no disk at all.

    This is what the window's heartbeat runs so the countdown keeps up with the minute hand. It is about
    a third of a millisecond for a full week, against twenty for a whole check, so it can afford to run
    every few seconds - which is the point: the user watched "in 0h31m" sit there unchanged and said so.
    """
    for v in report.get("venues", ()):
        v["when"] = when_for(v, report["monday"], now)
    return report


def load_chased(sunday=None):
    """Venues already asked for. All weeks, or just one week's {venue: when}."""
    try:
        with open(CHASED, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if sunday is None:
        return data
    got = data.get(sunday.isoformat(), {})
    return got if isinstance(got, dict) else {}


def save_chased(sunday, label, on=True):
    """Remember that this venue has been chased for this week, or that it has not."""
    data = load_chased()
    week = data.setdefault(sunday.isoformat(), {})
    if on:
        week[label] = datetime.datetime.now().strftime("%a %d %b %H:%M")
    else:
        week.pop(label, None)
    if not week:
        data.pop(sunday.isoformat(), None)
    if data:
        with open(CHASED, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False, sort_keys=True)
    elif os.path.exists(CHASED):
        os.remove(CHASED)


def late_list(roster, today, weeks=12, places=None):
    """Which venues go missing most often, over the last finished weeks that were actually collected.

    A week nobody collected would make every venue look late, so only weeks with sheets in them count.
    Returns [{'label', 'missed', 'of', 'weeks'}] worst first, and how many weeks were counted.
    """
    sunday = sunday_of(today) - datetime.timedelta(days=7)
    missed, rostered, counted = collections.Counter(), collections.Counter(), []
    while len(counted) < weeks and sunday > sunday_of(today) - datetime.timedelta(days=7 * (weeks * 3)):
        try:
            r = check(sunday, roster, places)
        except Problem:
            sunday -= datetime.timedelta(days=7)
            continue
        if r["files"]:                                # a week that was never collected tells us nothing
            counted.append(sunday)
            for v in r["venues"]:
                rostered[v["label"]] += 1
                if not v["files"]:
                    missed[v["label"]] += 1
        sunday -= datetime.timedelta(days=7)
    out = [{"label": label, "missed": n, "of": rostered[label],
            "weeks": [w.strftime("%d.%m") for w in counted]}
           for label, n in missed.items()]
    out.sort(key=lambda v: (-v["missed"], v["label"]))
    return out, counted


def _phrase_in(text, phrase):
    return re.search(r"(?:^| )%s(?:$| )" % re.escape(phrase), text) is not None


def match_file(name, venues, taught=None):
    """Which venue a file belongs to: (label, how) or (None, why).

    how is 'taught', 'exact', 'name', 'part' or 'close'; an even match between two venues is
    left unassigned so it gets reported rather than guessed at.
    """
    key = canon(name)
    if not key:
        return None, "nothing in the name to go on"
    taught = load_names() if taught is None else taught
    if key in taught:
        return taught[key], "taught"
    tight = key.replace(" ", "")
    best = {}                                         # label -> (rank, length)
    for v in venues:
        for alias in v["aliases"]:
            thin = alias.replace(" ", "")
            if key == alias or (thin and tight == thin):
                score = (3, len(alias))
            elif _phrase_in(key, alias):
                score = (2, len(alias))
            elif len(thin) >= 5 and thin in tight:
                # the spaces run out sometimes ("powercitynaas2"), but a short alias must be a whole
                # word or the whole name: "37" may not match itself out of the middle of "IMG_3745"
                score = (1, len(thin))
            else:
                continue
            if score > best.get(v["label"], (0, 0)):
                best[v["label"]] = score
    if best:
        order = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        if len(order) > 1 and order[0][1] == order[1][1]:
            return None, "could be %s" % " or ".join(l for l, _ in order if _ == order[0][1])
        return order[0][0], {3: "exact", 2: "name", 1: "part"}[order[0][1][0]]
    # nothing contained the other: allow for a misspelling ("0garvy bar")
    scores = []
    for v in venues:
        ratio = max(difflib.SequenceMatcher(None, key, a).ratio() for a in v["aliases"])
        tightest = max(difflib.SequenceMatcher(None, tight, a.replace(" ", "")).ratio() for a in v["aliases"])
        scores.append((max(ratio, tightest), v["label"]))
    scores.sort(reverse=True)
    if scores and scores[0][0] >= 0.72:
        close = [l for r, l in scores if scores[0][0] - r < 0.05]
        if len(close) == 1:
            return close[0], "close"
        return None, "could be %s" % " or ".join(sorted(close))     # too alike to choose between
    return None, "no venue with a name like this on the roster this week"


# ---- the folder -------------------------------------------------------------

def folder_date(name):
    m = FOLDER_RE.match(name)
    if not m:
        return None
    dd, mo, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if yy < 100:
        yy += 2000
    try:
        return datetime.date(yy, mo, dd)
    except ValueError:
        return None


def known_folders(places=None):
    """Every timesheet folder we can see: {date: path}, the first place searched winning."""
    if places is None:
        places = [DESKTOP, ARCHIVE] + ([os.path.join(ARCHIVE, n) for n in sorted(os.listdir(ARCHIVE))
                                        if os.path.isdir(os.path.join(ARCHIVE, n))] if os.path.isdir(ARCHIVE) else [])
    out = {}
    for place in places:
        try:
            entries = sorted(os.listdir(place))
        except OSError:
            continue
        for n in entries:
            path = os.path.join(place, n)
            d = folder_date(n)
            if d and os.path.isdir(path):
                out.setdefault(d, path)
    return out


def find_folder(sunday, places=None):
    """The folder for that week: (path, how) - how is 'named', 'in the week' or None."""
    folders = known_folders(places)
    if sunday in folders:
        return folders[sunday], "named"
    for d in week_dates(sunday):                      # named for another day of the same week
        if d in folders:
            return folders[d], "named %s, inside this week" % d.strftime("%d.%m.%y")
    return None, None


def sheets_in(folder):
    """The timesheet files in the folder (and any subfolder), newest name order."""
    out = []
    for here, dirs, files in os.walk(folder):
        dirs.sort()
        for n in sorted(files):
            if os.path.splitext(n)[1].lower() in SHEET_EXT:
                path = os.path.join(here, n)
                rel = os.path.relpath(path, folder)
                # When it landed in the folder. The photos themselves carry no date taken - they come
                # through WhatsApp, which strips the Exif - so the file's own time is the best there is.
                try:
                    when = datetime.datetime.fromtimestamp(os.path.getmtime(path))
                except OSError:
                    when = None
                out.append({"name": n, "stem": os.path.splitext(n)[0], "rel": rel, "path": path,
                            "when": when, "when_text": when.strftime("%a %d %b %H:%M") if when else ""})
    return out


# ---- putting it together ----------------------------------------------------

def check(sunday, roster, places=None, folder=None):
    """The whole answer for one week: which venues are in, which are missing, what could not be matched."""
    venues, idle, notes = roster.week(sunday)
    for v in venues + idle:
        v["aliases"] = aliases_for(v["label"])
        v["files"] = []
    how = "given"
    if folder is None:
        folder, how = find_folder(sunday, places)
    files = sheets_in(folder) if folder and os.path.isdir(folder) else []
    taught, spare = load_names(), []
    by_label = {v["label"]: v for v in venues}
    for f in files:
        label, why = match_file(f["stem"], venues, taught)
        f["venue"], f["how"] = label, why
        if label in by_label:
            by_label[label]["files"].append(f)
            continue
        if not label and idle:                        # a sheet for a venue the roster has nobody on this week
            asleep, _ = match_file(f["stem"], idle, taught)
            label = asleep or label
        if label:                                     # taught, or a venue that is on the roster but not this week
            f["venue"], f["how"] = label, ("a sheet for %s, but the roster has nobody there this week - "
                                           "worth checking the roster" % label)
        spare.append(f)
    missing = [v for v in venues if not v["files"]]
    asked = load_chased(sunday)                       # venues already chased for this week
    contacts, regular, closing = load_contacts(), regulars(roster, sunday), load_closing()
    monday = sunday - datetime.timedelta(days=6)
    for v in venues:
        v["ask"], v["away"] = who_has_it(v, contacts, regular)
        v["closes"] = closing.get(v["label"])
        v["when"] = when_for(v, monday)
        # the roster still has days on this venue that nobody confirmed is covering
        v["gap"] = ", ".join((monday + datetime.timedelta(days=i)).strftime("%a") for i in v["uncovered"])
    for v in missing:
        v["chased"] = asked.get(v["label"], "")
    return {"sunday": sunday, "monday": sunday - datetime.timedelta(days=6), "week": week_text(sunday),
            "folder": folder, "folder_how": how, "folder_name": folder_name(sunday),
            "venues": venues, "in": [v for v in venues if v["files"]], "missing": missing,
            "spare": spare, "files": files, "notes": notes}


def week_name(sunday, today):
    """'Last week' / 'This week' / 'Next week' / '3 weeks ago', so the window and the print always say which."""
    off = (sunday - sunday_of(today)).days // 7
    if off in (-1, 0, 1):
        return {-1: "Last week", 0: "This week", 1: "Next week"}[off]
    return "%d weeks %s" % (abs(off), "ago" if off < 0 else "ahead")


def lines(report, width=26):
    """The check as text, the way it is printed and saved."""
    out = ["=== %s:  Timesheets  %s ===" % (week_name(report["sunday"], datetime.date.today()), report["week"])]
    if report.get("opening_note"):
        out.append(report["opening_note"])
    if report["folder"]:
        out.append("Folder: %s   (%d file%s)" % (report["folder"], len(report["files"]),
                                                 "" if len(report["files"]) == 1 else "s"))
        if report["folder_how"] not in ("named", "given"):
            out.append("        this folder is %s" % report["folder_how"])
    else:
        out.append("Folder: none yet - looked for %r on the Desktop and in %s" % (report["folder_name"], ARCHIVE))
    total, got = len(report["venues"]), len(report["in"])
    out.append("Venues rostered this week: %d   |   in: %d   |   missing: %d" % (total, got, total - got))
    out.append("")
    if report["missing"]:
        out.append("STILL TO COME IN (%d)   - the sheet is held by the venue's own man, and the night it"
                   " finishes is the night to get it" % len(report["missing"]))
        monday = report["monday"]
        for _, head, venues in to_collect(report):
            out.append("")
            out.append("  %s (%d)" % (head.upper(), len(venues)))
            for v in venues:
                tail = "   [all struck through - may be cancelled]" if not v["live"] else ""
                if v.get("chased"):
                    tail += "   [asked %s]" % v["chased"]
                first = v["ask"][0] if v.get("ask") else None
                ask = ("ask %s  (%s %s)" % (first["name"],
                                            (monday + datetime.timedelta(days=first["day"])).strftime("%a %d"),
                                            first["shift"])) if first else ", ".join(v["names"])
                out.append("    %-*s %-10s %s%s" % (width, v["label"], v["day_text"], ask, tail))
                if (v.get("when") or {}).get("text"):
                    out.append("    %-*s %-10s %s" % (width, "", "", v["when"]["text"]))
                if v.get("away"):
                    out.append("    %-*s %-10s %s usually sends it, but is not on this week"
                               % (width, "", "", " and ".join(v["away"])))
        out.append("")
    if report["in"]:
        out.append("IN (%d)" % len(report["in"]))
        for v in report["in"]:
            names = ", ".join(f["name"] for f in v["files"])
            out.append("  %-*s %s%s" % (width, v["label"], names,
                                        "   [%d files]" % len(v["files"]) if len(v["files"]) > 1 else ""))
        out.append("")
    if report["spare"]:
        out.append("FILES NOT MATCHED TO A VENUE (%d)" % len(report["spare"]))
        for f in report["spare"]:
            out.append("  %-*s %s" % (width, f["name"], f["how"]))
        out.append("")
    for n in report["notes"]:
        out.append("NOTE: " + n)
    return out


def main():
    ap = argparse.ArgumentParser(description="Check which venues' timesheets have come in for a week.")
    ap.add_argument("week", nargs="?", help="last, this, next, or a date in the week (04/10, 2026-10-04); "
                                            "with nothing given, this week if it has a folder, else last week")
    ap.add_argument("--folder", help="check this folder instead of looking for the week's one")
    ap.add_argument("--no-download", action="store_true", help="use the roster copy saved last time")
    ap.add_argument("--save", metavar="FILE", help="also write the list to a text file")
    ap.add_argument("--late", nargs="?", type=int, const=12, metavar="WEEKS",
                    help="instead of a week: which venues go missing most often over the last WEEKS collected weeks")
    ap.add_argument("--make-folder", action="store_true",
                    help="make this week's folder on the Desktop if it is not there (the window does this on its own)")
    ap.add_argument("--open", action="store_true", help="open the week's folder when done")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")
    try:
        today = datetime.date.today()
        if args.make_folder:
            path, is_new = make_week_folder(sunday_of(today))
            print("Folder: made %s" % path if is_new else "Folder: this week already has one")
        sunday = pick_week(args.week, today) if args.week else default_week(today)
        if args.no_download and os.path.exists(ROSTER_PATH):
            print("Roster: saved copy (not re-downloaded)")
        else:
            print("Roster: " + download_roster())
        roster = Roster()
        if args.late:
            rows, weeks = late_list(roster, today, args.late)
            print("\n=== Often late: the last %d collected weeks, %s to %s ===" % (
                len(weeks), weeks[-1].strftime("%d %b") if weeks else "-",
                weeks[0].strftime("%d %b %Y") if weeks else "-"))
            for v in rows:
                print("  %-28s missed %2d of %2d" % (v["label"], v["missed"], v["of"]))
            if not rows:
                print("  nothing was late")
            return 0
        report = check(sunday, roster, folder=args.folder)
        if not args.week and not args.folder:         # don't let the week before drop out of sight
            before = sunday - datetime.timedelta(days=7)
            try:
                behind = check(before, roster)["missing"]
            except Problem:
                behind = []
            if behind:
                report["opening_note"] = "%s is still waiting on %d (%s)  -  run:  timesheets.py %s" % (
                    week_name(before, today), len(behind),
                    ", ".join(v["label"] for v in behind[:4]) + (" ..." if len(behind) > 4 else ""),
                    before.strftime("%d/%m"))
    except Problem as e:
        print("PROBLEM: %s" % e)
        return 1
    text = "\n".join(lines(report))
    print(text)
    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("saved: " + args.save)
    if args.open and report["folder"]:
        os.startfile(report["folder"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
