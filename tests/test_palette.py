"""The assembly palette (eto/palette.py, eto/tiles.py, MCPaintAssembly).

Run inside Rhino (e.g. via the MCP run_python tool), in an EMPTY, unsaved document (it is cleared):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_palette.py")["run"](__rhino_doc__, captures=True)

Covers: every library assembly and window / door type renders a tile (cached per definition;
captures: a contact sheet docs/captures/palette_tiles.png); the window opens with a tab per kind
and a tile per entry; a click with nothing selected sets what the next one will be (saved with the
model; windows: MCOpening's type); a click with walls selected swaps them (and only walls), the
selection stays and its tiles are marked; a window type click swaps selected windows; the palette
follows the selection (tab + marks); apply_to for curtain walls / floors; the command modules
import. The window is driven through its methods (no clicks).
"""

import os
import time

import Eto.Drawing as drawing
import Rhino
import scriptcontext

from mindcanvas import engine, library, meta, units
from mindcanvas.cmd import opening as opcmd
from mindcanvas.cmd import ui
from mindcanvas.eto import palette, tiles
from mindcanvas.openings import core

G = Rhino.Geometry
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CAPTURES = os.path.join(ROOT, "docs", "captures")
WOOD = "Ext - 2x6 Wood, Fiber Cement"
BRICK = 'Ext - Brick Veneer / 6" Metal Stud'
FLOOR = "Floor - 2x10 Wood Joists, Plywood"
FAILS = []


def say(*a):
    print(" ".join(str(x) for x in a))


def check(cond, label):
    say(("ok   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def _ft(doc, v):
    return units.to_model(doc, v * 12.0)


def _line(doc, x0, y0, x1, y1):
    f = lambda v: _ft(doc, v)
    return doc.Objects.FindId(doc.Objects.AddCurve(G.LineCurve(G.Point3d(f(x0), f(y0), 0), G.Point3d(f(x1), f(y1), 0))))


def _rect(doc, x0, y0, x1, y1):
    f = lambda v: _ft(doc, v)
    pts = [G.Point3d(f(x), f(y), 0) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))]
    return doc.Objects.FindId(doc.Objects.AddCurve(G.PolylineCurve(pts)))


def contact_sheet(lib, path, cols=5, tw=168, th=92):
    items = []
    for k, _ in palette.TABS:
        items += [(k, n) for n in palette.names(lib, k)]
    rows = (len(items) + cols - 1) // cols
    sheet = drawing.Bitmap(cols * (tw + 8), rows * (th + 22), drawing.PixelFormat.Format32bppRgba)
    g = drawing.Graphics(sheet)
    font = drawing.Fonts.Sans(7.0)
    try:
        g.FillRectangle(drawing.Color.FromArgb(232, 232, 232), 0, 0, sheet.Width, sheet.Height)
        for i, (k, n) in enumerate(items):
            x, y = (i % cols) * (tw + 8) + 4, (i // cols) * (th + 22) + 4
            g.DrawImage(tiles.bitmap(lib, k, n, tw, th), float(x), float(y))
            g.DrawText(font, drawing.SolidBrush(drawing.Colors.Black), float(x), float(y + th + 3), n[:36])
    finally:
        g.Dispose()
    sheet.Save(path, drawing.ImageFormat.Png)
    return path


def run(doc, lib=None, captures=False):
    del FAILS[:]
    assert not doc.Path, "run the test in an empty, unsaved document"
    t0 = time.time()
    doc.Objects.Clear()
    engine.setup_document(doc)
    lib = lib or library.get()

    say("-- tiles")
    tiles._CACHE.clear()
    n_items, bad = 0, []
    for k, _ in palette.TABS:
        for n in palette.names(lib, k):
            n_items += 1
            try:
                b = tiles.bitmap(lib, k, n)
                if b.Width != 168 or b.Height != 92:
                    bad.append(n)
            except Exception as ex:
                bad.append("{} ({})".format(n, ex))
    check(not bad and n_items >= 30, "{} tiles render ({})".format(n_items, bad))
    b1 = tiles.bitmap(lib, "wall", WOOD)
    check(tiles.bitmap(lib, "wall", WOOD) is b1, "tiles are cached")
    if captures:
        say("capture", contact_sheet(lib, os.path.join(CAPTURES, "palette_tiles.png")))

    say("-- window")
    w1 = engine.create(doc, _line(doc, 0, 0, 20, 0), WOOD, {"lod": "schematic"}, lib).driver_id
    w2 = engine.create(doc, _line(doc, 0, 10, 20, 10), WOOD, {"lod": "schematic"}, lib).driver_id
    fl = engine.create(doc, _rect(doc, 0, -20, 20, -5), FLOOR, {"lod": "schematic", "base_offset": 120}, lib).driver_id
    win = engine.add_opening(doc, doc.Objects.FindId(w1), "Window - Fixed", {}, G.Point3d(_ft(doc, 6), 0, 0), lib)[0].Id
    old = palette.current_palette()
    if old is not None:
        old.form.Close()
    p = palette.open_palette()
    try:
        check([pg.Text.split(" (")[0] for pg in p.tabs.Pages] == [t for _, t in palette.TABS], "a tab per kind")
        check(len(p.tiles) == n_items, "a tile per library entry ({})".format(len(p.tiles)))
        doc.Objects.UnselectAll()
        p.refresh()
        p.pick("wall", BRICK)
        check(ui.current_assembly(lib, "wall", doc) == BRICK, "click, nothing selected: the next wall is the brick wall")
        check(doc.Strings.GetValue(ui.DOC_SECTION, "current.wall") == BRICK, "... saved with the model")
        check(all(meta.get(doc.Objects.FindId(i), meta.ASSEMBLY) == WOOD for i in (w1, w2)), "... and no wall changed")
        check(p.next.get("wall") == BRICK, "the tile is marked NEXT")
        doc.Objects.Select(w1, True)
        doc.Objects.Select(fl, True)
        p.refresh()
        check(("wall", WOOD) in p.selected and ("floor", FLOOR) in p.selected, "selected assemblies' tiles are marked")
        check(p.tabs.SelectedIndex in (0, 2), "the palette turns to a selected kind's tab ({})".format(p.tabs.SelectedIndex))
        p.pick("wall", BRICK)
        check(meta.get(doc.Objects.FindId(w1), meta.ASSEMBLY) == BRICK, "click with a wall selected: it takes the tile")
        check(meta.get(doc.Objects.FindId(w2), meta.ASSEMBLY) == WOOD, "an unselected wall keeps its assembly")
        check(meta.get(doc.Objects.FindId(fl), meta.ASSEMBLY) == FLOOR, "the selected floor is not touched by a wall tile")
        sel = [o.Id for o in doc.Objects.GetSelectedObjects(False, False)]
        check(w1 in sel, "the wall stays selected")
        check(("wall", BRICK) in p.selected, "its new tile is marked")
        doc.Objects.UnselectAll()
        doc.Objects.Select(win, True)
        p.pick("opening", "Window - Casement")
        check(meta.get(doc.Objects.FindId(win), meta.ASSEMBLY) == "Window - Casement", "window tile swaps the selected window")
        check((scriptcontext.sticky.get(opcmd.STICKY) or {}).get("type") == "Window - Casement", "... and is MCOpening's next type")
        check(p.focus() == ("opening", "Window - Casement") or p.tabs.SelectedIndex != 4,
              "the buttons act on the open tab's NEXT tile")
        doc.Objects.UnselectAll()
        floor2 = [n for n in lib.assemblies("floor") if n != FLOOR][0]
        rs = palette.apply_to(doc, lib, [doc.Objects.FindId(fl)], floor2)
        check(rs and meta.get(doc.Objects.FindId(fl), meta.ASSEMBLY) == floor2, "apply_to swaps a floor")
        p.refresh()
    finally:
        p.form.Close()
    check(palette.current_palette() is None, "closing the palette forgets it")
    for m in ("palette", "paintassembly"):
        try:
            __import__("mindcanvas.cmd." + m, fromlist=["x"])
            ok = True
        except Exception as ex:
            ok = False
            say(ex)
        check(ok, "command module {} imports".format(m))
    say("{} checks failed; {:.1f}s".format(len(FAILS), time.time() - t0))
    for f in FAILS:
        say("  FAIL " + f)
    return not FAILS
