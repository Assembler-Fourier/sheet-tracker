"""Checks the things that must always be true, on every week the roster covers.

    python audit.py            every week of the current year
    python audit.py 2026 --all every week, folder or no folder

selftest/faketest prove known cases; this proves **invariants** - statements that must hold for any week,
whatever is in the roster that month. It is the net for the bugs nobody thought to write a case for.
Reads only: the saved roster and the timesheet folders. Writes nothing at all.
"""
import argparse
import collections
import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import timesheets as ts  # noqa: E402

WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
faults = collections.Counter()
examples = collections.defaultdict(list)


def bad(rule, where, detail):
    faults[rule] += 1
    if len(examples[rule]) < 3:
        examples[rule].append("%s: %s" % (where, detail))


def check_week(sunday, roster, now):
    where = sunday.strftime("%d.%m.%y")
    try:
        r = ts.check(sunday, roster)
    except ts.Problem:
        return False
    venues = r["venues"]

    # --- the week adds up ---
    if len(r["in"]) + len(r["missing"]) != len(venues):
        bad("in + missing = every venue", where, "%d + %d != %d"
            % (len(r["in"]), len(r["missing"]), len(venues)))
    labels = [v["label"] for v in venues]
    for label, n in collections.Counter(labels).items():
        if n > 1:
            bad("a venue appears once", where, "%s appears %d times" % (label, n))
    if any("NOTE" in l.upper() for l in labels):
        bad("no note is read as a venue", where, [l for l in labels if "NOTE" in l.upper()])

    # --- every file lands in exactly one place ---
    seen = collections.Counter()
    for v in venues:
        for f in v["files"]:
            seen[f["rel"]] += 1
    for f in r["spare"]:
        seen[f["rel"]] += 1
    for rel, n in seen.items():
        if n > 1:
            bad("a file counts for one venue only", where, "%s counted %d times" % (rel, n))
    if len(seen) != len(r["files"]):
        bad("every file is accounted for", where, "%d files, %d placed" % (len(r["files"]), len(seen)))

    # --- the collection groups are a clean split of what is missing ---
    grouped = [v["label"] for _, _, vs in ts.to_collect(r) for v in vs]
    if sorted(grouped) != sorted(v["label"] for v in r["missing"]):
        bad("the nights split the missing exactly", where,
            "%d grouped vs %d missing" % (len(grouped), len(r["missing"])))

    for v in venues:
        tag = "%s/%s" % (where, v["label"][:18])
        # --- days and the last day ---
        if not v["open"]:
            bad("a venue is open some day", tag, "no open days at all")
        elif v["last_day"] != v["open"][-1]:
            bad("the last day is the last open day", tag,
                "last=%s open=%s" % (WEEK[v["last_day"]], [WEEK[i] for i in v["open"]]))
        if v["people"] and max(p["day"] for p in v["people"]) > v["last_day"]:
            bad("nobody works after the last day", tag, "someone is on past %s" % WEEK[v["last_day"]])
        if not v["day_text"]:
            bad("a venue says which days it worked", tag, "day_text is empty")

        # --- who to ask ---
        if not v["ask"]:
            if v["people"]:
                bad("a venue with people has somebody to ask", tag, "no candidates")
        else:
            top = v["ask"][0]
            if top["name"] not in {p["name"] for p in v["people"]}:
                bad("the one to ask is rostered there", tag, "%s is not on this week" % top["name"])
            if not top.get("why"):
                bad("the one to ask comes with a reason", tag, "no reason given")
            names = [p["name"] for p in v["ask"]]
            if len(names) != len(set(names)):
                bad("nobody is listed twice", tag, names)
            # the "only one" claim has to be true
            for p in v["ask"]:
                if "only one on the last day" in p.get("why", "") \
                        and len(v["days"].get(v["last_day"], [])) != 1:
                    bad("'the only one' really is the only one", tag,
                        "%d people on %s" % (len(v["days"].get(v["last_day"], [])), WEEK[v["last_day"]]))

        # --- when to ask ---
        w = v.get("when") or {}
        if w.get("state") not in ("on", "later", "gone", "open", "unknown", None):
            bad("when-to-ask has a known state", tag, w.get("state"))
        if w.get("state") == "on" and w.get("from") and w.get("to"):
            if not (w["from"] <= now <= w["to"]):
                bad("'on now' is actually now", tag, "%s..%s vs %s" % (w["from"], w["to"], now))
        if w.get("state") == "later" and w.get("from") and w["from"] <= now:
            bad("'not on until' is in the future", tag, w["from"])
        if w.get("state") == "gone" and w.get("to") and w["to"] >= now:
            bad("'finished' really has finished", tag, w["to"])
        if w.get("from") and w.get("to") and w["to"] <= w["from"]:
            bad("a shift ends after it starts", tag, "%s -> %s" % (w["from"], w["to"]))
        # Twenty, not fifteen: the control room really does work 11.00-06.00, nineteen hours, and the
        # roster says so in as many words. The old bound only held because LONGEST_SHIFT was truncating
        # those shifts - which is the very bug that had Kilcarran "finished" three hours before it was.
        # What is still worth catching is a span no roster would ever state.
        if w.get("from") and w.get("to") and (w["to"] - w["from"]).total_seconds() > 20 * 3600:
            bad("a shift is not longer than 20 hours", tag,
                "%.1f hours" % ((w["to"] - w["from"]).total_seconds() / 3600))

        # --- wind the clock through the whole week against this venue ---
        # The checks above only ever see one instant: whatever time the audit is run. This runs the
        # clock from the Monday to the Tuesday after in twenty-minute steps and insists the answer only
        # ever goes one way - not yet, then on now, then finished. A state that goes backwards, or an
        # "on now" outside the shift, is the bug the user met as "how is k9 on right now its closed".
        if v.get("ask"):
            order = {"later": 0, "on": 1, "gone": 2}
            person, seen, broke = v["ask"][0], None, False
            monday = sunday - datetime.timedelta(days=6)
            t = datetime.datetime.combine(monday, datetime.time())
            last = datetime.datetime.combine(sunday + datetime.timedelta(days=2), datetime.time())
            while t <= last and not broke:
                w = ts.when_for(v, monday, t)
                s, text = w.get("state"), w.get("text", "")
                if s in order:
                    if seen is not None and order[s] < order[seen]:
                        bad("the clock only ever moves one way", tag, "%s -> %s at %s" % (seen, s, t))
                        broke = True
                    seen = s
                    if s == "on" and w.get("from") and w.get("to") and not (w["from"] <= t <= w["to"]):
                        bad("'on now' falls inside the shift", tag, t)
                        broke = True
                    # "in 0h07m" is what the user read and said "what is 0 hours anyways". Note the
                    # "in ": a plain "0h" also sits inside a perfectly good "in 20h 40m".
                    if "in 0h" in text or " 0m" in text:
                        bad("the countdown never says nought hours", tag, text)
                        broke = True
                t += datetime.timedelta(minutes=20)
            # "unknown" all week is honest when the roster gives no times at all; a shift with a start
            # on it must have finished by the Tuesday after.
            if not broke:
                if seen is None and person.get("start", -1) >= 0:
                    bad("a shift with a time on it ends", tag, "never left 'unknown'")
                elif seen is not None and seen != "gone":
                    bad("every shift is over by the Tuesday after", tag, seen)

        # --- the closing time ---
        shut = v.get("closes")
        if shut:
            mins, source, sure = shut
            if not 0 <= mins < 1440:
                bad("a closing time is a time of day", tag, mins)
            if source == "the sheets" and not (20 * 60 <= mins or mins <= 7 * 60):
                bad("a reckoned close is at night", tag, ts.hhmm(mins))
            if not 0 <= sure <= 1:
                bad("how sure is a fraction", tag, sure)
    return True


def main():
    ap = argparse.ArgumentParser(description="Check what must always be true, week after week.")
    ap.add_argument("year", nargs="?", type=int, default=datetime.date.today().year)
    ap.add_argument("--all", action="store_true", help="weeks with no folder too")
    args = ap.parse_args()

    roster = ts.Roster()
    now = datetime.datetime.now()
    day = datetime.date(args.year, 1, 1)
    sundays = []
    while day.year == args.year:
        if day.weekday() == 6:
            sundays.append(day)
        day += datetime.timedelta(days=1)

    folders = ts.known_folders()
    done = 0
    for sunday in sundays:
        if not args.all and not any(d in folders for d in ts.week_dates(sunday)):
            continue
        done += check_week(sunday, roster, now)
    print("audit of %d weeks in %d\n" % (done, args.year))
    if not faults:
        print("every rule held, on every week")
        return 0
    for rule, n in faults.most_common():
        print("  BROKEN  %-44s %d time%s" % (rule, n, "" if n == 1 else "s"))
        for line in examples[rule]:
            print("            %s" % line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
