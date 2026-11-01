"""Run every week of a year through the check and report anything odd.

    python sweep.py           2026
    python sweep.py 2025

Reads only: the saved roster and the timesheet folders. Writes nothing. Use it after changing how the
roster is read, to see that no week has quietly started coming out wrong.
"""
import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import timesheets as ts  # noqa: E402


def main():
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    roster = ts.Roster()
    day = datetime.date(year, 1, 1)
    sundays = []
    while day.year == year:
        if day.weekday() == 6:
            sundays.append(day)
        day += datetime.timedelta(days=1)

    folders = ts.known_folders()
    print("%d Sundays in %d, %d timesheet folders in reach\n" % (len(sundays), year, len(folders)))
    bad = counted = 0
    for sunday in sundays:
        try:
            r = ts.check(sunday, roster)
        except ts.Problem as e:
            print("  %s  no check: %s" % (sunday.strftime("%d.%m.%y"), e))
            continue
        except Exception as e:
            bad += 1
            print("  %s  BROKE: %s: %s" % (sunday.strftime("%d.%m.%y"), type(e).__name__, e))
            continue
        total, got, spare = len(r["venues"]), len(r["in"]), r["spare"]
        if not r["folder"]:
            print("  %s  %2d venues, no folder" % (sunday.strftime("%d.%m.%y"), total))
            continue
        counted += 1
        flags = []
        if spare:
            flags.append("UNMATCHED: " + ", ".join("%s (%s)" % (f["name"], f["how"]) for f in spare))
        if got > total:
            flags.append("more venues in than rostered?")
        if total and got == 0 and r["files"]:
            flags.append("a folder with sheets but nothing matched")
        print("  %s  %2d rostered  %2d in  %2d missing  %3d files%s"
              % (sunday.strftime("%d.%m.%y"), total, got, total - got, len(r["files"]),
                 ("   " + "; ".join(flags)) if flags else ""))
    print("\n%d weeks with a folder checked, %d broke" % (counted, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
