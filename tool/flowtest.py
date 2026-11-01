"""Drives the window through everything a hand would do, off-screen, and reports anything that breaks.

    python flowtest.py

Tkinter swallows exceptions raised inside callbacks, so the window can look fine while something is
quietly broken underneath; this installs report_callback_exception and fails on anything caught there.
Nothing is written outside this tool's own folder, the roster is not re-downloaded, no folder is made on
the Desktop, the clipboard is never touched, and the window is parked off-screen.
"""
import datetime
import importlib.util
import os
import sys
import tempfile
import time
import tkinter as tk
import traceback
from tkinter import messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import timesheets as ts  # noqa: E402

os.environ.update(CTS_GEOMETRY="1180x780+-4000+-4000", CTS_NO_DOWNLOAD="1", CTS_NOOPEN="1")
os.environ.pop("CTS_AUTORUN", None)
problems, done, slow = [], [], []


def fail(where, why):
    problems.append("%s: %s" % (where, why))


SLOW = 2.0                                            # a step taking longer than this is worth knowing about


def step(name, fn):
    """Run one thing a hand would do and keep going if it breaks. Slow ones are called out: a window
    that takes seconds to answer a click is a defect even when nothing raises."""
    start = time.time()
    try:
        fn()
        done.append(name)
    except Exception:
        fail(name, traceback.format_exc(limit=3).strip().splitlines()[-1])
    took = time.time() - start
    if took > SLOW:
        slow.append((took, name))


APP_MOD = None


def main():
    global APP_MOD
    spec = importlib.util.spec_from_file_location("app_under_test", os.path.join(HERE, "app.pyw"))
    app_mod = APP_MOD = importlib.util.module_from_spec(spec)
    sys.modules["app_under_test"] = app_mod
    spec.loader.exec_module(app_mod)
    messagebox.askokcancel = lambda *a, **k: False     # never actually make a folder from a test
    messagebox.showerror = lambda *a, **k: None
    root = tk.Tk()
    caught = []
    root.report_callback_exception = lambda *e: caught.append("".join(traceback.format_exception(*e)).strip())
    ts.DESKTOP = tempfile.mkdtemp(prefix="ts-flow-")   # a made folder would land here, not on the real Desktop
    ts.CHASED = os.path.join(ts.DESKTOP, "chased.json")    # and his own chased marks are left alone
    app = app_mod.App(root)

    def ready():
        if app.report is None:
            root.after(200, ready)
            return
        run(app, root)
        root.after(80, root.destroy)

    root.after(300, ready)
    root.mainloop()
    for c in caught:
        fail("an error escaped into the window", c.splitlines()[-1])
    print("flow check - %d things done" % len(done))
    for took, name in sorted(slow, reverse=True):
        print("  SLOW    %5.1fs  %s" % (took, name))
    for p in problems:
        print("  BROKEN  " + p)
    print("\n%s" % ("ALL OK" if not problems else "%d BROKEN" % len(problems)))
    return 1 if problems else 0


def run(app, root):
    """Everything a hand would do, in the order a hand would do it."""
    def settle():
        root.update_idletasks()
        root.update()

    step("opens on the right week", lambda: check(app.sunday == ts.default_week(datetime.date.today()),
                                                  "opened on %s" % app.sunday))
    step("the default tab is what is still to get", lambda: check(
        app.view == ("todo" if app.report["missing"] else "in") or not app.report["venues"],
        "opened on the %r tab" % app.view))
    step("the three week pills are there",
         lambda: check(len(app.pills) == 3 and all(p.label.cget("text") for p in app.pills.values()),
                       "a week pill is missing or blank"))

    for key in ("last", "this", "next", "last"):
        step("click %r" % key, lambda k=key: (app.go(k), settle()))
        step("after %r: the shown week is the one chosen" % key,
             lambda k=key: check(app.sunday == ts.pick_week(k, datetime.date.today()), "it moved somewhere else"))
        step("after %r: the headline says something" % key, lambda: check(
            bool(app.big.cget("text")) and bool(app.headline.cget("text")), "the hero is blank"))
        step("after %r: 'Every venue' really is every venue" % key, lambda: (
            app.show_view("all"), settle(), check(
                rows_on_show(app) == len(app.report["venues"]), "rows %d, venues %d"
                % (rows_on_show(app), len(app.report["venues"])))))
        step("after %r: save the list" % key, lambda: app.save_list())
        step("after %r: the missing text builds" % key, lambda: app.missing_text())
        step("after %r: open folder" % key, lambda: app.open_folder())
        step("after %r: make folder" % key, lambda: app.make_folder())
        step("after %r: check again without a download" % key, lambda: (app.rescan(), settle()))

    for i in range(4):                                 # back through weeks the roster may not cover
        step("step back %d" % (i + 1), lambda: (app.step(-1), settle()))
    for i in range(9):
        step("step forward %d" % (i + 1), lambda: (app.step(1), settle()))
    step("far past", lambda: (app.go("this"), app.step(-40), settle()))
    step("far future", lambda: (app.step(80), settle()))
    step("back to this week", lambda: (app.go("this"), settle()))

    def hover_each():
        rows = [w for w in app.listing.inner.winfo_children() if getattr(w, "venue_row", False)]
        for t in rows[:8]:
            t.event_generate("<Enter>")
            settle()
            if app.report["venues"] and not app.status.get().strip():
                raise AssertionError("hovering a tile said nothing")
            t.event_generate("<Leave>")               # a hand always leaves again
            settle()

    step("hover every tile, and come off it", hover_each)
    step("the status bar goes back to the week after hovering", lambda: check(
        ts.week_text(app.sunday) in app.status.get(), "it is stuck on %r" % app.status.get()))

    for w, h in ((940, 640), (1500, 900), (1000, 700)):
        step("resize to %dx%d" % (w, h), lambda w=w, h=h: (root.geometry("%dx%d+-4000+-4000" % (w, h)), settle()))
    step("every filter draws exactly what its chip claims", lambda: filters_agree(app, settle))
    step("the wheel scrolls the list", lambda: scrolls(app, root))
    step("the scroll bar can be dragged", lambda: dragging(app, root))
    step("PageUp / PageDown move a week", lambda: (root.event_generate("<Prior>"), settle(),
                                                   root.event_generate("<Next>"), settle()))
    step("F5 re-reads the roster", lambda: (root.event_generate("<F5>"), settle()))
    step("a week with no folder at all", lambda: (app.go("next"), app.step(40), settle()))
    step("...and saving that one", lambda: app.save_list())
    step("back home", lambda: (app.go("this"), settle()))

    # --- the paths a hand reaches less often ---
    step("make the folder, for real this time", lambda: make_for_real(app, root, settle))
    step("the odd-file picker opens and closes", lambda: picker(app, root, settle))
    step("teaching a file name, and forgetting it again", lambda: teach(app, settle))
    step("squeezed to one column", lambda: (root.geometry("600x600+-4000+-4000"), settle()))
    step("...and back", lambda: (root.geometry("1180x780+-4000+-4000"), settle()))
    step("the roster failing", lambda: roster_fails(app, root, settle))
    step("clicking Check again twice in a row", lambda: (app.reload(True), app.reload(True), settle()))
    step("clicking venues: open a sheet, chase a missing one", lambda: clicking(app, settle))
    step("the often-late list", lambda: late(app, settle))
    step("it notices a sheet arriving on its own", lambda: notices(app, root, settle))
    step("the heartbeat changes cells, not the whole list", lambda: quiet_redraw(app, settle))
    step("dark theme on", lambda: theme(app, settle, "dark"))
    step("...everything still works in the dark", lambda: (app.go("last"), settle(), app.step(-1), settle(),
                                                           app.save_list(), app.missing_text()))
    step("...and the who-has-it window", lambda: dark_who(app, settle))
    step("light theme back", lambda: theme(app, settle, "light"))


def notices(app, root, settle):
    """Drop a sheet into the week's folder and let the window find it by itself - no button pressed.

    This is the heartbeat: he adds photos while the window is open, so it has to keep up on its own.
    """
    app.go("last")
    settle()
    folder = app.report.get("folder")
    if not folder or not os.path.isdir(folder):
        return                                        # nothing to drop into; nothing to prove
    missing = app.report["missing"]
    if not missing:
        return
    venue = missing[0]
    was_in = len(app.report["in"])
    dropped = os.path.join(folder, "%s.jpg" % venue["label"].replace("/", "-"))
    if os.path.exists(dropped):
        return
    try:
        with open(dropped, "w", encoding="utf-8") as f:
            f.write("x")
        for _ in range(int(14 / 0.1)):                # wait for the heartbeat, not for a button
            settle()
            if len(app.report["in"]) > was_in:
                break
            time.sleep(0.1)
        if len(app.report["in"]) <= was_in:
            raise AssertionError("a sheet appeared in the folder and the window never noticed")
        if "just in" not in app.status.get() and "changed" not in app.status.get():
            raise AssertionError("it noticed but said nothing: %r" % app.status.get())
    finally:
        try:
            os.remove(dropped)                        # put his folder back exactly as it was
        except OSError:
            pass
        for _ in range(int(14 / 0.1)):
            settle()
            if len(app.report["in"]) == was_in:
                break
            time.sleep(0.1)


def quiet_redraw(app, settle):
    """The heartbeat must change only the cells that moved, and never tear the list down.

    Rebuilding all thirty-nine rows several times a minute is what the user saw as the screen flashing:
    "donot make the screen flash ... if it is changed then hcange that cell not eveyting". So this
    pins the contract: words moving is a touch-up with nothing destroyed, and the list genuinely
    reordering makes touch_up() stand aside so the caller redraws it properly.
    """
    import app_under_test as m
    app.show_view("all")
    settle()

    built = [0]
    real_row = m.App.row

    def counted(self, v, tone, i=0):
        built[0] += 1
        return real_row(self, v, tone, i)

    def rows():
        return [w for w in app.listing.inner.winfo_children() if getattr(w, "venue_row", False)]

    m.App.row = counted
    try:
        start = len(rows())
        out = next((n for n, v in enumerate(app.report["venues"]) if not v["files"]), None)
        if out is None:
            return                                    # every sheet is in: no countdown to move
        said = "not on until Sun 19:00 (in 7 min)"
        app.report["venues"][out]["when"] = dict(app.report["venues"][out].get("when") or {},
                                                 state="later", text=said)
        kept = rows()[out].cells["when"]
        if not app.touch_up():
            raise AssertionError("the words moved but it would not touch the row up")
        if built[0]:
            raise AssertionError("it rebuilt %d rows to change one word - that is the flashing" % built[0])
        if kept.cget("text") != said:
            raise AssertionError("the cell was not updated: %r" % kept.cget("text"))
        if rows()[out].cells["when"] is not kept or len(rows()) != start:
            raise AssertionError("the row was replaced rather than updated")

        # now make the list genuinely reorder: a venue comes on shift and sorts to the top
        app.show_view("todo")
        settle()
        order = [w.venue["label"] for w in rows()]
        if len(order) < 2:
            return                                    # nothing to reorder
        last = next(v for v in app.report["missing"] if v["label"] == order[-1])
        last["when"] = dict(last.get("when") or {}, state="on", text="on now, until 03:00",
                            **{"from": datetime.datetime.now()})
        if [v["label"] for v, _ in app.venues_for("todo")] == order:
            return                                    # it did not actually move; nothing to prove
        built[0] = 0
        if app.touch_up():
            raise AssertionError("the list reordered and it touched up anyway - rows would be wrong")
        if built[0]:
            raise AssertionError("touch_up() drew rows itself; that is the caller's job")
    finally:
        m.App.row = real_row
        app.rescan()
        settle()


def theme(app, settle, want):
    import app_under_test as m
    if app.theme != want:
        app.flip_theme()
        settle()
    if app.theme != want:
        raise AssertionError("asked for the %s theme, got %s" % (want, app.theme))
    if m.PAPER != (m.DARK if want == "dark" else m.LIGHT)["PAPER"]:
        raise AssertionError("the %s palette was not put in place" % want)
    if not rows_on_show(app) and app.report["venues"]:
        raise AssertionError("the window came back empty after changing theme")


def dark_who(app, settle):
    gone = [v for v in app.report["venues"] if not v["files"]]
    if not gone:
        return
    app.who(gone[0])
    settle()
    if not tops(app):
        raise AssertionError("the who-has-it window did not open in the dark theme")
    for t in tops(app):
        t.destroy()
    settle()


def tops(app):
    return [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]


def clicking(app, settle):
    """A tile whose sheet is in opens it; a missing one asks who is holding it; chasing sticks."""
    app.go("last")                                    # a week with some in and one missing
    settle()
    got = [v for v in app.report["venues"] if v["files"]]
    gone = [v for v in app.report["venues"] if not v["files"]]
    if got:
        app.clicked(got[0])                           # CTS_NOOPEN: says what it would open, opens nothing
        settle()
        if "would open" not in app.status.get():
            raise AssertionError("clicking a sheet that is in did not offer to open it")
        app.who(got[0])                               # right-click: who worked there, sheet in or not
        settle()
        if not tops(app):
            raise AssertionError("right-clicking a venue opened nothing")
        for t in tops(app):
            t.destroy()
        settle()
    if not gone:
        return
    v = gone[0]
    if not v.get("holders"):
        raise AssertionError("a missing venue with nobody to ask for it")
    app.clicked(v)                                    # a missing one opens the who-has-it window
    settle()
    if not tops(app):
        raise AssertionError("clicking a missing venue opened no window")
    for t in tops(app):
        t.destroy()
    settle()
    app.chase(v)                                      # the window's Mark as asked button does this
    settle()
    again = [x for x in app.report["missing"] if x["label"] == v["label"]]
    if not again or not again[0].get("chased"):
        raise AssertionError("marking a venue as chased did not stick")
    app.chase(again[0])
    settle()
    back = [x for x in app.report["missing"] if x["label"] == v["label"]]
    if back and back[0].get("chased"):
        raise AssertionError("unmarking a chased venue did not stick")


def late(app, settle):
    """The often-late list: worked out in a thread, then shown in its own window."""
    app.show_late()
    for _ in range(600):
        settle()
        if not app.busy:
            break
        time.sleep(0.05)
    if app.busy:
        raise AssertionError("the often-late list never finished")
    tops = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]
    if not tops:
        raise AssertionError("the often-late list opened no window")
    for t in tops:
        t.destroy()
    settle()


def make_for_real(app, root, settle):
    """Make folder, with the question answered yes, into the scratch Desktop this test set up."""
    app.go("next")
    settle()
    messagebox.askokcancel = lambda *a, **k: True
    try:
        app.make_folder()
        settle()
        made = os.path.join(ts.DESKTOP, app.report["folder_name"])
        if not os.path.isdir(made):
            raise AssertionError("pressing Make folder made no folder")
        if app.make_btn.enabled:
            raise AssertionError("Make folder is still on after the folder was made")
    finally:
        messagebox.askokcancel = lambda *a, **k: False
        app.go("this")
        settle()


def picker(app, root, settle):
    """The 'which venue is this?' list, opened and shut without choosing."""
    labels = [v["label"] for v in app.report["venues"]] or ["Somewhere"]
    chosen = []
    p = app_picker(app, labels, chosen.append)
    settle()
    if not p.list.get(0):
        raise AssertionError("the picker came up empty")
    p.take()                                          # choose the first and make sure it comes back
    settle()
    if not chosen:
        raise AssertionError("choosing a venue in the picker told nobody")


def app_picker(app, labels, on_pick):
    return APP_MOD.Picker(app.root, "Which venue is this?", labels, on_pick)


def teach(app, settle):
    """Teach a made-up file name, see it kept, then take it away again."""
    name = "zz test sheet do not keep"
    label = app.report["venues"][0]["label"] if app.report["venues"] else "Somewhere"
    ts.save_name(name, label)
    if ts.load_names().get(ts.canon(name)) != label:
        raise AssertionError("the taught name was not kept")
    if ts.match_file(name, [{"label": label, "aliases": ts.aliases_for(label)}])[0] != label:
        raise AssertionError("the taught name is not used when matching")
    ts.save_name(name, None)
    if ts.canon(name) in ts.load_names():
        raise AssertionError("the taught name would not go away again")


def roster_fails(app, root, settle):
    """No roster, no network: the window has to say so and stay alive."""
    real = ts.download_roster
    ts.download_roster = lambda *a, **k: (_ for _ in ()).throw(ts.Problem("no roster and no saved copy"))
    was = os.environ.pop("CTS_NO_DOWNLOAD", None)
    try:
        app.reload(True)
        wait(app, settle)
        if app.busy:
            raise AssertionError("it is still waiting on the roster")
        if "roster" not in app.status.get().lower():
            raise AssertionError("it did not say the roster failed, it says %r" % app.status.get())
    finally:
        ts.download_roster = real
        if was:
            os.environ["CTS_NO_DOWNLOAD"] = was
        app.reload(True)
        wait(app, settle)


def wait(app, settle, seconds=8):
    """Let the reading thread finish. Real time has to pass, or the window's 200ms poll never fires."""
    for _ in range(int(seconds / 0.05)):
        settle()
        if not app.busy:
            return
        time.sleep(0.05)


def rows_on_show(app):
    return sum(1 for w in app.listing.inner.winfo_children() if getattr(w, "venue_row", False))


def filters_agree(app, settle):
    """Every tab's number must be the number of rows it draws. Nothing may be silently cut short."""
    app.go("this")
    settle()
    bad = []
    for key in list(app.tabs):
        app.show_view(key)
        settle()
        claimed = int(app.tabs[key].count.cget("text"))
        drawn = rows_on_show(app)
        if claimed != drawn:
            bad.append("%s says %d, draws %d" % (key, claimed, drawn))
    if "all" in app.tabs:
        app.show_view("all")
    settle()
    if bad:
        raise AssertionError("; ".join(bad))


def scrolls(app, root):
    """The wheel has to work over a row, not just over the gaps between them."""
    app.listing.canvas.yview_moveto(0)
    root.update_idletasks()
    lo, hi = app.listing.canvas.yview()
    if lo <= 0 and hi >= 1:
        return                                        # it all fits: nothing to scroll is right
    rows = [w for w in app.listing.inner.winfo_children() if getattr(w, "venue_row", False)]
    target = rows[3] if len(rows) > 3 else app.listing.canvas
    target.event_generate("<MouseWheel>", delta=-360, x=10, y=10)
    root.update_idletasks()
    if app.listing.canvas.yview()[0] <= lo:
        raise AssertionError("the wheel over a row did not scroll the list")


def dragging(app, root):
    """The bar has to be visible and draggable when there is more than fits - version 2 had neither."""
    app.listing.canvas.yview_moveto(0)
    root.update_idletasks()
    lo, hi = app.listing.canvas.yview()
    if lo <= 0 and hi >= 1:
        return
    if not app.listing.rail.winfo_manager():
        raise AssertionError("there is more than fits but no scroll bar is shown")
    h = max(1, app.listing.rail.winfo_height())
    app.listing.press(type("E", (), {"y": int(h * 0.7)})())
    root.update_idletasks()
    if app.listing.canvas.yview()[0] <= 0:
        raise AssertionError("dragging the scroll bar moved nothing")
    app.listing.grab = None
    app.listing.canvas.yview_moveto(0)


def check(ok, why):
    if not ok:
        raise AssertionError(why)


if __name__ == "__main__":
    sys.exit(main())

