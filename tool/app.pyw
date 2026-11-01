"""Window for the weekly timesheet check. Opened by the desktop shortcut or "Sheet Tracker.bat".

Version 4. The window answers one question the moment it opens: **what do I have to collect tonight?**
On a Saturday that is the venues shut on Sunday, on a Sunday the rest, and on a weekday it is everything
still outstanding. That answer is the biggest thing on the screen; everything else - the other nights,
what is already in, the whole week - is a tab away. One list is on show at a time, so no venue is ever
printed twice and no count can be larger than the rows under it.

All the roster reading, folder scanning and name matching is done by timesheets.py; this file is only the
window. It starts no other program - the only things it ever opens are Explorer on the week's folder, and
one timesheet in the user's own viewer, when he presses for them.
"""
import datetime
import json
import os
import queue
import sys
import threading
import traceback
import tkinter as tk
from tkinter import font as tkfont, messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import timesheets as ts  # noqa: E402

SETTINGS = os.path.join(ts.CACHE, "settings.json")
ICON = os.path.join(HERE, "app.ico")
VERSION = "4.0"
ROSTER_FRESH = 300                         # seconds a downloaded roster is reused before fetching it again
WATCH_MS = 4000                            # how often the week's folder is looked at for new sheets
# How often "not on until Sun 19:00 (in 31 min)" is worked out again. It used to be 45 seconds and it
# used to cost a whole re-check; the user watched the countdown sit still and said so. ts.retime() is
# about a third of a millisecond for a full week, so there is no reason not to run it every few seconds
# and let the minutes tick down the way a clock does.
RETIME_S = 5
FIND_S = 20                                # how often to go looking for a folder that is not there yet
FONT, FONT_BOLD = "Segoe UI", "Segoe UI Semibold"
ICON_FONT = "Segoe MDL2 Assets"            # Windows' own icon font; without it the buttons are simply text

# Two palettes, the same shapes in both. One colour language: green is in hand, amber is Saturday (the
# deadline), blue is Sunday, red is a night already gone. Nothing else may use those colours.
# Every widget reads these names when it is made, so changing theme rebuilds the window (App.flip_theme).
LIGHT = dict(
    PAPER="#ffffff", SUNK="#f5f6f8", LINE="#e6e8ec", SOFT="#eff1f4", BAND="#f7f8fa",
    INK="#0f1623", BODY="#434c5a", MUTED="#6b7483", FAINT="#99a0ad",
    BLUE="#2563eb", BLUE_DOWN="#1d4ed8", BLUE_TINT="#eaf0fd", BLUE_EDGE="#bdd0f8",
    GREEN="#15803d", GREEN_TINT="#e8f6ed", GREEN_EDGE="#c2e4ce",
    RED="#be1b1b", RED_TINT="#fdedec", RED_EDGE="#f4c7c4",
    AMBER="#b45309", AMBER_TINT="#fdf3e2", THUMB="#c6ccd5", THUMB_ON="#9aa3b0")
DARK = dict(
    PAPER="#171a20", SUNK="#12151a", LINE="#282d36", SOFT="#20242c", BAND="#1d2128",
    INK="#f0f3f8", BODY="#c6ccd7", MUTED="#8d96a5", FAINT="#6e7786",
    BLUE="#5d97f7", BLUE_DOWN="#8fb6fb", BLUE_TINT="#1a2740", BLUE_EDGE="#33507e",
    GREEN="#4ec77f", GREEN_TINT="#15281d", GREEN_EDGE="#2c5537",
    RED="#f4756f", RED_TINT="#2c191a", RED_EDGE="#5a2e2f",
    AMBER="#e8b25c", AMBER_TINT="#2a2216", THUMB="#3b424f", THUMB_ON="#4f5968")
globals().update(LIGHT)

ICONS = {"folder": "", "refresh": "", "check": "", "warning": "", "info": "",
         "prev": "", "next": "", "save": "", "copy": "", "add": "",
         "link": "", "cancel": "", "sync": "", "moon": "", "sun": "",
         "open": "", "more": ""}


def set_theme(name):
    """Put one palette's colours into the module's names. Widgets made after this use them."""
    globals().update(DARK if name == "dark" else LIGHT)


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8-sig") as f:    # -sig: a byte-order mark must not lose the settings
            got = json.load(f)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data):
    try:
        os.makedirs(ts.CACHE, exist_ok=True)
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def pointer_inside(widget):
    """Is the mouse over this widget or anything inside it? (Moving onto a child must not count as leaving.)"""
    try:
        under = widget.winfo_containing(*widget.winfo_pointerxy())
    except tk.TclError:
        return False
    while under is not None:
        if under is widget:
            return True
        under = under.master
    return False


def rule(parent, back=None):
    tk.Frame(parent, bg=LINE, height=1).pack(fill="x", pady=0) if back is None else None


class Button(tk.Frame):
    """A flat button. kind: 'primary' (filled blue), 'plain' (hairline edge) or 'quiet' (bare).
    The looks are read when the button is made, so they follow whichever theme is on."""

    @staticmethod
    def looks(kind):
        #       back   text  icon  edge  hover back  hover edge  off back  off text
        return {"primary": (BLUE, PAPER, PAPER, BLUE, BLUE_DOWN, BLUE_DOWN, BLUE_EDGE, PAPER),
                "plain": (PAPER, INK, MUTED, LINE, SOFT, BLUE_EDGE, SOFT, FAINT),
                "quiet": (None, BODY, MUTED, None, SOFT, SOFT, None, FAINT)}[kind]

    def __init__(self, parent, text, command, icon=None, kind="plain", size=10, pad=(12, 7), back=None):
        back = PAPER if back is None else back
        base, self.fg, self.icon_fg, edge, self.hover_bg, self.hover_edge, off, self.off_fg = self.looks(kind)
        self.bg, self.edge, self.off_bg = base or back, edge or back, off or back
        self.off_edge = SOFT if kind == "plain" else self.off_bg
        self.command, self.enabled = command, True
        super().__init__(parent, bg=self.bg, highlightthickness=1, highlightbackground=self.edge, cursor="hand2")
        self.inner = tk.Frame(self, bg=self.bg)
        self.inner.pack(padx=pad[0], pady=pad[1])
        self.glyph = None
        if ICONS.get(icon):
            self.glyph = tk.Label(self.inner, text=ICONS[icon], font=(ICON_FONT, size), bg=self.bg, fg=self.icon_fg)
            self.glyph.pack(side="left", padx=(0, 8 if text else 0))
        self.label = tk.Label(self.inner, text=text, font=(FONT_BOLD if kind == "primary" else FONT, size),
                              bg=self.bg, fg=self.fg)
        if text:
            self.label.pack(side="left")
        for w in [self, self.inner, self.label] + ([self.glyph] if self.glyph else []):
            w.bind("<Button-1>", lambda e: self.command() if self.enabled else None)
            w.bind("<Enter>", lambda e: self.paint(True))
            w.bind("<Leave>", lambda e: self.paint(pointer_inside(self)))

    def configure(self, cnf=None, **kw):
        if isinstance(cnf, dict):
            kw, cnf = dict(cnf, **kw), None
        mine = "state" in kw or "text" in kw
        if "state" in kw:
            self.enabled = kw.pop("state") != "disabled"
            self.paint()
        if "text" in kw:
            self.label.configure(text=kw.pop("text"))
        return None if mine and not kw else super().configure(cnf, **kw)

    config = configure

    def paint(self, hover=False):
        if not self.enabled:
            bg, edge, fg, icon_fg = self.off_bg, self.off_edge, self.off_fg, self.off_fg
        elif hover:
            bg, edge, fg, icon_fg = self.hover_bg, self.hover_edge, self.fg, self.icon_fg
        else:
            bg, edge, fg, icon_fg = self.bg, self.edge, self.fg, self.icon_fg
        self.configure(bg=bg, highlightbackground=edge)
        self.inner.configure(bg=bg)
        self.label.configure(bg=bg, fg=fg)
        if self.glyph:
            self.glyph.configure(bg=bg, fg=icon_fg)


class Tab(tk.Frame):
    """One view of the week: a name, its count, and a line under it when it is the one on show."""

    def __init__(self, parent, text, command, tone=None, back=None):
        back = PAPER if back is None else back
        super().__init__(parent, bg=back, cursor="hand2")
        self.chosen, self.tone, self.back, self.empty = False, tone, back, False
        row = tk.Frame(self, bg=back)
        row.pack(padx=2, pady=(2, 7))
        self.label = tk.Label(row, text=text, font=(FONT, 11), bg=back, fg=BODY)
        self.label.pack(side="left")
        self.count = tk.Label(row, text="", font=(FONT_BOLD, 11), bg=back, fg=MUTED)
        self.count.pack(side="left", padx=(8, 0))
        self.bar = tk.Frame(self, bg=back, height=3)
        self.bar.pack(fill="x")
        self.parts = [row, self.label, self.count]
        for w in [self] + self.parts:
            w.bind("<Button-1>", lambda e: command())
            w.bind("<Enter>", lambda e: self.paint(True))
            w.bind("<Leave>", lambda e: self.paint(pointer_inside(self)))

    def show(self, n):
        if self.count.cget("text") == str(n):     # the heartbeat comes through here several times a
            return                                # minute; don't repaint a number that has not moved
        self.count.configure(text=str(n))
        self.empty = not n
        self.paint(pointer_inside(self))

    def paint(self, hover=False):
        tone = self.tone or BLUE
        on = self.chosen
        self.bar.configure(bg=tone if on else (LINE if hover else self.back))
        quiet = self.empty and not on
        self.label.configure(font=(FONT_BOLD if on else FONT, 11),
                             fg=FAINT if quiet else (INK if on or hover else BODY))
        self.count.configure(font=(FONT_BOLD, 11), fg=FAINT if quiet else (tone if on else MUTED))

    def choose(self, on):
        self.chosen = on
        self.paint()


class Pill(tk.Frame):
    """One week in the switcher: small, with a dot when it is still waiting on sheets."""

    def __init__(self, parent, text, command, back=None):
        back = PAPER if back is None else back
        super().__init__(parent, bg=back, highlightthickness=1, highlightbackground=LINE, cursor="hand2")
        self.chosen, self.back = False, back
        row = tk.Frame(self, bg=back)
        row.pack(padx=11, pady=5)
        self.label = tk.Label(row, text=text, font=(FONT, 9), bg=back, fg=BODY)
        self.label.pack(side="left")
        self.badge = tk.Label(row, text="", font=(FONT_BOLD, 8), bg=back, fg=RED)
        self.parts = [row, self.label]
        for w in [self] + self.parts + [self.badge]:
            w.bind("<Button-1>", lambda e: command())
            w.bind("<Enter>", lambda e: self.paint(True))
            w.bind("<Leave>", lambda e: self.paint(pointer_inside(self)))

    def show(self, missing, done):
        if (missing, done) == getattr(self, "showing", None):
            return                                # nothing has moved: leave the badge alone
        self.showing = (missing, done)
        if missing:
            self.badge.configure(text=str(missing), fg=RED)
            self.badge.pack(side="left", padx=(7, 0))
        elif done:
            self.badge.configure(text=ICONS.get("check", "ok"), fg=GREEN,
                                 font=(ICON_FONT if ICONS else FONT_BOLD, 8))
            self.badge.pack(side="left", padx=(7, 0))
        else:
            self.badge.pack_forget()

    def paint(self, hover=False):
        bg = BLUE_TINT if self.chosen else SOFT if hover else self.back
        self.configure(bg=bg, highlightbackground=BLUE if self.chosen else BLUE_EDGE if hover else LINE)
        for w in self.parts + [self.badge]:
            w.configure(bg=bg)
        self.label.configure(fg=BLUE_DOWN if self.chosen else BODY,
                             font=(FONT_BOLD if self.chosen else FONT, 9))

    def choose(self, on):
        self.chosen = on
        self.paint()


class Bar(tk.Canvas):
    """The week in one line: what is in, then what is left in the order it has to be collected."""

    def __init__(self, parent, height=8, back=None):
        super().__init__(parent, height=height, bg=back or PAPER, highlightthickness=0)
        self.parts = []
        self.bind("<Configure>", lambda e: self.draw())

    def show(self, parts):
        self.parts = [(n, c) for n, c in parts if n]
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        total = sum(n for n, _ in self.parts)
        if w < 2:
            return
        self.create_rectangle(0, 0, w, h, fill=SOFT, outline="")
        if not total:
            return
        x = 0.0
        for i, (n, colour) in enumerate(self.parts):
            wide = w * n / float(total)
            right = w if i == len(self.parts) - 1 else x + wide
            self.create_rectangle(int(x), 0, int(right), h, fill=colour, outline="")
            x += wide


class Scroller(tk.Frame):
    """A vertical scrolling area with a scroll bar you can see and drag."""
    WIDE = 10

    def __init__(self, parent, back=None):
        # NOT back=PAPER as a default argument: that is evaluated when the module loads and would freeze
        # the light palette in, painting white behind everything in the dark theme.
        back = PAPER if back is None else back
        super().__init__(parent, bg=back)
        self.canvas = tk.Canvas(self, bg=back, highlightthickness=0)
        self.rail = tk.Canvas(self, width=self.WIDE, bg=back, highlightthickness=0)
        self.inner = tk.Frame(self.canvas, bg=back)
        self.window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.back, self.grab, self.rail_shown = back, None, False
        self.canvas.bind("<Configure>", self.resize)
        self.inner.bind("<Configure>", self.measured)
        for w in (self.canvas, self.inner):
            w.bind("<MouseWheel>", self.wheel)
        self.rail.bind("<Button-1>", self.press)
        self.rail.bind("<B1-Motion>", self.drag)
        self.rail.bind("<ButtonRelease-1>", lambda e: setattr(self, "grab", None))
        self.rail.bind("<MouseWheel>", self.wheel)

    def clear(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.canvas.yview_moveto(0)

    def catch_wheel(self, widget):
        """The wheel has to work over a row too, not only over the gaps between them."""
        widget.bind("<MouseWheel>", self.wheel)
        for child in widget.winfo_children():
            self.catch_wheel(child)

    def wheel(self, event):
        lo, hi = self.canvas.yview()
        if lo <= 0 and hi >= 1:
            return
        self.canvas.yview_scroll(-1 * (event.delta // 120), "units")
        self.draw_rail()
        return "break"

    def press(self, event):
        lo, hi = self.canvas.yview()
        h = max(1, self.rail.winfo_height())
        top, bottom = h * lo, h * hi
        self.grab = (event.y - top) if top <= event.y <= bottom else (bottom - top) / 2.0
        self.drag(event)

    def drag(self, event):
        if self.grab is None:
            return
        h = max(1, self.rail.winfo_height())
        self.canvas.yview_moveto(max(0.0, min(1.0, (event.y - self.grab) / float(h))))
        self.draw_rail()

    def resize(self, event=None):
        self.canvas.itemconfigure(self.window, width=self.canvas.winfo_width())
        self.measured()

    def measured(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.draw_rail()

    def draw_rail(self):
        # Showing or hiding the bar changes the canvas width, which fires <Configure>, which comes back
        # here - so only ever touch the packing when the answer has actually changed, or the two chase
        # each other forever and the window locks up.
        lo, hi = self.canvas.yview()
        want = not (lo <= 0 and hi >= 1)
        if want != self.rail_shown:
            self.rail_shown = want
            if want:
                self.rail.pack(side="left", fill="y", padx=(8, 0))
            else:
                self.rail.pack_forget()
        if not want:
            return
        h = max(1, self.rail.winfo_height())
        self.rail.delete("all")
        self.rail.create_rectangle(4, 0, self.WIDE - 4, h, fill=SOFT, outline="")
        top, bottom = h * lo, max(h * hi, h * lo + 28)
        self.rail.create_rectangle(3, int(top), self.WIDE - 3, int(bottom), fill=THUMB, outline="")


class Picker(tk.Toplevel):
    """A small list of this week's venues, to say which one an unmatched file belongs to."""

    def __init__(self, parent, title, options, on_pick):
        super().__init__(parent)
        self.transient(parent)
        self.title("Which venue?")
        self.configure(bg=SUNK)
        self.resizable(False, False)
        self.on_pick = on_pick
        tk.Label(self, text=title, font=(FONT_BOLD, 10), bg=SUNK, fg=INK, wraplength=330,
                 justify="left").pack(padx=18, pady=(16, 10), anchor="w")
        self.list = tk.Listbox(self, height=14, width=38, font=(FONT, 10), bg=PAPER, fg=INK, relief="flat",
                               highlightthickness=1, highlightbackground=LINE, selectbackground=BLUE_TINT,
                               selectforeground=INK, activestyle="none", exportselection=False)
        self.list.pack(padx=18, fill="both", expand=True)
        for o in options:
            self.list.insert("end", o)
        if options:
            self.list.selection_set(0)
        self.list.bind("<Double-Button-1>", lambda e: self.take())
        self.list.bind("<Return>", lambda e: self.take())
        row = tk.Frame(self, bg=SUNK)
        row.pack(padx=18, pady=16, fill="x")
        Button(row, "Use this venue", self.take, kind="primary", back=SUNK).pack(side="left")
        Button(row, "Cancel", self.destroy, kind="quiet", back=SUNK).pack(side="left", padx=(8, 0))
        self.bind("<Escape>", lambda e: self.destroy())
        self.list.focus_set()
        self.update_idletasks()
        self.geometry("+%d+%d" % (parent.winfo_rootx() + max(0, (parent.winfo_width() - self.winfo_width()) // 2),
                                  parent.winfo_rooty() + 100))
        self.grab_set()

    def take(self):
        sel = self.list.curselection()
        if sel:
            self.on_pick(self.list.get(sel[0]))
        self.destroy()


class Who(tk.Toplevel):
    """Who worked at one venue this week, and so who is holding the sheet.

    The sheet sits at the venue all week and goes in with the last guard on it, so the last shift of the
    week is the one to ask - that is the whole point of this window, and it is said first and biggest.
    """

    def __init__(self, app, venue, monday, on_chase):
        super().__init__(app.root)
        self.transient(app.root)
        self.title(venue["label"])
        self.configure(bg=SUNK)
        self.app, self.venue, self.on_chase = app, venue, on_chase
        got = bool(venue["files"])
        wrap = app.px(340)

        tk.Label(self, text=venue["label"], font=(FONT_BOLD, 15), bg=SUNK, fg=INK, anchor="w",
                 wraplength=wrap, justify="left").pack(padx=22, pady=(18, 0), anchor="w")
        tk.Label(self, text=("sheet is in: " + ", ".join(f["name"] for f in venue["files"])) if got
                 else "no sheet in yet", font=(FONT, 9), bg=SUNK, fg=GREEN if got else RED,
                 anchor="w", wraplength=wrap, justify="left").pack(padx=22, anchor="w")
        shut = venue.get("closes")
        if shut:                                      # where a closing time came from, so it is not taken as fact
            mins, source, sure = shut
            tk.Label(self, text="closes %s%s  (%s%s)" % (
                "about " if source != "the roster" else "", ts.hhmm(mins), source,
                "" if source == "the roster" else ", %d%% of the readings" % round(sure * 100)),
                font=(FONT, 8), bg=SUNK, fg=MUTED, anchor="w").pack(padx=22, anchor="w", pady=(2, 0))

        if not got:
            box = tk.Frame(self, bg=PAPER, highlightbackground=LINE, highlightthickness=1)
            box.pack(padx=22, pady=(14, 0), fill="x")
            pad = tk.Frame(box, bg=PAPER)
            pad.pack(fill="x", padx=16, pady=13)
            head = tk.Frame(pad, bg=PAPER)
            head.pack(fill="x")
            tk.Label(head, text="ASK", font=(FONT_BOLD, 8), bg=PAPER, fg=RED).pack(side="left")
            when = venue.get("when") or {}
            if when.get("text"):                      # no use ringing a man who is not on until five
                tk.Label(head, text=when["text"], font=(FONT_BOLD, 9), bg=PAPER,
                         fg={"on": GREEN, "later": AMBER}.get(when.get("state"), MUTED)).pack(side="right")
            for name in venue.get("away", []):        # the usual sender, when he is not on this week
                tk.Label(pad, text="%s usually sends it, but is not on this week" % name, font=(FONT, 9),
                         bg=PAPER, fg=AMBER, anchor="w", wraplength=wrap - app.px(40),
                         justify="left").pack(anchor="w", pady=(3, 0))
            for i, p in enumerate(venue.get("ask", [])[:4]):
                line = tk.Frame(pad, bg=PAPER)
                line.pack(fill="x", anchor="w", pady=(6 if not i else 4, 0))
                tk.Label(line, text=p["name"], font=(FONT_BOLD, 13 if not i else 10), bg=PAPER,
                         fg=INK if not i else BODY, anchor="w").pack(side="left")
                Button(line, "sends it ✓" if p.get("taught") else "sends it",
                       lambda n=p["name"], on=not p.get("taught"): self.teach(n, on),
                       kind="primary" if p.get("taught") else "plain", size=8, pad=(8, 3),
                       back=PAPER).pack(side="right")
                tk.Label(pad, text="%s   %s   ·   %s" % (
                    (monday + datetime.timedelta(days=p["day"])).strftime("%a %d %b"),
                    p["shift"] or "no time on the roster", p["why"]),
                    font=(FONT, 8 if i else 9), bg=PAPER, fg=MUTED, anchor="w",
                    wraplength=wrap - app.px(40), justify="left").pack(anchor="w")
            tk.Label(pad, text="the sheet is held by the venue's own man - press \"sends it\" beside whoever "
                               "really does, and it is remembered", font=(FONT, 8), bg=PAPER, fg=FAINT,
                     anchor="w", wraplength=wrap - app.px(40), justify="left").pack(anchor="w", pady=(8, 0))

        box = tk.Frame(self, bg=PAPER, highlightbackground=LINE, highlightthickness=1)
        box.pack(padx=22, pady=(12, 0), fill="both", expand=True)
        pad = tk.Frame(box, bg=PAPER)
        pad.pack(fill="both", expand=True, padx=16, pady=13)
        tk.Label(pad, text="EVERYONE ON IT THIS WEEK", font=(FONT_BOLD, 8), bg=PAPER,
                 fg=MUTED).pack(anchor="w", pady=(0, 6))
        # A big door can have twenty-five people on it in a week. This is capped rather than scrolled:
        # a Toplevel sizes itself to its content, so a scroll bar appearing widens the window, which
        # resizes the canvas, which shows the bar again - the two grow each other and it never settles.
        room, shown = 10, 0                           # keeps the window clear of the bottom of a 1080 screen
        total_people = sum(len(venue["days"][i]) for i in venue["days"])
        for i in sorted(venue["days"]):
            if shown >= room:
                break
            day = monday + datetime.timedelta(days=i)
            last = i == venue["last_day"] and not got
            row = tk.Frame(pad, bg=PAPER)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=day.strftime("%a %d"), font=(FONT_BOLD if last else FONT, 9),
                     bg=PAPER, fg=INK if last else MUTED, width=7, anchor="w").pack(side="left")
            names = tk.Frame(row, bg=PAPER)
            names.pack(side="left", fill="x", expand=True)
            # Earliest start first, and a man with no time cell last - the same order who_has_it() uses
            # to pick the one to ask. It used to be latest-first, so the ASK box named a man as "first
            # on the last night" while the list underneath showed somebody else above him on that night.
            for p in sorted(venue["days"][i], key=lambda p: (p["start"] if p["start"] >= 0 else 9999)):
                if shown >= room:
                    break
                tk.Label(names, text="%s   %s%s" % (p["name"], p["shift"], "   (struck out)" if p["strike"] else ""),
                         font=(FONT_BOLD if last else FONT, 9), bg=PAPER, fg=INK if last else BODY, anchor="w",
                         wraplength=wrap - app.px(70), justify="left").pack(anchor="w")
                shown += 1
        if total_people > shown:
            tk.Label(pad, text="and %d more on it this week" % (total_people - shown), font=(FONT, 8),
                     bg=PAPER, fg=FAINT, anchor="w").pack(anchor="w", pady=(5, 0))

        if not venue["live"]:
            tk.Label(self, text="every name here is struck out on the roster - the shift may have been "
                                "cancelled, in which case there is no sheet to collect",
                     font=(FONT, 8), bg=SUNK, fg=AMBER, anchor="w", wraplength=wrap,
                     justify="left").pack(padx=22, pady=(10, 0), anchor="w")

        row = tk.Frame(self, bg=SUNK)
        row.pack(padx=22, pady=18, fill="x")
        if got:
            Button(row, "Open the sheet", self.open_it, icon="open", kind="primary", back=SUNK).pack(side="left")
        else:
            asked = bool(venue.get("chased"))
            Button(row, "Asked already - undo" if asked else "Mark as asked", self.chase,
                   icon="check", kind="plain" if asked else "primary", back=SUNK).pack(side="left")
            if asked:
                tk.Label(row, text="asked %s" % venue["chased"], font=(FONT, 8), bg=SUNK,
                         fg=AMBER).pack(side="left", padx=(10, 0))
        Button(row, "Close", self.destroy, kind="quiet", back=SUNK).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        self.geometry("+%d+%d" % (app.root.winfo_rootx() + max(0, (app.root.winfo_width() - self.winfo_width()) // 2),
                                  app.root.winfo_rooty() + 70))

    def open_it(self):
        self.app.open_sheet(self.venue)
        self.destroy()

    def chase(self):
        self.on_chase(self.venue)
        self.destroy()

    def teach(self, name, on):
        """Say who really sends this venue's sheet. Kept in contacts.json and used first from then on."""
        try:
            ts.save_contact(self.venue["label"], name, on)
        except OSError as e:
            self.app.tell("could not remember that: %s" % e, "warn")
            return
        self.app.tell("%s %s sends %s" % (name, "now" if on else "no longer", self.venue["label"]))
        self.app.rescan()
        self.destroy()


class App:
    #: The table's columns: heading, width in **pixels**, which way the text sits. Pixels, not characters:
    #: a Label's character width is measured in its own font, so an 8pt heading and an 11pt row never
    #: line up - the headings sat adrift of their columns until this was fixed.
    COLUMNS = (("", 30, "center"), ("VENUE", 215, "w"), ("WHO TO ASK", 180, "w"),
               ("WHEN", 265, "w"), ("CLOSES", 80, "w"), ("DAYS", 110, "w"))
    #: a gutter inside every column, so a long one - "Kilcarran Business Campus.jpg" - is cut short of
    #: its neighbour instead of running up against it with no white space between them
    GUTTER = 9

    def __init__(self, root):
        self.root = root
        self.settings = load_settings()
        self.queue = queue.Queue()
        self.widths, self.fitted = {}, {}          # one Font per style and a cache of trimmed strings:
        #                                            the list redraws every few seconds, so fit() has to
        #                                            be free on everything it has already measured
        self.roster = None
        self.roster_at = None
        self.reports = {}                             # sunday -> the check for that week
        self.report = None
        self.busy = False
        self.view = None                              # which tab is on show
        self.groups = []
        self.stamp = None                             # what the week's folder looked like last time
        self.retimed = self.found_at = datetime.datetime.now()
        self.watch_ms = int(os.environ.get("CTS_WATCH_MS") or WATCH_MS)
        self.summary, self.summary_kind = "Reading the roster...", "busy"
        self.places = None
        if os.environ.get("CTS_PLACES"):              # tests point the folder search somewhere harmless
            self.places = [p for p in os.environ["CTS_PLACES"].split(os.pathsep) if p]

        today = datetime.date.today()
        self.made_folder = ""
        if os.environ.get("CTS_AUTORUN"):
            self.sunday = ts.pick_week(os.environ["CTS_AUTORUN"], today)
        else:
            # The folder is made from the Friday on, not before: collecting starts at the weekend, and an
            # empty folder sitting on the Desktop from Monday is just clutter.
            if not self.places and today.weekday() >= 4:
                made, is_new = ts.make_week_folder(ts.sunday_of(today))
                if is_new:
                    self.made_folder = "Made this week's folder on the Desktop: %s" % os.path.basename(made)
            self.sunday = ts.default_week(today)      # Monday opens on last week, the one being chased

        root.title("Sheet Tracker")
        root.minsize(1140, 620)                       # narrower than this and the buttons run off the edge
        try:
            root.iconbitmap(ICON)
        except tk.TclError:
            pass
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        if ICON_FONT not in tkfont.families():
            ICONS.clear()
        self.theme = os.environ.get("CTS_THEME") or self.settings.get("theme", "light")
        set_theme(self.theme)
        root.configure(bg=PAPER)
        self.status = tk.StringVar(value="Reading the roster...")
        self.roster_info = tk.StringVar(value="")
        self.checked = tk.StringVar(value="")
        self.build()
        want_w, want_h = self.px(1180), self.px(860)
        wide = min(want_w, root.winfo_screenwidth() - self.px(80))
        tall = min(want_h, root.winfo_screenheight() - self.px(90))
        root.geometry(os.environ.get("CTS_GEOMETRY") or self.settings.get("geometry") or "%dx%d+%d+%d" % (
            wide, tall, max(0, (root.winfo_screenwidth() - wide) // 2), 30))
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<F5>", lambda e: self.reload(True))
        root.bind("<Control-r>", lambda e: self.reload(True))
        root.bind("<Prior>", lambda e: self.step(-1))
        root.bind("<Next>", lambda e: self.step(1))
        root.bind("<Control-c>", lambda e: self.copy_missing())
        root.bind("<Control-s>", lambda e: self.save_list())
        self.show_week()
        self.poll()
        self.reload(force=False)
        self.watch()

    def px(self, n):
        return int(n * self.scale)

    def tone_for(self, key):
        """One colour per collection night, used by the hero, the bar and the rows alike."""
        return {"sat": AMBER, "sun": BLUE, "past": RED, "todo": BLUE, "in": GREEN, "all": BLUE}[key]

    def lead_key(self):
        """Which list leads: on a Saturday the Saturday one, on a Sunday the Sunday one, else all that
        is still out. Only the week being collected has a 'tonight' - any other week leads with the lot."""
        today = datetime.date.today()
        if self.sunday != ts.sunday_of(today):
            return "todo"
        return {5: "sat", 6: "sun"}.get(today.weekday(), "todo")

    # ---- the window ----
    def build(self):
        root = self.root
        strip = tk.Frame(root, bg=SUNK)               # packed before the body, or its expand eats this
        strip.pack(fill="x", side="bottom")
        tk.Frame(strip, bg=LINE, height=1).pack(fill="x")
        line = tk.Frame(strip, bg=SUNK)
        line.pack(fill="x", padx=26, pady=7)
        self.status_icon = tk.Label(line, text="", font=(ICON_FONT, 10), bg=SUNK, fg=GREEN)
        self.status_icon.pack(side="left", padx=(0, 8))
        tk.Label(line, textvariable=self.status, font=(FONT, 9), bg=SUNK, fg=BODY).pack(side="left")
        tk.Label(line, textvariable=self.roster_info, font=(FONT, 9), bg=SUNK, fg=FAINT).pack(side="right")
        tk.Label(line, text="  ·  ", font=(FONT, 9), bg=SUNK, fg=LINE).pack(side="right")
        tk.Label(line, textvariable=self.checked, font=(FONT, 9), bg=SUNK, fg=FAINT).pack(side="right")

        # --- a quiet top bar: the name, which week, and the two switches ---
        top = tk.Frame(root, bg=SUNK)
        top.pack(fill="x", side="top")
        bar = tk.Frame(top, bg=SUNK)
        bar.pack(fill="x", padx=26, pady=11)
        tk.Label(bar, text="Sheet Tracker", font=(FONT_BOLD, 12), bg=SUNK, fg=INK).pack(side="left")
        self.week_label = tk.Label(bar, text="", font=(FONT, 10), bg=SUNK, fg=MUTED)
        self.week_label.pack(side="left", padx=(14, 0))
        Button(bar, "", lambda: self.step(1), icon="next", pad=(8, 5), back=SUNK).pack(side="right")
        Button(bar, "", lambda: self.step(-1), icon="prev", pad=(8, 5), back=SUNK).pack(side="right", padx=(0, 6))
        Button(bar, "Light" if self.theme == "dark" else "Dark", self.flip_theme,
               icon="sun" if self.theme == "dark" else "moon", kind="quiet", pad=(9, 5),
               back=SUNK).pack(side="right", padx=(0, 16))
        self.pills = {}
        holder = tk.Frame(bar, bg=SUNK)
        holder.pack(side="right", padx=(0, 20))
        for i, (key, name) in enumerate((("last", "Last week"), ("this", "This week"), ("next", "Next week"))):
            pill = Pill(holder, name, lambda k=key: self.go(k), back=SUNK)
            pill.pack(side="left", padx=(0 if not i else 6, 0))
            self.pills[key] = pill
        tk.Frame(top, bg=LINE, height=1).pack(fill="x")

        body = tk.Frame(root, bg=PAPER)
        body.pack(fill="both", expand=True)

        # --- the hero: the one question, answered ---
        hero = tk.Frame(body, bg=PAPER)
        hero.pack(fill="x", padx=34, pady=(26, 0))
        headline = tk.Frame(hero, bg=PAPER)
        headline.pack(fill="x")
        self.big = tk.Label(headline, text="", font=(FONT_BOLD, 52), bg=PAPER, fg=INK)
        self.big.pack(side="left")
        words = tk.Frame(headline, bg=PAPER)
        words.pack(side="left", padx=(18, 0), pady=(10, 0))
        self.headline = tk.Label(words, text="", font=(FONT_BOLD, 15), bg=PAPER, fg=INK, anchor="w")
        self.headline.pack(anchor="w")
        self.subline = tk.Label(words, text="", font=(FONT, 10), bg=PAPER, fg=MUTED, anchor="w")
        self.subline.pack(anchor="w", pady=(2, 0))
        acts = tk.Frame(headline, bg=PAPER)
        acts.pack(side="right", pady=(8, 0))
        self.make_btn = Button(acts, "Make folder", self.make_folder, icon="add")
        self.open_btn = Button(acts, "Open folder", self.open_folder, icon="folder")
        self.copy_btn = Button(acts, "Copy list", self.copy_missing, icon="copy")
        self.save_btn = Button(acts, "Save", self.save_list, icon="save")
        self.late_btn = Button(acts, "Often late", self.show_late, icon="warning")
        self.refresh_btn = Button(acts, "", lambda: self.reload(True), icon="refresh", pad=(9, 7))
        for b in (self.make_btn, self.open_btn, self.copy_btn, self.save_btn, self.late_btn, self.refresh_btn):
            b.pack(side="left", padx=(8, 0))

        self.bar = Bar(hero)
        self.bar.pack(fill="x", pady=(22, 0))
        self.bar_words = tk.Label(hero, text="", font=(FONT, 9), bg=PAPER, fg=MUTED, anchor="w")
        self.bar_words.pack(fill="x", pady=(7, 0))

        # --- the tabs, and the one list under them ---
        tabs = tk.Frame(body, bg=PAPER)
        tabs.pack(fill="x", padx=34, pady=(20, 0))
        self.tabs, self.tab_order = {}, []
        tk.Frame(body, bg=LINE, height=1).pack(fill="x", padx=34)
        self.tab_holder = tabs
        # a heading that stays put, so a long list never leaves you guessing which column is which
        head = tk.Frame(body, bg=PAPER)
        head.pack(fill="x", padx=34, pady=(9, 5))
        self.heads = []
        for text, wide, side in self.COLUMNS:
            box = self.cell(head, wide, PAPER, tall=14)
            label = tk.Label(box, text=text, font=(FONT_BOLD, 8), bg=PAPER, fg=FAINT, anchor=side)
            label.pack(fill="both", expand=True, padx=(0, self.px(self.GUTTER)) if side == "w" else 0)
            self.heads.append(label)
        tk.Frame(body, bg=LINE, height=1).pack(fill="x", padx=34)
        self.listing = Scroller(body)
        self.listing.pack(fill="both", expand=True, padx=34, pady=(0, 6))

        # --- one line for the odd thing ---
        self.foot = tk.Frame(body, bg=PAPER)
        self.foot.pack(fill="x", padx=34, pady=(0, 10))
        self.note_icon = tk.Label(self.foot, text="", font=(ICON_FONT, 9), bg=PAPER, fg=BLUE)
        self.note_icon.pack(side="left", padx=(0, 7))
        self.note_text = tk.Label(self.foot, text="", font=(FONT, 9), bg=PAPER, fg=BODY, justify="left", anchor="w")
        self.note_text.pack(side="left", fill="x", expand=True)
        self.spare_btn = Button(self.foot, "Name the odd files...", self.assign, icon="link", kind="quiet")

    def tab_specs(self):
        """The tabs and their counts: [(key, text, tone, count)], the leading list first.

        "Still to get" leads and is the default, because that is the number in the headline. The nights
        are their own tabs after it, so Saturday's deadline is one click away without taking over.
        Worked out here rather than inside fill(), because the heartbeat needs the counts again - "Can
        ask now" changes as people come on shift - without redrawing the rest of the window.
        """
        r = self.report
        total, got = len(r["venues"]), len(r["in"])
        gone = total - got
        by_key = {k: len(v) for k, _, v in self.groups}
        specs = [("todo", "Still to get", AMBER, gone)] if gone else []
        on_now = [v for v in r["missing"] if (v.get("when") or {}).get("state") == "on"]
        if on_now:                                    # the ones you can actually ring this minute
            specs.append(("now", "Can ask now", GREEN, len(on_now)))
        for k, head, _ in ts.COLLECT:
            if by_key.get(k):
                specs.append((k, head.replace("Get on ", ""), self.tone_for(k), by_key[k]))
        specs.append(("in", "In", GREEN, got))
        specs.append(("all", "Every venue", MUTED, total))
        return specs

    def make_tabs(self, specs):
        """The tab strip. specs: [(key, text, tone, count)] - the leading one first.

        When only the numbers have moved - "Can ask now" gaining a venue as somebody comes on shift -
        the tabs already there are told their new count instead of being destroyed and built again. The
        heartbeat comes through here several times a minute, and remaking the strip every time is what
        makes the top of the window flash.
        """
        shape = [(k, text, tone) for k, text, tone, _ in specs]
        if shape == getattr(self, "tab_shape", None):
            try:
                for key, _, _, n in specs:
                    self.tabs[key].show(n)
                return
            except (tk.TclError, KeyError):
                pass                                  # rebuilt under us (a theme flip): make it again
        for w in self.tab_holder.winfo_children():
            w.destroy()
        self.tabs, self.tab_order, self.tab_shape = {}, [k for k, _, _, _ in specs], shape
        for i, (key, text, tone, n) in enumerate(specs):
            tab = Tab(self.tab_holder, text, lambda k=key: self.show_view(k), tone)
            tab.pack(side="left", padx=(0 if not i else 26, 0))
            tab.show(n)
            self.tabs[key] = tab

    # ---- saying things ----
    def tell(self, text, kind=None):
        self.status.set(text)
        glyph, colour = {"ok": ("check", GREEN), "warn": ("warning", AMBER), "stop": ("cancel", RED),
                         "busy": ("sync", BLUE)}[kind or ("busy" if text.endswith("...") else "ok")]
        self.status_icon.configure(text=ICONS.get(glyph, ""), fg=colour)

    def note(self, text, kind="info"):
        self.note_icon.configure(text=ICONS.get({"info": "info", "warn": "warning"}[kind], ""),
                                 fg=BLUE if kind == "info" else AMBER)
        self.note_text.configure(text=text, fg=BODY if kind == "info" else AMBER)

    def flip_theme(self):
        """Dark or light. Every widget takes its colours when it is made, so the window is built again."""
        self.theme = "dark" if self.theme == "light" else "light"
        self.settings["theme"] = self.theme
        if not os.environ.get("CTS_GEOMETRY"):
            save_settings(self.settings)
        set_theme(self.theme)
        self.root.configure(bg=PAPER)
        for w in self.root.winfo_children():
            w.destroy()
        self.build()
        self.show_week()
        if self.report is not None:
            self.fill()
        else:
            self.tell("Reading the roster...", "busy")

    # ---- the week ----
    def go(self, key):
        self.sunday = ts.pick_week(key, datetime.date.today())
        self.view = None                              # a new week leads with its own best list
        self.show_week()
        self.rescan()

    def step(self, weeks):
        self.sunday += datetime.timedelta(days=7 * weeks)
        self.view = None
        self.show_week()
        self.rescan()

    def show_week(self):
        today = datetime.date.today()
        self.week_label.configure(text="%s  ·  %s" % (ts.week_name(self.sunday, today),
                                                           ts.week_text(self.sunday)))
        for key, pill in self.pills.items():
            sunday = ts.pick_week(key, today)
            pill.choose(sunday == self.sunday)
            got = self.reports.get(sunday)
            pill.show(len(got["missing"]) if got else 0, bool(got and got["venues"] and not got["missing"]))

    # ---- the roster ----
    def reload(self, force=True):
        if self.busy:
            return
        fresh = self.roster is not None and self.roster_at is not None and \
            (datetime.datetime.now() - self.roster_at).total_seconds() < ROSTER_FRESH
        if fresh and not force:
            self.rescan()
            return
        self.busy = True
        self.refresh_btn.configure(state="disabled")
        self.tell("Reading the roster...", "busy")
        threading.Thread(target=self.fetch, daemon=True).start()

    def fetch(self):
        """In a thread: get the roster, read it, send it back. Never touches a widget."""
        try:
            if os.environ.get("CTS_NO_DOWNLOAD") and os.path.exists(ts.ROSTER_PATH):
                info = "roster: saved copy"
            else:
                info = "roster: " + ts.download_roster()
            self.queue.put(("roster", (ts.Roster(), info)))
        except ts.Problem as e:
            self.queue.put(("problem", str(e)))
        except Exception:
            self.queue.put(("problem", "could not read the roster:\n" + traceback.format_exc(limit=3)))

    def poll(self):
        """Pick up whatever the thread has finished. Must never raise: the window may be closing."""
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "roster":
                    self.roster, info = payload
                    self.roster_at = datetime.datetime.now()
                    self.roster_info.set(info)
                    self.busy = False
                    self.reports = {}
                    self.refresh_btn.configure(state="normal")
                    # keep=True: this fires by itself every five minutes, and throwing him back to the
                    # top of the list while he is halfway down reading it is the sort of thing that
                    # makes a window feel like it is fighting you.
                    self.rescan(keep=True)
                elif kind == "late":
                    self.busy = False
                    self.late_btn.configure(state="normal")
                    rows, weeks = payload
                    self.tell(self.summary, self.summary_kind)
                    self.late_window(rows, weeks)
                elif kind == "problem":
                    self.busy = False
                    self.refresh_btn.configure(state="normal")
                    self.tell("Could not read the roster", "stop")
                    self.note(payload.splitlines()[0], "warn")
        except queue.Empty:
            pass
        except tk.TclError:
            return
        try:
            self.root.after(200, self.poll)
        except tk.TclError:
            pass

    # ---- keeping itself up to date ----
    def folder_stamp(self):
        """A cheap fingerprint of the week's folder: what is in it and when each one landed.

        Walking forty files and stat-ing them costs nothing, so this can run every few seconds; the
        week is only worked out again when the fingerprint actually changes.
        """
        r = self.report
        if not r or not r.get("folder"):
            return None
        try:
            return tuple(sorted((f["name"], f["when_text"]) for f in ts.sheets_in(r["folder"])))
        except OSError:
            return None

    def watch(self):
        """Look for new sheets every few seconds, and for a new roster every few minutes.

        The user drops photos into the folder while the window is open, so it has to notice by itself.
        Must never raise: the window may be closing.
        """
        try:
            now = datetime.datetime.now()
            if self.report is not None and not self.busy:
                stamp = self.folder_stamp()
                if stamp is not None and self.stamp is not None and stamp != self.stamp:
                    was = len(self.report["in"])
                    self.rescan(keep=True)
                    came = len(self.report["in"]) - was
                    self.flash("%d new sheet%s just in" % (came, "" if came == 1 else "s") if came > 0
                               else "the folder changed", "ok" if came > 0 else None)
                elif stamp is None and self.report.get("folder") is None \
                        and (now - self.found_at).total_seconds() > FIND_S:
                    self.found_at = now               # the folder may have been made since we looked
                    if ts.find_folder(self.sunday, self.places)[0]:
                        self.rescan(keep=True)
                        self.flash("the folder for this week turned up")
                elif (now - self.retimed).total_seconds() >= RETIME_S:
                    self.retimed = now                # the countdown has to keep up with the minute hand
                    self.retime()
                self.stamp = stamp if stamp is not None else self.stamp
                if self.roster_at and (now - self.roster_at).total_seconds() > ROSTER_FRESH:
                    self.reload(force=True)           # a fresh roster, in its own thread
            self.checked.set("checked %s" % now.strftime("%H:%M:%S"))
        except tk.TclError:
            return
        except Exception:
            pass                                      # never let the heartbeat kill the window
        try:
            self.root.after(self.watch_ms, self.watch)
        except tk.TclError:
            pass

    def retime(self):
        """Re-word the clock lines in place, without going near the roster or the folder.

        The only thing that has moved is the time, so this re-words every venue's "when" in the report
        already in hand and then changes **only the cells whose words actually changed**. No disk, no
        roster, and nothing destroyed - so the countdown ticks down without the screen flashing. A full
        redraw happens only when the list itself has moved on, which is a venue coming on or off shift.
        """
        if self.report is None or self.report.get("problem"):
            return
        ts.retime(self.report)
        for sunday, got in self.reports.items():       # the other weeks' pills carry counts too
            if got is not self.report and not got.get("problem"):
                ts.retime(got)
        if self.touch_up():
            self.make_tabs(self.tab_specs())           # just the numbers; the strip is not rebuilt
            self.show_week()
            return
        where = self.listing.canvas.yview()[0]         # the shape changed: draw it again, keeping place
        self.fill()
        self.show_week()
        if where:
            self.listing.after(20, lambda: self.listing.canvas.yview_moveto(where))
        self.rehover()

    def touch_up(self):
        """Change only the cells whose words have moved. False if the list needs drawing again instead.

        It bails out the moment the rows on screen are not the rows that should be there - a different
        number of them, or a different venue in a given place - because then nothing can be matched up
        cell by cell and the list has to be rebuilt properly.
        """
        try:
            drawn = [w for w in self.listing.inner.winfo_children() if getattr(w, "venue_row", False)]
            rows = self.venues_for(self.view)
            if len(drawn) != len(rows) or any(a.venue is not b for a, (b, _) in zip(drawn, rows)):
                return False
            for line, (v, tone) in zip(drawn, rows):
                fresh = self.look(v, tone)
                for key, value in fresh.items():
                    if value != line.look.get(key):
                        text, fg, font = value
                        line.cells[key].configure(text=text, fg=fg, font=font)
                line.look = fresh
        except (tk.TclError, AttributeError):
            return False                               # mid-rebuild: let the caller draw it properly
        return True

    def rehover(self):
        """Put the status bar back on whatever the mouse is actually over.

        A redraw destroys the row under the cursor, so its <Leave> never fires and the new row under the
        cursor gets no <Enter> until the mouse moves - the status bar would sit there describing a venue
        the pointer left, which is exactly the defect version 2.0 had. Harmless when it happened once on
        a button press; not harmless now the list redraws itself every few seconds.
        """
        try:
            under = self.root.winfo_containing(*self.root.winfo_pointerxy())
        except tk.TclError:
            return
        while under is not None:
            if getattr(under, "venue_row", False):
                self.hover(getattr(under, "venue", None))
                return
            under = under.master
        self.hover(None)

    def flash(self, text, kind=None):
        """Say what just changed, and leave it up for a while rather than a blink."""
        self.summary, self.summary_kind = text, kind or self.summary_kind
        self.tell(text, kind)

    def week_report(self, sunday):
        """The check for a week, worked out once and kept."""
        if sunday not in self.reports:
            try:
                self.reports[sunday] = ts.check(sunday, self.roster, self.places)
            except ts.Problem as e:
                self.reports[sunday] = {                   # every key a full report has, so nothing downstream
                    "problem": str(e), "sunday": sunday, "monday": sunday - datetime.timedelta(days=6),
                    "week": ts.week_text(sunday), "folder": None, "folder_how": None,
                    "folder_name": ts.folder_name(sunday), "venues": [], "in": [], "missing": [],
                    "spare": [], "files": [], "notes": [str(e)]}
        return self.reports[sunday]

    def rescan(self, keep=False):
        """Work the shown week out from the roster in hand and the folders on disk, and show it.

        keep=True is for the background heartbeat: hold the scroll where it is, so a sheet arriving
        while he is halfway down the list does not throw him back to the top.
        """
        if self.roster is None:
            return
        where = self.listing.canvas.yview()[0] if keep else 0.0
        self.reports.pop(self.sunday, None)           # the folder may have changed since last time
        try:
            self.report = self.week_report(self.sunday)
            for key in ("last", "this"):              # the switcher carries both weeks' outstanding counts
                self.week_report(ts.pick_week(key, datetime.date.today()))
        except Exception:
            self.tell("Something went wrong reading that week", "stop")
            self.note(traceback.format_exc(limit=2).splitlines()[-1], "warn")
            return
        self.fill()
        self.show_week()
        self.stamp = self.folder_stamp()
        if keep and where:
            self.listing.after(20, lambda: self.listing.canvas.yview_moveto(where))

    # ---- showing a week ----
    def fill(self):
        r = self.report
        total, got = len(r["venues"]), len(r["in"])
        gone = total - got
        self.groups = ts.to_collect(r) if gone else []
        by_key = {k: len(v) for k, _, v in self.groups}
        # The headline is always the whole of what is left - that is the number he wants on opening.
        # Which night each one falls on is a tab away, and a line under the headline when it is that night.
        tonight = self.lead_key() if self.sunday == ts.sunday_of(datetime.date.today()) else "todo"
        if r.get("problem"):
            self.big.configure(text="-", fg=MUTED)
            self.headline.configure(text="%s is not on the roster" % self.which_week().capitalize(),
                                    fg=INK)
            self.subline.configure(text=r["problem"])
        elif not total:
            self.big.configure(text="0", fg=MUTED)
            self.headline.configure(text="Nothing rostered", fg=INK)
            self.subline.configure(text="no venue has anybody on it %s" % self.which_week())
        elif not gone:
            self.big.configure(text=ICONS.get("check", "0"), fg=GREEN,
                               font=(ICON_FONT if ICONS else FONT_BOLD, 44))
            self.headline.configure(text="Every sheet is in", fg=GREEN)
            self.subline.configure(text="all %d venues for %s" % (total, ts.week_text(self.sunday)))
        else:
            self.big.configure(text=str(gone), fg=RED if by_key.get("past") else AMBER, font=(FONT_BOLD, 52))
            self.headline.configure(text="still to come in", fg=INK)
            if tonight in ("sat", "sun") and by_key.get(tonight):
                self.subline.configure(
                    text="%d of them tonight - %s" % (by_key[tonight],
                                                      "these are shut tomorrow, so it is tonight or they wait"
                                                      " a week" if tonight == "sat" else "the last of the week"),
                    fg=self.tone_for(tonight))
            else:
                # "this week" was hard-coded here, so the top of the window read "Last week" while the
                # line under the big number said "rostered this week". Name whichever week is on show.
                self.subline.configure(text="of %d venues rostered %s" % (total, self.which_week()),
                                       fg=MUTED)
        self.bar.show([(got, GREEN)] + [(by_key.get(k, 0), self.tone_for(k)) for k, _, _ in ts.COLLECT])
        self.bar_words.configure(text="%d of %d sheets in%s" % (
            got, total, "" if not gone else "   ·   " + "   ·   ".join(
                "%d %s" % (by_key[k], head.lower()) for k, head, _ in ts.COLLECT if by_key.get(k))))

        self.open_btn.configure(state="normal" if r["folder"] else "disabled")
        self.make_btn.configure(state="disabled" if r["folder"] else "normal")
        self.copy_btn.configure(state="normal" if r["missing"] else "disabled")
        self.save_btn.configure(state="normal" if total else "disabled")

        specs = self.tab_specs()
        self.make_tabs(specs)
        if self.view not in self.tabs:
            self.view = specs[0][0]
        self.show_view(self.view)

        self.spare_btn.pack_forget()
        if r.get("problem"):
            self.note(r["problem"], "warn")
        elif r["spare"]:
            self.note("%d file%s here match no venue: %s" % (len(r["spare"]), "" if len(r["spare"]) == 1 else "s",
                                                             ", ".join(f["name"] for f in r["spare"])), "warn")
            self.spare_btn.pack(side="right")
        elif self.made_folder and self.sunday == ts.sunday_of(datetime.date.today()):
            self.note(self.made_folder)
        elif not r["folder"]:
            self.note("No folder for %s yet - make one and the sheets have somewhere to go."
                      % self.which_week(), "warn")
        elif r["notes"]:
            self.note(r["notes"][0])
        else:
            self.note("%d sheet%s in the folder." % (len(r["files"]), "" if len(r["files"]) == 1 else "s"))

        if r.get("problem"):
            self.summary, self.summary_kind = r["problem"], "warn"
        else:
            self.summary = "%s  ·  %d rostered, %d in, %d still to come" % (
                ts.week_text(self.sunday), total, got, gone)
            self.summary_kind = "warn" if gone else "ok"
        self.tell(self.summary, self.summary_kind)

    def venues_for(self, key):
        """Exactly the venues one tab shows. The tab's count comes from here too, so they cannot disagree."""
        r = self.report
        if key == "all":
            return [(v, self.state_tone(v)) for v in r["venues"]]
        if key == "in":
            return [(v, GREEN) for v in r["in"]]
        if key == "now":                              # the man is at work this minute: ring the place
            return [(v, GREEN) for v in r["missing"] if (v.get("when") or {}).get("state") == "on"]
        if key == "todo":
            # soonest first: whoever is on now, then whoever comes on next, then the ones to ring
            order = {"on": 0, "later": 1, "unknown": 2, "gone": 3}
            rows = [(v, self.tone_for(k)) for k, _, vs in self.groups for v in vs]
            return sorted(rows, key=lambda pair: (order.get((pair[0].get("when") or {}).get("state"), 2),
                                                  (pair[0].get("when") or {}).get("from") or
                                                  datetime.datetime.max))
        return [(v, self.tone_for(key)) for k, _, vs in self.groups if k == key for v in vs]

    def state_tone(self, v):
        if v["files"]:
            return GREEN
        last = v.get("last_day")
        return self.tone_for("sun" if last == 6 else "sat" if last == 5 else "past")

    def show_view(self, key):
        self.view = key
        for k, tab in self.tabs.items():
            tab.choose(k == key)
        if self.report is not None:
            self.draw_rows()

    def which_week(self):
        """"last week", "this week", "3 weeks ago" - whichever is actually on show.

        Several lines used to say "this week" whatever was in front of him, so the top of the window
        read "Last week" while the line under the big number said "rostered this week".
        """
        return ts.week_name(self.sunday, datetime.date.today()).lower()

    def label_heads(self):
        """The heading has to say what is under it: on the 'In' tab that column holds files, not people."""
        if not getattr(self, "heads", None):
            return
        every = self.view in ("all",)
        self.heads[2].configure(text="SHEET" if self.view == "in"
                                else "WHO TO ASK / SHEET" if every else "WHO TO ASK")
        self.heads[3].configure(text="CAME IN" if self.view == "in" else "WHEN")

    def draw_rows(self):
        """One list, the one the chosen tab asks for. Nothing is cut: every venue it counts, it draws."""
        self.label_heads()
        self.listing.clear()
        rows = self.venues_for(self.view)
        for i, (v, tone) in enumerate(rows):
            self.row(v, tone, i)
        if not rows:
            tk.Label(self.listing.inner, text="Nothing here.", font=(FONT, 11), bg=PAPER,
                     fg=MUTED).pack(anchor="w", pady=18)
        self.listing.catch_wheel(self.listing.inner)
        self.listing.after(10, self.listing.measured)

    #: the row, left to right: which cell goes in which column and how it lines up
    CELLS = (("mark", 0, "center"), ("name", 1, "w"), ("who", 2, "w"),
             ("when", 3, "w"), ("shuts", 4, "w"), ("days", 5, "w"))

    def look(self, v, tone):
        """Everything a row shows, worked out as plain values - text, colour, font - and no widgets.

        The heartbeat compares the look it drew against the look it would draw now and touches only the
        cells that really differ. Tearing the whole list down and building it again several times a
        minute is what made the window flash: "donot make the screen flash again and again".
        """
        got = bool(v["files"])
        asked = bool(v.get("chased"))
        state = (v.get("when") or {}).get("state", "unknown")
        cols = [w for _, w, _ in self.COLUMNS]
        # when it is any use ringing - you cannot ask Brennans at three for a man who starts at five
        when = (v.get("when") or {}).get("text", "")
        paint = {"on": GREEN, "later": AMBER, "gone": MUTED, "open": RED}.get(state, FAINT)
        if got:
            when, paint = "came in %s" % v["files"][0].get("when_text", ""), FAINT
            if len(v["files"]) > 1:
                when += "  +%d" % (len(v["files"]) - 1)
        elif asked:
            when, paint = "asked %s" % v["chased"], AMBER
        name_font = (FONT if got else FONT_BOLD, 11)
        when_font = (FONT_BOLD if state in ("on", "open") and not got else FONT, 10)
        holder = v["ask"][0] if v.get("ask") else None
        shut = v.get("closes")
        return {
            "mark": (ICONS.get("check", "+") if got else ("○" if asked else "●"),
                     GREEN if got else (RED if state == "open" else AMBER if asked else tone),
                     (ICON_FONT if got and ICONS else FONT_BOLD, 10)),
            "name": (self.fit(v["label"], name_font, cols[1]), MUTED if got else INK, name_font),
            "who": (self.fit(", ".join(f["name"] for f in v["files"]) if got
                             else (holder["name"] if holder else "nobody on it"), (FONT, 10), cols[2]),
                    MUTED if got else BODY, (FONT, 10)),
            "when": (self.fit(when, when_font, cols[3]), paint, when_font),
            "shuts": (("%s%s" % ("~" if shut and shut[1] != "the roster" else "", ts.hhmm(shut[0])))
                      if shut else "", FAINT, (FONT, 10)),
            "days": (v["day_text"], FAINT, (FONT, 9)),
        }

    def row(self, v, tone, i=0):
        """One venue across the table: state, name, who to ask, when, when it shuts, days worked."""
        look = self.look(v, tone)
        rest = BAND if i % 2 else PAPER                # zebra, so a wide row is easy to follow across
        line = tk.Frame(self.listing.inner, bg=rest, cursor="hand2")
        line.venue_row = True                         # so a test can count what is really on show
        line.venue = v                                # and so rehover() can tell what it is pointing at
        line.look, line.cells = look, {}
        line.pack(fill="x")
        cols = [w for _, w, _ in self.COLUMNS]
        boxes = [self.cell(line, w, rest) for w in cols]
        gut = (0, self.px(self.GUTTER))

        for key, col, side in self.CELLS:
            text, fg, font = look[key]
            label = tk.Label(boxes[col], text=text, fg=fg, font=font, bg=rest, anchor=side)
            label.pack(fill="both", expand=True, padx=0 if side == "center" else gut)
            line.cells[key] = label

        parts = tuple([line] + list(line.cells.values()) + boxes)
        for w in parts:
            w.bind("<Button-1>", lambda e, v=v: self.clicked(v))
            w.bind("<Button-3>", lambda e, v=v: self.who(v))
            w.bind("<Enter>", lambda e, p=parts, v=v: (self.shade(p, BLUE_TINT), self.hover(v)))
            w.bind("<Leave>", lambda e, p=parts, l=line, b=rest: (
                self.shade(p, b), None if pointer_inside(l) else self.hover(None)))

    ROW_HIGH = 27                                     # a row's height in pixels

    def fit(self, text, font, wide):
        """Trim a string to its column and mark it with an ellipsis.

        A fixed-width cell clips whatever will not fit, which left "Kilcarran Business Campus.jpg" sitting
        in the list as "Kilcarran Business Campus.j" - and a cut file name that still looks like a whole
        one is exactly the kind of thing he is scanning for. The ellipsis says it was cut; the full name
        is in the status bar as soon as he hovers the row.
        """
        if len(text) * 9 <= wide:                 # no glyph here is under 9px at this size: it fits
            return text
        key = (text, font, wide)
        if key in self.fitted:                    # the same names redraw every few seconds; measure once
            return self.fitted[key]
        room = self.px(wide - 2 * self.GUTTER)
        if font not in self.widths:
            self.widths[font] = tkfont.Font(font=font)
        rule = self.widths[font]
        if rule.measure(text) <= room:
            self.fitted[key] = text
            return text
        lo, hi = 0, len(text)                     # longest prefix that still fits with the ellipsis
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if rule.measure(text[:mid] + "…") <= room:
                lo = mid
            else:
                hi = mid - 1
        self.fitted[key] = text[:lo].rstrip() + "…"
        return self.fitted[key]

    def cell(self, parent, wide, back, tall=None):
        """A column of a fixed width in pixels, so the headings and the rows line up whatever the font.

        It needs a height as well: a frame told not to size itself to its contents collapses to nothing
        without one, and the whole table folded into a fifteen-pixel smear.
        """
        box = tk.Frame(parent, bg=back, width=self.px(wide), height=self.px(tall or self.ROW_HIGH))
        box.pack_propagate(False)
        box.pack(side="left")
        return box

    @staticmethod
    def shade(parts, colour):
        for w in parts:
            try:
                w.configure(bg=colour)
            except tk.TclError:
                pass

    def hover(self, venue):
        """Reading a row tells you what is behind it, without having to click anything."""
        if venue is None:
            self.tell(self.summary, self.summary_kind)
        elif venue["files"]:
            came = venue["files"][0].get("when_text", "")
            self.tell("%s  ·  %s  ·  %s%s  ·  click to open it, right-click for who worked" % (
                venue["label"], venue["day_text"], ", ".join(f["name"] for f in venue["files"]),
                "  ·  came in " + came if came else ""), "ok")
        else:
            top = venue["ask"][0] if venue.get("ask") else None
            state = (venue.get("when") or {}).get("state")
            # the short form of the reason here; the full "22 shifts over 10 of the last 12 weeks"
            # belongs in the window that has room for it, not jammed into the status bar
            why = (top["why"].split(" - ")[0] if top else "nobody on it")
            self.tell("%s  ·  ask %s (%s)  ·  %s%s  ·  click for the rest"
                      % (venue["label"], top["name"] if top else "?", why,
                         (venue.get("when") or {}).get("text", ""),
                         "  ·  asked %s" % venue["chased"] if venue.get("chased") else ""),
                      "ok" if state == "on" else "warn")

    # ---- what a click does ----
    def clicked(self, venue):
        """A venue whose sheet is in opens it; one that is missing asks who is holding it."""
        if venue["files"]:
            self.open_sheet(venue)
        else:
            self.who(venue)

    def who(self, venue):
        """The whole week at one venue, in a window of its own - the list stays uncluttered."""
        Who(self, venue, self.sunday - datetime.timedelta(days=6), self.chase)

    def open_sheet(self, venue):
        if not venue["files"]:
            return
        if os.environ.get("CTS_NOOPEN"):
            self.tell("would open %s" % venue["files"][0]["name"])
            return
        try:
            os.startfile(venue["files"][0]["path"])
        except OSError as e:
            self.tell("could not open that sheet: %s" % e, "warn")

    def chase(self, venue):
        """Mark a missing venue as asked for, or take the mark off again."""
        on = not venue.get("chased")
        try:
            ts.save_chased(self.sunday, venue["label"], on)
        except OSError as e:
            self.tell("could not remember that: %s" % e, "warn")
            return
        self.tell("%s %s" % (venue["label"], "marked as asked for" if on else "no longer marked as asked"))
        self.rescan()

    # ---- buttons ----
    def open_folder(self):
        if self.report and self.report["folder"] and not os.environ.get("CTS_NOOPEN"):
            try:
                os.startfile(self.report["folder"])
            except OSError as e:
                self.tell("could not open the folder: %s" % e, "warn")

    def make_folder(self):
        """Make the shown week's folder on the Desktop."""
        if not self.report:
            return
        path = os.path.join(ts.DESKTOP, self.report["folder_name"])
        if not messagebox.askokcancel("Make the folder", "Make this folder on the Desktop?\n\n%s" % path,
                                      parent=self.root):
            return
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            self.tell("could not make the folder: %s" % e, "warn")
            return
        self.made_folder = "Made %s on the Desktop." % self.report["folder_name"]
        self.rescan()

    def save_list(self):
        if not self.report:
            return
        if self.report.get("problem"):
            self.tell("nothing to save for %s - %s" % (self.which_week(), self.report["problem"]), "warn")
            return
        out = os.path.join(ts.ROOT, "Lists")
        try:
            os.makedirs(out, exist_ok=True)
            path = os.path.join(out, "Timesheets %s.txt" % self.sunday.strftime("%d.%m.%y"))
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(ts.lines(self.report)) + "\n")
        except OSError as e:
            self.tell("could not save the list: %s" % e, "warn")
            return
        self.tell("saved: %s" % path)

    def missing_text(self):
        """The missing venues as a few lines to send to somebody, in collection order."""
        if not self.report or not self.report["missing"]:
            return ""
        out = ["Timesheets still needed for %s:" % ts.week_text(self.sunday)]
        for _, head, venues in ts.to_collect(self.report):
            out.append("")
            out.append("%s:" % head)
            for v in venues:
                top = v["ask"][0]["name"] if v.get("ask") else ", ".join(v["names"])
                out.append("  %s (%s) - %s" % (v["label"], v["day_text"], top))
                for name in v.get("away", []):
                    out.append("      (%s usually sends it but is not on this week)" % name)
        return "\n".join(out)

    def copy_missing(self):
        """Put the missing venues on the clipboard, to paste into a message. Only ever on this button -
        nothing else in the tool reads or writes the clipboard, and no test may call this."""
        text = self.missing_text()
        if not text:
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except tk.TclError:
            self.tell("could not copy the list", "warn")
            return
        self.tell("%d still to come in - copied, ready to paste" % len(self.report["missing"]))

    def show_late(self):
        """Which venues go missing most often, over the last finished weeks that were actually collected."""
        if self.roster is None or self.busy:
            return
        self.busy = True
        self.late_btn.configure(state="disabled")
        self.tell("Looking back over the last twelve weeks...", "busy")
        threading.Thread(target=self.work_late, daemon=True).start()

    def work_late(self):
        try:
            rows, weeks = ts.late_list(self.roster, datetime.date.today(), 12, self.places)
            self.queue.put(("late", (rows, weeks)))
        except Exception:
            self.queue.put(("late", ([], [])))

    def late_window(self, rows, weeks):
        top = tk.Toplevel(self.root)
        top.transient(self.root)
        top.title("Often late")
        top.configure(bg=SUNK)
        tk.Label(top, text="Over the last %d weeks that were collected" % len(weeks), font=(FONT_BOLD, 11),
                 bg=SUNK, fg=INK).pack(padx=18, pady=(16, 2), anchor="w")
        tk.Label(top, text=(("%s to %s" % (weeks[-1].strftime("%d %b"), weeks[0].strftime("%d %b %Y")))
                            if weeks else "no collected weeks to look at"),
                 font=(FONT, 9), bg=SUNK, fg=MUTED).pack(padx=18, anchor="w")
        box = tk.Frame(top, bg=PAPER, highlightbackground=LINE, highlightthickness=1)
        box.pack(padx=18, pady=14, fill="both", expand=True)
        if not rows:
            tk.Label(box, text="Nothing was late.", font=(FONT, 10), bg=PAPER, fg=GREEN).pack(padx=16, pady=16)
        for v in rows[:18]:
            line = tk.Frame(box, bg=PAPER)
            line.pack(fill="x", padx=16, pady=3)
            tk.Label(line, text=v["label"], font=(FONT, 10), bg=PAPER, fg=INK, anchor="w", width=24).pack(side="left")
            share = v["missed"] / float(max(1, v["of"]))
            tk.Label(line, text="%d of %d" % (v["missed"], v["of"]), font=(FONT_BOLD, 10), bg=PAPER,
                     fg=RED if share >= 0.5 else AMBER if share >= 0.25 else BODY).pack(side="left")
            bar = tk.Canvas(line, height=8, width=self.px(140), bg=PAPER, highlightthickness=0)
            bar.pack(side="right")
            bar.create_rectangle(0, 0, self.px(140), 8, fill=SOFT, outline="")
            bar.create_rectangle(0, 0, max(2, int(self.px(140) * share)), 8,
                                 fill=RED if share >= 0.5 else AMBER, outline="")
        Button(top, "Close", top.destroy, kind="primary", back=SUNK).pack(padx=18, pady=(0, 16), anchor="e")
        top.bind("<Escape>", lambda e: top.destroy())
        top.update_idletasks()
        top.geometry("+%d+%d" % (self.root.winfo_rootx() + max(0, (self.root.winfo_width() - top.winfo_width()) // 2),
                                 self.root.winfo_rooty() + 80))

    def assign(self):
        """Say which venue an unmatched file belongs to; the name is remembered in names.json."""
        if not self.report or not self.report["spare"]:
            return
        f = self.report["spare"][0]
        labels = [v["label"] for v in self.report["venues"]]

        def took(label):
            try:
                ts.save_name(f["stem"], label)
            except OSError as e:
                self.tell("could not remember that: %s" % e, "warn")
                return
            self.tell("%s counts as %s from now on" % (f["name"], label))
            self.rescan()

        Picker(self.root, "Which venue is \"%s\"?" % f["name"], labels, took)

    def on_close(self):
        try:
            self.settings["geometry"] = self.root.winfo_geometry()
            if not os.environ.get("CTS_GEOMETRY"):
                save_settings(self.settings)
        except tk.TclError:
            pass
        done = os.environ.get("CTS_DONE_FILE")
        if done:
            try:
                with open(done, "w", encoding="utf-8") as f:
                    f.write("closed\n")
            except OSError:
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        App(root)
    except Exception:
        messagebox.showerror("Sheet Tracker", "The window could not start:\n\n" + traceback.format_exc(limit=4))
        raise
    root.mainloop()


if __name__ == "__main__":
    main()
