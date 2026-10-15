"""Phase 1 test: framed walls (wood + metal) on straight, L-shaped, closed and arc drivers.

Run inside Rhino (e.g. via the MCP run_python tool):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_phase1.py")["run"](__rhino_doc__)

captures=True also writes docs/captures/phase1_*.png.
"""

import os
import runpy
import time
from collections import Counter

import Rhino

from mindcanvas import engine, library, meta, units
from mindcanvas.components import framing
from mindcanvas.kinds import wall as wallkind

G = Rhino.Geometry
WOOD = "Ext - 2x6 Wood, Fiber Cement"
METAL = "Ext - 6\" Metal Stud, Fiber Cement"
PART_METAL = "Int - 3-5/8\" Metal Stud Partition"
PART_WOOD = "Int - 2x4 Wood Partition"
HERE = os.path.dirname(os.path.abspath(__file__))


def _ft(doc, feet):
    return units.to_model(doc, feet * 12.0)


def _add(doc, curve):
    return doc.Objects.FindId(doc.Objects.AddCurve(curve))


def _parts(doc, result):
    return meta.parts_of(doc, result.driver_id)


def _roles(doc, result):
    return Counter(meta.get(o, meta.ROLE) for o in _parts(doc, result))


def _check(label, result, doc, studs=None):
    roles = _roles(doc, result)
    print("{:<28} {:>5.2f}s  {}".format(label, result.seconds, dict(roles)))
    bad = [w for w in result.warnings if "fail" in w.lower() or "could not" in w.lower()]
    assert not bad, "{}: {}".format(label, bad)
    if studs is not None:
        assert roles["stud"] == studs, "{}: expected {} studs, got {}".format(label, studs, roles["stud"])
    return roles


def _context(doc, result):
    drv = doc.Objects.FindId(result.driver_id)
    ctx = wallkind.make_context(doc, library.get(), drv, meta.get(drv, meta.ASSEMBLY), meta.params(drv))
    band = [b for b in ctx.bands if b.component == "framing"][0]
    return ctx, band


def _layer_box(doc, result, layer):
    bb = G.BoundingBox.Empty
    for o in _parts(doc, result):
        if meta.get(o, meta.LAYER) == layer:
            bb.Union(o.Geometry.GetBoundingBox(True))
    return bb


def run(doc, clear=True, captures=True):
    if clear:
        for o in list(doc.Objects):
            doc.Objects.Delete(o, True)
    engine.setup_document(doc)
    f = lambda v: _ft(doc, v)
    s = units.inch_scale(doc)
    t_all = time.time()
    R = {}

    def line(x0, y0, x1, y1):
        return G.LineCurve(G.Point3d(f(x0), f(y0), 0), G.Point3d(f(x1), f(y1), 0))

    def poly(*pts):
        return G.PolylineCurve([G.Point3d(f(x), f(y), 0) for x, y in pts])

    # straight 20'-0" walls: 16" o.c. -> 15 spaces, 16 studs (incl. both end studs)
    R["wood straight"] = engine.create(doc, _add(doc, line(0, 0, 20, 0)), WOOD)
    R["metal straight"] = engine.create(doc, _add(doc, line(0, -12, 20, -12)), METAL)
    _check("wood straight", R["wood straight"], doc, 16)
    _check("metal straight", R["metal straight"], doc, 16)

    # partitions
    R["wood partition"] = engine.create(doc, _add(doc, line(0, -24, 12, -24)), PART_WOOD)
    R["metal partition"] = engine.create(doc, _add(doc, line(0, -30, 12, -30)), PART_METAL)
    _check("wood partition", R["wood partition"], doc, 10)
    _check("metal partition", R["metal partition"], doc, 10)

    # L-shaped polylines: 3-stud wood corner, 2-stud metal corner
    R["wood L"] = engine.create(doc, _add(doc, poly((30, 0), (50, 0), (50, 14))), WOOD)
    R["metal L"] = engine.create(doc, _add(doc, poly((30, -30), (50, -30), (50, -16))), METAL)
    _check("wood L", R["wood L"], doc)
    _check("metal L", R["metal L"], doc)

    # closed rectangles (drawn counter-clockwise)
    rect = lambda x0, x1, y0, y1: G.Rectangle3d(G.Plane.WorldXY, G.Interval(f(x0), f(x1)),
                                                G.Interval(f(y0), f(y1))).ToNurbsCurve()
    R["wood rect"] = engine.create(doc, _add(doc, rect(60, 80, 0, 16)), WOOD)
    R["metal rect"] = engine.create(doc, _add(doc, rect(60, 80, -36, -20)), PART_METAL)
    _check("wood rect", R["wood rect"], doc)
    _check("metal rect", R["metal rect"], doc)

    # arcs
    arc = lambda x0, y0: G.ArcCurve(G.Arc(G.Point3d(f(x0), f(y0), 0), G.Point3d(f(x0 + 10), f(y0 + 8), 0),
                                          G.Point3d(f(x0 + 20), f(y0), 0)))
    R["wood arc"] = engine.create(doc, _add(doc, arc(90, 0)), WOOD)
    R["metal arc"] = engine.create(doc, _add(doc, arc(90, -30)), METAL)
    _check("wood arc", R["wood arc"], doc)
    _check("metal arc", R["metal arc"], doc)

    # corner stud counts: per run (20' and 14' long), plus the corner set
    wl, ml = _roles(doc, R["wood L"])["stud"], _roles(doc, R["metal L"])["stud"]
    assert ml == wl - 1, "wood corner should have one more stud (backer) than metal: {} / {}".format(wl, ml)

    # stud stations: sorted, one per stud, on the driver
    for key in ("wood straight", "wood L", "metal rect", "wood arc"):
        ctx, band = _context(doc, R[key])
        st = framing.stud_stations(ctx, band)
        L = ctx.curve.GetLength()
        assert st == sorted(st) and len(st) == _roles(doc, R[key])["stud"], key
        assert all(-1e-6 <= x <= L + 1e-6 for x in st), key
        if key == "wood straight":
            got = [round(x / s, 3) for x in st]
            want = [0.75] + [16.0 * k for k in range(1, 15)] + [239.25]
            assert got == want, got

    # studs sit between the plates / inside the tracks
    for key in ("wood straight", "metal straight"):
        fr = _layer_box(doc, R[key], "Framing")
        for o in _parts(doc, R[key]):
            if meta.get(o, meta.ROLE) == "stud":
                bb = o.Geometry.GetBoundingBox(True)
                assert bb.Min.Z > fr.Min.Z + 1e-6 and bb.Max.Z < fr.Max.Z - 1e-6, key

    # swap wood -> metal on the same assembly (2x6 -> 6" metal stud, wall grows 1/2")
    R["swap"] = engine.create(doc, _add(doc, line(0, 12, 20, 12)), WOOD)
    drv = doc.Objects.FindId(R["swap"].driver_id)
    gyp0 = _layer_box(doc, R["swap"], "Siding")
    R["swap"] = engine.set_override(doc, drv, "Framing", "system", "metal")
    roles = _check("swap wood -> metal", R["swap"], doc, 16)
    assert roles["track"] == 2 and roles["plate"] == 0, roles
    members = set(meta.get(o, meta.EXTRA_PREFIX + "member") for o in _parts(doc, R["swap"])
                  if meta.get(o, meta.ROLE) == "stud")
    assert members == {'6" Metal Stud, 18 ga'}, members
    gyp1 = _layer_box(doc, R["swap"], "Siding")
    grow = (gyp1.Max.Y - gyp0.Max.Y) / s
    assert abs(grow - 0.5) < 1e-3, "wall should grow by 1/2\", grew {}".format(grow)
    R["swap back"] = engine.set_override(doc, drv, "Framing", "system", None)
    _check("swap back", R["swap back"], doc, 16)
    # 4" nominal: 2x4 partition -> 3-5/8" metal studs
    pdrv = doc.Objects.FindId(R["wood partition"].driver_id)
    R["partition swap"] = engine.set_override(doc, pdrv, "Framing", "system", "metal")
    members = set(meta.get(o, meta.EXTRA_PREFIX + "member") for o in _parts(doc, R["partition swap"])
                  if meta.get(o, meta.ROLE) == "stud")
    assert members == {'3-5/8" Metal Stud, 20 ga'}, members
    engine.set_override(doc, pdrv, "Framing", "system", None)

    # level of detail
    R["lod design"] = engine.create(doc, _add(doc, line(0, 24, 20, 24)), METAL, {"lod": "design"})
    roles = _check("metal design LOD", R["lod design"], doc, 16)
    assert not roles["insulation"] and not roles["bridging"], roles
    R["lod schematic"] = engine.create(doc, _add(doc, line(0, 30, 20, 30)), WOOD, {"lod": "schematic"})
    roles = _check("wood schematic LOD", R["lod schematic"], doc, 0)
    assert roles["framing"] == 1, roles

    # spacing override
    R["24 oc"] = engine.set_override(doc, doc.Objects.FindId(R["lod design"].driver_id), "Framing", "spacing", 24)
    _check("metal 24\" o.c.", R["24 oc"], doc, 11)

    # linear feet for the schedule
    for o in _parts(doc, R["wood straight"]):
        if meta.get(o, meta.ROLE) in ("stud", "plate"):
            assert float(meta.get(o, meta.EXTRA_PREFIX + "length")) > 0

    print("total {:.2f}s".format(time.time() - t_all))
    if captures:
        take_captures(doc, R)
    doc.Views.Redraw()
    print("PHASE 1 OK")
    return R


# -- captures -------------------------------------------------------------------
def _show_only(doc, results, keep):
    """Hide every object except parts of `results` for which keep(obj) is true."""
    ids = set()
    for r in results:
        ids.update(o.Id for o in _parts(doc, r) if keep(o))
    for o in doc.Objects:
        if o.Id not in ids:
            doc.Objects.Hide(o, True)


def _show_all(doc):
    settings = Rhino.DocObjects.ObjectEnumeratorSettings()
    settings.HiddenObjects = True
    for o in doc.Objects.GetObjectList(settings):
        if o.IsHidden:
            doc.Objects.Show(o, True)


def _camera(doc, view, loc, target, lens=35):
    v = doc.Views.Find(view, False)
    vp = v.ActiveViewport
    vp.ChangeToPerspectiveProjection(True, lens)
    vp.SetCameraLocations(target, loc)
    return v


def take_captures(doc, R):
    capture = runpy.run_path(os.path.join(HERE, "capture.py"))["capture"]
    f = lambda v: _ft(doc, v)
    P = lambda x, y, z: G.Point3d(f(x), f(y), f(z))

    def cap(name, cam=None, **kwargs):
        doc.Views.Redraw()
        Rhino.RhinoApp.Wait()
        if cam:
            _camera(doc, "Perspective", P(*cam[0]), P(*cam[1]))
            kwargs["zoom_extents"] = False
        return capture(doc, name, **kwargs)

    role = lambda o: meta.get(o, meta.ROLE)
    framing_only = lambda o: meta.get(o, meta.LAYER) == "Framing" and role(o) != "insulation"
    with_fill = lambda o: meta.get(o, meta.LAYER) == "Framing"
    plan = lambda o: meta.get(o, meta.LAYER) == "Framing" and role(o) in ("stud", "insulation")
    shots = [
        ("phase1_wood", ["wood straight"], framing_only, ((-4, -7, 7), (3, 0.3, 4))),
        ("phase1_wood_fill", ["wood straight"], with_fill, ((-4, -7, 7), (3, 0.3, 4))),
        ("phase1_wood_layers", ["wood straight"], None, ((-2.5, -3, 3), (0.5, 0.3, 1.5))),
        ("phase1_metal_base", ["metal straight"], framing_only, ((-2.5, -15.5, 1.8), (1.5, -12, 0.8))),
        ("phase1_metal_top", ["metal straight"], framing_only, ((-2.5, -15.5, 8.6), (1.5, -12, 9.6))),
        ("phase1_metal_fill", ["metal straight"], with_fill, ((-4, -19, 7), (3, -11.7, 4))),
        ("phase1_corner_metal_3d", ["metal L"], framing_only, ((45, -35, 3.5), (50, -30, 1.5))),
        ("phase1_corner_wood_3d", ["wood L"], framing_only, ((45, -5, 3.5), (50, 0, 1.5))),
        ("phase1_arc_wood", ["wood arc"], framing_only, ((100, -14, 10), (100, 4, 4))),
        ("phase1_arc_metal", ["metal arc"], with_fill, ((100, -44, 10), (100, -26, 4))),
    ]
    try:
        for name, keys, keep, cam in shots:
            if keep:
                _show_only(doc, [R[k] for k in keys], keep)
            cap(name, cam)
            _show_all(doc)
        plans = [("phase1_corner_wood", "wood L", (48.6, -0.3), (50.2, 0.9)),
                 ("phase1_corner_metal", "metal L", (48.6, -30.3), (50.2, -29.1)),
                 ("phase1_corner_rect", "wood rect", (59.0, -1.0), (60.6, 0.4)),
                 ("phase1_arc_plan", "metal arc", (90.4, -28.6), (92.6, -25.6))]
        for name, key, a, b in plans:
            _show_only(doc, [R[key]], plan)
            cap(name, view="Top", box=G.BoundingBox(P(a[0], a[1], 0), P(b[0], b[1], 10)))
            _show_all(doc)
        _camera(doc, "Perspective", P(-6, -40, 30), P(55, -5, 0))
        cap("phase1_overview")
    finally:
        _show_all(doc)
