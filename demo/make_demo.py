"""Demo data for Sheet Tracker: a made-up roster and a made-up Desktop of timesheet photos.

roster-template.xlsx is a real roster layout with every person, venue and note replaced by invented ones and
all cell comments removed. build() moves its dates forward so its newest week is always the current week,
then fills a demo Desktop with timesheet "photos" (generated placeholder images) for most venues, so the
window has something real-looking to show: some weeks complete, this week still coming in.

    python demo/make_demo.py            rebuild the demo roster and Desktop now
"""
import datetime
import os
import random
import re
import struct
import sys
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "roster-template.xlsx")
TEMPLATE_SUNDAY = datetime.date(2026, 11, 1)      # the week the template was taken in
EPOCH = datetime.date(1899, 12, 30)


def sunday_of(d):
    return d + datetime.timedelta(days=6 - d.weekday())


def shifted_roster(dest, today):
    """Copy the template with every date moved on by whole weeks, so weekdays stay put."""
    shift = (sunday_of(today) - TEMPLATE_SUNDAY).days
    lo, hi = (datetime.date(2020, 1, 1) - EPOCH).days, (datetime.date(2035, 1, 1) - EPOCH).days

    def move(g):
        n = float(g.group(2))
        if lo <= n <= hi and n == int(n):
            return "%s%d%s" % (g.group(1), int(n) + shift, g.group(3))
        return g.group(0)

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with zipfile.ZipFile(TEMPLATE) as zin, zipfile.ZipFile(dest + ".part", "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.startswith("xl/worksheets/sheet"):
                text = data.decode("utf-8")
                # only number cells (no t="s"); their value is a date serial when it is a whole number in range
                text = re.sub(r'(<c r="[A-Z]+\d+"(?: s="\d+")?><v>)([\d.]+)(</v>)', move, text)
                data = text.encode("utf-8")
            zout.writestr(info, data)
    os.replace(dest + ".part", dest)
    return shift


def png(width=360, height=500, seed=0):
    """A grey placeholder 'photo of a timesheet': a header band and ruled rows. Pure stdlib."""
    rnd = random.Random(seed)
    tint = rnd.randint(228, 246)
    rows = []
    for y in range(height):
        line = bytearray([0])
        for x in range(width):
            v = tint
            if 20 < y < 60:
                v = 70
            elif y > 80 and (y - 80) % 28 == 0 and 16 < x < width - 16:
                v = 150
            elif y > 80 and x in (90, 180, 270) and y < height - 30:
                v = 180
            line += bytes((v, v, v))
        rows.append(bytes(line))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def file_names(label, rnd):
    base = re.sub(r"[/()]", " ", label)
    base = re.sub(r"\s+", " ", base).strip()
    style = rnd.random()
    if style < 0.45:
        return [base + ".png"]
    if style < 0.7:
        return ["%s timesheet.png" % base]
    if style < 0.85:
        return ["%s (1).png" % base, "%s (2).png" % base]
    return ["%s %s.png" % (base.lower(), "signed")]


def populate(desktop, roster_path, today):
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tool"))
    import timesheets as ts
    roster = ts.Roster(roster_path)
    this = sunday_of(today)
    image = png()
    for back in range(0, 10):
        sunday = this - datetime.timedelta(days=7 * back)
        if back <= 1:
            folder = os.path.join(desktop, ts.folder_name(sunday))
        else:
            folder = os.path.join(desktop, "Important DATA", "Timesheets", str(sunday.year), ts.folder_name(sunday))
        if os.path.isdir(folder):
            continue
        try:
            venues, _idle, _notes = roster.week(sunday)
        except ts.Problem:
            continue
        rnd = random.Random(1000 + back)          # the same demo every week, whatever today's date
        share = {0: 0.55, 1: 0.86}.get(back, 0.97)
        os.makedirs(folder, exist_ok=True)
        monday = sunday - datetime.timedelta(days=6)
        for v in venues:
            last_day = max(v["days"]) if v.get("days") else 6
            arrives = monday + datetime.timedelta(days=last_day, hours=0)
            if back == 0 and arrives > today:
                continue                      # its week is not over yet
            if rnd.random() > share:
                continue                      # still missing - the demo's chase list
            for name in file_names(v["label"], rnd):
                path = os.path.join(folder, name)
                with open(path, "wb") as f:
                    f.write(image)
                when = datetime.datetime.combine(arrives, datetime.time(rnd.randint(0, 23), rnd.randint(0, 59)))
                when += datetime.timedelta(hours=rnd.choice([3, 6, 10, 14, 26]))
                when = min(when, datetime.datetime.now())
                os.utime(path, (when.timestamp(), when.timestamp()))


def build(dest, desktop, today=None):
    today = today or datetime.date.today()
    stamp = dest + ".demo"
    want = str(sunday_of(today))
    have = open(stamp).read().strip() if os.path.exists(stamp) else ""
    if have != want or not os.path.exists(dest):
        shifted_roster(dest, today)
        with open(stamp, "w") as f:
            f.write(want)
    populate(desktop, dest, today)
    return dest


if __name__ == "__main__":
    root = os.path.dirname(HERE)
    print(build(os.path.join(root, "tool", "cache", "roster.xlsx"), os.path.join(HERE, "Desktop")))
