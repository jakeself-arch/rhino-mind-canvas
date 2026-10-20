"""Fast UI: the inspector (props.py + eto/inspector.py), MCMatch (match.py), the current assembly
saved with the model (cmd/ui.py) and double-click editing.

Run inside Rhino (e.g. via the MCP run_python tool), in an EMPTY, unsaved document (it is cleared):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_inspector.py")["run"](__rhino_doc__)

Covers: what a selection stands for (parts -> their wall, window parts -> the window); every field
of walls, curtain walls, floors, roofs and windows reads a value; mixed values; changing a field
on several assemblies at once (length, choice, bool, assembly / window type, brick head snap);
the inspector window driven through its controls (no clicks): sections per kind, typing a height,
picking a detail level, ticking Flip, the empty view with the current assemblies; MCMatch (all
settings, assembly only, curtain walls, windows); the current assembly coming back from the
model; the double-click callback; the new command modules import.
"""

import importlib
import time

import Rhino
import scriptcontext

from mindcanvas import engine, library, match, meta, props, units
from mindcanvas.cmd import ui
from mindcanvas.eto import inspector

G = Rhino.Geometry
WOOD = "Ext - 2x6 Wood, Fiber Cement"
PART = "Int - 2x4 Wood Partition"
PART2 = 'Int - 3-5/8" Metal Stud Partition'
BRICK = 'Ext - Brick Veneer / 6" Metal Stud'
FLOOR = "Floor - 2x10 Wood Joists, Plywood"
ROOF = "Roof - Low Slope Membrane / 2x10 Joists"
CW = "CW - Captured, Aluminum 2-1/2 x 6"
FAILS = []


def say(*a):
    print(" ".join(str(x) for x in a))


def check(cond, label):
    say(("ok   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def _line(doc, x0, y0, x1, y1):
    f = lambda v: units.to_model(doc, v)
    return doc.Objects.FindId(doc.Objects.AddCurve(G.LineCurve(G.Point3d(f(x0), f(y0), 0), G.Point3d(f(x1), f(y1), 0))))


def _rect(doc, x0, y0, x1, y1):
    f = lambda v: units.to_model(doc, v)
    pts = [G.Point3d(f(x), f(y), 0) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))]
    return doc.Objects.FindId(doc.Objects.AddCurve(G.PolylineCurve(pts)))


def _drv(doc, oid):
    return doc.Objects.FindId(oid)


def _select(doc, objs):
    doc.Objects.UnselectAll()
    for o in objs:
        doc.Objects.Select(o.Id, True)


def _field(kind, key):
    return [f for f in props.fields(kind) if f.key == key][0]


def run(doc, lib=None):
    del FAILS[:]
    t0 = time.time()
    doc.Objects.Clear()
    engine.setup_document(doc)
    lib = lib or library.get()

    w1 = engine.create(doc, _line(doc, 0, 0, 240, 0), WOOD, {"height": 108, "lod": "design"}, lib).driver_id
    w2 = engine.create(doc, _line(doc, 0, 120, 240, 120), PART, {"height": 96, "lod": "design"}, lib).driver_id
    w3 = engine.create(doc, _line(doc, 0, 240, 240, 240), PART, {"height": 96, "lod": "design"}, lib).driver_id
    br = engine.create(doc, _line(doc, 0, -200, 240, -200), BRICK, {"height": 120, "lod": "design"}, lib).driver_id
    f = lambda v: units.to_model(doc, v)
    op, _ = engine.add_opening(doc, _drv(doc, br), "Window - Fixed", {"width": 36, "height": 48, "sill": 30},
                               G.Point3d(f(80), f(-200), 0), lib)
    op2, _ = engine.add_opening(doc, _drv(doc, br), "Window - Fixed", {"width": 24, "height": 24, "sill": 40},
                                G.Point3d(f(180), f(-200), 0), lib)
    fl = engine.create(doc, _rect(doc, 400, 0, 640, 240), FLOOR, {"base_offset": 108, "lod": "schematic"}, lib).driver_id
    rf = engine.create(doc, _rect(doc, 700, 0, 940, 240), ROOF, {"base_offset": 108, "lod": "schematic"}, lib).driver_id
    cw1 = engine.create(doc, _line(doc, 0, 400, 240, 400), CW, {"height": 160, "lod": "schematic"}, lib).driver_id
    cw2 = engine.create(doc, _line(doc, 0, 500, 240, 500), CW, {"height": 120, "lod": "schematic"}, lib).driver_id
    say("built the model in {:.1f}s".format(time.time() - t0))

    # -- what a selection stands for ---------------------------------------------------------
    part = meta.parts_of(doc, w1)[0]
    op_part = [p for p in meta.parts_of(doc, br) if meta.get(p, "mc.x.opening") == str(op.Id)][0]
    _select(doc, [part, op_part, _drv(doc, w1)])
    sel = props.selected(doc)
    check([d.Id for d in sel] == [w1, op.Id] or [d.Id for d in sel] == [op.Id, w1], "a part selects its wall, a window part the window")
    check([k for k, _ in props.by_kind(sel)] in (["wall", "opening"], ["opening", "wall"]), "grouped by kind")

    # -- every field reads ------------------------------------------------------------------
    for kind, oid in (("wall", w1), ("curtain_wall", cw1), ("floor", fl), ("roof", rf), ("opening", op.Id)):
        d = _drv(doc, oid)
        vals = dict((fd.key, props.value(lib, d, fd)) for fd in props.fields(kind))
        say("  {}: {}".format(kind, vals))
        missing = [k for k, v in vals.items() if v is None and not (kind == "opening" and k in ("swing", "hinge"))]
        check(not missing, "{} fields all read ({})".format(kind, missing or "ok"))
    check(props.value(lib, _drv(doc, w1), _field("wall", "height")) == 108.0, "wall height reads 108")
    check(props.value(lib, _drv(doc, fl), _field("floor", "base_offset")) == 108.0, "floor elevation reads 108")

    # -- mixed + apply ----------------------------------------------------------------------
    walls = [_drv(doc, w1), _drv(doc, w2)]
    h = _field("wall", "height")
    v, mixed = props.common(lib, walls, h)
    check(mixed, "two wall heights are mixed")
    t = time.time()
    rs = props.apply(doc, lib, walls, h, 100.0)
    say("  height on 2 walls in {:.2f}s".format(time.time() - t))
    check(len(rs) == 2 and all(meta.params(_drv(doc, i))["height"] == 100.0 for i in (w1, w2)), "height applied to both walls")
    check(meta.parts_of(doc, w1), "wall rebuilt with parts")
    check(props.apply(doc, lib, [_drv(doc, w1), _drv(doc, w2)], h, 100.0) == [], "same value: nothing rebuilt")
    props.apply(doc, lib, [_drv(doc, w2)], _field("wall", "assembly"), PART2)
    check(meta.get(_drv(doc, w2), meta.ASSEMBLY) == PART2, "assembly changed")
    props.apply(doc, lib, [_drv(doc, w1)], _field("wall", "reference"), "exterior_face")
    props.apply(doc, lib, [_drv(doc, w1)], _field("wall", "flip"), True)
    p = meta.params(_drv(doc, w1))
    check(p["reference"] == "exterior_face" and p["flip"] is True, "choice and bool applied")

    props.apply(doc, lib, [_drv(doc, op.Id)], _field("opening", "width"), 40.0, snap=False)
    check(meta.params(_drv(doc, op.Id))["width"] == 40.0, "window width applied")
    props.apply(doc, lib, [_drv(doc, op.Id)], _field("opening", "sill"), 33.0, snap=True)
    s = meta.params(_drv(doc, op.Id))
    snapped, delta = engine.snap_to_coursing(doc, _drv(doc, br), "Window - Fixed",
                                             {"width": 40.0, "height": 48.0, "sill": 33.0}, lib)
    check(s.get("sill") == snapped.get("sill", 33.0), "sill lands where the head snaps to the brick ({} -> {})".format(
        33.0, s.get("sill")))
    props.apply(doc, lib, [_drv(doc, op.Id), _drv(doc, op2.Id)], _field("opening", "assembly"), "Window - Casement")
    check(all(meta.get(_drv(doc, i), meta.ASSEMBLY) == "Window - Casement" for i in (op.Id, op2.Id)), "window type changed on both")
    check(any(meta.get(p_, "mc.x.opening") == str(op.Id) for p_ in meta.parts_of(doc, br)), "host rebuilt with the window")

    props.apply(doc, lib, [_drv(doc, rf)], _field("roof", "shape"), "gable")
    props.apply(doc, lib, [_drv(doc, rf)], _field("roof", "pitch"), 6.0)
    check(props.value(lib, _drv(doc, rf), _field("roof", "shape")) == "gable"
          and props.value(lib, _drv(doc, rf), _field("roof", "pitch")) == 6.0, "roof shape + pitch applied")
    props.apply(doc, lib, [_drv(doc, cw1)], _field("curtain_wall", "style"), "ssg4")
    props.apply(doc, lib, [_drv(doc, cw1)], _field("curtain_wall", "spacing"), 48.0)
    check(props.value(lib, _drv(doc, cw1), _field("curtain_wall", "style")) == "ssg4"
          and props.value(lib, _drv(doc, cw1), _field("curtain_wall", "spacing")) == 48.0, "curtain wall style + spacing applied")
    props.apply(doc, lib, [_drv(doc, fl)], _field("floor", "base_offset"), 120.0)
    check(props.value(lib, _drv(doc, fl), _field("floor", "base_offset")) == 120.0, "floor elevation applied")

    # -- match ------------------------------------------------------------------------------
    w3d = _drv(doc, w3)
    meta.write_driver(doc, w3d, "wall", PART, dict(meta.params(w3d), joins={"start": "butt"}))
    r = match.match(doc, lib, _drv(doc, w1), _drv(doc, w3), assembly_only=True)
    p3 = meta.params(_drv(doc, w3))
    check(meta.get(_drv(doc, w3), meta.ASSEMBLY) == WOOD and p3["height"] == 96, "match assembly only")
    match.match(doc, lib, _drv(doc, w1), _drv(doc, w3))
    p3 = meta.params(_drv(doc, w3))
    check(p3["height"] == 100.0 and p3["flip"] is True and p3["joins"] == {"start": "butt"}, "match all settings, own joins kept")
    check(meta.parts_of(doc, w3), "matched wall rebuilt")
    match.match(doc, lib, _drv(doc, cw1), _drv(doc, cw2))
    check(props.value(lib, _drv(doc, cw2), _field("curtain_wall", "style")) == "ssg4"
          and props.value(lib, _drv(doc, cw2), h) == 160.0, "match curtain wall")
    station = meta.params(_drv(doc, op2.Id))["station"]
    match.match(doc, lib, _drv(doc, op.Id), _drv(doc, op2.Id))
    p2 = meta.params(_drv(doc, op2.Id))
    check(p2["width"] == 40.0 and p2["station"] == station, "match window: size copied, place kept")
    try:
        match.match(doc, lib, _drv(doc, w1), _drv(doc, fl))
        check(False, "match refuses another kind")
    except ValueError:
        check(True, "match refuses another kind")

    # -- current assembly saved with the model ------------------------------------------------
    ui.set_current_assembly("wall", BRICK, doc)
    scriptcontext.sticky.pop(ui.LAST_ASSEMBLY + "wall", None)
    check(ui.current_assembly(lib, "wall", doc) == BRICK, "current wall assembly comes back from the model")
    doc.Strings.Delete(ui.DOC_SECTION, "current.floor")
    scriptcontext.sticky.pop(ui.LAST_ASSEMBLY + "floor", None)
    check(ui.current_assembly(lib, "floor", doc) == lib.assemblies("floor")[0], "no current floor: the library's first")

    # -- the window -------------------------------------------------------------------------
    ins = inspector.open_inspector()
    try:
        _select(doc, [meta.parts_of(doc, w1)[0], _drv(doc, op.Id)])   # parts were rebuilt above
        ins.refresh()
        kinds_ = [r_.kind for r_ in ins.rows]
        check("wall" in kinds_ and "opening" in kinds_, "inspector shows a wall and a window section")
        hrow = [r_ for r_ in ins.rows if r_.kind == "wall" and r_.field.key == "height"][0]
        check(hrow.control.Text == units.format_inches(100.0), "height box shows 8'-4\"")
        hrow.control.Text = "9'"
        hrow._typed()
        check(meta.params(_drv(doc, w1))["height"] == 108.0, "typing 9' in the height box rebuilds the wall")
        lrow = [r_ for r_ in ins.rows if r_.kind == "wall" and r_.field.key == "lod"][0]
        lrow.control.SelectedIndex = list(lrow.values).index("schematic")
        check(meta.params(_drv(doc, w1))["lod"] == "schematic", "picking a detail level applies it")
        frow = [r_ for r_ in ins.rows if r_.kind == "wall" and r_.field.key == "flip"][0]
        frow.control.Checked = False
        check(meta.params(_drv(doc, w1))["flip"] is False, "unticking Flip applies it")
        check(ins.ids and w1 in ins.ids, "inspector stays on the wall after its rebuild")
        _select(doc, [_drv(doc, w1), _drv(doc, w2)])
        ins.refresh(force=True)
        hrow = [r_ for r_ in ins.rows if r_.kind == "wall" and r_.field.key == "height"][0]
        check(hrow.mixed and hrow.control.Text == "", "two walls of different heights show (varies)")
        doc.Objects.UnselectAll()
        ins.refresh()
        check(not ins.rows, "nothing selected: the current-assembly view")
    finally:
        ins.form.Close()
    check(inspector.current() is None, "closing the inspector unhooks it")

    # -- double-click -------------------------------------------------------------------------
    cb = inspector.enable_double_click()
    check(cb.Enabled and inspector.enable_double_click() is cb, "double-click callback on (once)")
    _select(doc, [_drv(doc, w1)])
    check(inspector.open_editor_for(doc) == "inspector", "double-clicking a wall opens the inspector")
    ins = inspector.current()
    if ins is not None:
        ins.form.Close()
    inspector.disable_double_click()

    for name in ("inspector", "match", "wall", "floor", "roof", "curtainwall", "wallmass", "setup"):
        importlib.import_module("mindcanvas.cmd." + name)
    check(True, "command modules import")
    doc.Objects.UnselectAll()
    say("test_inspector: {} in {:.1f}s".format("OK" if not FAILS else "{} FAILED: {}".format(len(FAILS), FAILS),
                                               time.time() - t0))
    return FAILS
