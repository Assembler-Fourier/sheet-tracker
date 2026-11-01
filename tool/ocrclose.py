"""Turns what the OCR read off the timesheets into a closing time per venue.

    python ocrclose.py            read ocr\\words.jsonl, write ocr\\closing.json
    python ocrclose.py --show     print what it found and how sure it is

The sheets are handwritten, so any one reading is unreliable - "03:00" comes back as "0:300", "o3oo",
"0:3æ". What makes this work is that there are hundreds of them: the right answer repeats and the noise
does not, so the most common plausible time wins. Venues whose roster shift already carries a real end
time (the Voltmart stores, Lucky Bingo, QuickStop) do not need this at all and are not guessed at.

Only the right-hand edge of the page is read: that is the "Time out" column. A venue is identified by the
file name, through the same matcher the tool uses everywhere else.
"""
import argparse
import collections
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import timesheets as ts  # noqa: E402

WORDS = os.path.join(HERE, "ocr", "words.jsonl")
CLOSING = os.path.join(HERE, "ocr", "closing.json")
#: Measured, not guessed: across ~950 sheets the time-like words pile up at x 0.75-0.80 ("Time in",
#: full of 20:00 and 22:00 starts) and again at 0.85-0.90 ("Time out", full of 3:00 and 0:00). A cutoff
#: of 0.70 dragged the start times in and made Loft and Perch "close" at 20:00.
RIGHT = 0.82                                          # a word this far across the page is a "time out"
#: "0:300" and "o300" are how 03:00 gets written in a hurry; allow 3 or 4 digits with or without a colon
TIME = re.compile(r"^[oO0-9]{1,2}\s*[:.;]?\s*([0-9]{2})[0-9oO]?$")
NIGHT = set(range(20, 24)) | set(range(0, 7))         # a closing hour is late evening or small hours


def as_minutes(text):
    """A scrap of OCR into a closing time, or None. Only times that could be a closing hour get through."""
    raw = text.strip().replace(" ", "").replace("O", "0").replace("o", "0")
    raw = raw.rstrip("-/.,;:")
    m = re.match(r"^(\d{1,2})[:.;]?(\d{2})\d?$", raw)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None
    if hour not in NIGHT:
        return None
    if minute not in (0, 15, 30, 45):                 # people write the half hour, not 03:07
        return None
    return hour * 60 + minute


def read(path=WORDS):
    """Per venue: every closing-time candidate the OCR produced, and how many sheets were read."""
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return {}, 0, {}
    seen = collections.defaultdict(collections.Counter)
    sheets = collections.Counter()
    read_ok = 0
    venues = None
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if "words" not in row:
            continue
        read_ok += 1
        if venues is None:                            # the venue labels, for the file-name matcher
            venues = [{"label": lab, "aliases": ts.aliases_for(lab)} for lab in all_labels()]
        label, _ = ts.match_file(os.path.splitext(row["file"])[0], venues, taught=ts.load_names())
        if not label:
            continue
        sheets[label] += 1
        for word in row["words"]:
            if word.get("x", 0) < RIGHT:
                continue
            mins = as_minutes(word.get("t", ""))
            if mins is not None:
                seen[label][mins] += 1
    return seen, read_ok, sheets


def all_labels():
    """Every venue the roster has shown lately, so a file name can be matched to one."""
    try:
        roster = ts.Roster()
    except Exception:
        return []
    out, sunday = [], ts.sunday_of(datetime.date.today())
    for _ in range(14):
        try:
            venues, idle, _ = roster.week(sunday)
        except ts.Problem:
            venues, idle = [], []
        for v in venues + idle:
            if v["label"] not in out:
                out.append(v["label"])
        sunday -= datetime.timedelta(days=7)
    return out


#: How much of a venue's shifts must carry the same written end before the roster is believed over the
#: sheets. Without this, one typo beat eleven readings: "12 Harbour st" had three shifts ending 20:00 out
#: of 348 and closed at eight in the evening, and Hanlons closed at 20:30 on the strength of one cell.
ROSTER_SHARE = 0.25


def roster_ends():
    """Venues whose roster shift says when they finish: {venue: (minutes, times seen, shifts in all)}."""
    try:
        roster = ts.Roster()
    except Exception:
        return {}
    ends = collections.defaultdict(collections.Counter)
    shifts = collections.Counter()
    sunday = ts.sunday_of(datetime.date.today())
    for _ in range(14):
        try:
            venues, _, _ = roster.week(sunday)
        except ts.Problem:
            venues = []
        for v in venues:
            for p in v["people"]:
                if p.get("shift"):
                    shifts[v["label"]] += 1
                if p.get("end") is not None:
                    ends[v["label"]][p["end"]] += 1
        sunday -= datetime.timedelta(days=7)
    out = {}
    for label, counter in ends.items():
        mins, seen = counter.most_common(1)[0]
        out[label] = (mins, seen, max(1, shifts[label]))
    return out


def main():
    ap = argparse.ArgumentParser(description="Work out each venue's closing time from the read sheets.")
    ap.add_argument("--words", default=WORDS)
    ap.add_argument("--out", default=CLOSING)
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()

    seen, read_ok, sheets = read(args.words)
    if not read_ok:
        print("no OCR output at %s - run ocrscan.ps1 first" % args.words)
        return 1
    known = roster_ends()
    out = {}
    for label, counter in seen.items():
        total = sum(counter.values())
        best, n = counter.most_common(1)[0]
        out[label] = {"close": ts.hhmm(best), "close_min": best, "votes": n, "of": total,
                      "sheets": sheets[label], "sure": round(n / float(total), 2),
                      "from": "the sheets"}
    # The roster wins only where it really says so - a written end on a fair share of the venue's
    # shifts. One stray cell does not get to overrule a hundred sheets.
    for label, (mins, times, total) in known.items():
        share = times / float(total)
        if share >= ROSTER_SHARE or label not in out:
            out[label] = {"close": ts.hhmm(mins), "close_min": mins, "votes": times, "of": total,
                          "sheets": sheets.get(label, 0), "sure": round(min(1.0, share), 2),
                          "from": "the roster" if share >= ROSTER_SHARE else "the roster (thin)"}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False, sort_keys=True)
    print("%d sheets read, %d venues with a closing time -> %s" % (read_ok, len(out), args.out))
    if args.show:
        print("\n%-26s %-7s %-12s %6s %s" % ("venue", "closes", "from", "sure", "runners-up"))
        for label in sorted(out, key=lambda l: (out[l]["from"], l)):
            got = out[label]
            others = ""
            if label in seen:
                others = "  ".join("%s x%d" % (ts.hhmm(t), n) for t, n in seen[label].most_common(4)[1:])
            print("%-26s %-7s %-12s %5.0f%% %s" % (label[:26], got["close"], got["from"],
                                                   got["sure"] * 100, others))
    return 0


if __name__ == "__main__":
    sys.exit(main())
