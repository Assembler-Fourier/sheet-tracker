"""Throwaway: how much does the roster already say about when each venue closes?

Shift cells read like "20:00-close", "21:00-03-00", "17:00-22:00", "18:00-01:30". The ones with a real
end time tell us the venue's closing hour for free. This counts how far that gets us before any OCR.
"""
import collections
import datetime
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import timesheets as ts

# a shift cell with a real end: "21:00-03-00", "17:00-22:00", "18:00-01:30", "20-00 - 02.00"
END = re.compile(r"^\s*\d{1,2}\s*[:.\-]\s*\d{2}\s*(?:hrs?)?\s*-\s*(\d{1,2})\s*[:.\-]\s*(\d{2})")


def main():
    roster = ts.Roster()
    sunday = ts.sunday_of(datetime.date.today())
    ends = collections.defaultdict(collections.Counter)
    shifts = collections.Counter()
    closes = collections.Counter()
    for _ in range(20):
        try:
            venues, _, _ = roster.week(sunday)
        except ts.Problem:
            sunday -= datetime.timedelta(days=7)
            continue
        for v in venues:
            for p in v["people"]:
                text = p["shift"]
                if not text:
                    continue
                shifts[v["label"]] += 1
                m = END.match(text)
                if m:
                    ends[v["label"]][int(m.group(1)) * 60 + int(m.group(2))] += 1
                elif "close" in text.lower():
                    closes[v["label"]] += 1
        sunday -= datetime.timedelta(days=7)

    print("%-26s %6s %8s %8s   %s" % ("venue", "shifts", "with end", "'close'", "end times seen"))
    known = unknown = 0
    for label in sorted(shifts, key=lambda l: -shifts[l]):
        got = ends.get(label, collections.Counter())
        if got:
            known += 1
        else:
            unknown += 1
        top = "  ".join("%d:%02d x%d" % (t // 60, t % 60, n) for t, n in got.most_common(3))
        print("%-26s %6d %8d %8d   %s" % (label[:26], shifts[label], sum(got.values()),
                                          closes.get(label, 0), top or "-"))
    print("\n%d venues have at least one real end time on the roster, %d never do" % (known, unknown))


if __name__ == "__main__":
    main()
