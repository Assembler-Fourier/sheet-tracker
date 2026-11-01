"""Builds a made-up roster .xlsx, so the awkward cases can be tested without waiting for them to happen.

The real roster only shows what it happens to contain this month. This writes one by hand - same shapes,
same fills - so a test can set up a venue with nobody on it, a note sitting in the venue column, a name
struck through, a venue label typed into a day column, a duplicated date, and so on, and then check the
tool reads every one of them the way it should.

Standard library only: an .xlsx is a zip of XML, and xl.py reads only the few parts written here.
"""
import datetime
import os
import zipfile

EPOCH = datetime.date(1899, 12, 30)
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# style ids written into cells: 1 venue label (black), 2 a name (green), 3 a time (white),
# 4 a name struck through, 5 a note in the venue column (white, not black - so not a venue)
VENUE, NAME, TIME, STRUCK, NOTE = 1, 2, 3, 4, 5

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

WORKBOOK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>"""

WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2"><font><sz val="11"/></font><font><strike/><sz val="11"/></font></fonts>
<fills count="5">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF000000"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF92D050"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFFFFF"/></patternFill></fill>
</fills>
<borders count="1"><border/></borders>
<cellStyleXfs count="1"><xf/></cellStyleXfs>
<cellXfs count="6">
<xf fontId="0" fillId="0"/>
<xf fontId="0" fillId="2" applyFill="1"/>
<xf fontId="0" fillId="3" applyFill="1"/>
<xf fontId="0" fillId="4" applyFill="1"/>
<xf fontId="1" fillId="3" applyFill="1" applyFont="1"/>
<xf fontId="0" fillId="4" applyFill="1"/>
</cellXfs></styleSheet>"""


def col_name(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class FakeRoster:
    """Lay out weeks the way the real sheet does: a label column then Mon..Sun, eight columns to a week."""

    def __init__(self):
        self.cells = {}                               # (row, col) -> (text, style, is_number)
        self.week_at = {}                             # sunday -> its label column

    def put(self, row, col, text, style=None, number=False):
        self.cells[(row, col)] = (str(text), style, number)

    def week(self, sunday, label_col, header_row=1, skip_days=(), twice=None):
        """Write a week's header block. skip_days leaves a date out of the header row; twice repeats one."""
        monday = sunday - datetime.timedelta(days=6)
        self.week_at[sunday] = label_col
        for i in range(7):
            day = monday + datetime.timedelta(days=i)
            col = label_col + 1 + i
            self.put(header_row, col, WEEKDAYS[i])
            if i not in skip_days:
                self.put(header_row + 1, col, (day - EPOCH).days, number=True)
        if twice is not None:                         # the same date in two columns, as Feb 2026 had
            self.put(header_row + 1, label_col + 1 + twice[0], (monday + datetime.timedelta(days=twice[1])
                                                                - EPOCH).days, number=True)

    def venue(self, row, label_col, label, days, style=VENUE):
        """A venue and who is on it. days: {weekday: [(time, name) or (time, name, STRUCK)]}."""
        self.put(row, label_col, label, style)
        at = {}
        for i in sorted(days):
            at[i] = row + 1
        for i in sorted(days):
            col = label_col + 1 + i
            r = row + 1
            for shift in days[i]:
                time, name = shift[0], shift[1]
                how = shift[2] if len(shift) > 2 else NAME
                self.put(r, col, time, TIME)
                self.put(r + 1, col, name, how)
                r += 2
        return row + 1 + 2 * max((len(v) for v in days.values()), default=0)

    def note(self, row, label_col, text):
        """Text in the venue column that is NOT a venue - white filled, like the roster's IMPORTANT NOTE."""
        self.put(row, label_col, text, NOTE)

    def save(self, path):
        shared, order = {}, []

        def share(text):
            if text not in shared:
                shared[text] = len(order)
                order.append(text)
            return shared[text]

        rows = {}
        for (r, c), (text, style, number) in sorted(self.cells.items()):
            bits = ' s="%d"' % style if style else ""
            if number:
                cell = '<c r="%s%d"%s><v>%s</v></c>' % (col_name(c), r, bits, text)
            else:
                cell = '<c r="%s%d"%s t="s"><v>%d</v></c>' % (col_name(c), r, bits, share(text))
            rows.setdefault(r, []).append(cell)
        body = "".join("<row r='%d'>%s</row>" % (r, "".join(cs)) for r, cs in sorted(rows.items()))
        sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                 '<sheetData>%s</sheetData></worksheet>' % body)
        strings = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="%d" uniqueCount="%d">'
                   '%s</sst>' % (len(order), len(order),
                                 "".join("<si><t>%s</t></si>" % _esc(s) for s in order)))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", CONTENT_TYPES)
            z.writestr("_rels/.rels", ROOT_RELS)
            z.writestr("xl/workbook.xml", WORKBOOK)
            z.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
            z.writestr("xl/styles.xml", STYLES)
            z.writestr("xl/sharedStrings.xml", strings)
            z.writestr("xl/worksheets/sheet1.xml", sheet)
        return path


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
