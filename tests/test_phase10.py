"""Phase 10: wall masses.

Run inside Rhino (e.g. via the MCP run_python tool), in an EMPTY, unsaved document (it is cleared):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_phase10.py")["run"](__rhino_doc__, log=ROOT + r"\\phase10.log")

Covers: boxes -> walls whose finished exterior face lies on the mass's outer face (the mass's
thickness is ignored; base / height from the mass); an L of two boxes and a closed ring of four
(butt and overlapping corners) orient themselves (exterior outside) and join (L), a partition box
joins as a T at the interior face; live mode (the idle handler is called directly): a gumball
height scale, a Ctrl+Shift face drag (the corners follow), a box moved away and back (corners
retract / rejoin); openings keep their place, an opening mass follows its wall; two-way: height /
base offset edits resize the mass, Flip (MCEdit and wallmasses.flip); a single strip mass (L
polyline), a curved strip and a ring mass; a lone box faces the camera and keeps its side when
turned; Convert keeps a wall where it is; deleting a mass deletes its wall + openings, deleting a
wall deletes its mass; perimeter masses (a cube with a partition, an L-shaped block, a cylinder:
one closed wall around the outline), Mode strip / perimeter; masses never reach a drawing; the command module + panel button; timings.
"""

import math
import os
import runpy
import time

import scriptcontext
import Rhino

from mindcanvas import docutil, engine, library, live, masses, meta, units, wallmasses
from mindcanvas.drawing import scene as scene_mod
from mindcanvas.kinds import wall as wk
from mindcanvas.openings import core

G = Rhino.Geometry
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = [None]

WOOD = "Ext - 2x6 Wood, Fiber Cement"
BRICK = 'Ext - Brick Veneer / 6" Metal Stud'
WINDOW = "Window - Fixed"
TIMINGS = {}


def say(*a):
    msg = " ".join(str(x) for x in a)
    print(msg)
    if LOG[0]:
        with open(LOG[0], "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def _ft(doc, v):
    return units.to_model(doc, v * 12.0)


def _box(doc, x0, x1, y0, y1, z0, z1, plane=None):
    f = lambda v: _ft(doc, v)
    b = G.Box(plane or G.Plane.WorldXY, G.Interval(f(x0), f(x1)), G.Interval(f(y0), f(y1)),
              G.Interval(f(z0), f(z1))).ToBrep()
    return doc.Objects.FindId(doc.Objects.AddBrep(b))


def _prism(doc, pts_ft, z0, z1, holes=()):
    f = lambda v: _ft(doc, v)
    tol = doc.ModelAbsoluteTolerance
    crvs = [G.PolylineCurve([G.Point3d(f(x), f(y), f(z0)) for x, y in list(p) + [p[0]]]) for p in [pts_ft] + list(holes)]
    region = G.Brep.CreatePlanarBreps(crvs, tol)[0]
    solid = region.Faces[0].CreateExtrusion(G.LineCurve(G.Point3d(0, 0, 0), G.Point3d(0, 0, f(z1 - z0))), True)
    if solid.SolidOrientation == G.BrepSolidOrientation.Inward:
        solid.Flip()
    return doc.Objects.FindId(doc.Objects.AddBrep(solid))


def _idle():
    """What Rhino's Idle does in live mode after a command."""
    st = scriptcontext.sticky[live.STICKY_KEY]
    st["handlers"][2](None, None)
    assert not st["queue"], st["queue"]


def _near(a, b, tol=1.0 / 64):
    return abs(a - b) < tol


def _wall(doc, m):
    w = wallmasses.wall_of(doc, doc.Objects.FindId(m.Id))
    assert w is not None, "mass {} has a wall".format(str(m.Id)[:8])
    return w


def _ends(doc, w):
    """(start, end) of a wall driver in feet (x, y)."""
    c = doc.Objects.FindId(w.Id).Geometry
    k = 1.0 / _ft(doc, 1)
    return ((round(c.PointAtStart.X * k, 3), round(c.PointAtStart.Y * k, 3)),
            (round(c.PointAtEnd.X * k, 3), round(c.PointAtEnd.Y * k, 3)))


def _ctx(doc, lib, w):
    w = doc.Objects.FindId(w.Id)
    return wk.make_context(doc, lib, w, meta.get(w, meta.ASSEMBLY), meta.params(w))


def _joins(doc, lib, w):
    return " | ".join(_ctx(doc, lib, w).joins.notes)


def _exterior(doc, lib, w):
    """(point on the exterior face at mid-length, outward unit vector), feet."""
    ctx = _ctx(doc, lib, w)
    crv = ctx.curve
    ok, t = crv.LengthParameter(0.5 * crv.GetLength())
    pl = __import__("mindcanvas.geo", fromlist=["x"]).frame_at(crv, t, 0.0)
    y = max(b.d_ext for b in ctx.bands)
    p = pl.Origin + pl.YAxis * y
    k = 1.0 / _ft(doc, 1)
    return (round(p.X * k, 3), round(p.Y * k, 3)), (round(pl.YAxis.X, 3), round(pl.YAxis.Y, 3))


def _thick(doc, lib, w):
    ctx = _ctx(doc, lib, w)
    return (max(b.d_ext for b in ctx.bands) - min(b.d_int for b in ctx.bands)) / _ft(doc, 1)


def _bb(doc, oid):
    return doc.Objects.FindId(oid).Geometry.GetBoundingBox(True)


def _deleted(doc, oid):
    o = doc.Objects.FindId(oid)
    return o is None or o.IsDeleted


# -- tests ---------------------------------------------------------------------------------------
def l_corner(doc, lib):
    """Two boxes (one butting into the other): exterior faces on the outer faces, an L join."""
    a = _box(doc, 0, 20, -60, -58.5, 0, 9)        # 1'-6" thick masses, the wall is ~7-1/2"
    b = _box(doc, 0, 1.5, -58.5, -46, 0, 9)
    objs, sr = wallmasses.make_many(doc, [a, b], WOOD, {}, lib)
    assert not sr.warnings and len(sr.walls) == 2 and len(sr.results) == 2, (sr.warnings, sr)
    wa, wb = _wall(doc, objs[0]), _wall(doc, objs[1])
    pa, na = _exterior(doc, lib, wa)
    pb, nb = _exterior(doc, lib, wb)
    assert _near(pa[1], -60) and na == (0.0, -1.0), (pa, na)
    assert _near(pb[0], 0) and nb == (-1.0, 0.0), (pb, nb)
    assert (0.0, -60.0) in _ends(doc, wa) and (0.0, -60.0) in _ends(doc, wb), (_ends(doc, wa), _ends(doc, wb))
    p = meta.params(wa)
    assert p["height"] == 108.0 and p["reference"] == "exterior_face" and p.get("base_offset", 0) == 0, p
    assert "L join" in _joins(doc, lib, wa) and "L join" in _joins(doc, lib, wb)
    t = _thick(doc, lib, wa)
    assert 0.5 < t < 1.0, t
    say("  L: exterior on the outer faces, drivers meet at the corner, L joined (wall {:.3f}' in a 1.5' mass)".format(t))


def ring(doc, lib):
    """A closed ring of four boxes (butt + overlapping corners) and a partition (T)."""
    S = _box(doc, 0, 30, 0, 1.5, 0, 9)
    N = _box(doc, 0, 30, 20, 21.5, 0, 9)
    W = _box(doc, 0, 1.5, 1.5, 20, 0, 9)          # butts between S and N
    E = _box(doc, 28.5, 30, 0, 21.5, 0, 9)        # overlaps S and N
    P = _box(doc, 14, 15, 1.5, 20, 0, 9)          # partition
    t0 = time.time()
    objs, sr = wallmasses.make_many(doc, [S, N, W, E, P], WOOD, {}, lib)
    TIMINGS["ring of 4 + partition, make (wood, detail)"] = time.time() - t0
    assert not sr.warnings, sr.warnings
    S, N, W, E, P = objs
    expect = {"S": ((15, 0), (0.0, -1.0)), "N": ((15, 21.5), (0.0, 1.0)),
              "W": ((0, 10.75), (-1.0, 0.0)), "E": ((30, 10.75), (1.0, 0.0))}
    for key, m in zip("SNWE", (S, N, W, E)):
        w = _wall(doc, m)
        p, n = _exterior(doc, lib, w)
        (ex, ey), en = expect[key]
        assert n == en and (_near(p[0], ex) if key in "WE" else _near(p[1], ey)), (key, p, n)
        j = _joins(doc, lib, w)
        assert j.count("L join") == 2, (key, j)
    assert sorted(_ends(doc, _wall(doc, W))) == [(0.0, 0.0), (0.0, 21.5)], _ends(doc, _wall(doc, W))
    assert sorted(_ends(doc, _wall(doc, E))) == [(30.0, 0.0), (30.0, 21.5)]
    wp = _wall(doc, P)
    jp = _joins(doc, lib, wp)
    assert jp.count("T join") == 2, jp
    ts = _thick(doc, lib, _wall(doc, S))
    ys = sorted(e[1] for e in _ends(doc, wp))
    assert _near(ys[0], ts, 1e-3) and _near(ys[1], 21.5 - ts, 1e-3), (ys, ts)
    assert "T join from" in _joins(doc, lib, _wall(doc, S))
    say("  ring: exterior outside on all four, 4 L corners, partition T at the interior faces")
    return S, N, W, E, P


def live_ring(doc, lib, S, N, W, E, P):
    """Gumball edits of ring masses (live), openings / opening mass along."""
    f = lambda v: _ft(doc, v)
    wS, wN = _wall(doc, S), _wall(doc, N)
    # a window in S (station from its start) and an opening mass through N
    op, r = engine.add_opening(doc, wS, WINDOW, {"width": 36, "height": 48, "sill": 30},
                               G.Point3d(f(8), 0, 0), lib)
    om, osr = masses.make(doc, _box(doc, 20, 23, 19, 22.5, 3, 7), WINDOW, {}, lib)
    assert len(osr.openings) == 1, osr.warnings

    def win_x():
        ctx = _ctx(doc, lib, wS)
        rec = [o for o in ctx.openings if o.id == op.Id][0]
        return round(rec.plane.Origin.X / f(1), 3), round(rec.plane.Origin.Y / f(1), 3)

    x0 = win_x()
    assert _near(x0[0], 8, 0.01), x0
    bo = _bb(doc, om.Id)
    # 1. gumball: N taller by 20% (scale about its base)
    t = time.time()
    doc.Objects.Transform(N.Id, G.Transform.Scale(G.Plane(G.Point3d(0, 0, 0), G.Vector3d.ZAxis), 1, 1, 1.2), True)
    _idle()
    TIMINGS["live: height scale of one ring wall"] = time.time() - t
    assert _near(meta.params(_wall(doc, N))["height"], 129.6), meta.params(_wall(doc, N))
    # 2. Ctrl+Shift face drag: E's outer face 1' out -> S and N follow to the new corner
    b = masses.to_brep(doc.Objects.FindId(E.Id).Geometry)
    face = max(range(b.Faces.Count), key=lambda i: b.Faces[i].GetBoundingBox(True).Min.X)
    assert b.TransformComponent([G.ComponentIndex(G.ComponentIndexType.BrepFace, face)],
                                G.Transform.Translation(f(1), 0, 0), doc.ModelAbsoluteTolerance, 0, True)
    t = time.time()
    doc.Objects.Replace(E.Id, b)
    _idle()
    TIMINGS["live: face drag (corner wall + 2 neighbors)"] = time.time() - t
    for m in (S, N):
        xs = sorted(e[0] for e in _ends(doc, _wall(doc, m)))
        assert _near(xs[1], 31.0, 1e-3), (xs, _ends(doc, _wall(doc, m)))
        assert _joins(doc, lib, _wall(doc, m)).count("L join") == 2
    assert win_x() == x0, (win_x(), x0)
    bb = _bb(doc, om.Id)
    assert _near(bb.Min.X, bo.Min.X, 1e-6) and _near(bb.Min.Y, bo.Min.Y, 1e-6), "the opening mass stays"
    # 3. S moved 2' away (-y): it stands alone, W loses its corner; then back
    t = time.time()
    doc.Objects.Transform(S.Id, G.Transform.Translation(0, f(-2), 0), True)
    _idle()
    TIMINGS["live: move a wall mass (detaches)"] = time.time() - t
    pS, nS = _exterior(doc, lib, _wall(doc, S))
    assert nS == (0.0, -1.0) and _near(pS[1], -2), (pS, nS)
    assert "L join" not in _joins(doc, lib, _wall(doc, S))
    assert sorted(e[1] for e in _ends(doc, _wall(doc, W)))[0] == 1.5, _ends(doc, _wall(doc, W))
    assert win_x() == (x0[0], -2.0), win_x()
    doc.Objects.Transform(S.Id, G.Transform.Translation(0, f(2), 0), True)
    _idle()
    assert _joins(doc, lib, _wall(doc, S)).count("L join") == 2
    assert sorted(e[1] for e in _ends(doc, _wall(doc, W)))[0] == 0.0
    assert win_x() == x0, (win_x(), x0)
    # 4. N moved 1' out (+y): the opening mass through it follows its opening
    doc.Objects.Transform(N.Id, G.Transform.Translation(0, f(1), 0), True)
    _idle()
    bb = _bb(doc, om.Id)
    assert _near(bb.Min.Y - bo.Min.Y, f(1), 1e-6) and _near(bb.Min.X, bo.Min.X, 1e-6), (bb.Min, bo.Min)
    doc.Objects.Transform(N.Id, G.Transform.Translation(0, f(-1), 0), True)      # and back
    _idle()
    assert _near(_bb(doc, om.Id).Min.Y, bo.Min.Y, 1e-6)
    assert _joins(doc, lib, _wall(doc, P)).count("T join") == 2
    say("  live: height scale, face drag (corners follow), detach + rejoin, window stays, opening mass follows")
    return op, om


def two_way(doc, lib, S, N):
    """Numbers drive the mass; Flip."""
    f = lambda v: _ft(doc, v)
    wN = _wall(doc, N)
    t = time.time()
    engine.update_params(doc, wN, {"height": 100, "base_offset": 6}, lib)
    TIMINGS["MCEdit height + base of a mass wall"] = time.time() - t
    bb = _bb(doc, N.Id)
    assert _near(bb.Min.Z, f(0.5), 1e-6) and _near(bb.Max.Z - bb.Min.Z, f(100 / 12.0), 1e-6), bb
    assert _near(doc.Objects.FindId(wN.Id).Geometry.PointAtStart.Z, 0.0, 1e-9)
    # flip from the wall's params (MCEdit Flip): exterior on the mass's other face (y = 1.5')
    wS = _wall(doc, S)
    engine.update_params(doc, wS, {"flip": True}, lib)
    p, n = _exterior(doc, lib, _wall(doc, S))
    assert n == (0.0, 1.0) and _near(p[1], 1.5), (p, n)
    assert meta.params(doc.Objects.FindId(S.Id))["flip"] is True
    # ... and back with wallmasses.flip (MCWallMass Flip)
    sr = wallmasses.flip(doc, [doc.Objects.FindId(S.Id)], lib)
    p, n = _exterior(doc, lib, _wall(doc, S))
    assert n == (0.0, -1.0) and _near(p[1], 0) and not meta.params(_wall(doc, S))["flip"], (p, n)
    assert _joins(doc, lib, _wall(doc, S)).count("L join") == 2
    say("  two-way: height / base resize the mass, flip and back")


def shapes(doc, lib):
    """One strip mass for an L, a curved strip, a ring; a lone box faces the camera."""
    f = lambda v: _ft(doc, v)
    # L strip, 1' thick
    Lm, sr = wallmasses.make(doc, _prism(doc, [(60, 0), (80, 0), (80, 1), (61, 1), (61, 15), (60, 15)], 0, 9), WOOD, {}, lib)
    assert not sr.warnings, sr.warnings
    c = _wall(doc, Lm).Geometry
    ok, pl = c.TryGetPolyline()
    assert ok and pl.Count == 3, "an L driver"
    L1 = c.GetLength() / f(1)
    assert _near(L1, 35, 1e-3) or _near(L1, 33, 1e-3), L1
    wallmasses.flip(doc, [Lm], lib)
    L2 = _wall(doc, Lm).Geometry.GetLength() / f(1)
    assert _near(L1 + L2, 68, 1e-3), (L1, L2)
    # curved strip: an annular sector, radii 10' and 11'
    arc_o = G.Arc(G.Point3d(f(111), 0, 0), G.Point3d(f(100 + 11 * math.cos(math.pi / 4)), f(11 * math.sin(math.pi / 4)), 0),
                  G.Point3d(f(100), f(11), 0)).ToNurbsCurve()
    arc_i = G.Arc(G.Point3d(f(100), f(10), 0), G.Point3d(f(100 + 10 * math.cos(math.pi / 4)), f(10 * math.sin(math.pi / 4)), 0),
                  G.Point3d(f(110), 0, 0)).ToNurbsCurve()
    outline = G.Curve.JoinCurves([arc_o, G.LineCurve(arc_o.PointAtEnd, arc_i.PointAtStart), arc_i,
                                  G.LineCurve(arc_i.PointAtEnd, arc_o.PointAtStart)], doc.ModelAbsoluteTolerance)[0]
    reg = G.Brep.CreatePlanarBreps([outline], doc.ModelAbsoluteTolerance)[0]
    solid = reg.Faces[0].CreateExtrusion(G.LineCurve(G.Point3d(0, 0, 0), G.Point3d(0, 0, f(9))), True)
    if solid.SolidOrientation == G.BrepSolidOrientation.Inward:
        solid.Flip()
    Cm, sr = wallmasses.make(doc, doc.Objects.FindId(doc.Objects.AddBrep(solid)), WOOD, {}, lib)
    assert not sr.warnings, sr.warnings
    cc = _wall(doc, Cm).Geometry
    assert not cc.IsLinear(doc.ModelAbsoluteTolerance)
    r = cc.PointAtNormalizedLength(0.5).DistanceTo(G.Point3d(f(100), 0, 0)) / f(1)
    assert _near(r, 11, 1e-2) or _near(r, 10, 1e-2), r
    # ring mass (one hole): a closed wall, exterior outside
    Rm, sr = wallmasses.make(doc, _prism(doc, [(130, 0), (150, 0), (150, 12), (130, 12)], 0, 9,
                                         holes=[[(131, 1), (131, 11), (149, 11), (149, 1)]]), WOOD, {}, lib)
    assert not sr.warnings, sr.warnings
    rc = _wall(doc, Rm).Geometry
    assert rc.IsClosed and _near(rc.GetLength() / f(1), 64, 1e-3), rc.GetLength() / f(1)
    p, n = _exterior(doc, lib, _wall(doc, Rm))
    say("  shapes: L strip (polyline, flip {:.0f}' <-> {:.0f}'), curved strip r={:.2f}', ring (closed, {})".format(L1, L2, r, n))
    # lone box: faces the camera, keeps its side when turned 30 degrees
    view = [v for v in doc.Views if v.ActiveViewport.Name == "Perspective"][0]
    doc.Views.ActiveView = view
    vp = view.ActiveViewport
    vp.ChangeToPerspectiveProjection(True, 35.0)          # (target, camera): camera south
    vp.SetCameraLocations(G.Point3d(f(170), f(5), f(4)), G.Point3d(f(170), f(-30), f(6)))
    Bm, sr = wallmasses.make(doc, _box(doc, 160, 180, 0, 2, 0, 9), WOOD, {}, lib)
    p, n = _exterior(doc, lib, _wall(doc, Bm))
    assert n == (0.0, -1.0) and _near(p[1], 0), (p, n)
    vp.SetCameraLocations(G.Point3d(f(170), f(-5), f(4)), G.Point3d(f(170), f(30), f(6)))
    doc.Objects.Transform(Bm.Id, G.Transform.Rotation(math.radians(30), G.Vector3d.ZAxis, G.Point3d(f(170), f(1), 0)), True)
    _idle()
    p, n = _exterior(doc, lib, _wall(doc, Bm))
    assert _near(n[0], 0.5, 1e-3) and _near(n[1], -0.866, 1e-3), n
    return Lm, Cm, Rm, Bm


def perimeter(doc, lib):
    """Blocks -> one closed wall around the whole outline (exterior outside): a cube with a
    partition (T at the interior faces), an L-shaped block, a cylinder; Mode strip / perimeter;
    a live face drag; an opening mass through a perimeter wall; Flip is ignored."""
    f = lambda v: _ft(doc, v)
    tol = doc.ModelAbsoluteTolerance
    cube = _box(doc, 200, 212, 0, 12, 0, 9)
    part = _box(doc, 205.5, 206.5, 0, 12, 0, 9)
    t0 = time.time()
    (C, Pm), sr = wallmasses.make_many(doc, [cube, part], WOOD, {}, lib)
    TIMINGS["perimeter cube + partition, make"] = time.time() - t0
    assert not sr.warnings, sr.warnings
    wc = _wall(doc, C)
    c = wc.Geometry
    ok, pl = c.TryGetPolyline()
    assert c.IsClosed and ok and pl.Count == 5 and _near(c.GetLength() / f(1), 48, 1e-3), c.GetLength() / f(1)
    for (px, py), n in [_exterior(doc, lib, wc)]:
        assert _dot2((px - 206, py - 6), n) > 0, (px, py, n)      # outward
    T = _thick(doc, lib, wc)
    jp = _joins(doc, lib, _wall(doc, Pm))
    assert jp.count("T join") == 2, jp
    ys = sorted(e[1] for e in _ends(doc, _wall(doc, Pm)))
    assert _near(ys[0], T, 1e-3) and _near(ys[1], 12 - T, 1e-3), (ys, T)
    # an L-shaped block and a cylinder
    Lb, sr = wallmasses.make(doc, _prism(doc, [(230, 0), (250, 0), (250, 10), (240, 10), (240, 20), (230, 20)], 0, 9), WOOD, {}, lib)
    assert not sr.warnings, sr.warnings
    lc = _wall(doc, Lb).Geometry
    ok, pl = lc.TryGetPolyline()
    assert lc.IsClosed and ok and pl.Count == 7 and _near(lc.GetLength() / f(1), 80, 1e-3), lc.GetLength() / f(1)
    cyl = G.Cylinder(G.Circle(G.Plane(G.Point3d(f(275), f(10), 0), G.Vector3d.ZAxis), f(8)), f(9)).ToBrep(True, True)
    Cy, sr = wallmasses.make(doc, doc.Objects.FindId(doc.Objects.AddBrep(cyl)), WOOD, {}, lib)
    assert not sr.warnings, sr.warnings
    cc = _wall(doc, Cy).Geometry
    assert cc.IsClosed and _near(cc.GetLength() / f(1), 2 * math.pi * 8, 1e-2), cc.GetLength() / f(1)
    assert _joins(doc, lib, _wall(doc, Cy)) == ""
    # Mode: a cube read as a strip (one wall), then as a perimeter again
    Sq, sr = wallmasses.make(doc, _box(doc, 300, 310, 0, 10, 0, 9), WOOD, {"mode": "strip"}, lib)
    assert not _wall(doc, Sq).Geometry.IsClosed
    wallmasses.set_mode(doc, [doc.Objects.FindId(Sq.Id)], "perimeter", lib)
    assert _wall(doc, Sq).Geometry.IsClosed and _near(_wall(doc, Sq).Geometry.GetLength() / f(1), 40, 1e-3)
    # live: drag the cube's east face 2' out -> 52' around, the partition still T's both sides
    b = masses.to_brep(doc.Objects.FindId(C.Id).Geometry)
    face = max(range(b.Faces.Count), key=lambda i: b.Faces[i].GetBoundingBox(True).Min.X)
    assert b.TransformComponent([G.ComponentIndex(G.ComponentIndexType.BrepFace, face)],
                                G.Transform.Translation(f(2), 0, 0), tol, 0, True)
    t = time.time()
    doc.Objects.Replace(C.Id, b)
    _idle()
    TIMINGS["live: face drag of a perimeter cube"] = time.time() - t
    assert _near(_wall(doc, C).Geometry.GetLength() / f(1), 52, 1e-3)
    assert _joins(doc, lib, _wall(doc, Pm)).count("T join") == 2
    # an opening mass through the south side
    om, osr = masses.make(doc, _box(doc, 201.5, 204.5, -1, 1.5, 3, 7), WINDOW, {}, lib)
    assert len(osr.openings) == 1 and meta.get(_ops_one(doc, om), core.HOST) == str(wc.Id), osr.warnings
    # Flip leaves a perimeter alone
    sr = wallmasses.flip(doc, [doc.Objects.FindId(C.Id)], lib)
    assert any("perimeter" in w for w in sr.warnings) and not meta.params(doc.Objects.FindId(C.Id))["flip"]
    say("  perimeter: cube 48' closed (+ partition T, face drag -> 52'), L block 80', cylinder, Mode strip <-> perimeter, "
        "opening mass, flip ignored")
    return C


def _dot2(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _ops_one(doc, m):
    ops = masses.openings_of(doc, m.Id)
    assert len(ops) == 1, ops
    return ops[0]


def convert(doc, lib):
    """An existing wall (reference center, with a window) gets a mass; it stays where it is."""
    f = lambda v: _ft(doc, v)
    crv = G.PolylineCurve([G.Point3d(f(0), f(40), 0), G.Point3d(f(24), f(40), 0)])
    r = engine.create(doc, doc.Objects.FindId(doc.Objects.AddCurve(crv)), BRICK,
                      {"height": 108, "reference": "center", "base_offset": 12}, lib)
    w = doc.Objects.FindId(r.driver_id)
    op, r = engine.add_opening(doc, w, WINDOW, {}, G.Point3d(f(10), f(40), 0), lib)
    before = _exterior(doc, lib, w)
    st0 = meta.params(doc.Objects.FindId(op.Id))["station"]
    ms, sr, skipped = wallmasses.convert(doc, [w], lib)
    assert not skipped and len(ms) == 1, skipped
    m = ms[0]
    w = doc.Objects.FindId(w.Id)
    assert wallmasses.mass_of(doc, w).Id == m.Id
    assert _exterior(doc, lib, w) == before, (_exterior(doc, lib, w), before)
    assert meta.params(w)["reference"] == "center" and meta.params(w)["base_offset"] == 12
    bb = _bb(doc, m.Id)
    assert _near(bb.Min.Z, f(1), 1e-6) and _near(bb.Max.Z - bb.Min.Z, f(9), 1e-6), bb
    ctx = _ctx(doc, lib, w)
    rec = [o for o in ctx.openings if o.id == op.Id][0]
    assert _near(rec.plane.Origin.X / f(1), 10, 0.01), rec.plane.Origin
    say("  convert: brick wall (center reference, base 12\") keeps its exterior face, window at x=10' ({} -> {})".format(
        st0, meta.params(doc.Objects.FindId(op.Id))["station"]))
    return w, m, op


def deletes(doc, lib, S, N, W, E, P, op, om, conv):
    """Deleting a mass deletes its wall + openings; deleting a wall deletes its mass."""
    wS, wW, wE = _wall(doc, S), _wall(doc, W), _wall(doc, E)
    doc.Objects.Delete(S.Id, True)
    _idle()
    assert _deleted(doc, wS.Id) and _deleted(doc, op.Id) and not meta.parts_of(doc, wS.Id)
    assert _joins(doc, lib, wW).count("L join") == 1, _joins(doc, lib, wW)
    assert _exterior(doc, lib, wW)[1] == (-1.0, 0.0)
    # the partition lost its T at S
    assert _joins(doc, lib, _wall(doc, P)).count("T join") == 1
    # delete E's wall driver: its mass goes
    doc.Objects.Delete(wE.Id, True)
    _idle()
    assert _deleted(doc, E.Id), "the mass of a deleted wall is deleted"
    # the converted wall: delete its mass -> the wall and its window go
    w, m, cop = conv
    doc.Objects.Delete(m.Id, True)
    _idle()
    assert _deleted(doc, w.Id) and _deleted(doc, cop.Id)
    say("  deletes: mass -> wall + window, wall -> mass, neighbors rebuilt")


def drawing_scene(doc):
    sc = scene_mod.Scene(doc)
    items = sc.collect()
    ids = set(str(m.Id) for m in masses.all_masses(doc))
    assert ids and not [it for it in items if str(it.obj_id) in ids]
    say("  drawing scene: {} items, no masses".format(len(items)))


def ui_bits(doc):
    import importlib
    mod = importlib.import_module("mindcanvas.cmd.wallmass")
    assert hasattr(mod, "run")
    assert os.path.exists(os.path.join(ROOT, "commands", "MCWallMass.py"))
    from mindcanvas.eto import panel, editor
    assert ("Wall mass", "MCWallMass") in panel.BUILD
    m = wallmasses.all_wall_masses(doc)[0]
    doc.Objects.UnselectAll()
    doc.Objects.Select(m.Id)
    sel = editor.selected_drivers(doc)
    doc.Objects.UnselectAll()
    assert sel and sel[0].Id == wallmasses.wall_of(doc, m).Id, "a selected wall mass selects its wall"
    assert wallmasses.show_arrows(True) and scriptcontext.sticky[wallmasses.ARROWS_KEY]["arrows"]


def brick_timing(doc, lib):
    """Live move of a mass driving a 24' brick veneer wall at detail."""
    f = lambda v: _ft(doc, v)
    m, sr = wallmasses.make(doc, _box(doc, 0, 24, 80, 81, 0, 9), BRICK, {}, lib)
    TIMINGS["brick wall at detail, make"] = sr.seconds
    t = time.time()
    doc.Objects.Transform(m.Id, G.Transform.Translation(f(2), 0, 0), True)
    _idle()
    TIMINGS["brick wall at detail, live move"] = time.time() - t
    xs = sorted(e[0] for e in _ends(doc, _wall(doc, m)))
    assert xs == [2.0, 26.0], xs
    return m


# -- run ------------------------------------------------------------------------------------------
def run(doc, clear=True, drawing_on=True, captures=True, log=None):
    assert not doc.Path, "test_phase10 clears the document: run it in an empty, unsaved model"
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
        say("-- L corner")
        l_corner(doc, lib)
        say("-- ring")
        S, N, W, E, P = ring(doc, lib)
        say("-- live")
        op, om = live_ring(doc, lib, S, N, W, E, P)
        say("-- two-way")
        two_way(doc, lib, S, N)
        say("-- shapes")
        shapes(doc, lib)
        say("-- perimeter")
        perimeter(doc, lib)
        say("-- convert")
        conv = convert(doc, lib)
        say("-- brick timing")
        brick_timing(doc, lib)
        if captures:
            try:
                cap = runpy.run_path(os.path.join(HERE, "capture.py"))["capture"]
                f = lambda v_: _ft(doc, v_)
                vp = [x for x in doc.Views if x.ActiveViewport.Name == "Perspective"][0].ActiveViewport
                vp.ChangeToPerspectiveProjection(True, 35.0)
                vp.SetCameraLocations(G.Point3d(f(15), f(11), f(4)), G.Point3d(f(-18), f(-22), f(28)))
                say(cap(doc, "phase10_wall_masses", mode="Shaded", zoom_extents=False, width=1200, height=700))
                masses.set_visible(doc, False)
                try:
                    say(cap(doc, "phase10_wall_masses_walls", mode="Shaded", zoom_extents=False, width=1200, height=700))
                    vp.SetCameraLocations(G.Point3d(f(242), f(10), f(2)), G.Point3d(f(242), f(-62), f(48)))
                    say(cap(doc, "phase10_perimeter_walls", mode="Shaded", zoom_extents=False, width=1200, height=700))
                finally:
                    masses.set_visible(doc, True)
            except Exception as ex:
                say("captures skipped:", ex)
        say("-- deletes")
        deletes(doc, lib, S, N, W, E, P, op, om, conv)
        say("-- drawing scene, ui")
        drawing_scene(doc)
        ui_bits(doc)
    finally:
        live.disable()
        if was_live:
            live.enable()
    for k, v in sorted(TIMINGS.items()):
        say("  timing {}: {:.2f}s".format(k, v))
    doc.Views.Redraw()
    say("total {:.1f}s".format(time.time() - t0))
    say("PHASE 10 OK")
