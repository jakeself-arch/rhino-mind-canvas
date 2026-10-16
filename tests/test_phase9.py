"""Phase 9: mass drivers + opening masses.

Run inside Rhino (e.g. via the MCP run_python tool), in an EMPTY, unsaved document (it is cleared):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_phase9.py")["run"](__rhino_doc__, log=ROOT + r"\\phase9.log")

Covers: a box crossing a wall becomes a window / door whose rough opening is the box's cut (depth
ignored; unit = RO - shims); live mode: a gumball scale / move of the box re-derives the opening
(the idle handler is called directly), deleting the box deletes the opening, deleting the wall
deletes the box; two-way: a numeric edit, a moved opening line and a moved / rotated wall move and
resize the box; a type change goes to the mass; one box through two parallel walls opens both,
and moving it off one removes that opening; a box over a wall corner or past a wall end is
rejected with a warning; a tilted box uses its bounding rectangle (warning); a curved wall;
SnapHead on brick (the unit snaps, the box stays); masses are on an `exclude` layer and never
reach a drawing scene; Convert gives a line opening a box; the command module imports and the
panel has its button; rebuild timings of a brick wall at detail.
drawing_on=True writes h_opening_masses_quarter (a brick wall whose openings come from masses).
"""

import os
import runpy
import time

import scriptcontext
import Rhino

from mindcanvas import docutil, engine, library, live, masses, meta, units
from mindcanvas.drawing import scene as scene_mod, tags
from mindcanvas.openings import core

G = Rhino.Geometry
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "drawings")
LOG = [None]

WOOD = "Ext - 2x6 Wood, Fiber Cement"
BRICK = 'Ext - Brick Veneer / 6" Metal Stud'
WINDOW, CASEMENT, DOOR = "Window - Fixed", "Window - Casement", "Door - Hollow Metal"
HEIGHT = 109.0
TIMINGS = {}


def say(*a):
    msg = " ".join(str(x) for x in a)
    print(msg)
    if LOG[0]:
        with open(LOG[0], "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def _ft(doc, v):
    return units.to_model(doc, v * 12.0)


def _wall(doc, lib, asm, *pts_ft, **prm):
    f = lambda v: _ft(doc, v)
    prm.setdefault("height", HEIGHT)
    crv = G.PolylineCurve([G.Point3d(f(x), f(y), 0) for x, y in pts_ft])
    obj = doc.Objects.FindId(doc.Objects.AddCurve(crv))
    r = engine.create(doc, obj, asm, prm, lib)
    assert not [w for w in r.warnings if "skipped" in w or "failed" in w], r.warnings
    return doc.Objects.FindId(r.driver_id)


def _box(doc, x0, x1, y0, y1, z0, z1, plane=None):
    f = lambda v: _ft(doc, v)
    b = G.Box(plane or G.Plane.WorldXY, G.Interval(f(x0), f(x1)), G.Interval(f(y0), f(y1)),
              G.Interval(f(z0), f(z1))).ToBrep()
    return doc.Objects.FindId(doc.Objects.AddBrep(b))


def _idle():
    """What Rhino's Idle does in live mode after a command."""
    st = scriptcontext.sticky[live.STICKY_KEY]
    st["handlers"][2](None, None)
    assert not st["queue"], st["queue"]


def _bb(doc, oid):
    return doc.Objects.FindId(oid).Geometry.GetBoundingBox(True)


def _near(a, b, tol=1.0 / 64):
    return abs(a - b) < tol


def _ops(doc, mass):
    return masses.openings_of(doc, mass.Id)


def _p(doc, op):
    return meta.params(doc.Objects.FindId(op.Id))


# -- tests ---------------------------------------------------------------------------------------
def basics(doc, lib):
    """Box -> window / door: unit = rough opening - shims; depth ignored."""
    w = _wall(doc, lib, WOOD, (0, 0), (16, 0))
    m, sr = masses.make(doc, _box(doc, 6, 9, -0.2, 3, 3, 7), CASEMENT, {"snap": False}, lib)
    assert not sr.warnings, sr.warnings
    assert len(sr.openings) == 1 and len(sr.results) == 1
    p = _p(doc, _ops(doc, m)[0])
    assert p["ro"] == {"width": 36.0, "bottom": 36.0, "top": 84.0}, p
    assert (p["width"], p["height"], p["sill"], p["station"]) == (35.0, 47.0, 36.5, 90.0), p
    lay = doc.Layers[doc.Objects.FindId(m.Id).Attributes.LayerIndex]
    assert lay.FullPath == docutil.MASS_LAYER and "exclude" in tags.parse(lay.GetUserString(tags.KEY))
    unit = [o for o in meta.parts_of(doc, w.Id)
            if str(_ops(doc, m)[0].Id) in (meta.get(o, meta.EXTRA_PREFIX + core.OPENING_KEY) or "")]
    assert len(unit) > 5, "the casement was built"
    # a door box that starts below the floor: sill 0, no shim under it
    d, sr = masses.make(doc, _box(doc, 11, 14.25, -1, 1, -0.5, 7.25), DOOR, {}, lib)
    pd = _p(doc, _ops(doc, d)[0])
    assert (pd["sill"], pd["width"], pd["height"]) == (0.0, 38.0, 86.5), pd
    say("  box -> window {}x{} sill {}; door {}x{}".format(p["width"], p["height"], p["sill"], pd["width"], pd["height"]))
    return w, m, d


def live_edits(doc, lib, w, m):
    """Gumball scale + move of the box (Replace) rebuilds on Idle."""
    f = lambda v: _ft(doc, v)
    xf = G.Transform.Translation(0, 0, f(1)) * G.Transform.Scale(G.Plane(G.Point3d(f(6), 0, 0), G.Vector3d.ZAxis), 1.5, 1, 1)
    t = time.time()
    assert doc.Objects.Transform(m.Id, xf, True) == m.Id
    _idle()
    TIMINGS["wood wall, design->detail live edit"] = time.time() - t
    p = _p(doc, _ops(doc, m)[0])
    assert p["ro"]["width"] == 54.0 and p["ro"]["bottom"] == 48.0 and p["station"] == 99.0, p
    assert _near(p["width"], 53.0) and _near(p["sill"], 48.5), p
    # Ctrl+Shift face drag = a Replace with new geometry: push the top face up 6"
    b = masses.to_brep(doc.Objects.FindId(m.Id).Geometry)
    top = max(range(b.Faces.Count), key=lambda i: b.Faces[i].GetBoundingBox(True).Min.Z)
    moved = b.TransformComponent([G.ComponentIndex(G.ComponentIndexType.BrepFace, top)],
                                 G.Transform.Translation(0, 0, f(0.5)), doc.ModelAbsoluteTolerance, 0, True)
    assert moved
    doc.Objects.Replace(m.Id, b)
    _idle()
    p = _p(doc, _ops(doc, m)[0])
    assert p["ro"]["top"] == 102.0 and _near(p["height"], 53.0), p
    say("  live: scale + move, face push -> RO {}".format(p["ro"]))


def two_way(doc, lib, w, m, d):
    """Numbers, the opening line and the wall drive the box back."""
    f = lambda v: _ft(doc, v)
    op = _ops(doc, m)[0]
    engine.update_opening(doc, op, {"width": 24, "sill": 30})
    bb = _bb(doc, m.Id)
    assert "ro" not in _p(doc, op)
    assert _near(bb.Max.X - bb.Min.X, f(25 / 12.0), 1e-6) and _near(bb.Min.Z, f(29.5 / 12.0), 1e-6), bb
    assert _near(0.5 * (bb.Min.X + bb.Max.X), f(99 / 12.0), 1e-6), bb
    # the type goes to the mass
    engine.update_opening(doc, doc.Objects.FindId(op.Id), type_name=WINDOW)
    assert meta.get(doc.Objects.FindId(m.Id), meta.ASSEMBLY) == WINDOW
    # the opening line moved 2' along the wall (what live mode does on its Replace)
    line = doc.Objects.FindId(op.Id).Geometry.DuplicateCurve()
    line.Translate(G.Vector3d(f(-2), 0, 0))
    with live.quiet():
        doc.Objects.Replace(op.Id, line)
    engine.build(doc, op.Id, lib)
    assert _near(0.5 * (_bb(doc, m.Id).Min.X + _bb(doc, m.Id).Max.X), f(75 / 12.0), 1e-6)
    # the wall moved 3' and turned 20 degrees: the box goes with the opening
    import math
    xf = G.Transform.Rotation(math.radians(20), G.Vector3d.ZAxis, G.Point3d(0, f(3), 0)) * G.Transform.Translation(0, f(3), 0)
    doc.Objects.Transform(w.Id, xf, True)
    _idle()
    from mindcanvas.kinds import wall as wk
    w = doc.Objects.FindId(w.Id)
    ctx = wk.make_context(doc, lib, w, meta.get(w, meta.ASSEMBLY), meta.params(w))
    rec = [o for o in ctx.openings if o.id == op.Id][0]
    cur = masses.rect_local(ctx, rec, masses.to_brep(doc.Objects.FindId(m.Id).Geometry))
    tgt = masses.target_local(ctx, rec)
    assert cur is not None and masses._close(cur, tgt, ctx.u(1.0 / 32)), (cur, tgt)
    # the other box in that wall (the door) followed too
    drec = [o for o in ctx.openings if o.id == _ops(doc, d)[0].Id][0]
    cur = masses.rect_local(ctx, drec, masses.to_brep(doc.Objects.FindId(d.Id).Geometry))
    assert cur is not None and masses._close(cur, masses.target_local(ctx, drec), ctx.u(1.0 / 32))
    say("  two-way: numbers, line, wall move + turn -> box follows")
    return w


def parallel_and_corners(doc, lib):
    """One box through two walls opens both; corners and wall ends are rejected; tilted boxes warn."""
    a = _wall(doc, lib, WOOD, (0, 30), (20, 30))
    b = _wall(doc, lib, WOOD, (20, 36), (0, 36))
    m, sr = masses.make(doc, _box(doc, 8, 11, 28, 38, 3, 7), WINDOW, {}, lib)
    assert len(sr.openings) == 2 and len(sr.results) == 2, sr
    hosts = sorted(meta.get(o, core.HOST) for o in _ops(doc, m))
    assert hosts == sorted([str(a.Id), str(b.Id)])
    # pull the box back so it only crosses wall a
    b_brep = masses.to_brep(doc.Objects.FindId(m.Id).Geometry)
    b_brep.Transform(G.Transform.Scale(G.Plane(G.Point3d(0, _ft(doc, 28), 0), G.Vector3d.XAxis, G.Vector3d.YAxis), 1, 0.4, 1))
    doc.Objects.Replace(m.Id, b_brep)
    _idle()
    assert [meta.get(o, core.HOST) for o in _ops(doc, m)] == [str(a.Id)]
    assert not core.hosted(doc, b.Id)
    # corner of an L wall
    L = _wall(doc, lib, WOOD, (40, 30), (56, 30), (56, 44))
    mc, sr = masses.make(doc, _box(doc, 54, 58, 28, 32, 3, 7), WINDOW, {}, lib)
    assert not sr.openings and any("corner" in x for x in sr.warnings), sr.warnings
    # past the end of a straight wall
    me, sr = masses.make(doc, _box(doc, 18, 22, 29, 31, 3, 7), WINDOW, {}, lib)
    assert any("end" in x for x in sr.warnings), sr.warnings
    assert [meta.get(o, core.HOST) for o in _ops(doc, me)] == [], "a crosses at its end only"
    # tilted box: bounding rectangle
    pl = G.Plane(G.Point3d(_ft(doc, 46), _ft(doc, 30), 0), G.Vector3d.XAxis, G.Vector3d.YAxis)
    pl.Rotate(0.15, G.Vector3d.YAxis)
    mt, sr = masses.make(doc, _box(doc, -1.5, 1.5, -1, 1, 3, 7, plane=pl), WINDOW, {}, lib)
    assert len(sr.openings) == 1 and any("bounding rectangle" in x for x in sr.warnings), sr.warnings
    # curved wall
    arc = G.Arc(G.Point3d(_ft(doc, 70), _ft(doc, 30), 0), G.Point3d(_ft(doc, 80), _ft(doc, 36), 0),
                G.Point3d(_ft(doc, 90), _ft(doc, 30), 0)).ToNurbsCurve()
    cw = engine.create(doc, doc.Objects.FindId(doc.Objects.AddCurve(arc)), WOOD, {"height": HEIGHT}, lib)
    mk, sr = masses.make(doc, _box(doc, 78.5, 81.5, 33, 39, 3, 7), WINDOW, {}, lib)
    assert len(sr.openings) == 1, sr.warnings
    pk = _p(doc, _ops(doc, mk)[0])
    assert abs(pk["ro"]["width"] - 36.0) < 0.5, pk
    say("  parallel walls, corner / end rejected, tilted box, curved wall OK")


def brick_snap(doc, lib):
    """SnapHead on brick: the unit snaps to the coursing, the box stays; timings at detail."""
    f = lambda v: _ft(doc, v)
    w = _wall(doc, lib, BRICK, (0, 60), (24, 60), reference="core_exterior")
    m, sr = masses.make(doc, _box(doc, 8, 12, 59, 62, 3, 7.3), WINDOW, {"snap": True}, lib)
    assert len(sr.openings) == 1, sr.warnings
    p = _p(doc, _ops(doc, m)[0])
    assert p["ro"] == {"width": 48.0, "bottom": 36.0, "top": 87.6}, p
    raw_sill = 36.0 + 0.5
    assert not _near(p["sill"], raw_sill), "the sill snapped to the coursing"
    TIMINGS["brick wall at detail, make"] = sr.seconds
    bb0 = _bb(doc, m.Id)
    # a gumball move along the wall: the box stays where it is put, the unit snaps again
    t = time.time()
    doc.Objects.Transform(m.Id, G.Transform.Translation(f(4), 0, 0), True)
    _idle()
    TIMINGS["brick wall at detail, live move"] = time.time() - t
    bb1 = _bb(doc, m.Id)
    assert _near(bb1.Min.X - bb0.Min.X, f(4), 1e-6) and _near(bb1.Min.Z, bb0.Min.Z, 1e-6)
    # a rebuild of the wall alone (MCUpdate) does not move the box by the snap
    engine.build(doc, w.Id, lib)
    bb2 = _bb(doc, m.Id)
    assert _near(bb2.Min.Z, bb1.Min.Z, 1e-6) and _near(bb2.Max.Z, bb1.Max.Z, 1e-6), (bb1, bb2)
    n = len(meta.parts_of(doc, w.Id))
    say("  brick + SnapHead: sill {} (RO bottom 36), {} parts".format(p["sill"], n))
    return w, m


def convert_and_deletes(doc, lib, brick_wall, brick_mass):
    """Convert a line opening; deleting a box / a wall / an opening."""
    op, r = engine.add_opening(doc, brick_wall, DOOR, {}, brick_wall.Geometry.PointAtNormalizedLength(0.8), lib)
    m = masses.from_opening(doc, op, lib)
    assert masses.mass_of(doc, doc.Objects.FindId(op.Id)).Id == m.Id
    bb = _bb(doc, m.Id)
    t = core.merged_type(lib, DOOR)
    assert _near(bb.Max.X - bb.Min.X, _ft(doc, (units.parse_length(t["width"]) + 1.0) / 12.0), 1e-6)
    # sync of a converted box keeps the opening (same rough opening)
    p0 = _p(doc, op)
    masses.sync(doc, doc.Objects.FindId(m.Id), lib)
    p1 = _p(doc, op)
    assert all(_near(p0[k], p1[k]) for k in ("width", "height", "sill", "station")), (p0, p1)
    # delete the box (live): its opening goes, the wall rebuilds
    doc.Objects.Delete(m.Id, True)
    _idle()
    assert doc.Objects.FindId(op.Id) is None or doc.Objects.FindId(op.Id).IsDeleted
    # delete the wall (live): its last box goes too
    n = len(masses.all_masses(doc))
    doc.Objects.Delete(brick_wall.Id, True)
    _idle()
    gone = doc.Objects.FindId(brick_mass.Id)
    assert gone is None or gone.IsDeleted, "the brick wall's box was deleted with it"
    assert len(masses.all_masses(doc)) == n - 1
    say("  convert, delete box, delete wall OK")


def drawing_scene(doc, lib):
    """Masses never reach a drawing."""
    sc = scene_mod.Scene(doc)
    items = sc.collect()
    ids = set(str(m.Id) for m in masses.all_masses(doc))
    assert ids and not [it for it in items if str(it.obj_id) in ids]
    say("  drawing scene: {} items, no masses".format(len(items)))


def ui_bits(doc):
    import importlib
    mod = importlib.import_module("mindcanvas.cmd.openingmass")
    assert hasattr(mod, "run")
    assert os.path.exists(os.path.join(ROOT, "commands", "MCOpeningMass.py"))
    from mindcanvas.eto import panel
    assert ("Opening mass", "MCOpeningMass") in panel.BUILD
    assert masses.set_visible(doc, False) is False and masses.set_visible(doc, True) is True


def drawing(doc, lib):
    from mindcanvas.drawing import displaymode, pipeline, sectionstyle, styles
    f = lambda v: _ft(doc, v)
    y = 100.0
    w = _wall(doc, lib, BRICK, (0, y), (20, y), reference="core_exterior", lod="design")
    for x0, x1, z0, z1, t in ((2, 6, 3, 7.3, WINDOW), (8.5, 11.75, -0.5, 7.4, DOOR), (14, 18, 3, 7.3, CASEMENT)):
        masses.make(doc, _box(doc, x0, x1, y - 1.5, y + 1.5, z0, z1), t, {"snap": True}, lib)
    st = styles.get("1/4", lib)
    view = [v for v in doc.Views if v.ActiveViewport.Name == "Perspective"][0]
    vp = view.ActiveViewport
    vp.ChangeToPerspectiveProjection(True, 35.0)
    vp.SetCameraLocations(G.Point3d(f(10), f(y + 2), f(5)), G.Point3d(f(4), f(y - 22), f(6)))
    doc.Views.ActiveView = view
    displaymode.assign(view)
    sectionstyle.apply(doc, st)
    doc.Views.Redraw()
    t = time.time()
    dwg = pipeline.make(doc, view, st, True, False, say)
    pipeline.write(dwg, os.path.join(OUT, "h_opening_masses_quarter"))
    say("  drawing h_opening_masses_quarter: {:.1f}s {}".format(time.time() - t, dwg.stats))
    return w


# -- run ------------------------------------------------------------------------------------------
def run(doc, clear=True, drawing_on=True, captures=True, log=None):
    assert not doc.Path, "test_phase9 clears the document: run it in an empty, unsaved model"
    LOG[0] = log
    if clear:
        for o in list(doc.Objects):
            doc.Objects.Delete(o, True)
        docutil.purge_unused_blocks(doc)
    engine.setup_document(doc)
    lib = library.get(force_reload=True)
    was_live = live.is_on()
    live.disable()
    live.enable()       # fresh handlers (the code may have been reloaded)
    t0 = time.time()
    try:
        say("-- basics")
        w, m, d = basics(doc, lib)
        say("-- live")
        live_edits(doc, lib, w, m)
        say("-- two-way")
        two_way(doc, lib, w, m, d)
        say("-- parallel walls, corners")
        parallel_and_corners(doc, lib)
        say("-- brick + SnapHead")
        bw, bm = brick_snap(doc, lib)
        say("-- convert, delete")
        convert_and_deletes(doc, lib, bw, bm)
        say("-- drawing scene, ui")
        drawing_scene(doc, lib)
        ui_bits(doc)
        if drawing_on:
            say("-- drawing")
            drawing(doc, lib)
        if captures:
            try:
                cap = runpy.run_path(os.path.join(HERE, "capture.py"))["capture"]
                f = lambda v_: _ft(doc, v_)
                vp = [x for x in doc.Views if x.ActiveViewport.Name == "Perspective"][0].ActiveViewport
                vp.ChangeToPerspectiveProjection(True, 35.0)
                if drawing_on:      # the brick wall of the drawing, its boxes around the openings
                    vp.SetCameraLocations(G.Point3d(f(10), f(100), f(5)), G.Point3d(f(-2), f(80), f(12)))
                say(cap(doc, "phase9_masses", mode="Shaded", zoom_extents=not drawing_on, width=1200, height=700))
            except Exception as ex:
                say("captures skipped:", ex)
    finally:
        live.disable()
        if was_live:
            live.enable()
    for k, v in sorted(TIMINGS.items()):
        say("  timing {}: {:.2f}s".format(k, v))
    doc.Views.Redraw()
    say("total {:.1f}s".format(time.time() - t0))
    say("PHASE 9 OK")
