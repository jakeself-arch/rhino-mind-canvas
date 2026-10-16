"""Phase 7: joins (L / T wall joins, wall <-> floor, wall <-> roof).

Run inside Rhino (e.g. via the MCP run_python tool), in an EMPTY, unsaved document (it is cleared):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_phase7.py")["run"](__rhino_doc__, log=ROOT + r"\\phase7.log")

Covers: L corners between separate wall drivers (wood, metal, brick lap, mixed stacks, oblique,
concave) in the wrap / miter / butt styles and 'none'; T joins (partition into an exterior wall:
core through the host's gypsum, host notched + backer studs); the cascade (moving one wall rebuilds
its partners, also the one it left); four walls under a platform floor and walls above it
(exterior layers over the rim, per-edge ceiling / finish insets); walls under a gable roof (roof
wall dimensions from the walls, exterior layers under the rafters, gable-end infill with gable
studs) and a shed (high wall filled). No two joined walls may overlap (plain brep parts are
intersected). drawing_on=True writes f_corner_plan_1-1-2, f_tee_plan_1-1-2 and
f_gable_section_1-1-2 to docs/drawings/.
"""

import os
import runpy
import time
from collections import Counter

import Rhino

from mindcanvas import docutil, engine, library, meta, units
from mindcanvas.kinds import floor as floorkind
from mindcanvas.kinds import roof as roofkind
from mindcanvas.kinds import wall as wallkind

G = Rhino.Geometry
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = [None]

WOOD = "Ext - 2x6 Wood, Fiber Cement"
METAL = "Ext - 6\" Metal Stud, Fiber Cement"
BRICK = "Ext - Brick Veneer / 2x6 Wood"
PART = "Int - 2x4 Wood Partition"
F_WOOD = "Floor - 2x10 Wood Joists, Plywood"
R_ATTIC = "Roof - Asphalt Shingle / 2x8 Rafters, Vented Attic"
R_SHED = "Roof - Asphalt Shingle / 2x10 Rafters, Shed"
PLATE = 109.0


def say(*a):
    msg = " ".join(str(x) for x in a)
    print(msg)
    if LOG[0]:
        with open(LOG[0], "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def _ft(doc, v):
    return units.to_model(doc, v * 12.0)


def _add(doc, crv):
    return doc.Objects.FindId(doc.Objects.AddCurve(crv))


def _pl(doc, *pts_ft):
    f = lambda v: _ft(doc, v)
    return G.PolylineCurve([G.Point3d(f(x), f(y), 0) for x, y in pts_ft])


def _wall(doc, lib, asm, *pts, **prm):
    prm.setdefault("height", PLATE)
    prm.setdefault("reference", "interior_face")
    r = engine.create(doc, _add(doc, _pl(doc, *pts)), asm, prm, lib)
    assert not _bad(r), r.warnings
    return r


def roles(doc, drv_id):
    return Counter(meta.get(o, meta.ROLE) for o in meta.parts_of(doc, drv_id))


def _bad(r):
    return [w for w in r.warnings if "fail" in w.lower() or "could not" in w.lower() or "unknown" in w.lower()
            or "skipped" in w.lower()]


def _ctx(doc, lib, drv_id):
    drv = doc.Objects.FindId(drv_id)
    kmod = {"wall": wallkind, "floor": floorkind, "roof": roofkind}[meta.get(drv, meta.TYPE)]
    return kmod.make_context(doc, lib, drv, meta.get(drv, meta.ASSEMBLY), meta.params(drv))


def _check_solids(doc, drv_id, label):
    seen = set()
    for o in meta.parts_of(doc, drv_id):
        if isinstance(o, Rhino.DocObjects.InstanceObject):
            idef = o.InstanceDefinition
            if idef.Index in seen:
                continue
            seen.add(idef.Index)
            geoms = [x.Geometry for x in idef.GetObjects()]
        else:
            geoms = [o.Geometry]
        for g in geoms:
            if isinstance(g, G.Brep):
                assert g.IsSolid, "{}: open brep ({} / {})".format(label, meta.get(o, meta.ROLE), meta.get(o, meta.MATERIAL))


def _breps(doc, drv_id):
    return [o.Geometry for o in meta.parts_of(doc, drv_id)
            if not isinstance(o, Rhino.DocObjects.InstanceObject) and isinstance(o.Geometry, G.Brep)]


def _overlap(doc, a_id, b_id, label):
    """Largest intersection volume (in^3) between plain brep parts of two assemblies."""
    tol = doc.ModelAbsoluteTolerance
    inch3 = units.inch_scale(doc) ** 3
    worst = 0.0
    bs = [(b, b.GetBoundingBox(True)) for b in _breps(doc, b_id)]
    for a in _breps(doc, a_id):
        ab = a.GetBoundingBox(True)
        ab.Inflate(-tol * 4)
        for b, bb in bs:
            if not G.BoundingBox.Intersection(ab, bb).IsValid:
                continue
            res = G.Brep.CreateBooleanIntersection([a], [b], tol) or []
            for r in res:
                vp = G.VolumeMassProperties.Compute(r)
                if vp is not None:
                    worst = max(worst, abs(vp.Volume) / inch3)
    assert worst < 0.5, "{}: joined walls overlap ({:.2f} in3)".format(label, worst)
    return worst


def _ends(doc, lib, drv_id):
    ctx = _ctx(doc, lib, drv_id)
    return ctx, dict((n, c) for n, c in ctx.joins.ends.items())


def _top_z(doc, drv_id, layer):
    zs = [o.Geometry.GetBoundingBox(True).Max.Z for o in meta.parts_of(doc, drv_id)
          if meta.get(o, meta.LAYER) == layer and not isinstance(o, Rhino.DocObjects.InstanceObject)]
    return max(zs) / units.inch_scale(doc) if zs else None


# -- L joins --------------------------------------------------------------------------------------
def l_joins(doc, lib, y0=0.0):
    out = {}
    # wood: two walls on their interior faces meeting at the inside corner
    a = _wall(doc, lib, WOOD, (0, y0), (0, y0 + 14))
    b = _wall(doc, lib, WOOD, (0, y0 + 14), (20, y0 + 14))
    ca, ea = _ends(doc, lib, a.driver_id)
    cb, eb = _ends(doc, lib, b.driver_id)
    assert ea.get("end") is not None and ea["end"].kind == "L", ea
    assert eb.get("start") is not None and eb["start"].kind == "L", eb
    assert {ea["end"].role, eb["start"].role} == {"primary", "secondary"}, (ea["end"].role, eb["start"].role)
    assert str(b.driver_id) in ca.join_partners and str(a.driver_id) in cb.join_partners
    # the exterior faces meet at the outer corner: 5-1/2" + 1/2" + 1-17/32" past the interior faces
    reach = ea["end"].ext(ca.bands[0].d_ext) / ca.s
    assert abs(reach - (wallkind.total_thickness(wallkind.effective_layers(lib, doc.Objects.FindId(a.driver_id))))) < 0.01, reach
    for i in (a, b):
        _check_solids(doc, i.driver_id, "wood L")
    _overlap(doc, a.driver_id, b.driver_id, "wood L")
    out["wood"] = (a.driver_id, b.driver_id)
    say("  wood L: {} + {} parts, {:.2f}s".format(len(a.part_ids), len(b.part_ids), a.seconds + b.seconds))
    # the primary wall gets a backer stud at the corner
    prim = a if ea["end"].role == "primary" else b
    assert roles(doc, prim.driver_id)["stud"] >= 1
    # styles
    sec = b if prim is a else a
    for style in ("miter", "butt", "wrap"):
        r = engine.update_params(doc, doc.Objects.FindId(prim.driver_id), {"joins": {"end" if prim is a else "start": style}}, lib)
        assert not _bad(r), (style, r.warnings)
        assert r.joined and str(r.joined[0].driver_id) == str(sec.driver_id), "partner not rebuilt"
        _overlap(doc, a.driver_id, b.driver_id, "wood L " + style)
    r = engine.update_params(doc, doc.Objects.FindId(a.driver_id), {"joins": {"end": "none"}}, lib)
    assert "end" not in _ends(doc, lib, a.driver_id)[1] and "start" not in _ends(doc, lib, b.driver_id)[1]
    engine.update_params(doc, doc.Objects.FindId(a.driver_id), {"joins": None}, lib)
    assert "end" in _ends(doc, lib, a.driver_id)[1]
    # priority decides who runs through
    engine.update_params(doc, doc.Objects.FindId(sec.driver_id), {"join_priority": 5}, lib)
    assert _ends(doc, lib, sec.driver_id)[1]["end" if sec is a else "start"].role == "primary"
    engine.update_params(doc, doc.Objects.FindId(sec.driver_id), {"join_priority": None}, lib)
    say("  wood L: miter / butt / wrap / none / priority OK")
    # metal + wood (different stacks), drawn on the exterior faces this time
    x0 = 30
    m = _wall(doc, lib, METAL, (x0, y0), (x0, y0 + 14), reference="exterior_face")
    w = _wall(doc, lib, WOOD, (x0, y0 + 14), (x0 + 20, y0 + 14), reference="exterior_face")
    assert _ends(doc, lib, m.driver_id)[1].get("end") is not None
    _overlap(doc, m.driver_id, w.driver_id, "metal / wood L")
    _check_solids(doc, m.driver_id, "metal L")
    out["metal"] = (m.driver_id, w.driver_id)
    # oblique (120 degrees) and concave (exterior inside the turn)
    x0 = 60
    o1 = _wall(doc, lib, WOOD, (x0, y0), (x0 + 12, y0))
    o2 = _wall(doc, lib, WOOD, (x0 + 12, y0), (x0 + 18, y0 + 10.392))
    assert _ends(doc, lib, o1.driver_id)[1].get("end") is not None
    _overlap(doc, o1.driver_id, o2.driver_id, "oblique L")
    c1 = _wall(doc, lib, WOOD, (x0 + 30, y0 + 12), (x0 + 30, y0))
    c2 = _wall(doc, lib, WOOD, (x0 + 30, y0), (x0 + 42, y0))      # turns left: exterior inside
    assert _ends(doc, lib, c1.driver_id)[1].get("end") is not None
    _overlap(doc, c1.driver_id, c2.driver_id, "concave L")
    say("  metal / wood, oblique, concave L OK")
    # brick on both walls: square corner laps (alternate courses run through)
    x0 = 110
    k1 = _wall(doc, lib, BRICK, (x0, y0), (x0, y0 + 10), height=96, reference="core_exterior")
    k2 = _wall(doc, lib, BRICK, (x0, y0 + 10), (x0 + 12, y0 + 10), height=96, reference="core_exterior")
    cut = _ends(doc, lib, k1.driver_id)[1]["end"]
    assert getattr(cut, "lap", None) is not None, "brick corner should lap"
    n1 = roles(doc, k1.driver_id)["brick"] + roles(doc, k1.driver_id)["brick_closure"]
    assert n1 > 100, n1
    out["brick"] = (k1.driver_id, k2.driver_id)
    say("  brick L (lapped) OK")
    return out


# -- T joins --------------------------------------------------------------------------------------
def t_joins(doc, lib, y0=-40.0):
    host = _wall(doc, lib, WOOD, (0, y0), (24, y0))          # exterior toward +y... interior face on the driver
    ctx = _ctx(doc, lib, host.driver_id)
    side = 1 if ctx.curve.TangentAtStart.X > 0 else -1
    # a partition from the interior side, drawn on its center up to the host's interior face
    p = _wall(doc, lib, PART, (12, y0 - 10 * side), (12, y0), reference="center")
    cp, ep = _ends(doc, lib, p.driver_id)
    assert ep.get("end") is not None and ep["end"].kind == "T", ep
    ch = _ctx(doc, lib, host.driver_id)
    assert len(ch.joins.notches) == 1 and len(ch.joins.backers) == 2, (ch.joins.notches, ch.joins.backers)
    gyp = [o for o in meta.parts_of(doc, host.driver_id) if meta.get(o, meta.LAYER) == "Gypsum"]
    assert len(gyp) == 2, "host gypsum should be notched in two ({})".format(len(gyp))
    _overlap(doc, host.driver_id, p.driver_id, "T")
    _check_solids(doc, p.driver_id, "T partition")
    # butt: the partition stops at the host's face, no notch
    r = engine.update_params(doc, doc.Objects.FindId(p.driver_id), {"joins": {"end": "butt"}}, lib)
    assert not _bad(r), r.warnings
    gyp = [o for o in meta.parts_of(doc, host.driver_id) if meta.get(o, meta.LAYER) == "Gypsum"]
    assert len(gyp) == 1, len(gyp)
    engine.update_params(doc, doc.Objects.FindId(p.driver_id), {"joins": None}, lib)
    say("  T: core / butt, notch, backers OK")
    # cascade: moving the partition away leaves the host whole again
    orig = doc.Objects.FindId(p.driver_id).Geometry.DuplicateCurve()
    f = lambda v: _ft(doc, v)
    moved = G.LineCurve(G.Point3d(f(12), f(y0 - 10 * side), 0), G.Point3d(f(12), f(y0 - 3 * side), 0))
    doc.Objects.Replace(p.driver_id, moved)
    r = engine.build(doc, p.driver_id, lib)
    assert any(str(j.driver_id) == str(host.driver_id) for j in r.joined), "host not rebuilt after the move"
    gyp = [o for o in meta.parts_of(doc, host.driver_id) if meta.get(o, meta.LAYER) == "Gypsum"]
    assert len(gyp) == 1, len(gyp)
    doc.Objects.Replace(p.driver_id, orig)
    engine.build(doc, p.driver_id, lib)
    say("  T: cascade on move OK")
    return host.driver_id, p.driver_id


# -- floors ---------------------------------------------------------------------------------------
def floor_joins(doc, lib, x0=0.0, y0=-90.0):
    W, D = 24.0, 16.0
    pts = [(x0, y0), (x0, y0 + D), (x0 + W, y0 + D), (x0 + W, y0), (x0, y0)]     # clockwise: exterior outside
    lower = [_wall(doc, lib, WOOD, pts[i], pts[i + 1], reference="core_exterior") for i in range(4)]
    fl = engine.create(doc, _add(doc, _pl(doc, *pts)), F_WOOD, {"base_offset": PLATE}, lib)
    assert not _bad(fl), fl.warnings
    fctx = _ctx(doc, lib, fl.driver_id)
    sub = [b for b in fctx.bands if b.name == "Subfloor"][0]
    base_up = sub.d_ext / fctx.s
    upper = [_wall(doc, lib, WOOD, pts[i], pts[i + 1], reference="core_exterior", base_offset=base_up, height=96)
             for i in range(4)]
    assert len(fctx.join_insets) == 2, fctx.join_insets.keys()
    poly, dists = list(fctx.join_insets.values())[0]
    assert all(abs(d / fctx.s - 6.0) < 0.01 for d in dists), [d / fctx.s for d in dists]
    for w in lower:
        top = _top_z(doc, w.driver_id, "Sheathing")
        assert abs(top - base_up) < 0.01, (top, base_up)
        assert str(fl.driver_id) in _ctx(doc, lib, w.driver_id).join_partners
    r = engine.build(doc, fl.driver_id, lib)
    assert len(r.joined) == 8, len(r.joined)
    say("  floor: sheathing over the rim to {:.2f}\", insets {}, cascade OK".format(base_up, [round(d / fctx.s, 3) for d in dists]))
    return fl.driver_id, lower, upper


# -- roofs ----------------------------------------------------------------------------------------
def roof_joins(doc, lib, x0=40.0, y0=-90.0):
    W, D = 30.0, 20.0
    pts = [(x0, y0), (x0, y0 + D), (x0 + W, y0 + D), (x0 + W, y0), (x0, y0)]
    walls = [_wall(doc, lib, WOOD, pts[i], pts[i + 1], reference="core_exterior") for i in range(4)]
    r = engine.create(doc, _add(doc, _pl(doc, *pts)), R_ATTIC, {"base_offset": PLATE}, lib)
    assert not _bad(r), r.warnings
    rctx = _ctx(doc, lib, r.driver_id)
    assert abs(float(rctx.st["wall_ext"]) - (5.0 / 16 + 0.75 + 1.0 / 32 + 7.0 / 16)) < 1e-3, rctx.st["wall_ext"]
    gables = [w for w in walls if roles(doc, w.driver_id)["gable_stud"] > 0]
    assert len(gables) == 2, [dict(roles(doc, w.driver_id)) for w in walls]
    for w in walls:
        _check_solids(doc, w.driver_id, "wall under roof")
    eaves = [w for w in walls if w not in gables]
    top = _top_z(doc, eaves[0].driver_id, "Siding")
    assert top < PLATE - 1.0, top
    say("  gable roof: {} gable studs, siding stops {:.2f}\" below the plate".format(
        sum(roles(doc, w.driver_id)["gable_stud"] for w in gables), PLATE - top))
    # shed: the high wall is filled up to the rafters
    x1 = x0 + 40
    pts = [(x1, y0), (x1, y0 + 14), (x1 + 24, y0 + 14), (x1 + 24, y0), (x1, y0)]
    sw = [_wall(doc, lib, WOOD, pts[i], pts[i + 1], reference="core_exterior") for i in range(4)]
    s = engine.create(doc, _add(doc, _pl(doc, *pts)), R_SHED, {"base_offset": PLATE}, lib)
    assert not _bad(s), s.warnings
    filled = [w for w in sw if roles(doc, w.driver_id)["gable_stud"] > 0]
    assert len(filled) == 3, len(filled)      # both sides + the high wall
    say("  shed roof: {} walls filled".format(len(filled)))
    return r.driver_id, walls


# -- drawings -------------------------------------------------------------------------------------
def _view(doc, name):
    v = [x for x in doc.Views if x.ActiveViewport.Name == name][0]
    v.Maximized = True
    doc.Views.ActiveView = v
    return v


def _clear_clips(doc):
    for o in list(doc.Objects.FindByObjectType(Rhino.DocObjects.ObjectType.ClipPlane) or []):
        doc.Objects.Delete(o, True)


def _plan(doc, lib, drv_id, at, half_in, name):
    from mindcanvas.drawing import pipeline, sectioncut, styles
    st = styles.get("1-1/2", lib)
    _clear_clips(doc)
    view = _view(doc, "Top")
    sectioncut.make_plan(doc, doc.Objects.FindId(drv_id), at, view, name="phase7 " + name, depth_in=6.0, style=st)
    inch = units.inch_scale(doc)
    box = G.BoundingBox([at + G.Vector3d(-half_in * inch, -half_in * inch, 0), at + G.Vector3d(half_in * inch, half_in * inch, 0)])
    view.ActiveViewport.ZoomBoundingBox(box)
    doc.Views.Redraw()
    t = time.time()
    dwg = pipeline.make(doc, view, st, False, False, say, window=[box.Min, box.Max])
    paths = pipeline.write(dwg, os.path.join(ROOT, "docs", "drawings", name), px_per_mm=16)
    say("  drawing {}: {:.1f}s {} -> {}".format(name, time.time() - t, dwg.stats, os.path.basename(paths[-1])))
    _clear_clips(doc)
    return dwg


def _section(doc, lib, drv_id, at, lo, hi, name, depth_in=20.0):
    from mindcanvas.drawing import pipeline, sectioncut, styles
    st = styles.get("1-1/2", lib)
    _clear_clips(doc)
    view = _view(doc, "Front")
    sectioncut.make(doc, doc.Objects.FindId(drv_id), at, view, name="phase7 " + name, depth_in=depth_in, style=st)
    box = G.BoundingBox([lo, hi])
    view.ActiveViewport.ZoomBoundingBox(box)
    doc.Views.Redraw()
    t = time.time()
    dwg = pipeline.make(doc, view, st, True, False, say, window=[box.Min, box.Max])
    paths = pipeline.write(dwg, os.path.join(ROOT, "docs", "drawings", name), px_per_mm=16)
    say("  drawing {}: {:.1f}s {} -> {}".format(name, time.time() - t, dwg.stats, os.path.basename(paths[-1])))
    _clear_clips(doc)
    return dwg


def run_drawings(doc, lib, lj, tj, roof):
    f = lambda v: _ft(doc, v)
    a, b = lj["wood"]
    dwg = _plan(doc, lib, a, G.Point3d(0, f(14), f(4)), 16.0, "f_corner_plan_1-1-2")
    mats = set(rg.material for rg in dwg.regions)
    for m in ("Fiber Cement Siding", "OSB Sheathing", "Wood Framing", "Gypsum Board"):
        assert m in mats, "{} missing from the corner plan".format(m)
    host, part = tj
    _plan(doc, lib, host, G.Point3d(f(12), f(-40), f(4)), 14.0, "f_tee_plan_1-1-2")
    rid, walls = roof
    inch = units.inch_scale(doc)
    gable = [w for w in walls if roles(doc, w.driver_id)["gable_stud"] > 0][0]
    gc = _ctx(doc, lib, gable.driver_id).curve
    # a quarter along the gable wall (the middle is under the ridge board), cropped across the
    # wall: sectioncut.make looks along the wall, so the drawing's horizontal is the wall normal
    t = gc.Domain.ParameterAt(0.25)
    p = gc.PointAt(t)
    at = G.Point3d(p.X, p.Y, PLATE * inch)
    n = G.Vector3d.CrossProduct(G.Vector3d.ZAxis, gc.TangentAt(t))
    n.Unitize()
    _section(doc, lib, gable.driver_id, at, at - n * (20 * inch) - G.Vector3d(0, 0, 12 * inch),
             at + n * (20 * inch) + G.Vector3d(0, 0, 50 * inch), "f_gable_section_1-1-2")


def run(doc, clear=True, drawing_on=True, captures=True, log=None):
    assert not doc.Path, "test_phase7 clears the document: run it in an empty, unsaved model"
    LOG[0] = log
    if clear:
        for o in list(doc.Objects):
            doc.Objects.Delete(o, True)
        for i in range(doc.NamedViews.Count - 1, -1, -1):
            doc.NamedViews.Delete(i)
        docutil.purge_unused_blocks(doc)
    engine.setup_document(doc)
    lib = library.get(force_reload=True)
    t0 = time.time()
    say("-- L joins")
    lj = l_joins(doc, lib)
    say("-- T joins")
    tj = t_joins(doc, lib)
    say("-- floor")
    floor_joins(doc, lib)
    say("-- roofs")
    roof = roof_joins(doc, lib)
    if captures:
        try:
            cap = runpy.run_path(os.path.join(HERE, "capture.py"))["capture"]
            v = [x for x in doc.Views if x.ActiveViewport.Name == "Perspective"][0]
            vp = v.ActiveViewport
            f = lambda v_: _ft(doc, v_)
            vp.ChangeToPerspectiveProjection(True, 35)
            vp.SetCameraLocations(G.Point3d(f(3), f(12), f(5)), G.Point3d(f(-14), f(-6), f(16)))
            say(cap(doc, "phase7_corner", zoom_extents=False, width=1400, height=900))
            vp.SetCameraLocations(G.Point3d(f(55), f(-80), f(10)), G.Point3d(f(20), f(-130), f(40)))
            say(cap(doc, "phase7_roof_walls", zoom_extents=False, width=1400, height=900))
        except Exception as ex:
            say("captures skipped:", ex)
    if drawing_on:
        say("-- drawings")
        run_drawings(doc, lib, lj, tj, roof)
    doc.Views.Redraw()
    say("total {:.1f}s".format(time.time() - t0))
    say("PHASE 7 OK")
