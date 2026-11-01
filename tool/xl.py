"""Minimal read-only .xlsx reader using only the standard library."""
import re
import zipfile
import xml.etree.ElementTree as ET

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}
M = "{%s}" % NS["m"]


def col_to_idx(col):
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def idx_to_col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _color(el):
    if el is None:
        return None
    if el.get("rgb"):
        return el.get("rgb").upper()
    if el.get("theme") is not None:
        return "theme" + el.get("theme")
    if el.get("indexed"):
        return "idx" + el.get("indexed")
    return None


class Book:
    def __init__(self, path):
        # Everything is read up front and the file is closed again straight away: an open handle
        # would stop the next roster download from replacing the file.
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            self.shared = []
            if "xl/sharedStrings.xml" in names:
                root = ET.fromstring(z.read("xl/sharedStrings.xml"))
                for si in root.findall("m:si", NS):
                    self.shared.append("".join(t.text or "" for t in si.iter(M + "t")))
            wb = ET.fromstring(z.read("xl/workbook.xml"))
            rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            relmap = {r.get("Id"): r.get("Target") for r in rels.findall("pr:Relationship", NS)}
            self.sheets = []
            for s in wb.find("m:sheets", NS).findall("m:sheet", NS):
                target = relmap[s.get("{%s}id" % NS["r"])].lstrip("/")
                if not target.startswith("xl/"):
                    target = "xl/" + target
                self.sheets.append({"name": s.get("name"), "state": s.get("state", "visible"), "path": target})
            self._xml = {s["path"]: z.read(s["path"]) for s in self.sheets}
            self._xml["styles"] = z.read("xl/styles.xml")
        self._styles = None

    def cells(self, sheet):
        """Return {(row, col): (text, style_id, type)} for every non-empty cell."""
        root = ET.fromstring(self._xml[sheet["path"]])
        out = {}
        for c in root.iter(M + "c"):
            m = re.match(r"([A-Z]+)(\d+)", c.get("r"))
            col, row = col_to_idx(m.group(1)), int(m.group(2))
            t = c.get("t")
            v = c.find("m:v", NS)
            if t == "s" and v is not None:
                val = self.shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(M + "t"))
            elif v is not None:
                val = v.text
            else:
                val = None
            if val is not None and val != "":
                out[(row, col)] = (val, c.get("s"), t)
        return out

    def style(self, style_id):
        """Return {'fill', 'font', 'strike', 'bold'} for a cell style id."""
        if self._styles is None:
            st = ET.fromstring(self._xml["styles"])
            fonts = [{"strike": f.find("m:strike", NS) is not None, "bold": f.find("m:b", NS) is not None,
                      "font": _color(f.find("m:color", NS))} for f in st.find("m:fonts", NS)]
            fills = []
            for f in st.find("m:fills", NS):
                p = f.find("m:patternFill", NS)
                fills.append(None if p is None or p.get("patternType") in (None, "none") else _color(p.find("m:fgColor", NS)))
            self._styles = [dict(fonts[int(x.get("fontId", 0))], fill=fills[int(x.get("fillId", 0))])
                            for x in st.find("m:cellXfs", NS)]
        if style_id is None:
            return {"fill": None, "font": None, "strike": False, "bold": False}
        return self._styles[int(style_id)]
