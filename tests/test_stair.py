"""Stairs (kind 'stair', MCStair / MCEditStair).

Run inside Rhino (e.g. via the MCP run_python tool), in an EMPTY, unsaved document (it is cleared):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_stair.py")["run"](__rhino_doc__)

Covers straight, L (curve on the outer / inner edge), U (half landing) and curved stairs in the
three styles (slab, solid, open), left / right side, flip, floor height / riser edits, the section
frame. captures=True writes docs/captures/stairs.png. The pure layout is also checked offline:
python tests/offline/test_stair_plan.py
"""

import os
import runpy
import time

import Rhino

from mindcanvas import docutil, engine, library, meta, units
from mindcanvas.kinds import stair as stairkind

G = Rhino.Geometry
HERE = os.path.dirname(os.path.abspath(__file__))
SLAB, SOLID, OPEN = "Stair - Concrete", "Stair - Solid Mass", "Stair - Open Wood Treads"


def say(*a):
    print(" ".join(str(x) for x in a))


def _ft(doc, v):
    return units.to_model(doc, v * 12.0)


def _poly(doc, pts, ox=0.0, oy=0.0):
    P = [G.Point3d(_ft(doc, x + ox), _ft(doc, y + oy), 0) for x, y in pts]
    return doc.Objects.FindId(doc.Objects.AddPolyline(P))


def _bbox(doc, ids):
    bb = G.BoundingBox.Empty
    for o in meta.parts_of(doc, ids):
        bb.Union(o.Geometry.GetBoundingBox(True))
    return bb


def _check(doc, r, name, risers=None, pieces=None):
    parts = meta.parts_of(doc, r.driver_id)
    assert parts, name + ": no parts"
    for o in parts:
        g = o.Geometry
        assert isinstance(g, G.Brep) and g.IsSolid, "{}: a part is not a closed Brep ({})".format(name, type(g).__name__)
    if pieces is not None:
        assert len(parts) == pieces, "{}: {} parts, expected {}".format(name, len(parts), pieces)
    d = doc.Objects.FindId(r.driver_id)
    ctx = stairkind.make_context(doc, library.get(), d, meta.get(d, meta.ASSEMBLY), meta.params(d))
    if risers is not None:
        assert ctx.layout.risers == risers, "{}: {} risers".format(name, ctx.layout.risers)
    bb = _bbox(doc, r.driver_id)
    H = units.to_inches(doc, ctx.height)
    top = units.to_inches(doc, bb.Max.Z - ctx.base_z)
    assert abs(top - (H - ctx.layout.R)) < 1e-3, "{}: top tread at {:.3f}, expected {:.3f}".format(name, top, H - ctx.layout.R)
    say("  {}: {} part(s), {} | warnings: {}".format(name, len(parts), stairkind.describe(ctx), r.warnings or "-"))
    return ctx


def run(doc, clear=True, captures=True):
    assert not doc.Path, "test_stair clears the document: run it in an empty, unsaved model"
    if clear:
        for o in list(doc.Objects):
            doc.Objects.Delete(o, True)
        docutil.purge_unused_blocks(doc)
    engine.setup_document(doc)
    lib = library.get(force_reload=True)
    t0 = time.time()

    # straight, 10' floor to floor, 7" max riser -> 18 risers; 15'-7" line -> 11" treads
    c = _poly(doc, [(0, 0), (187 / 12.0, 0)])
    r = engine.create(doc, c, SLAB, {"height": 120, "width": 42, "side": "left"})
    ctx = _check(doc, r, "straight slab", risers=18, pieces=1)
    assert abs(ctx.layout.flights[0].depth - 11.0) < 1e-6
    bb = _bbox(doc, r.driver_id)
    assert bb.Max.Y <= 1e-6 and abs(units.to_inches(doc, bb.Min.Y) + 42) < 1e-3, "left side: the stair is right of the line"
    assert abs(bb.Min.Z) < 1e-6, "the slab soffit reaches the lower floor"

    # edits: right side, flip, floor height 9', risers override
    d = doc.Objects.FindId(r.driver_id)
    r = engine.update_params(doc, d, {"side": "right"})
    bb = _bbox(doc, r.driver_id)
    assert bb.Min.Y >= -1e-6 and abs(units.to_inches(doc, bb.Max.Y) - 42) < 1e-3, "right side: the stair is left of the line"
    r = engine.update_params(doc, d, {"flip": True})
    ctx = _check(doc, r, "flipped", risers=18)
    first = ctx.layout.cuts[0].c
    assert abs(first[0] - 187) < 1e-6, "flip: the stair starts at the curve's end"
    r = engine.update_params(doc, d, {"flip": False, "side": "left", "height": 108})
    _check(doc, r, "9' floor", risers=16)
    r = engine.update_params(doc, d, {"risers": 17})
    _check(doc, r, "17 risers", risers=17)
    r = engine.update_params(doc, d, {"risers": None, "style": "open"})
    _check(doc, r, "straight open", pieces=15)
    r = engine.update_params(doc, d, {"style": None})

    # L stairs: curve on the outer edge (turning toward the stair) / the inner edge
    for asm, name, off in ((SLAB, "L outer slab", 0), (SOLID, "L outer solid", 0)):
        c = _poly(doc, [(0, 0), (10, 0), (10, -12.5)], oy=-6 if asm == SLAB else -26)
        _check(doc, engine.create(doc, c, asm, {"height": 120, "width": 42}), name, risers=18, pieces=1)
    c = _poly(doc, [(0, 0), (10, 0), (10, 12.5)], oy=-50)
    _check(doc, engine.create(doc, c, SLAB, {"height": 120, "width": 42}), "L inner slab", risers=18, pieces=1)
    c = _poly(doc, [(0, 0), (10, 0), (10, 12.5)], ox=16, oy=-50)
    _check(doc, engine.create(doc, c, OPEN, {"height": 120, "width": 42}), "L inner open")

    # U stair with a half landing (middle leg = 2 x width)
    for asm, ox in ((SLAB, 24), (SOLID, 36)):
        c = _poly(doc, [(0, 0), (9, 0), (9, -7), (0, -7)], ox=ox)
        _check(doc, engine.create(doc, c, asm, {"height": 120, "width": 42}), "U " + asm.split(" - ")[1], risers=18)

    # curved stair along a 4' radius arc, curve on the inner side
    arc = G.Arc(G.Plane(G.Point3d(_ft(doc, 30), _ft(doc, -30), 0), G.Vector3d.ZAxis), _ft(doc, 4), 1.25 * 3.14159265)
    cid = doc.Objects.AddCurve(G.ArcCurve(arc))
    r = engine.create(doc, doc.Objects.FindId(cid), SLAB, {"height": 120, "width": 40})
    ctx = _check(doc, r, "curved slab", risers=18, pieces=1)
    d = doc.Objects.FindId(cid)
    _check(doc, engine.update_params(doc, d, {"style": "open"}), "curved open", pieces=17)
    engine.update_params(doc, d, {"style": None})

    # the curved slab is trimmed to the true curves: few faces, smooth (non-planar) sides
    b = meta.parts_of(doc, cid)[0].Geometry
    curvy = [f for f in b.Faces if not f.IsPlanar(doc.ModelAbsoluteTolerance) and abs(f.NormalAt(
        f.Domain(0).Mid, f.Domain(1).Mid).Z) < 0.05]
    say("  curved slab: {} faces, {} vertical curved".format(b.Faces.Count, len(curvy)))
    assert len(curvy) == 2, "the curved stair's sides are not single smooth faces ({})".format(len(curvy))
    assert b.Faces.Count < 6 * 17, "the curved stair is faceted ({} faces)".format(b.Faces.Count)

    # spiral with a landing halfway
    arc2 = G.Arc(G.Plane(G.Point3d(_ft(doc, 50), _ft(doc, -30), 0), G.Vector3d.ZAxis), _ft(doc, 5), 1.5 * 3.14159265)
    a2 = doc.Objects.FindId(doc.Objects.AddCurve(G.ArcCurve(arc2)))
    r = engine.create(doc, a2, SLAB, {"height": 120, "width": 42, "landing_count": 1})
    ctx = _check(doc, r, "spiral + landing", risers=18, pieces=1)
    assert ctx.layout.landing_runs == 1 and len(ctx.layout.flights) == 2

    # elevator wrap: a circle around an 8' shaft, 2 floors, 1.2 laps per floor, a landing per floor
    circ = G.Circle(G.Plane(G.Point3d(_ft(doc, 80), _ft(doc, -30), 0), G.Vector3d.ZAxis), _ft(doc, 4))
    cw = doc.Objects.FindId(doc.Objects.AddCurve(G.ArcCurve(circ)))
    for asm in (SLAB, OPEN):
        r = engine.create(doc, cw, asm, {"height": 144, "width": 44, "floors": 2, "laps": 2.4, "side": "left",
                                         "landing_count": 1, "start": 0})
        ctx = _check(doc, r, "elevator wrap " + asm.split(" - ")[1], risers=42)
        lay = ctx.layout
        fl = [e for e in lay.landings if e.floor]
        assert len(fl) == 1 and abs(fl[0].level0 * lay.R - 144) < 1e-6, "no landing at the second floor"
        bb = _bbox(doc, r.driver_id)
        rad = units.to_inches(doc, max(bb.Max.X - _ft(doc, 80), _ft(doc, -30) - bb.Min.Y))
        assert abs(rad - 92) < 0.05, "wrap: outer radius {:.3f}, expected 48 + 44".format(rad)
        engine.delete_parts(doc, r.driver_id)
    r = engine.create(doc, cw, SLAB, {"height": 144, "width": 44, "floors": 2, "laps": 2.4, "side": "left",
                                      "landing_count": 1})
    _check(doc, r, "elevator wrap slab", risers=42, pieces=1)
    # start point + direction on the closed curve, a clicked landing
    d = doc.Objects.FindId(cw.Id)
    L = units.to_inches(doc, cw.Geometry.GetLength())
    r = engine.update_params(doc, d, {"start": L / 4, "flip": True, "side": "right", "landings": [L / 2]})
    bb = _bbox(doc, r.driver_id)
    assert abs(units.to_inches(doc, bb.Max.X - _ft(doc, 80)) - 92) < 0.05, "reversed wrap must stay outside the shaft"
    ctx = _check(doc, r, "wrap, start 1/4 round, reversed, + clicked landing", risers=42)
    p0 = ctx.layout.cuts[0].c
    exp = cw.Geometry.PointAtLength(_ft(doc, L / 4 / 12.0))
    assert abs(p0[0] - units.to_inches(doc, exp.X)) < 0.01 and abs(p0[1] - units.to_inches(doc, exp.Y)) < 0.01, \
        "the wrap does not start at the start point"
    assert ctx.layout.landing_runs >= 4, "clicked landing missing ({} runs)".format(ctx.layout.landing_runs)

    # section frame (MCSectionCut) along the flight
    from mindcanvas.drawing import sectioncut
    frame, ext = sectioncut.wall_frame(doc, doc.Objects.FindId(c.Id), G.Point3d(_ft(doc, ox + 4), _ft(doc, -1), 0))
    assert abs(abs(frame.XAxis.Y) - 1) < 1e-6, "section frame: the cut runs along the flight"
    assert ext["d_ext"] > ext["d_int"]

    # a closed square (8' shaft): the stair wraps it with a landing at each corner it turns
    sq = _poly(doc, [(60, 0), (68, 0), (68, 8), (60, 8), (60, 0)], oy=-60)
    r = engine.create(doc, sq, SLAB, {"height": 120, "width": 42, "side": "left", "laps": 1.0})
    ctx = _check(doc, r, "square wrap", risers=18, pieces=1)
    assert ctx.layout.landing_runs == 3, "square wrap: {} landings".format(ctx.layout.landing_runs)
    say("stairs ok in {:.1f}s".format(time.time() - t0))
    if captures:
        cap = runpy.run_path(os.path.join(HERE, "capture.py"))["capture"]
        say(cap(doc, "stairs", view="Perspective", mode="Shaded"))
        # the elevator wrap, with a glass shaft for scale
        shaft = G.Cylinder(G.Circle(G.Plane(G.Point3d(_ft(doc, 80), _ft(doc, -30), 0), G.Vector3d.ZAxis), _ft(doc, 4)),
                           _ft(doc, 24))
        sid = doc.Objects.AddBrep(shaft.ToBrep(True, True))
        bb = _bbox(doc, cw.Id)
        bb.Union(G.Point3d(bb.Min.X, bb.Min.Y, bb.Max.Z + _ft(doc, 2)))
        v = doc.Views.Find("Perspective", False)
        v.ActiveViewport.SetCameraLocations(bb.Center, bb.Center + G.Vector3d(_ft(doc, 30), _ft(doc, -40), _ft(doc, 14)))
        say(cap(doc, "stair_elevator_wrap", view="Perspective", mode="Shaded", box=bb))
        doc.Objects.Delete(sid, True)
    return True
