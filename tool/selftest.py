"""Checks for the timesheet tool. Run it after changing anything:

    python selftest.py              core only (no window, no download)
    python selftest.py --window     also starts the window off-screen and drives it

Nothing is written outside this tool's own folder, the roster is not re-downloaded, and the window
is parked off-screen so it never appears on the user's display. The expected numbers below come
from four weeks whose folders were checked by hand in October 2026.
"""
import datetime
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import timesheets as ts  # noqa: E402

# week-ending Sunday -> (venues rostered, venues with a sheet in, names expected missing)
# The roster is a live sheet and old weeks get deleted from it - February 2026 was there in October and
# gone by the end of the month - so a week the roster no longer reaches is SKIPPED, not failed. Only a
# week it still covers has to come out right.
WEEKS = {
    datetime.date(2026, 9, 13): (36, 36, []),
    datetime.date(2026, 9, 20): (36, 36, []),
    datetime.date(2026, 9, 27): (36, 35, ["Fogartys"]),
    datetime.date(2026, 10, 4): (39, 38, ["Fogartys"]),
}
CHECKED_WEEK = datetime.date(2026, 10, 4)               # the week checked name by name
EMPTY_WEEK = datetime.date(2026, 10, 11)
if ts.DEMO:
    # The demo roster's dates move forward with today (demo/make_demo.py), so its weeks are counted back from
    # the current one. Weeks 4-7 back are the template's 4 Oct - 13 Sep. Their sheets are made-up but fixed.
    # weeks back from the current one -> (venues rostered, sheets in, names missing)
    DEMO_WEEKS = {
        7: (36, 34, ["SEAVIEW", "12 Harbour st"]),
        6: (36, 35, ["ELMHURST"]),
        5: (36, 35, ["MEADOWBANK"]),
        4: (39, 38, ["Glenmore"]),
    }
    _this = ts.sunday_of(datetime.date.today())
    WEEKS = {_this - datetime.timedelta(days=7 * n): want for n, want in DEMO_WEEKS.items()}
    CHECKED_WEEK = _this - datetime.timedelta(days=7 * 4)
    EMPTY_WEEK = _this - datetime.timedelta(days=7 * 3)
fails = []


def ok(what, got, want):
    if got == want:
        print("  ok    %-52s %s" % (what, got))
    else:
        print("  FAIL  %-52s got %r, wanted %r" % (what, got, want))
        fails.append(what)


def test_weeks():
    """A week is Monday to Sunday, and the names of the folders follow the Sunday."""
    mon, sat, sun = datetime.date(2026, 10, 5), datetime.date(2026, 10, 10), datetime.date(2026, 10, 11)
    ok("Sunday of a Monday", ts.sunday_of(mon), sun)
    ok("Sunday of a Sunday", ts.sunday_of(sun), sun)
    ok("the week runs Mon-Sun", (ts.week_dates(sun)[0], ts.week_dates(sun)[-1]), (mon, sun))
    ok("the name of the week", (ts.week_name(sun, mon), ts.week_name(datetime.date(2026, 10, 4), mon)),
       ("This week", "Last week"))
    ok("Monday opens on last week, the one being chased", ts.default_week(mon), datetime.date(2026, 10, 4))
    ok("Saturday opens on the week being collected", ts.default_week(sat), sun)
    ok("so does a Wednesday", ts.default_week(datetime.date(2026, 10, 7)), sun)
    ok("an empty folder is not 'collected'", ts.collected(sun, places=[tempfile.gettempdir()]), False)
    ok("'last' from a Monday", ts.pick_week("last", mon), datetime.date(2026, 10, 4))
    ok("'this' from a Saturday", ts.pick_week("this", sat), sun)
    ok("'next' from a Friday", ts.pick_week("next", datetime.date(2026, 10, 9)), datetime.date(2026, 10, 18))
    ok("a date inside the week", ts.pick_week("30/09", mon), datetime.date(2026, 10, 4))
    ok("folder name", ts.folder_name(datetime.date(2026, 10, 4)), "Timesheets 04.10.26")
    # the week's folder is made once and never again
    shed, far = tempfile.mkdtemp(prefix="ts-check-"), datetime.date(2027, 3, 7)
    ok("making the week's folder", ts.make_week_folder(far, where=shed)[1], True)
    ok("...and not making it twice", ts.make_week_folder(far, where=shed)[1], False)
    ok("...it is really there", os.path.isdir(os.path.join(shed, "Timesheets 07.03.27")), True)
    for name, want in (("Timesheets 04.10.26", datetime.date(2026, 10, 4)),
                       ("Timesheets 5.04.26", datetime.date(2026, 4, 5)),
                       ("Timesheet 09.02.25", datetime.date(2025, 2, 9)),
                       ("Timesheets 02.11.2025", datetime.date(2025, 11, 2)),
                       ("timesheets w.e. 20.04.25", datetime.date(2025, 4, 20)),
                       ("Timesheets", None), ("rosters", None), ("Timesheets 32.01.26", None)):
        ok("folder %r" % name, ts.folder_date(name), want)


def test_names():
    """Every spelling of a file name that has turned up, against the venue it belongs to."""
    labels = ["WESTGATE", "HILLCREST", "BROOKVALE", "QuickStop Elmfield", "Kilcarran", "Portlane", "Brennans Mill st",
              "Elysium Ferncourt", "Orchard House", "O'Garvey", "12 Harbour st", "The Meadows", "Town Ballyrock",
              "Loft", "Lido", "The Old Haunt", "Keystone", "Fogartys", "The Jug", "Lucky Bingo", "K9 / Red Door",
              "The Wharf", "Perch Kilcarran", "Bullseye Club Darts / Pats", "Nona's", "Quinlans", "Hanlons"]
    venues = [{"label": l, "aliases": ts.aliases_for(l)} for l in labels]
    cases = {
        "Voltmart Westgate": "WESTGATE", "WESTGATE": "WESTGATE", "Voltmart hillcrest": "HILLCREST",
        "Voltmart Brookvale": "BROOKVALE", "QuickStop": "QuickStop Elmfield", "Kilcarran": "Kilcarran",
        "Kilcarran Business Campus": "Kilcarran", "Portlane": "Portlane", "Portlane Dock view": "Portlane",
        "Dabrowski's": "Brennans Mill st", "Brennans": "Brennans Mill st", "Elysium": "Elysium Ferncourt",
        "Orchard House": "Orchard House", "Loft": "Loft", "the lido": "Lido", "The Old Haunt": "The Old Haunt",
        "O’Garvey": "O'Garvey", "o'garveys": "O'Garvey", "O'Garvy bar": "O'Garvey",
        "0garvy bar": "O'Garvey", "12 Harbour St": "12 Harbour st", "12 Harbour Street (2)": "12 Harbour st",
        "Meadows": "The Meadows", "Town": "Town Ballyrock", "Town Ballyrock": "Town Ballyrock",
        "Keystone": "Keystone", "Fogartys timesheet": "Fogartys", "The Jug": "The Jug", "Lucky Bingo": "Lucky Bingo",
        "K9 (1)": "K9 / Red Door", "K9(2)": "K9 / Red Door", "K9 Part 4": "K9 / Red Door",
        "K9 - 1": "K9 / Red Door", "Red Door": "K9 / Red Door", "Wharf": "The Wharf",
        "Perch": "Perch Kilcarran", "Perch - 3": "Perch Kilcarran", "Perch (1)": "Perch Kilcarran",
        "Bullseye Club": "Bullseye Club Darts / Pats", "Nona’s": "Nona's", "Nonas": "Nona's",
        "Quinlans": "Quinlans", "Hanlons": "Hanlons",
        "12": "12 Harbour st", "voltmartkilmoran2": None,    # KILMORAN is not in this short list
        "Lucerne (missing mon to thu)": None,          # nor is Lucerne
        "IMG_20261004_193245": None, "": None,
        # a short alias must be the whole name or a whole word: "12" may not come out of a camera's number
        "IMG_3125": None, "DSC_0012": None, "20261004_121245": None,
    }
    for name, want in cases.items():
        got, why = ts.match_file(name, venues, taught={})
        ok("%r -> %s" % (name, want or "nothing"), got, want)
    # a name taught by hand wins, and does not need to look like the venue at all
    got, why = ts.match_file("sheet from the lads", venues, taught={ts.canon("sheet from the lads"): "Fogartys"})
    ok("a taught name", (got, why), ("Fogartys", "taught"))


def test_folders():
    """The real weeks, against the real folders."""
    if not os.path.exists(ts.ROSTER_PATH):
        print("  SKIP  no saved roster - run timesheets.py once first")
        return
    roster = ts.Roster()
    for sunday, (total, got, missing) in sorted(WEEKS.items()):
        try:
            r = ts.check(sunday, roster)
        except ts.Problem as e:
            print("  SKIP  week ending %s - the roster no longer reaches it (%s)"
                  % (sunday.strftime("%d.%m.%y"), e))
            continue
        where = "week ending %s" % sunday.strftime("%d.%m.%y")
        ok("%s: venues rostered" % where, len(r["venues"]), total)
        ok("%s: sheets in" % where, len(r["in"]), got)
        ok("%s: missing" % where, [v["label"] for v in r["missing"]], missing)
        ok("%s: files matched to no venue" % where, [f["name"] for f in r["spare"]], [])
        ok("%s: every file used once" % where,
           sum(len(v["files"]) for v in r["venues"]) + len(r["spare"]), len(r["files"]))
        if sunday == CHECKED_WEEK:                       # the week checked name by name
            ok("%s: Lido is in the list" % where, "Lido" in [v["label"] for v in r["venues"]], True)
            ok("%s: the control room is in the list" % where, "Kilcarran" in [v["label"] for v in r["venues"]], True)
        else:
            ok("%s: Lido not rostered, so not expected" % where,
               "Lido" in [v["label"] for v in r["venues"]], False)
        # a white cell in the venue column is a note, never a venue (the "IMPORTANT NOTE" that once
        # took Perch Kilcarran off the list and kept its people for itself)
        ok("%s: no note read as a venue" % where,
           [v["label"] for v in r["venues"] if "NOTE" in v["label"].upper()], [])
    nothing = ts.check(EMPTY_WEEK, roster, places=[tempfile.gettempdir()])
    ok("a week with no folder: none found", nothing["folder"], None)
    ok("a week with no folder: all missing", len(nothing["missing"]), len(nothing["venues"]))


def rows_on_show(app):
    """How many venue rows the list is actually showing - rules and spacers do not count.

    This is the check that version 2 needed and did not have: it said "Saturday 11" and drew ten.
    """
    return sum(1 for w in app.listing.inner.winfo_children() if getattr(w, "venue_row", False))


def test_window():
    """Start the window off-screen, let it read the roster, and look at what it put on the tables."""
    os.environ.update(CTS_GEOMETRY="1180x760+-4000+-4000", CTS_NO_DOWNLOAD="1", CTS_NOOPEN="1",
                      CTS_AUTORUN=CHECKED_WEEK.strftime("%d/%m/%Y"))
    import tkinter as tk
    spec = importlib.util.spec_from_file_location("app_under_test", os.path.join(HERE, "app.pyw"))
    app_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app_mod)
    root = tk.Tk()
    app = app_mod.App(root)
    seen = {}

    def look():
        if app.report is None:                        # the roster thread has not finished yet
            root.after(200, look)
            return
        seen["missing rows"] = [v["label"] for v in app.report["missing"]]
        app.show_view("all")
        root.update_idletasks()
        seen["venue rows"] = rows_on_show(app)
        seen["headline"] = (app.big.cget("text"), app.headline.cget("text"))
        seen["status"] = app.status.get()
        # every filter must draw exactly as many rows as its chip claims - the version 2 bug was a
        # heading that said 11 above a list of 10, with no way to reach the eleventh
        bad = []
        for key in list(app.tabs):
            app.show_view(key)
            root.update_idletasks()
            claimed = int(app.tabs[key].count.cget("text"))
            drawn = rows_on_show(app)
            if claimed != drawn:
                bad.append("%s: tab says %d, list draws %d" % (key, claimed, drawn))
        seen["filters agree with the list"] = bad
        app.show_view("all")
        app.step(-1)                                  # a week back, then forward again
        seen["stepped back"] = app.week_label.cget("text")
        app.step(1)
        app.go("next")
        seen["next week folder"] = app.report["folder"]
        app.go("last")
        app.save_list()
        seen["after save"] = app.status.get()
        # never copy_missing(): the user's clipboard is his. And check the text against whatever week is
        # actually on show - this used to assert "Fogartys (Thu-Sat)", which only held while last week
        # happened to be a week Fogartys was late. It passed by luck and failed the morning it ran over.
        seen["missing text"] = app.missing_text()
        seen["should be named"] = ["%s (%s)" % (v["label"], v["day_text"]) for v in app.report["missing"]]
        app.open_folder()                             # CTS_NOOPEN: must do nothing at all
        root.after(50, root.destroy)

    root.after(300, look)
    root.mainloop()
    ok("window: missing list", seen.get("missing rows"), [WEEKS[CHECKED_WEEK][2][0]] if ts.DEMO else ["Fogartys"])
    ok("window: a row per venue, none left out", seen.get("venue rows"), 39)
    ok("window: every tab draws what it claims", seen.get("filters agree with the list"), [])
    ok("window: the headline leads with the one still out", seen.get("headline"), ("1", "still to come in"))
    ok("window: a week back names the week", "Mon 21 - Sun 27 Sep 2026" in (seen.get("stepped back") or ""), True)
    ok("window: next week has no folder", seen.get("next week folder"), None)
    ok("window: saving says where it went", "saved:" in (seen.get("after save") or ""), True)
    want, text = seen.get("should be named") or [], seen.get("missing text") or ""
    ok("window: the list to send names every venue still out",
       [line for line in want if line not in text], [])
    ok("window: ...and says which week it is for", "Timesheets still needed for" in text or not want, True)
    ok("window: the status line", "39 rostered, 38 in, 1 still to come" in (seen.get("status") or ""), True)


def main():
    print("timesheet tool - checks")
    print("\nthe week")
    test_weeks()
    print("\nfile names")
    test_names()
    print("\nthe real weeks")
    test_folders()
    if "--window" in sys.argv:
        print("\nthe window (off-screen)")
        test_window()
    print("\n%s" % ("ALL OK" if not fails else "%d FAILED: %s" % (len(fails), "; ".join(fails))))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

