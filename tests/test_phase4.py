"""Phase 4: openings - windows and doors hosted by walls.

Run inside Rhino (e.g. via the MCP run_python tool), in an EMPTY, unsaved document (it is cleared):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_phase4.py")["run"](__rhino_doc__)

Covers windows + doors in wood, metal, brick veneer and two-sided brick walls on straight,
L-shaped (opening near the corner) and arc drivers; frames at the insulation line with brick
closures; openings following an edited wall curve, a moved opening line, deleting an opening;
every LOD; the opening schedule; snapping heads to the brick coursing. drawing_on=True also
writes docs/drawings/c_window_section_1-1-2.{svg,png} (1-1/2" section through a window head
and sill); captures=True writes docs/captures/phase4_*.png.
"""

import os
import runpy
import time
from collections import Counter

import Rhino

from mindcanvas import engine, library, meta, schedule, stack, units
from mindcanvas.kinds import wall as wallkind
from mindcanvas.openings import core

G = Rhino.Geometry
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WOOD = "Ext - 2x6 Wood, Fiber Cement"
METAL = 'Ext - 6" Metal Stud, Fiber Cement'
BRICK = 'Ext - Brick Veneer / 6" Metal Stud'
BRICK_WOOD = "Ext - Brick Veneer / 2x6 Wood"
WINDOW, DOOR = "Window - Fixed", "Door - Hollow Metal"
BRICK_ROLES = ("brick", "brick_half", "brick_header", "brick_closure", "brick_soldier", "brick_rowlock",
               "brick_sailor", "brick_shiner")
# modular coursing: bed joints every 8/3"; a head at 8k/3 - 3/8 lands the lintel in a bed joint
SILL_IN, HEIGHT_IN = 39.625, 40.0


def _ft(doc, v):
    return units.to_model(doc, v * 12.0)


def _add(doc, crv):
    return doc.Objects.FindId(doc.Objects.AddCurve(crv))


def _parts(doc, drv_id):
    return meta.parts_of(doc, drv_id)


def _roles(doc, drv_id, layer=None):
    return Counter(meta.get(o, meta.ROLE) for o in _parts(doc, drv_id)
                   if layer is None or meta.get(o, meta.LAYER) == layer)


def _ctx(doc, lib, drv_id):
    drv = doc.Objects.FindId(drv_id)
    return wallkind.make_context(doc, lib, drv, meta.get(drv, meta.ASSEMBLY), meta.params(drv))


def _bad(r):
    return [w for w in r.warnings if "fail" in w.lower() or "could not" in w.lower()]


def _inside(doc, drv_id, pt, layer=None, material=None, role=None):
    """Parts (plain geometry only) of a wall that contain pt."""
    tol = doc.ModelAbsoluteTolerance
    hits = []
    for o in _parts(doc, drv_id):
        if layer and meta.get(o, meta.LAYER) != layer:
            continue
        if material and meta.get(o, meta.MATERIAL) != material:
            continue
        if role and meta.get(o, meta.ROLE) != role:
            continue
        g = o.Geometry
        if isinstance(g, G.Extrusion):
            g = g.ToBrep()
        if isinstance(g, G.Brep) and g.IsSolid and g.IsPointInside(pt, tol, False):
            hits.append(o)
    return hits


def _instances_in(doc, drv_id, op, roles, x_pad=0.0, z_lo=None, z_hi=None):
    """Block parts whose bbox center is inside the opening's x range and z range."""
    out = []
    for o in _parts(doc, drv_id):
        if meta.get(o, meta.ROLE) not in roles or not isinstance(o, Rhino.DocObjects.InstanceObject):
            continue
        c = o.Geometry.GetBoundingBox(True).Center
        bb = o.InstanceDefinition.GetObjects()[0].Geometry.GetBoundingBox(True)
        bb.Transform(o.InstanceXform)
        c = bb.Center
        x, y, z = op.local(c)
        if -op.rx + x_pad < x < op.rx - x_pad and (z_lo if z_lo is not None else op.rz0) < z < (z_hi if z_hi is not None else op.rz1):
            out.append(o)
    return out


def check_wall(doc, lib, label, drv_id, framing=None, brick=False):
    """Common checks for a wall with openings."""
    ctx = _ctx(doc, lib, drv_id)
    ops = ctx.openings
    assert ops, "{}: no openings resolved".format(label)
    roles = _roles(doc, drv_id)
    for op in ops:
        mid = op.pt(0, 0.5 * (op.y_ext + op.y_int), 0.5 * (op.z0 + op.z1))
        for b in ctx.bands:
            if b.component in ("solid", "membrane") and op.y_int < b.d_mid < op.y_ext:
                p = op.pt(0, b.d_mid, 0.5 * (op.z0 + op.z1))
                assert not _inside(doc, drv_id, p, layer=b.name), "{}: '{}' not cut at {}".format(label, b.name, op.name)
        fb = [b for b in ctx.bands if b.component == "framing"]
        if fb and ctx.lod != "schematic":
            p = op.pt(0, fb[0].d_mid, 0.5 * (op.z0 + op.z1))
            assert not _inside(doc, drv_id, p, layer=fb[0].name), "{}: framing / insulation in {}".format(label, op.name)
            studs = _instances_in(doc, drv_id, op, ("stud", "jack_stud", "king_stud", "jamb_stud", "cripple"),
                                  z_lo=op.rz0 + 0.01, z_hi=op.rz1 - 0.01)
            assert not studs, "{}: {} studs inside the rough opening of {}".format(label, len(studs), op.name)
        if brick and ctx.lod != "schematic":
            inbrick = _instances_in(doc, drv_id, op, BRICK_ROLES, x_pad=ctx.u(0.5), z_lo=op.z0 + ctx.u(0.5),
                                    z_hi=op.z1 - ctx.u(0.5))
            inbrick = [o for o in inbrick if meta.get(o, meta.ROLE) != "brick_rowlock"]
            assert not inbrick, "{}: {} bricks inside {}".format(label, len(inbrick), op.name)
    print("  {:<34} {}".format(label, ", ".join("{} {}".format(k, v) for k, v in sorted(roles.items())
                                                 if k not in ("mortar_head", "mortar_bed"))))
    if framing == "wood":
        for role in ("king_stud", "jack_stud", "header", "cripple"):
            assert roles[role] > 0, "{}: no {}".format(label, role)
        if any(not op.door for op in ops):
            assert roles["rough_sill"] > 0, "{}: no rough sill".format(label)
    if framing == "metal":
        for role in ("jamb_stud", "header", "head_track", "cripple"):
            assert roles[role] > 0, "{}: no {}".format(label, role)
    if any(op.door for op in ops) and ctx.lod != "schematic":
        assert roles["leaf"] > 0 and roles["swing"] == 2 * sum(1 for op in ops if op.door), roles
    if any(not op.door for op in ops):
        assert roles["glass"] > 0, roles
    if brick and ctx.lod != "schematic":
        n_win = sum(1 for op in ops if not op.door)
        assert roles["lintel"] >= len(ops), "{}: lintels {}".format(label, roles["lintel"])
        assert roles["brick_rowlock"] >= 6 * n_win, "{}: rowlocks {}".format(label, roles["brick_rowlock"])
        # frames sit at the insulation line: face on the first solid layer behind the air space
        for op in ops:
            if op.t["frame"].get("depth") != "wall" and op.masonry_ext is not None:
                behind = sorted([b for b in ctx.bands if b.d_ext <= op.masonry_ext.d_int - ctx.u(0.5)
                                 and b.component != "void"], key=lambda b: -b.d_ext)
                assert behind and abs(op.y_fe - behind[0].d_ext) < ctx.tol * 10, \
                    "{}: frame of {} not at the insulation line".format(label, op.name)
                assert op.behind_brick
        if ctx.lod == "detail":
            assert roles["end_dam"] >= 2 * len(ops) and roles["sealant"] > 0, roles
            assert roles["closure"] >= 3 * len(ops), "{}: closures {}".format(label, roles["closure"])
    return ctx, roles


def _place(doc, lib, drv_id, kind, at, **params):
    host = doc.Objects.FindId(drv_id)
    op, r = engine.add_opening(doc, host, kind, params, at, lib)
    assert not _bad(r), r.warnings
    return op, r


def _two_sided(doc, lib, drv):
    layers = stack.current(lib, drv)
    gyp = len(layers) - 1
    brick = [spec for label, spec in stack.catalog(lib) if lib.resolve_layer(spec).get("component") == "masonry"][0]
    layers = stack.replace(layers, gyp, brick)
    air = [spec for label, spec in stack.catalog(lib) if label.startswith("Preset:") and spec.get("component") == "void"][0]
    layers = stack.insert(layers, gyp, air)
    return engine.set_layers(doc, drv, layers, lib)


def straight_walls(doc, lib):
    """Window + door in each wall type, straight 16' walls, exterior toward -Y (Front view)."""
    f = lambda v: _ft(doc, v)
    out = {}
    for i, (asm, framing, brick) in enumerate(((WOOD, "wood", False), (METAL, "metal", False),
                                               (BRICK, "metal", True), (BRICK_WOOD, "wood", True))):
        y = -12.0 * i
        t = time.time()
        r = engine.create(doc, _add(doc, G.LineCurve(G.Point3d(f(16), f(y), 0), G.Point3d(0, f(y), 0))),
                          asm, {"height": "10'"}, lib)
        _place(doc, lib, r.driver_id, WINDOW, G.Point3d(f(11), f(y), 0), sill=SILL_IN, height=HEIGHT_IN)
        _, r = _place(doc, lib, r.driver_id, DOOR, G.Point3d(f(4.5), f(y), 0))
        print("{} with window + door: {} parts in {:.1f}s".format(asm, len(r.part_ids), time.time() - t))
        check_wall(doc, lib, asm, r.driver_id, framing, brick)
        out[asm] = r.driver_id
    return out


def two_sided(doc, lib):
    f = lambda v: _ft(doc, v)
    y = -48.0
    r = engine.create(doc, _add(doc, G.LineCurve(G.Point3d(f(12), f(y), 0), G.Point3d(0, f(y), 0))),
                      BRICK, {"height": "9'"}, lib)
    r = _two_sided(doc, lib, doc.Objects.FindId(r.driver_id))
    _place(doc, lib, r.driver_id, WINDOW, G.Point3d(f(4), f(y), 0), sill=SILL_IN, height=HEIGHT_IN, head="soldier")
    _, r = _place(doc, lib, r.driver_id, DOOR, G.Point3d(f(9), f(y), 0))
    ctx, roles = check_wall(doc, lib, "two-sided brick", r.driver_id, "metal", True)
    names = [b.name for b in ctx.bands if b.component == "masonry"]
    ext, inner = names[0], names[-1]
    re_, ri = _roles(doc, r.driver_id, ext), _roles(doc, r.driver_id, inner)
    assert ri["lintel"] == 2 and re_["lintel"] == 2, (re_, ri)
    assert ri["flashing"] == 0 and ri["brick_rowlock"] == 0 and ri["weep"] == 0, ri
    assert re_["brick_soldier"] >= 8, "soldier course missing: {}".format(re_)
    return r.driver_id


def corner_and_arc(doc, lib):
    f = lambda v: _ft(doc, v)
    out = {}
    # L-shaped: window asked 1' from the corner (pushed clear: as close as the layers' miter at the
    # corner + the jamb framing allow), door on the other leg
    for k, asm in enumerate((BRICK, WOOD)):
        x0 = 24.0 + 22.0 * k
        pl = G.PolylineCurve([G.Point3d(f(x0 + 14), f(0), 0), G.Point3d(f(x0), f(0), 0), G.Point3d(f(x0), f(-12), 0)])
        r = engine.create(doc, _add(doc, pl), asm, {"height": "10'"}, lib)
        _, r1 = _place(doc, lib, r.driver_id, WINDOW, G.Point3d(f(x0 + 1), 0, 0), sill=SILL_IN, height=HEIGHT_IN)
        assert any("moved" in w for w in r1.warnings), "corner clamp warning missing: {}".format(r1.warnings)
        _, r = _place(doc, lib, r.driver_id, DOOR, G.Point3d(f(x0), f(-7), 0))
        ctx, _ = check_wall(doc, lib, "L-shaped " + asm, r.driver_id, "metal" if asm == BRICK else "wood",
                            asm == BRICK)
        thick = max(b.d_ext for b in ctx.bands) - min(b.d_int for b in ctx.bands)
        win = [op for op in ctx.openings if not op.door][0]
        corner = G.Point3d(f(x0), 0, 0)
        gap = abs(win.local(corner)[0]) - win.rx      # rough opening edge -> driver corner
        # at most the far face's miter (<= the wall thickness) + 4" of jamb framing; the old rule
        # kept thickness + 6"
        assert ctx.u(4) - 1e-6 <= gap <= thick + ctx.u(4) + 1e-6, "window gap {}".format(gap / ctx.s)
        out["L " + asm] = r.driver_id
    # arcs
    for k, asm in enumerate((BRICK, METAL)):
        cx = 70.0 + 24.0 * k
        arc = G.ArcCurve(G.Arc(G.Point3d(f(cx + 10), 0, 0), G.Point3d(f(cx), f(-7), 0), G.Point3d(f(cx - 10), 0, 0)))
        r = engine.create(doc, _add(doc, arc), asm, {"height": "10'"}, lib)
        _place(doc, lib, r.driver_id, WINDOW, G.Point3d(f(cx), f(-7), 0), sill=SILL_IN, height=HEIGHT_IN)
        _, r = _place(doc, lib, r.driver_id, DOOR, G.Point3d(f(cx - 6.5), f(-5), 0))
        check_wall(doc, lib, "arc " + asm, r.driver_id, "metal", asm == BRICK)
        out["arc " + asm] = r.driver_id
    return out


def edits(doc, lib, drv_id):
    """Openings follow an edited wall curve; a moved line moves the opening; delete one."""
    f = lambda v: _ft(doc, v)
    host = doc.Objects.FindId(drv_id)
    ops = core.hosted(doc, drv_id)
    win = [o for o in ops if not meta.get(o, meta.ASSEMBLY).startswith("Door")][0]
    st0 = meta.params(win)["station"]
    # 1. wall curve moved + lengthened: the window keeps its station (distance along the curve)
    c = host.Geometry
    new = G.LineCurve(c.PointAtStart + G.Vector3d(f(2), f(-1), 0), c.PointAtEnd + G.Vector3d(0, f(-1), 0))
    doc.Objects.Replace(drv_id, new)
    r = engine.build(doc, drv_id, lib)
    assert not _bad(r), r.warnings
    win = doc.Objects.FindId(win.Id)
    line = win.Geometry
    mid = line.PointAt(line.Domain.Mid)
    st = core.station_of(doc.Objects.FindId(drv_id).Geometry, mid) / units.inch_scale(doc)
    assert abs(st - st0) < 0.05, "opening did not follow its wall: station {} -> {}".format(st0, st)
    assert abs(mid.Y - (c.PointAtStart.Y - f(1))) < 1e-6, "opening line not on the moved wall"
    print("  wall curve moved: window line followed (station {:.2f}\")".format(st))
    # 2. the user moves the opening line 2' along the wall and 6" up: station + sill follow
    sill0 = meta.params(win)["sill"]
    doc.Objects.Transform(win.Id, G.Transform.Translation(G.Vector3d(f(-2), 0, f(0.5))), True)
    r = engine.build(doc, win.Id, lib)          # what live mode does on the opening's replace event
    p = meta.params(doc.Objects.FindId(win.Id))
    assert abs(p["station"] - (st0 + 24)) < 0.05 and abs(p["sill"] - (sill0 + 6)) < 0.05, p
    ctx = _ctx(doc, lib, drv_id)
    w = [op for op in ctx.openings if op.id == win.Id][0]
    assert not _inside(doc, drv_id, w.pt(0, ctx.band("Gypsum").d_mid, 0.5 * (w.z0 + w.z1)), layer="Gypsum")
    print("  opening line moved: station {:.2f}\", sill {:.2f}\"".format(p["station"], p["sill"]))
    # 3. delete the window: its parts go, the wall closes
    n_before = len(_parts(doc, drv_id))
    centre = w.pt(0, ctx.band("Gypsum").d_mid, 0.5 * (w.z0 + w.z1))
    doc.Objects.Delete(win.Id, True)
    r = engine.build(doc, drv_id, lib)
    gone = [o for o in _parts(doc, drv_id) if meta.get(o, meta.EXTRA_PREFIX + "opening") == str(win.Id)]
    assert not gone, "{} parts of the deleted window remain".format(len(gone))
    assert _inside(doc, drv_id, centre, layer="Gypsum"), "gypsum not closed after deleting the window"
    print("  window deleted: {} -> {} parts, wall closed".format(n_before, len(_parts(doc, drv_id))))
    # 4. deleting a wall deletes its openings (live mode does this)
    n = engine.delete_openings(doc, drv_id)
    assert n == 1 and not core.hosted(doc, drv_id), n
    engine.build(doc, drv_id, lib)


def lods(doc, lib):
    f = lambda v: _ft(doc, v)
    y = -60.0
    r = engine.create(doc, _add(doc, G.LineCurve(G.Point3d(f(12), f(y), 0), G.Point3d(0, f(y), 0))),
                      BRICK, {"height": "9'"}, lib)
    _place(doc, lib, r.driver_id, "Window - Double Hung", G.Point3d(f(4), f(y), 0), sill=36.625, height=48)
    _place(doc, lib, r.driver_id, "Door - Hollow Metal, Half Lite", G.Point3d(f(9), f(y), 0))
    drv = doc.Objects.FindId(r.driver_id)
    out = {}
    for lod in ("schematic", "design", "detail"):
        t = time.time()
        r = engine.update_params(doc, drv, {"lod": lod}, lib)
        drv = doc.Objects.FindId(r.driver_id)
        assert not _bad(r), r.warnings
        roles = _roles(doc, r.driver_id)
        out[lod] = roles
        print("  LOD {:<9} {:5d} parts {:.1f}s".format(lod, len(r.part_ids), time.time() - t))
        check_wall(doc, lib, "lod " + lod, r.driver_id, None if lod == "schematic" else "metal", lod != "schematic")
    assert out["schematic"]["masonry"] == 1 and out["schematic"]["brick"] == 0
    assert out["design"]["mortar_head"] == 0 and out["design"]["sash"] >= 8 and out["design"]["lintel"] == 2
    assert out["detail"]["mortar_head"] > 0 and out["detail"]["spacer"] > 0 and out["detail"]["flashing"] >= 3
    return r.driver_id


def snapping(doc, lib, brick_id, wood_id):
    """SnapHead: a window's sill (a door's height) moves so the head + joint is on a bed joint."""
    from mindcanvas.components import masonry
    host = doc.Objects.FindId(brick_id)
    p, d = engine.snap_to_coursing(doc, host, WINDOW, {"sill": 32, "height": 56}, lib)
    ctx = _ctx(doc, lib, brick_id)
    v = masonry.layout(ctx, [b for b in ctx.bands if b.component == "masonry"][0])
    head = ctx.base_z + (p["sill"] + p["height"] + 0.375) * ctx.s
    assert min(abs(c.z - head) for c in v.courses) < ctx.u(1.0 / 64), (p, d)
    assert p["height"] == 56 and abs(d) <= 8.0 / 6 + 1e-6, (p, d)
    pd, dd = engine.snap_to_coursing(doc, host, DOOR, {"sill": 0, "height": 86}, lib)
    assert pd["sill"] == 0 and abs(pd["height"] - 86 - dd) < 1e-3, pd
    p2, d2 = engine.snap_to_coursing(doc, doc.Objects.FindId(wood_id), WINDOW, {"sill": 32, "height": 56}, lib)
    assert d2 == 0.0 and p2["sill"] == 32, "no brick: no snapping"
    print("  window sill 32\" -> {}\" ({:+.3f}\"), door height 86\" -> {}\"".format(p["sill"], d, pd["height"]))


def opening_schedule(doc):
    rows = schedule.openings(doc)
    print(schedule.format_openings(rows))
    total = sum(r["count"] for r in rows)
    assert total == len(meta.all_drivers(doc, core.KIND)), rows
    return rows


def drawing(doc, lib):
    """1-1/2" wall section through a window head and sill (MCSectionCut logic + pipeline)."""
    from mindcanvas.drawing import pipeline, sectioncut, styles
    f = lambda v: _ft(doc, v)
    st = styles.get("1-1/2", lib)
    y = -84.0
    r = engine.create(doc, _add(doc, G.LineCurve(G.Point3d(f(8), f(y), 0), G.Point3d(0, f(y), 0))),
                      BRICK, {"height": "9'-4\"", "lod": "detail"}, lib)
    _place(doc, lib, r.driver_id, WINDOW, G.Point3d(f(4), f(y), 0), sill=SILL_IN, height=HEIGHT_IN)
    drv = doc.Objects.FindId(r.driver_id)
    view = [v for v in doc.Views if v.ActiveViewport.Name == "Front"][0]
    view.Maximized = True
    doc.Views.ActiveView = view
    # cut 1-1/4" off the window centre so the section passes through a rowlock, not a joint
    pt = G.Point3d(f(4) - units.to_model(doc, 1.25), f(y), f(4))
    res = sectioncut.make(doc, drv, pt, view, name="phase4 window", depth_in=30.0, style=st)
    o, N = res["origin"], res["frame"].YAxis
    lo = G.Point3d(o.X, o.Y, 0) + N * f(1.45)
    hi = G.Point3d(o.X, o.Y, 0) - N * f(1.3)
    box = G.BoundingBox([G.Point3d(lo.X, lo.Y, f(2.55)), G.Point3d(hi.X, hi.Y, f(7.55))])
    view.ActiveViewport.ZoomBoundingBox(box)
    doc.Views.Redraw()
    t = time.time()
    dwg = pipeline.make(doc, view, st, True, True, print, window=[box.Min, box.Max])
    paths = pipeline.write(dwg, os.path.join(ROOT, "docs", "drawings", "c_window_section_1-1-2"))
    print("(c) window section 1-1/2: {:.1f}s {}".format(time.time() - t, dwg.stats))
    for p in paths:
        print("   ->", p)
    mats = set(rg.material for rg in dwg.regions)
    print("   cut materials:", sorted(mats))
    for m in ("Glass", "Steel Angle", "Aluminum", "Wood Trim", "Flashing", "Sealant", "Backer Rod"):
        assert m in mats, "{} missing from the window section".format(m)
    assert any(m.startswith("Brick") for m in mats), mats
    assert dwg.stats["regions"] >= 40, dwg.stats
    return dwg


def run(doc, clear=True, drawing_on=True, captures=True):
    if clear:
        for o in list(doc.Objects):
            doc.Objects.Delete(o, True)
        for i in range(doc.NamedViews.Count - 1, -1, -1):
            doc.NamedViews.Delete(i)
    engine.setup_document(doc)
    lib = library.get(force_reload=True)
    t0 = time.time()
    print("-- straight walls")
    walls = straight_walls(doc, lib)
    print("-- two-sided brick")
    two_sided(doc, lib)
    print("-- corners and arcs")
    walls.update(corner_and_arc(doc, lib))
    print("-- level of detail")
    lods(doc, lib)
    print("-- schedule")
    opening_schedule(doc)
    print("-- snap heads to the brick coursing")
    snapping(doc, lib, walls[BRICK], walls[WOOD])
    print("-- edits")
    edits(doc, lib, walls[WOOD])
    if captures:
        try:
            cap = runpy.run_path(os.path.join(HERE, "capture.py"))["capture"]
            v = [x for x in doc.Views if x.ActiveViewport.Name == "Perspective"][0]
            vp = v.ActiveViewport
            f = lambda v_: _ft(doc, v_)
            vp.ChangeToPerspectiveProjection(True, 35)
            vp.SetCameraLocations(G.Point3d(f(8), f(-24), f(4)), G.Point3d(f(12), f(-44), f(7)))
            print(cap(doc, "phase4_brick_ext", zoom_extents=False))
            vp.SetCameraLocations(G.Point3d(f(78), f(-4), f(4)), G.Point3d(f(80), f(-30), f(9)))
            print(cap(doc, "phase4_arcs", zoom_extents=False))
            vp.SetCameraLocations(G.Point3d(f(30), f(-4), f(4)), G.Point3d(f(16), f(-26), f(12)))
            print(cap(doc, "phase4_corners", zoom_extents=False))
        except Exception as ex:
            print("captures skipped:", ex)
    if drawing_on:
        print("-- drawing")
        drawing(doc, lib)
    doc.Views.Redraw()
    print("total {:.1f}s".format(time.time() - t0))
    print("PHASE 4 OK")
