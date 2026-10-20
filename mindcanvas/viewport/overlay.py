"""The viewport overlay: drag handles on the selected assemblies and hover labels.

Handles: select walls, curtain walls, windows / doors, floors or roofs (their curve or any part)
and arrows show on them (viewport/shapes.py). Drag an arrow: a ghost of the assembly follows with
a dimension tag; release to apply (one undo step), through the same code as the inspector
(engine.update_params / update_opening), so mass-driven walls and opening masses follow. Click the
arrow out of a wall's exterior face to flip it. Hold Shift for 1/8" steps. Dragging back to where
it started changes nothing.

Hover labels: rest the mouse on an assembly for a moment: it is outlined and a label shows its
assembly and main sizes.

Both are off while a Rhino command runs. enable(handles, labels) / disable() (MCHandles,
MCSetup). The display / mouse / Idle handlers live in scriptcontext.sticky and call this module
through sys.modules, so a dev reload takes effect without re-registering them.
"""

import sys
import time

import System
import Rhino
import scriptcontext

G = Rhino.Geometry
STATE_KEY = "mindcanvas.viewport"
MODULE = "mindcanvas.viewport.overlay"
ARROW_PX = 44           # arrow length on screen
HIT_PX = 11             # a click this close to an arrow's tip grabs it
REST_S = 0.35           # the mouse rests this long before the hover pick
MOVE_PX = 4
MAX_SHAPES = 16         # handles for at most this many selected assemblies
PARALLEL = 0.97         # arrows pointing (almost) at the camera are hidden

HANDLE = (0, 120, 230)
HOT = (255, 120, 0)
GHOST = (255, 120, 0)
HOVER = (0, 150, 255)
TAG_FILL = (255, 255, 255)
TAG_INK = (30, 30, 30)
TEXT_PX = 12


def _c(rgb, a=255):
    return System.Drawing.Color.FromArgb(a, rgb[0], rgb[1], rgb[2])


def _mod():
    return sys.modules.get(MODULE) or __import__(MODULE, fromlist=["x"])


def state():
    st = scriptcontext.sticky.get(STATE_KEY)
    if st is None:
        st = {"handles": False, "labels": False, "snap": True, "hooks": None, "mouse": None,
              "dirty": True, "shapes": [], "hot": None, "drag": None,
              "hover": None, "hover_view": None, "mouse_xy": None, "mouse_view": None,
              "moved_at": 0.0, "picked_xy": None, "pending": None}
        scriptcontext.sticky[STATE_KEY] = st
    return st


def is_on():
    st = scriptcontext.sticky.get(STATE_KEY)
    return bool(st and (st["handles"] or st["labels"]))


# -- registration -------------------------------------------------------------------------------
def enable(handles=True, labels=True, snap=None):
    st = state()
    st["handles"], st["labels"] = bool(handles), bool(labels)
    st["off"] = False
    if snap is not None:
        st["snap"] = bool(snap)
    if st["hooks"] is None:
        draw = lambda s, e: _mod().on_draw(e)
        mark = lambda s, e: _mod().mark()
        idle = lambda s, e: _mod().on_idle()
        st["hooks"] = (draw, mark, idle)
        Rhino.Display.DisplayPipeline.DrawForeground += draw
        Rhino.RhinoDoc.SelectObjects += mark
        Rhino.RhinoDoc.DeselectObjects += mark
        Rhino.RhinoDoc.DeselectAllObjects += mark
        Rhino.RhinoDoc.ReplaceRhinoObject += mark
        Rhino.Commands.Command.EndCommand += mark
        Rhino.RhinoApp.Idle += idle
    if st["mouse"] is None:
        st["mouse"] = _make_mouse()
    st["mouse"].Enabled = True
    st["dirty"] = True
    _redraw()
    return st


def disable():
    st = scriptcontext.sticky.get(STATE_KEY)
    if st is None:
        return
    if st["hooks"] is not None:
        draw, mark, idle = st["hooks"]
        Rhino.Display.DisplayPipeline.DrawForeground -= draw
        Rhino.RhinoDoc.SelectObjects -= mark
        Rhino.RhinoDoc.DeselectObjects -= mark
        Rhino.RhinoDoc.DeselectAllObjects -= mark
        Rhino.RhinoDoc.ReplaceRhinoObject -= mark
        Rhino.Commands.Command.EndCommand -= mark
        Rhino.RhinoApp.Idle -= idle
        st["hooks"] = None
    if st["mouse"] is not None:
        st["mouse"].Enabled = False
    st.update(handles=False, labels=False, shapes=[], hot=None, drag=None, hover=None, off=True)
    _redraw()


def _make_mouse():
    class _MindCanvasViewportMouse(Rhino.UI.MouseCallback):
        __namespace__ = "MindCanvasViewport"

        def OnMouseMove(self, e):
            try:
                _mod().on_move(e)
            except Exception as ex:
                print("Mind Canvas viewport (move): {}".format(ex))

        def OnMouseDown(self, e):
            try:
                _mod().on_down(e)
            except Exception as ex:
                print("Mind Canvas viewport (down): {}".format(ex))

        def OnMouseUp(self, e):
            try:
                _mod().on_up(e)
            except Exception as ex:
                print("Mind Canvas viewport (up): {}".format(ex))

    return _MindCanvasViewportMouse()


def _redraw():
    doc = Rhino.RhinoDoc.ActiveDoc
    if doc is not None:
        doc.Views.Redraw()


def _busy():
    return Rhino.Commands.Command.InCommand()


# -- the selected assemblies' shapes ------------------------------------------------------------
def mark():
    state()["dirty"] = True


def refresh(doc=None):
    """Rebuild the handles of the selected assemblies (called on Idle after a selection change)."""
    from .. import library, props
    from . import shapes
    st = state()
    st["dirty"] = False
    doc = doc or Rhino.RhinoDoc.ActiveDoc
    out = []
    if doc is not None and st["handles"]:
        lib = library.get()
        for d in props.selected(doc)[:MAX_SHAPES]:
            sh = shapes.shape_of(doc, lib, d)
            if sh is not None and sh.handles:
                out.append(sh)
    st["shapes"] = out
    st["hot"] = None
    return out


def on_idle():
    st = state()
    if st["drag"] is not None:
        return
    if st["dirty"] and not _busy():
        refresh()
        _redraw()
    if st["labels"] and st["mouse_xy"] is not None and not _busy():
        if time.time() - st["moved_at"] >= REST_S and st["mouse_xy"] != st["picked_xy"]:
            st["picked_xy"] = st["mouse_xy"]
            view = st["mouse_view"]
            try:
                hov = hover_pick(view, st["mouse_xy"])
            except Exception as ex:
                hov = None
                print("Mind Canvas hover: {}".format(ex))
            if hov is not None or st["hover"] is not None:
                st["hover"], st["hover_view"] = hov, view
                if view is not None:
                    view.Redraw()


def hover_pick(view, xy):
    """The Shape of the assembly under a screen point (nearest to the camera), or None."""
    from .. import library, props
    from . import shapes
    if view is None:
        return None
    doc = view.Document
    vp = view.ActiveViewport
    x, y = xy
    pc = Rhino.Input.Custom.PickContext()
    pc.View = view
    pc.PickStyle = Rhino.Input.Custom.PickStyle.PointPick
    try:
        pc.PickMode = Rhino.Input.Custom.PickMode.Shaded if vp.DisplayMode.ShadedPipelineRequired \
            else Rhino.Input.Custom.PickMode.Wireframe
    except Exception:
        pass
    pc.SetPickTransform(vp.GetPickTransform(System.Drawing.Point(int(x), int(y))))
    ok, line = vp.GetFrustumLine(float(x), float(y))
    if ok:
        pc.PickLine = line
    pc.UpdateClippingPlanes()
    refs = doc.Objects.PickObjects(pc) or []
    cam = vp.CameraLocation
    best = None
    for r in refs:
        o = r.Object()
        if o is None:
            continue
        d = props.assembly_of(doc, o)
        if d is None or d.IsDeleted:
            continue
        p = r.SelectionPoint()
        dist = cam.DistanceTo(p) if p.IsValid else 1e30       # nearest to the camera wins
        if best is None or dist < best[0]:
            best = (dist, d)
    if best is None:
        return None
    return shapes.shape_of(doc, library.get(), best[1]) or _bare(doc, best[1])


def _bare(doc, d):
    from .. import library
    from . import shapes
    sh = shapes.Shape("other", d)
    sh.lines = shapes.label_lines(doc, library.get(), d)
    return sh


# -- screen math ----------------------------------------------------------------------------------
def tip(vp, h):
    """World point of a handle's arrow tip (ARROW_PX from its anchor on screen)."""
    return h.anchor + h.axis * (ARROW_PX / pixels_per_unit(vp, h.anchor))


def pixels_per_unit(vp, p):
    res = vp.GetWorldToScreenScale(p)
    ppu = res[1] if isinstance(res, tuple) else res
    return ppu if ppu and ppu > 1e-9 else 1.0


def visible(vp, h):
    cam = vp.CameraDirection
    L = cam.Length
    return L < 1e-12 or abs(cam * h.axis) / L < PARALLEL


def screen(vp, p):
    q = vp.WorldToClient(p)
    return q.X, q.Y


def handle_at(vp, shapes_, xy):
    """(shape, handle) whose arrow tip is nearest to the screen point (within HIT_PX), or None."""
    best = None
    for sh in shapes_:
        for h in sh.handles:
            if not visible(vp, h):
                continue
            tx, ty = screen(vp, tip(vp, h))
            dd = ((tx - xy[0]) ** 2 + (ty - xy[1]) ** 2) ** 0.5
            if dd <= HIT_PX and (best is None or dd < best[0]):
                best = (dd, sh, h)
    return (best[1], best[2]) if best else None


def axis_param(h, ray):
    """Distance (model units) along the handle's axis from its anchor to the point closest to the
    mouse ray; None when the ray runs (almost) along the axis."""
    axis = G.Line(h.anchor, h.anchor + h.axis)
    d = ray.Direction
    L = d.Length
    if L < 1e-12 or abs(d * h.axis) / L > 0.999:
        return None
    ok, a, b = Rhino.Geometry.Intersect.Intersection.LineLine(axis, ray)    # closest points (skew lines)
    return a if ok else None


def _ray(view, xy):
    ok, line = view.ActiveViewport.GetFrustumLine(float(xy[0]), float(xy[1]))
    return line if ok else None


# -- mouse ----------------------------------------------------------------------------------------
def _xy(e):
    p = e.ViewportPoint
    return (p.X, p.Y)


def on_move(e):
    st = state()
    xy = _xy(e)
    dr = st["drag"]
    if dr is not None:
        ray = _ray(e.View, xy)
        a = axis_param(dr["handle"], ray) if ray is not None else None
        if a is not None:
            dr["drag"] = dr["handle"].at(a - dr["a0"], bool(e.ShiftKeyDown))
        dr["xy"] = xy
        e.View.Redraw()
        return
    if _busy():
        return
    if st["handles"] and st["shapes"]:
        hit = handle_at(e.View.ActiveViewport, st["shapes"], xy)
        hot = hit[1] if hit else None
        if hot is not st["hot"]:
            st["hot"] = hot
            e.View.Redraw()
    if st["labels"]:
        old = st["mouse_xy"]
        st["mouse_xy"], st["mouse_view"] = xy, e.View
        if old is None or abs(old[0] - xy[0]) + abs(old[1] - xy[1]) > MOVE_PX:
            st["moved_at"] = time.time()
            if st["hover"] is not None and st["picked_xy"] is not None and \
                    abs(st["picked_xy"][0] - xy[0]) + abs(st["picked_xy"][1] - xy[1]) > MOVE_PX:
                st["hover"] = None
                e.View.Redraw()


def on_down(e):
    st = state()
    if e.MouseButton != Rhino.UI.MouseButton.Left or _busy() or not st["handles"] or not st["shapes"]:
        return
    xy = _xy(e)
    hit = handle_at(e.View.ActiveViewport, st["shapes"], xy)
    if hit is None:
        return
    e.Cancel = True
    sh, h = hit
    ray = _ray(e.View, xy)
    a0 = axis_param(h, ray) if ray is not None else None
    st["drag"] = {"shape": sh, "handle": h, "a0": a0 if a0 is not None else 0.0, "view": e.View,
                  "xy": xy, "drag": h.at(0.0, False) if h.click else None}
    st["hover"] = None
    e.View.Redraw()


def on_up(e):
    st = state()
    dr = st["drag"]
    if dr is None:
        return
    e.Cancel = True
    st["drag"] = None
    drag = dr["drag"]
    if drag is not None and drag.changes:
        did = dr["shape"].driver.Id
        changes = dict(drag.changes)
        label = dr["handle"].label
        doc = e.View.Document
        _later(lambda: _mod().apply(doc, did, changes, label))
    e.View.Redraw()


def _later(fn):
    def _once(sender, e):
        Rhino.RhinoApp.Idle -= _once
        try:
            fn()
        except Exception as ex:
            print("Mind Canvas: {}".format(ex))
    Rhino.RhinoApp.Idle += _once


# -- applying a drag ------------------------------------------------------------------------------
def _differs(a, b):
    from .. import units
    if isinstance(b, bool) or isinstance(a, bool):
        return bool(a) != bool(b)
    try:
        return abs(units.parse_length(a) - units.parse_length(b)) > 1.0 / 128
    except Exception:
        return a != b


def apply(doc, driver_id, changes, label="Drag", snap=None):
    """Apply a drag's changes to one driver (one undo step) and keep it selected. Returns the
    BuildResult, or None when nothing changed."""
    from .. import engine, library, meta, props, units
    from ..openings import core
    lib = library.get()
    d = doc.Objects.FindId(driver_id)
    if d is None or d.IsDeleted:
        return None
    cur = props.settings(lib, d)
    cur.update(meta.params(d))
    todo = dict((k, v) for k, v in changes.items() if _differs(cur.get(k), v))
    if not todo:
        return None
    if snap is None:
        snap = state()["snap"]
    t0 = time.time()
    undo = doc.BeginUndoRecord("Mind Canvas: " + label)
    try:
        if meta.get(d, meta.TYPE) == "opening":
            host = core.host_of(doc, d)
            if snap and host is not None and any(k in props.SNAP_KEYS for k in todo):
                full = dict((k, units.parse_length(cur[k])) for k in ("width", "height", "sill"))
                full.update((k, v) for k, v in todo.items() if k in full)
                out, delta = engine.snap_to_coursing(doc, host, meta.get(d, meta.ASSEMBLY), full, lib)
                if delta:
                    for k in ("height", "sill"):
                        if out.get(k) != full.get(k):
                            todo[k] = out[k]
            r = engine.update_opening(doc, d, todo, lib=lib)
        else:
            r = engine.update_params(doc, d, todo, lib)
    finally:
        doc.EndUndoRecord(undo)
    doc.Objects.Select(driver_id, True)
    st = state()
    st["dirty"] = True
    doc.Views.Redraw()
    Rhino.RhinoApp.WriteLine("Mind Canvas: {} -> {} ({:.2f}s)".format(
        label, ", ".join("{} {}".format(k, v) for k, v in sorted(todo.items())), time.time() - t0))
    for w in getattr(r, "warnings", []) or []:
        Rhino.RhinoApp.WriteLine("  warning: " + w)
    return r


# -- drawing --------------------------------------------------------------------------------------
def _polys(disp, polys, rgb, width):
    col = _c(rgb)
    for p in polys:
        if len(p) >= 2:
            disp.DrawPolyline(p, col, width)


def _tag(disp, lines, x, y, vp=None):
    """A white label box near screen (x, y): below right of it, kept inside the viewport."""
    if not lines:
        return
    w, h = 0, 0
    sizes = []
    for ln in lines:
        try:
            r = disp.Measure2dText(ln, G.Point2d(0, 0), False, 0.0, TEXT_PX, "Arial")
            sz = (r.Width, max(r.Height, TEXT_PX))
        except Exception:
            sz = (int(len(ln) * TEXT_PX * 0.55), TEXT_PX)
        sizes.append(sz)
        w = max(w, sz[0])
    pad, gap = 6, 4
    h = sum(s[1] for s in sizes) + gap * (len(lines) - 1) + 2 * pad
    W = w + 2 * pad
    if vp is not None:
        size = vp.Size
        if x + W > size.Width - 4:
            x = max(4, x - W - 36)             # to the left of the cursor
        if y + h > size.Height - 4:
            y = max(4, y - h - 28)             # above it
        x, y = max(4, x), max(4, y)
    rect = System.Drawing.Rectangle(int(x), int(y), int(W), int(h))
    disp.Draw2dRectangle(rect, _c(TAG_INK, 160), 1, _c(TAG_FILL, 235))
    yy = y + pad
    for ln, sz in zip(lines, sizes):
        disp.Draw2dText(ln, _c(TAG_INK), G.Point2d(x + pad, yy), False, TEXT_PX, "Arial")   # top-left
        yy += sz[1] + gap


def _arrow(disp, vp, h, rgb, hot):
    t = tip(vp, h)
    col = _c(rgb)
    head = 16.0 if hot else 12.0
    disp.DrawLine(h.anchor, t, col, 3 if hot else 2)
    disp.DrawArrowHead(t, h.axis, col, head, 0.0)
    if h.key == "move":          # slides both ways
        back = h.anchor - (t - h.anchor)
        disp.DrawLine(h.anchor, back, col, 3 if hot else 2)
        disp.DrawArrowHead(back, -h.axis, col, head, 0.0)
    disp.DrawPoint(h.anchor, Rhino.Display.PointStyle.RoundSimple, 6 if hot else 4, col)


def on_draw(e):
    try:
        _draw(e)
    except Exception as ex:
        print("Mind Canvas viewport (draw): {}".format(ex))


def _draw(e):
    st = state()
    disp = e.Display
    vp = e.Viewport
    dr = st["drag"]
    if dr is not None:
        if dr["view"].ActiveViewportID != vp.Id:
            return
        h = dr["handle"]
        _arrow(disp, vp, h, HOT, True)
        drag = dr["drag"]
        if drag is not None:
            _polys(disp, drag.ghost, GHOST, 2)
            x, y = dr["xy"]
            _tag(disp, [drag.text], x + 18, y + 14, vp)
        return
    if _busy():
        return
    if st["handles"]:
        for sh in st["shapes"]:
            for h in sh.handles:
                if visible(vp, h):
                    hot = h is st["hot"]
                    _arrow(disp, vp, h, HOT if hot else HANDLE, hot)
        if st["hot"] is not None and st["mouse_xy"] is not None and st["mouse_view"] is not None \
                and st["mouse_view"].ActiveViewportID == vp.Id:
            x, y = st["mouse_xy"]
            _tag(disp, [st["hot"].label + (" (click)" if st["hot"].click else " (drag)")], x + 18, y + 14, vp)
    hov = st["hover"]
    if st["labels"] and hov is not None and st["hover_view"] is not None \
            and st["hover_view"].ActiveViewportID == vp.Id and st["mouse_xy"] is not None:
        _polys(disp, hov.outline, HOVER, 2)
        x, y = st["picked_xy"] or st["mouse_xy"]
        _tag(disp, hov.lines, x + 18, y + 14, vp)
