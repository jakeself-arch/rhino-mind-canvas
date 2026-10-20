"""Editing in the viewport: drag handles, hover labels, ghost previews (mindcanvas/viewport/).

Run inside Rhino (e.g. via the MCP run_python tool), in an EMPTY, unsaved document (it is cleared):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_viewui.py")["run"](__rhino_doc__, captures=True)

Covers: the handles of a wall, curtain wall, window, door, floor and roof (keys, values a drag
makes, snapping, Shift = fine steps, limits); a drag driven through the mouse callback with
stand-in mouse events (hit test at the arrow tip, ghost + tag while dragging, applied on release:
wall height, flip click, window width / move, floor elevation, roof pitch); a drag back to the
start changes nothing; a mass-driven wall's
mass follows a height drag; an opening mass follows a window drag; the hover pick (nearest
assembly to the camera, labels); MCOpening's preview (3D ray and plan-view hits, the brick head
snap) and MCWall's band (faces, flip); captures of the handles, a drag and both previews.
The mouse callback is not clicked: Rhino's InCommand() is True inside run_python, so the
overlay's busy check is switched off for the test.
"""

import os
import time

import System
import Rhino

from mindcanvas import engine, library, masses, meta, props, units, wallmasses
from mindcanvas.cmd import opening as opcmd
from mindcanvas.openings import core
from mindcanvas.viewport import ghost, overlay, shapes

G = Rhino.Geometry
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CAPTURES = os.path.join(ROOT, "docs", "captures")
WOOD = "Ext - 2x6 Wood, Fiber Cement"
BRICK = 'Ext - Brick Veneer / 6" Metal Stud'
FLOOR = "Floor - 2x10 Wood Joists, Plywood"
ROOF = "Roof - Asphalt Shingle / 2x8 Rafters, Vented Attic"
CW = "CW - Captured, Aluminum 2-1/2 x 6"
WINDOW = "Window - Fixed"
FAILS = []


def say(*a):
    print(" ".join(str(x) for x in a))


def check(cond, label):
    say(("ok   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def near(a, b, tol=1.0 / 64):
    return abs(float(a) - float(b)) < tol


class Ev(object):
    """Stands in for Rhino.UI.MouseCallbackEventArgs."""

    def __init__(self, view, xy, shift=False):
        self.View = view
        self.ViewportPoint = System.Drawing.Point(int(round(xy[0])), int(round(xy[1])))
        self.MouseButton = Rhino.UI.MouseButton.Left
        self.ShiftKeyDown = shift
        self.Cancel = False


def _ft(doc, v):
    return units.to_model(doc, v * 12.0)


def _line(doc, x0, y0, x1, y1, z=0.0):
    f = lambda v: _ft(doc, v)
    return doc.Objects.FindId(doc.Objects.AddCurve(G.LineCurve(G.Point3d(f(x0), f(y0), f(z)), G.Point3d(f(x1), f(y1), f(z)))))


def _rect(doc, x0, y0, x1, y1, z=0.0):
    f = lambda v: _ft(doc, v)
    pts = [G.Point3d(f(x), f(y), f(z)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))]
    return doc.Objects.FindId(doc.Objects.AddCurve(G.PolylineCurve(pts)))


def _box(doc, x0, x1, y0, y1, z0, z1):
    f = lambda v: _ft(doc, v)
    b = G.Box(G.Plane.WorldXY, G.Interval(f(x0), f(x1)), G.Interval(f(y0), f(y1)), G.Interval(f(z0), f(z1))).ToBrep()
    return doc.Objects.FindId(doc.Objects.AddBrep(b))


def _drv(doc, oid):
    return doc.Objects.FindId(oid)


def _val(lib, d, key):
    v = props.settings(lib, d).get(key)
    if isinstance(v, bool) or v is None:
        return v
    try:
        return units.parse_length(v)
    except (TypeError, ValueError):
        return v


def _drag(doc, view, d, key, dx_px=0, dy_px=0, shift=False):
    """Select d, grab its handle `key` at the arrow tip, move the mouse, release. Returns the
    Drag shown just before the release."""
    vp = view.ActiveViewport
    doc.Objects.UnselectAll()
    doc.Objects.Select(d.Id, True)
    st = overlay.state()
    st["drag"] = None
    overlay.refresh(doc)
    hs = [h for s in st["shapes"] for h in s.handles if h.key == key and s.driver.Id == d.Id]
    assert hs, "no {} handle".format(key)
    tx, ty = overlay.screen(vp, overlay.tip(vp, hs[0]))
    overlay.on_move(Ev(view, (tx + 2, ty + 1)))
    e = Ev(view, (tx + 2, ty + 1))
    overlay.on_down(e)
    assert e.Cancel and st["drag"] is not None, "grabbed {}".format(key)
    overlay.on_move(Ev(view, (tx + 2 + dx_px, ty + 1 + dy_px), shift))
    drag = st["drag"]["drag"]
    overlay.on_up(Ev(view, (tx + 2 + dx_px, ty + 1 + dy_px), shift))
    return drag


def _capture(view, name, extra=None):
    """The view at its own size (screen points used by the overlay stay where they are)."""
    if extra is not None:
        Rhino.Display.DisplayPipeline.DrawForeground += extra
    try:
        bmp = view.CaptureToBitmap(view.ActiveViewport.Size)
    finally:
        if extra is not None:
            Rhino.Display.DisplayPipeline.DrawForeground -= extra
    path = os.path.join(CAPTURES, name)
    bmp.Save(path)
    return path


class _Args(object):
    pass


# -- tests ---------------------------------------------------------------------------------------
def handle_math(doc, lib, ids):
    s = units.inch_scale(doc)
    w = shapes.shape_of(doc, lib, _drv(doc, ids["wall"]))
    check([h.key for h in w.handles] == ["height", "base", "flip"], "wall handles: height, base, flip")
    check(w.handle("height").at(13.4 * s, False).changes == {"height": 133.0}, "height drag snaps to 1\"")
    check(w.handle("height").at(13.4 * s, True).changes == {"height": 133.375}, "Shift: 1/8\" steps")
    check(w.handle("height").at(-500 * s, False).changes == {"height": 12.0}, "a wall stays at least 1' high")
    b = w.handle("base").at(6 * s, False).changes
    check(b == {"base_offset": -6.0, "height": 126.0}, "base drag down: base -6\", top stays ({})".format(b))
    check(w.handle("flip").click and w.handle("flip").at(0, False).changes == {"flip": True}, "flip is a click")
    check(len(w.outline) == 6 and "7-1/2\" thick" in w.lines[1], "wall outline + label {}".format(w.lines))
    o = shapes.shape_of(doc, lib, _drv(doc, ids["window"]))
    check(sorted(h.key for h in o.handles) == ["head", "left", "move", "right", "sill"], "window handles")
    st0 = meta.params(_drv(doc, ids["window"]))["station"]
    r = o.handle("right").at(6 * s, False).changes
    check(near(r["width"], 54) and near(r["station"], st0 + 3), "right edge: +6\" wide, center +3\" ({})".format(r))
    l = o.handle("left").at(6 * s, False).changes
    check(near(l["station"], st0 - 3), "left edge: center -3\"")
    sl = o.handle("sill").at(4 * s, False).changes
    check(near(sl["sill"], 32) and near(sl["height"], 52), "sill down 4\": head stays ({})".format(sl))
    check(o.handle("sill").at(100 * s, False).changes["sill"] == 0.0, "sill stops at 0")
    dr = shapes.shape_of(doc, lib, _drv(doc, ids["door"]))
    check("sill" not in [h.key for h in dr.handles], "doors have no sill handle")
    c = shapes.shape_of(doc, lib, _drv(doc, ids["cw"]))
    check([h.key for h in c.handles] == ["height", "base"], "curtain wall: height, base")
    f = shapes.shape_of(doc, lib, _drv(doc, ids["floor"]))
    check(f.handle("elevation").at(-12 * s, False).changes == {"base_offset": 108.0}, "floor elevation drag")
    rf = shapes.shape_of(doc, lib, _drv(doc, ids["roof"]))
    check([h.key for h in rf.handles] == ["plate", "overhang", "pitch"], "roof: plate, overhang, pitch")
    p = rf.handle("pitch")
    run_ = p.anchor.Z - rf.handle("plate").anchor.Z      # 6 in 12 rise
    check(near(p.at(run_ / 3.0, False).changes["pitch"], 8.0, 0.01), "pitch: a third more rise = 8 in 12")
    check(rf.handle("overhang").at(-100 * s, False).changes["overhang"] == 0.0, "overhang stops at 0")


def mouse_drags(doc, lib, ids, view):
    s = units.inch_scale(doc)
    vp = view.ActiveViewport
    wd = _drv(doc, ids["wall"])
    h0 = _val(lib, wd, "height")
    drag = _drag(doc, view, wd, "height", dy_px=-60)
    wd = _drv(doc, ids["wall"])
    check(drag is not None and "Height" in drag.text and len(drag.ghost) == 6, "dragging shows a ghost + tag")
    check(near(_val(lib, wd, "height"), drag.changes["height"]) and _val(lib, wd, "height") > h0,
          "height drag applied on release ({} -> {})".format(h0, _val(lib, wd, "height")))
    check(any(d.Id == wd.Id for d in props.selected(doc)), "the wall stays selected")
    drag = _drag(doc, view, wd, "height", dy_px=0)
    check(not drag.changes or near(drag.changes.get("height", 0), _val(lib, _drv(doc, ids["wall"]), "height")),
          "a drag back to the start changes nothing")
    _drag(doc, view, _drv(doc, ids["wall"]), "flip")
    check(_val(lib, _drv(doc, ids["wall"]), "flip") is True, "clicking the flip arrow flips the wall")
    _drag(doc, view, _drv(doc, ids["wall"]), "flip")
    check(not _val(lib, _drv(doc, ids["wall"]), "flip"), "and back")
    win = _drv(doc, ids["window"])
    w0 = _val(lib, win, "width")
    _drag(doc, view, win, "right", dx_px=40)
    win = _drv(doc, ids["window"])
    check(_val(lib, win, "width") > w0, "window right edge widens it ({} -> {})".format(w0, _val(lib, win, "width")))
    st0 = meta.params(win)["station"]
    _drag(doc, view, win, "move", dx_px=-40)
    check(meta.params(_drv(doc, ids["window"]))["station"] != st0, "window slides along the wall")
    fl = _drv(doc, ids["floor"])
    b0 = _val(lib, fl, "base_offset")
    _drag(doc, view, fl, "elevation", dy_px=-30)
    check(_val(lib, _drv(doc, ids["floor"]), "base_offset") > b0, "floor elevation drag")
    rf = _drv(doc, ids["roof"])
    p0 = float(_val(lib, rf, "pitch"))
    _drag(doc, view, rf, "pitch", dy_px=-40)
    p1 = float(_val(lib, _drv(doc, ids["roof"]), "pitch"))
    check(p1 > p0 and near(p1 * 2, round(p1 * 2), 1e-6), "roof pitch drag snaps to 1/2 in 12 ({} -> {})".format(p0, p1))
    # (one undo step per drag: Undo cannot run inside run_python's command; checked by hand)


def mass_follow(doc, lib, view):
    s = units.inch_scale(doc)
    m, sr = wallmasses.make(doc, _box(doc, 0, 20, 40, 41, 0, 9), WOOD, {}, lib)
    w = wallmasses.wall_of(doc, doc.Objects.FindId(m.Id))
    sh = shapes.shape_of(doc, lib, w)
    overlay.apply(doc, w.Id, sh.handle("height").at(12 * s, False).changes, "Height")
    bb = doc.Objects.FindId(m.Id).Geometry.GetBoundingBox(True)
    check(near((bb.Max.Z - bb.Min.Z) / s, 120.0, 0.05), "a mass-driven wall's mass follows a height drag ({:.3f}\")".format((bb.Max.Z - bb.Min.Z) / s))
    sel = doc.Objects.FindId(m.Id)
    doc.Objects.UnselectAll()
    doc.Objects.Select(sel.Id, True)
    check([x.Id for x in props.selected(doc)] == [w.Id], "selecting the mass gives its wall's handles")
    om, osr = masses.make(doc, _box(doc, 8, 11, 39.5, 41.5, 3, 7), WINDOW, {}, lib)
    op = masses.openings_of(doc, om.Id)[0]
    so = shapes.shape_of(doc, lib, op)
    overlay.apply(doc, op.Id, so.handle("right").at(12 * s, False).changes, "Width", snap=False)
    bb = doc.Objects.FindId(om.Id).Geometry.GetBoundingBox(True)
    check(near((bb.Max.X - bb.Min.X) / s, 48.0, 0.6), "an opening mass follows a window drag ({:.2f}\" wide)".format((bb.Max.X - bb.Min.X) / s))


def hover(doc, lib, ids, view):
    vp = view.ActiveViewport
    s = units.inch_scale(doc)
    p = overlay.screen(vp, G.Point3d(_ft(doc, 3), 0, _ft(doc, 3)))
    hv = overlay.hover_pick(view, p)
    check(hv is not None and hv.kind == "wall" and hv.lines[0] == WOOD, "hover: the wall, with its assembly")
    fl = shapes.shape_of(doc, lib, _drv(doc, ids["floor"]))
    c = fl.handles[0].anchor
    hv = overlay.hover_pick(view, overlay.screen(vp, c))
    check(hv is not None and hv.kind == "floor" and "deep" in hv.lines[1], "hover: the floor in front of the roof ({})".format(hv and hv.lines))
    hv = overlay.hover_pick(view, (2, 2))
    check(hv is None, "hover over nothing: no label")


def previews(doc, lib, ids, view):
    s = units.inch_scale(doc)
    vp = view.ActiveViewport
    st = opcmd.Settings(doc, lib, WINDOW, {"width": 36, "height": 48, "sill": 30}, True)
    pv = ghost.OpeningPreview(doc, lib, st)
    check(len(pv.tgts) == len(meta.all_drivers(doc, "wall")) + len(meta.all_drivers(doc, "curtain_wall")), "preview: every wall is a target")
    brick = _drv(doc, ids["brick"])
    vp.SetCameraLocations(G.Point3d(_ft(doc, 106), 0, _ft(doc, 5)), G.Point3d(_ft(doc, 98), _ft(doc, -22), _ft(doc, 9)))
    p3 = G.Point3d(_ft(doc, 106), _ft(doc, 0), _ft(doc, 4))
    xy = overlay.screen(vp, p3)
    hit = pv.pick(view, xy)
    check(hit is not None and hit[0].driver.Id == brick.Id, "3D: the mouse ray finds the brick wall")
    pv.current, pv.xy = hit, xy
    polys, lines = pv.ghost()
    check(len(polys) == 6 and len(lines) >= 2 and "3'-0\"" in lines[1], "ghost: rough opening on both faces + size tag {}".format(lines))
    snapped = pv.params(hit[0])
    check(not near(snapped["sill"], 30) or not near(snapped["height"], 48), "SnapHead moves the ghost's head to the coursing ({})".format(snapped))
    check(any("coursing" in l for l in lines), "the tag says so")
    top = [v for v in doc.Views if v.ActiveViewport.Name == "Top"][0]
    xy2 = overlay.screen(top.ActiveViewport, G.Point3d(_ft(doc, 106), _ft(doc, 0.3), 0))
    h2 = pv.pick(top, xy2)
    check(h2 is not None and h2[0].driver.Id == brick.Id, "plan view: the nearest wall curve")
    check(pv.pick(top, overlay.screen(top.ActiveViewport, G.Point3d(_ft(doc, 106), _ft(doc, 30), 0))) is None,
          "plan view: nothing far from a wall")
    band = ghost.WallBand(doc, lib, BRICK, {"height": 120, "reference": "core_exterior"})
    pts = [G.Point3d(0, _ft(doc, -25), 0), G.Point3d(_ft(doc, 20), _ft(doc, -25), 0), G.Point3d(_ft(doc, 20), _ft(doc, -40), 0)]
    ext, itr = band.faces(pts)
    check(ext[0].Y > pts[0].Y and itr[0].Y < pts[0].Y, "band: exterior on the left of the drawing direction")
    check(near((ext[0].Y - itr[0].Y) / s, (band.y_ext - band.y_int) / s), "band: the assembly's thickness")
    fb = ghost.WallBand(doc, lib, BRICK, {"height": 120, "reference": "core_exterior", "flip": True})
    e2, i2 = fb.faces(pts)
    check(e2[0].Y < pts[0].Y, "band: Flip puts the exterior on the right")
    return pv, band, pts


def run(doc, lib=None, captures=False):
    del FAILS[:]
    assert not doc.Path, "run the test in an empty, unsaved document"
    t0 = time.time()
    doc.Objects.Clear()
    engine.setup_document(doc)
    lib = lib or library.get()
    overlay.disable()
    overlay.enable(True, True, snap=True)
    busy, later = overlay._busy, overlay._later
    overlay._busy = lambda: False          # run_python runs inside a command
    overlay._later = lambda fn: fn()
    try:
        ids = {}
        ids["wall"] = engine.create(doc, _line(doc, 0, 0, 20, 0), WOOD, {"lod": "schematic"}, lib).driver_id
        wd = _drv(doc, ids["wall"])
        ids["window"] = engine.add_opening(doc, wd, WINDOW, {"width": 48, "height": 48, "sill": 36}, G.Point3d(_ft(doc, 6), 0, 0), lib)[0].Id
        ids["door"] = engine.add_opening(doc, _drv(doc, ids["wall"]), "Door - Aluminum Entrance, Full Lite", {}, G.Point3d(_ft(doc, 14), 0, 0), lib)[0].Id
        ids["floor"] = engine.create(doc, _rect(doc, 0, -16, 20, -5), FLOOR, {"lod": "schematic", "base_offset": 120}, lib).driver_id
        ids["roof"] = engine.create(doc, _rect(doc, 25, 0, 40, 14), ROOF, {"lod": "schematic", "base_offset": 96}, lib).driver_id
        ids["cw"] = engine.create(doc, _line(doc, 50, 0, 70, 0), CW, {"lod": "schematic"}, lib).driver_id
        ids["brick"] = engine.create(doc, _line(doc, 100, 0, 112, 0), BRICK, {"lod": "schematic"}, lib).driver_id
        view = doc.Views.ActiveView
        for v in doc.Views:
            if v.ActiveViewport.Name == "Perspective":
                view = v
        doc.Views.ActiveView = view
        view.ActiveViewport.SetCameraLocations(G.Point3d(_ft(doc, 10), 0, _ft(doc, 5)), G.Point3d(_ft(doc, -5), _ft(doc, -30), _ft(doc, 14)))
        top = [v for v in doc.Views if v.ActiveViewport.Name == "Top"][0]
        top.ActiveViewport.ZoomBoundingBox(G.BoundingBox(G.Point3d(_ft(doc, 95), _ft(doc, -10), 0), G.Point3d(_ft(doc, 117), _ft(doc, 10), 0)))
        say("-- handle math")
        handle_math(doc, lib, ids)
        say("-- drags through the mouse callback")
        mouse_drags(doc, lib, ids, view)
        say("-- hover")
        hover(doc, lib, ids, view)
        say("-- previews")
        pv, band, pts = previews(doc, lib, ids, view)
        say("-- masses follow")
        mass_follow(doc, lib, view)
        if captures:
            view.ActiveViewport.SetCameraLocations(G.Point3d(_ft(doc, 10), 0, _ft(doc, 5)), G.Point3d(_ft(doc, -5), _ft(doc, -30), _ft(doc, 14)))
            doc.Objects.UnselectAll()
            doc.Objects.Select(ids["wall"], True)
            doc.Objects.Select(ids["window"], True)
            overlay.refresh(doc)
            st = overlay.state()
            st["hot"] = [h for s_ in st["shapes"] for h in s_.handles if h.key == "height"][0]
            st["mouse_xy"], st["mouse_view"] = overlay.screen(view.ActiveViewport, overlay.tip(view.ActiveViewport, st["hot"])), view
            say("capture", _capture(view, "viewui_handles.png"))
            st["hot"] = None
            h = [h for s_ in st["shapes"] for h in s_.handles if h.key == "height"][0]
            st["drag"] = {"shape": st["shapes"][0], "handle": h, "a0": 0.0, "view": view, "xy": (450, 140),
                          "drag": h.at(_ft(doc, 2), False)}
            say("capture", _capture(view, "viewui_drag.png"))
            st["drag"] = None
            hv = overlay.hover_pick(view, overlay.screen(view.ActiveViewport, G.Point3d(_ft(doc, 3), 0, _ft(doc, 3))))
            doc.Objects.UnselectAll()
            overlay.refresh(doc)
            st["hover"], st["hover_view"] = hv, view
            st["mouse_xy"] = st["picked_xy"] = overlay.screen(view.ActiveViewport, G.Point3d(_ft(doc, 3), 0, _ft(doc, 3)))
            say("capture", _capture(view, "viewui_hover.png"))
            st["hover"] = None

            def draw_op(sender, e):
                a = _Args()
                a.Display, a.Viewport = e.Display, e.Viewport
                pv.on_draw(None, a)
            view.ActiveViewport.SetCameraLocations(G.Point3d(_ft(doc, 106), 0, _ft(doc, 5)), G.Point3d(_ft(doc, 98), _ft(doc, -22), _ft(doc, 9)))
            p3 = G.Point3d(_ft(doc, 106), 0, _ft(doc, 4))
            pv.xy = overlay.screen(view.ActiveViewport, p3)
            pv.current = pv.pick(view, pv.xy)
            say("capture", _capture(view, "viewui_opening_preview.png", draw_op))

            def draw_band(sender, e):
                a = _Args()
                a.Display, a.Viewport, a.CurrentPoint = e.Display, e.Viewport, pts[-1]
                band.on_draw(None, a)
            band.points = pts[:2]
            view.ActiveViewport.SetCameraLocations(G.Point3d(_ft(doc, 10), _ft(doc, -30), 0), G.Point3d(_ft(doc, -12), _ft(doc, -62), _ft(doc, 30)))
            band.xy = overlay.screen(view.ActiveViewport, pts[-1])
            say("capture", _capture(view, "viewui_wall_band.png", draw_band))
    finally:
        overlay._busy, overlay._later = busy, later
    say("{} checks failed; {:.1f}s".format(len(FAILS), time.time() - t0))
    for f in FAILS:
        say("  FAIL " + f)
    return not FAILS
