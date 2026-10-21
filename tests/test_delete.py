"""Deleting an assembly keeps its curve (live.py + engine.release).

Run inside Rhino (e.g. via the MCP run_python tool), in an EMPTY, unsaved document (it is cleared):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_delete.py")["run"](__rhino_doc__)

The user's Delete is simulated by deleting every part of an assembly (clicking one selects its
group) outside live.quiet, then running live mode's Idle handler once.
"""

import time

import Rhino
import scriptcontext

from mindcanvas import docutil, engine, laylink, library, live, meta, units, wallmasses

G = Rhino.Geometry
WOOD = "Ext - 2x6 Wood, Fiber Cement"
BRICK = "Ext - Brick Veneer / 6\" Metal Stud"
FLOOR = "Floor - 2x10 Wood Joists, Plywood"
ROOF = "Roof - Low Slope Membrane / 2x10 Joists"
CW = "CW - Captured, Aluminum 2-1/2 x 6"
STAIR = "Stair - Concrete"
FAILS = []


def say(*a):
    print(" ".join(str(x) for x in a))


def check(cond, label):
    say(("ok   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def _layer(doc, name):
    return docutil.ensure_layer(doc, name)


def _add(doc, geom, layer):
    a = Rhino.DocObjects.ObjectAttributes()
    a.LayerIndex = layer
    return doc.Objects.FindId(doc.Objects.Add(geom, a))


def _line(doc, layer, x0, y0, x1, y1):
    f = lambda v: units.to_model(doc, v)
    return _add(doc, G.LineCurve(G.Point3d(f(x0), f(y0), 0), G.Point3d(f(x1), f(y1), 0)), layer)


def _rect(doc, layer, x0, y0, x1, y1):
    f = lambda v: units.to_model(doc, v)
    pts = [G.Point3d(f(x), f(y), 0) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))]
    return _add(doc, G.PolylineCurve(pts), layer)


def _idle():
    live._state()["handlers"][2](None, None)


def _delete_assembly(doc, driver_id, only=None):
    """What Delete does to a clicked assembly: its whole group (or only the first `only` parts)."""
    parts = meta.parts_of(doc, driver_id)
    for o in parts[:only] if only else parts:
        doc.Objects.Delete(o, True)
    _idle()


def _plain(doc, oid, layer, label):
    o = doc.Objects.FindId(oid)
    check(o is not None and not o.IsDeleted, label + ": the curve stays")
    if o is None:
        return
    keys = [k for k in (o.Attributes.GetUserStrings().AllKeys or []) if k and k.startswith("mc.")]
    check(not meta.is_driver(o) and not keys, label + ": it drives nothing (no mc.* user text: {})".format(keys))
    check(o.Attributes.LayerIndex == layer, label + ": back on its layer ({})".format(
        doc.Layers[o.Attributes.LayerIndex].FullPath))
    check(not meta.parts_of(doc, oid), label + ": no parts left")


def run(doc, lib=None):
    del FAILS[:]
    assert not doc.Path, "test_delete clears the document: run it in an empty, unsaved model"
    t0 = time.time()
    doc.Objects.Clear()
    engine.setup_document(doc)
    lib = lib or library.get()
    live.enable()
    sketch = _layer(doc, "Sketch")
    plan = _layer(doc, "Plan")
    doc.Layers.SetCurrentLayerIndex(plan, True)

    # a wall with a window
    w = engine.create(doc, _line(doc, sketch, 0, 0, 240, 0), BRICK, {"height": 120, "lod": "design"}, lib).driver_id
    f = lambda v: units.to_model(doc, v)
    op, _ = engine.add_opening(doc, doc.Objects.FindId(w), "Window - Fixed", {"width": 36, "height": 48, "sill": 30},
                               G.Point3d(f(80), 0, 0), lib)
    check(doc.Groups.FindName(engine._group_name("wall", w)) is not None, "the wall's parts are one group")
    _delete_assembly(doc, w)
    _plain(doc, w, sketch, "wall")
    o = doc.Objects.FindId(op.Id)
    check(o is None or o.IsDeleted, "the wall's window is deleted with it")
    g = doc.Groups.FindName(engine._group_name("wall", w))
    check(g is None or g.IsDeleted, "the wall's empty group is removed")

    # an L of two joined walls: the other one rebuilds without the deleted one
    a = engine.create(doc, _line(doc, sketch, 0, 300, 240, 300), WOOD, {"height": 108, "lod": "design"}, lib).driver_id
    b = engine.create(doc, _line(doc, sketch, 240, 300, 240, 500), WOOD, {"height": 108, "lod": "design"}, lib).driver_id
    check(str(b) in meta.joined_ids(doc.Objects.FindId(a)), "the L walls are joined")
    nb = len(meta.parts_of(doc, b))
    _delete_assembly(doc, a)
    _plain(doc, a, sketch, "joined wall")
    bo = doc.Objects.FindId(b)
    check(meta.is_driver(bo) and str(a) not in meta.joined_ids(bo), "the other wall is no longer joined to it")
    check(len(meta.parts_of(doc, b)) > 0, "the other wall rebuilt ({} -> {} parts)".format(nb, len(meta.parts_of(doc, b))))

    # some parts only (e.g. one stud picked with Ctrl+Shift): nothing is released
    c = engine.create(doc, _line(doc, sketch, 0, 700, 240, 700), WOOD, {"height": 108, "lod": "design"}, lib).driver_id
    _delete_assembly(doc, c, only=2)
    check(meta.is_driver(doc.Objects.FindId(c)), "deleting a few parts leaves the wall a wall")

    # a rebuild outside live.quiet (a command) deletes and re-adds parts: nothing is released
    engine.build(doc, c, lib)
    _idle()
    check(meta.is_driver(doc.Objects.FindId(c)) and meta.parts_of(doc, c), "a rebuild is not a delete")

    # floor, roof, curtain wall, stair: the same
    for label, crv, asm, prm in (
            ("floor", _rect(doc, sketch, 400, 0, 640, 240), FLOOR, {"base_offset": 108, "lod": "schematic"}),
            ("roof", _rect(doc, sketch, 700, 0, 940, 240), ROOF, {"base_offset": 108, "lod": "schematic"}),
            ("curtain wall", _line(doc, sketch, 0, 900, 240, 900), CW, {"height": 160, "lod": "schematic"}),
            ("stair", _line(doc, sketch, 400, 400, 587, 400), STAIR, {"height": 120, "width": 42})):
        d = engine.create(doc, crv, asm, prm, lib).driver_id
        check(len(meta.parts_of(doc, d)) > 0, label + " built")
        _delete_assembly(doc, d)
        _plain(doc, d, sketch, label)

    # a curve that came from an assembly layer (laylink) goes to the current layer, not back there
    made = laylink.ensure_layers(doc, lib)
    asm_layer = made[("wall", WOOD)]
    crv = _line(doc, asm_layer, 0, 1100, 240, 1100)
    laylink.convert(doc, crv, "wall", WOOD)
    check(meta.is_driver(doc.Objects.FindId(crv.Id)), "a line on a wall layer became a wall")
    _delete_assembly(doc, crv.Id)
    _plain(doc, crv.Id, plan, "wall from an assembly layer")

    # a wall mass: the SOLID stays (plain), the wall made from it goes
    massing = _layer(doc, "Massing")
    box = G.Box(G.Plane.WorldXY, G.Interval(f(1200), f(1440)), G.Interval(0, f(8)), G.Interval(0, f(108)))
    solid = _add(doc, box.ToBrep(), massing)
    m, _ = wallmasses.make(doc, solid, WOOD, {}, lib)
    wd = wallmasses.wall_of(doc, m)
    check(wd is not None and meta.parts_of(doc, wd.Id), "the wall mass made a wall")
    _delete_assembly(doc, wd.Id)
    o = doc.Objects.FindId(wd.Id)
    check(o is None or o.IsDeleted, "the wall mass's wall curve is gone")
    _plain(doc, m.Id, massing, "wall mass solid")

    # the driver curve itself deleted: everything goes (as before)
    d = engine.create(doc, _line(doc, sketch, 0, 1300, 240, 1300), WOOD, {"height": 108, "lod": "design"}, lib).driver_id
    doc.Objects.Delete(doc.Objects.FindId(d), True)
    _idle()
    check(not meta.parts_of(doc, d), "deleting the curve still deletes the wall")

    say("{} checks failed; {:.1f}s".format(len(FAILS), time.time() - t0))
    return not FAILS
