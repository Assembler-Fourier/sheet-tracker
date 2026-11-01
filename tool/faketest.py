"""Hard cases, on a roster built for the purpose.

    python faketest.py

The real roster shows only what it happens to contain this month, and the weeks it covers get deleted as
it rolls forward - so the awkward cases cannot be tested against it reliably. This builds a roster of its
own (fakeroster.py) with every nasty shape in it at once, puts made-up sheets in a made-up folder, and
checks the tool reads all of it correctly. Nothing outside a temp folder is touched: the real roster, the
real Desktop, names.json, chased.json and contacts.json are all left alone.
"""
import datetime
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import timesheets as ts  # noqa: E402
from fakeroster import FakeRoster, STRUCK  # noqa: E402

SUNDAY = datetime.date(2026, 7, 12)                   # the week under test: Mon 6 - Sun 12 Jul 2026
problems = []


def ok(what, got, want):
    if got == want:
        print("  ok    %-54s %s" % (what, got))
    else:
        print("  FAIL  %-54s got %r, wanted %r" % (what, got, want))
        problems.append(what)


def build_roster(path):
    """One week with every shape in it that has ever caused trouble."""
    r = FakeRoster()
    r.week(SUNDAY, label_col=1)                       # label col A, Mon..Sun in B..H
    row = 3
    # a plain venue, one man every day - he is the regular and the obvious one to ask
    row = r.venue(row, 1, "Plain Bar", {i: [("20:00-close", "Alan Regular")] for i in range(7)}) + 1
    # closed on Sunday: last day is Saturday, so it has to be got on the Saturday night
    row = r.venue(row, 1, "Shut Sundays", {4: [("18:00-close", "Bea Weekend")],
                                           5: [("18:00-close", "Bea Weekend")]}) + 1
    # finished on the Wednesday: its night has already gone
    row = r.venue(row, 1, "Midweek Only", {2: [("19:00-close", "Cal Midweek")]}) + 1
    # several on at once: the head doorman starts earliest, the others come in later
    row = r.venue(row, 1, "Big Door", {5: [("18:00-close", "Head Doorman"),
                                           ("22:00-close", "Late Helper"),
                                           ("23:00-close", "Later Still")],
                                       6: [("18:00-close", "Head Doorman"),
                                           ("22:00-close", "Late Helper")]}) + 1
    # every name struck through - the shift may have been cancelled
    row = r.venue(row, 1, "Struck Out", {5: [("20:00-close", "Dee Cancelled", STRUCK)]}) + 1
    # on the roster with nobody on it this week: no sheet should ever be expected
    row = r.venue(row, 1, "Nobody Home", {}) + 1
    # a note sitting in the venue column, directly under a venue, exactly as the real roster does
    r.venue(row, 1, "Under A Sign", {5: [("21:00-close", "Eve Survivor")]})
    r.note(row + 1, 1, "IMPORTANT NOTE")
    row += 4
    # a venue whose label is typed into a day column instead of the label column
    r.put(row, 4, "Day Column Venue", 1)
    r.put(row + 1, 4, "17:00-close", 3)
    r.put(row + 2, 4, "Fred Wednesday", 2)
    return r.save(path)


def sheets(folder, names):
    os.makedirs(folder, exist_ok=True)
    for n in names:
        with open(os.path.join(folder, n), "w", encoding="utf-8") as f:
            f.write("x")
    return folder


def main():
    work = tempfile.mkdtemp(prefix="ts-fake-")
    # keep every piece of the user's own data out of this
    ts.ROSTER_PATH = os.path.join(work, "roster.xlsx")
    ts.CONTACTS = os.path.join(work, "contacts.json")
    ts.CHASED = os.path.join(work, "chased.json")
    ts.NAMES = os.path.join(work, "names.json")
    ts.DESKTOP = os.path.join(work, "Desktop")
    build_roster(ts.ROSTER_PATH)
    roster = ts.Roster(ts.ROSTER_PATH)

    print("reading a roster written for the test")
    venues, idle, notes = roster.week(SUNDAY)
    names = [v["label"] for v in venues]
    ok("every venue with somebody on it is found", sorted(names), sorted(
        ["Plain Bar", "Shut Sundays", "Midweek Only", "Big Door", "Struck Out", "Under A Sign",
         "Day Column Venue"]))
    ok("a venue with nobody on it is not expected", [v["label"] for v in idle], ["Nobody Home"])
    ok("a note in the venue column is not a venue", [n for n in names if "NOTE" in n.upper()], [])
    ok("...and its people stay with the venue above",
       [p["name"] for v in venues if v["label"] == "Under A Sign" for p in v["people"]], ["Eve Survivor"])
    ok("a label typed into a day column is found",
       [p["name"] for v in venues if v["label"] == "Day Column Venue" for p in v["people"]],
       ["Fred Wednesday"])
    by = {v["label"]: v for v in venues}
    ok("all names struck through is flagged", by["Struck Out"]["live"], False)
    ok("a live venue is not flagged", by["Plain Bar"]["live"], True)
    ok("days read as a run", by["Plain Bar"]["day_text"], "Mon-Sun")
    ok("a two-day venue", by["Shut Sundays"]["day_text"], "Fri-Sat")

    print("\nwhich night each one has to be collected")
    folder = sheets(os.path.join(work, "Desktop", "Timesheets 12.07.26"), [])
    r = ts.check(SUNDAY, roster, folder=folder)
    groups = {k: [v["label"] for v in vs] for k, _, vs in ts.to_collect(r)}
    ok("Sunday venues", sorted(groups.get("sun", [])), ["Big Door", "Plain Bar"])
    ok("Saturday venues - shut on the Sunday", sorted(groups.get("sat", [])),
       sorted(["Under A Sign", "Shut Sundays", "Struck Out"]))
    ok("already finished", sorted(groups.get("past", [])), ["Day Column Venue", "Midweek Only"])

    print("\nwho to ask for it")
    by = {v["label"]: v for v in r["venues"]}
    ok("with nobody taught, the regular comes first", by["Plain Bar"]["ask"][0]["name"], "Alan Regular")
    ok("the man who starts earliest leads a big door",
       [p["name"] for p in by["Big Door"]["ask"][:3]],
       ["Head Doorman", "Late Helper", "Later Still"])
    ts.save_contact("Big Door", "Late Helper")         # the user says it is really the late one
    r = ts.check(SUNDAY, roster, folder=folder)
    by = {v["label"]: v for v in r["venues"]}
    ok("a name taught by hand wins", by["Big Door"]["ask"][0]["name"], "Late Helper")
    ok("...and says why", by["Big Door"]["ask"][0]["why"], "sends this one")
    ts.save_contact("Shut Sundays", "Ghost Whoisoff")  # taught, but not rostered this week
    r = ts.check(SUNDAY, roster, folder=folder)
    by = {v["label"]: v for v in r["venues"]}
    ok("a sender who is off is named separately", by["Shut Sundays"]["away"], ["Ghost Whoisoff"])
    ok("...and the stand-in is asked instead", by["Shut Sundays"]["ask"][0]["name"], "Bea Weekend")
    ts.save_contact("Big Door", "Late Helper", False)
    ok("a taught name can be taken off again", ts.load_contacts().get("Big Door"), None)

    print("\nsheets arriving")
    sheets(folder, ["Plain Bar.jpg", "big door 1.jpg", "big door 2.jpg", "something odd.jpg"])
    r = ts.check(SUNDAY, roster, folder=folder)
    by = {v["label"]: v for v in r["venues"]}
    ok("a sheet is matched", [f["name"] for f in by["Plain Bar"]["files"]], ["Plain Bar.jpg"])
    ok("two pages land on one venue", len(by["Big Door"]["files"]), 2)
    ok("a file matching nothing is reported", [f["name"] for f in r["spare"]], ["something odd.jpg"])
    ok("every file carries when it arrived", all(f["when_text"] for f in r["files"]), True)
    ok("the ones in are counted", len(r["in"]), 2)
    ok("the rest are still missing", len(r["missing"]), 5)
    ts.save_name("something odd", "Midweek Only")       # teach the odd file
    r = ts.check(SUNDAY, roster, folder=folder)
    ok("a taught file name is used", [f["name"] for f in r["spare"]], [])
    ok("...and counts for its venue", len(r["in"]), 3)

    print("\nwhen it is any use ringing")
    # Mon 6 Jul 2026 is the Monday of the test week; day 5 is the Saturday, day 6 the Sunday
    monday = SUNDAY - datetime.timedelta(days=6)

    def ask(day, start, end, now, closes=None):
        who = {"name": "X", "day": day, "start": start, "end": end, "shift": ""}
        return ts.when_to_ask(who, monday, now=now, closes=closes)

    sat_night = {"day": 5, "start": 22 * 60, "end": None}          # K9: Saturday 22:00-close
    ok("a Saturday night door, asked on the Saturday evening",
       ask(5, 22 * 60, None, datetime.datetime(2026, 7, 11, 23, 30))["state"], "on")
    ok("...still on in the small hours", ask(5, 22 * 60, None,
       datetime.datetime(2026, 7, 12, 2, 0))["state"], "on")
    # the bug the user caught: a club shut since 3am read as "on now" at half two the next afternoon
    ok("...but NOT the next afternoon", ask(5, 22 * 60, None,
       datetime.datetime(2026, 7, 12, 14, 27))["state"], "gone")
    ok("...and it says so", "ring him" in ask(5, 22 * 60, None,
       datetime.datetime(2026, 7, 12, 14, 27))["text"], True)
    ok("a shift that has not started", ask(6, 17 * 60, 22 * 60,
       datetime.datetime(2026, 7, 12, 14, 27))["state"], "later")
    ok("...says how long to wait", "in 2h 33m" in ask(6, 17 * 60, 22 * 60,
       datetime.datetime(2026, 7, 12, 14, 27))["text"], True)
    # "what is 0 hours anyways" - the countdown used to read "in 0h31m". Minutes are minutes.
    ok("under the hour it counts in minutes", "in 31 min" in ask(6, 17 * 60, 22 * 60,
       datetime.datetime(2026, 7, 12, 16, 29))["text"], True)
    ok("...and never says nought hours", "0h" in ask(6, 17 * 60, 22 * 60,
       datetime.datetime(2026, 7, 12, 16, 29))["text"], False)
    ok("a round hour drops the minutes", "in 2h" in ask(6, 17 * 60, 22 * 60,
       datetime.datetime(2026, 7, 12, 15, 0))["text"], True)
    ok("...without a stray 0m", "in 2h 0m" in ask(6, 17 * 60, 22 * 60,
       datetime.datetime(2026, 7, 12, 15, 0))["text"], False)
    ok("one minute reads as one minute", "in a minute" in ask(6, 17 * 60, 22 * 60,
       datetime.datetime(2026, 7, 12, 16, 59))["text"], True)
    ok("a day away is named by its day", "on Sun" in ask(6, 17 * 60, 22 * 60,
       datetime.datetime(2026, 7, 11, 10, 0))["text"], True)
    # The control room works 13.00-06.00. Capping a shift the roster states at fourteen hours had it
    # reading "finished Sun 13:00-6:00 - ring him" at half three in the morning - quoting the very time
    # it was ignoring. A stated end is a fact; only an invented one gets capped.
    long_night = ask(6, 13 * 60, 6 * 60, datetime.datetime(2026, 7, 13, 3, 30))
    ok("a seventeen-hour shift the roster states", long_night["state"], "on")
    ok("...is still on at half three", "on now" in long_night["text"], True)
    ok("...and over by seven", ask(6, 13 * 60, 6 * 60,
       datetime.datetime(2026, 7, 13, 7, 0))["state"], "gone")
    # but a "-close" with nothing to go on is still capped, or K9 reads "on now" all Sunday afternoon
    ok("an invented end is still capped", ask(5, 22 * 60, None,
       datetime.datetime(2026, 7, 12, 14, 27))["state"], "gone")
    ok("a shift with a real end, during it", ask(6, 17 * 60, 22 * 60,
       datetime.datetime(2026, 7, 12, 19, 0))["state"], "on")
    ok("...and after it", ask(6, 17 * 60, 22 * 60,
       datetime.datetime(2026, 7, 12, 22, 30))["state"], "gone")
    ok("an overnight shift, after midnight", ask(6, 18 * 60, 6 * 60,
       datetime.datetime(2026, 7, 13, 3, 0))["state"], "on")
    ok("...and once it has ended", ask(6, 18 * 60, 6 * 60,
       datetime.datetime(2026, 7, 13, 7, 0))["state"], "gone")
    ok("a known closing time is used instead of guessing", ask(5, 22 * 60, None,
       datetime.datetime(2026, 7, 12, 2, 30), closes=(3 * 60, "the sheets", 0.7))["state"], "on")
    ok("...and it closes when it says", ask(5, 22 * 60, None,
       datetime.datetime(2026, 7, 12, 4, 0), closes=(3 * 60, "the sheets", 0.7))["state"], "gone")
    ok("...and says it is a guess", "about 03:00" in ask(5, 22 * 60, None,
       datetime.datetime(2026, 7, 12, 2, 30), closes=(3 * 60, "the sheets", 0.7))["text"], True)

    print("\nre-timing in the background")
    # The window re-words the clock lines every few seconds without going near the roster or the folder.
    # ts.retime() is what it calls, and it has to agree with a full check - one definition, or the
    # countdown on screen and the list he saves would say different things about the same venue.
    r = ts.check(SUNDAY, roster, folder=folder)
    evening = datetime.datetime(2026, 7, 12, 16, 29)      # Big Door is on the Sunday at 18:00
    ts.retime(r, evening)

    def big_door():
        return next(v["when"]["text"] for v in r["venues"] if v["label"] == "Big Door")

    ok("a re-time re-words every venue",
       all(isinstance(v["when"].get("text"), str) for v in r["venues"]), True)
    ok("...an hour and a half out", "in 1h 31m" in big_door(), True)
    ts.retime(r, datetime.datetime(2026, 7, 12, 17, 29))
    ok("...half an hour out, counted in minutes", "in 31 min" in big_door(), True)
    ts.retime(r, datetime.datetime(2026, 7, 12, 19, 0))
    ok("...and once he is on, it says so", "on now" in big_door(), True)
    # the same instant through both paths must read identically
    fresh = ts.check(SUNDAY, roster, folder=folder)
    ts.retime(fresh, evening)
    ts.retime(r, evening)
    ok("a re-time says what a full check says",
       {v["label"]: v["when"]["text"] for v in r["venues"]},
       {v["label"]: v["when"]["text"] for v in fresh["venues"]})

    print("\nweeks the roster cannot answer")
    try:
        ts.check(SUNDAY + datetime.timedelta(days=70), roster)
        ok("a week off the end of the roster", "no complaint", "a Problem")
    except ts.Problem:
        ok("a week off the end of the roster", "Problem raised", "Problem raised")

    print("\nchasing")
    ts.save_chased(SUNDAY, "Plain Bar", True)
    ok("a chase mark is kept", bool(ts.load_chased(SUNDAY).get("Plain Bar")), True)
    ts.save_chased(SUNDAY, "Plain Bar", False)
    ok("and taken off again", ts.load_chased(SUNDAY).get("Plain Bar"), None)

    shutil.rmtree(work, ignore_errors=True)
    print("\n%s" % ("ALL OK" if not problems else "%d FAILED: %s" % (len(problems), "; ".join(problems))))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
