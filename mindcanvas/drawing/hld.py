"""HiddenLineDrawing (the Make2D engine) for model edges and silhouettes.

GOTCHAS (spike-verified): the HLD keeps the side of a clipping plane OPPOSITE to
the display convention, so planes are flipped here; Flatten=False keeps a depth
coordinate, so WorldToHiddenLine's inverse maps any output point back to world;
SectionCut segments (also produced by the view frustum) are dropped - cuts are
drawn from closed loops in cut.py; ParentCurve / SourceObject can be None.
"""

import math
import time

import Rhino

G = Rhino.Geometry
VIS = G.HiddenLineDrawingSegment.Visibility
ST = G.SilhouetteType
OUTLINE = (ST.Crease, ST.Projecting, ST.Tangent, ST.TangentProjects)


def _params(vp, tol, planes, hidden=False):
    p = G.HiddenLineDrawingParameters()
    p.AbsoluteTolerance = tol
    p.IncludeTangentEdges = False
    p.IncludeTangentSeams = False
    p.IncludeHiddenCurves = hidden
    p.Flatten = False
    p.SetViewport(vp)
    for pl in planes:
        f = G.Plane(pl)
        f.Flip()
        p.AddClippingPlane(f)
    return p


def probe(vp, tol):
    """WorldToHiddenLine is only exposed on a computed HLD: compute a single point."""
    p = _params(vp, tol, ())
    p.AddGeometry(G.Point(vp.CameraTarget), G.Transform.Identity, {})
    return G.HiddenLineDrawing.Compute(p, True).WorldToHiddenLine


def compute(vp, items, planes, tol, hidden=False):
    p = _params(vp, tol, planes, hidden)
    added = 0
    for it in items:
        if p.AddGeometry(it.geom, it.xf, it.tag()):
            added += 1
    t = time.time()
    hld = G.HiddenLineDrawing.Compute(p, True)
    return hld, added, time.time() - t


def _poly(crv, tol):
    ok, pl = crv.TryGetPolyline()
    if ok:
        return list(pl)
    pc = crv.ToPolyline(tol, 0.05, 0.0, 0.0)
    return list(pc.ToPolyline()) if pc else [crv.PointAtStart, crv.PointAtEnd]


def segments(hld, depth_fn, s_page, split_mm=12.0, hidden=False, tol=0.01):
    """Yield (pts_hl [(x, y)], cls, depth, item_index). Long lines are split so
    depth falloff varies along them."""
    ok, H2W = hld.WorldToHiddenLine.TryGetInverse()
    for s in hld.Segments:
        vis = s.SegmentVisibility
        if vis == VIS.Visible:
            is_hidden = False
        elif hidden and vis == VIS.Hidden:
            is_hidden = True
        else:
            continue
        crv = s.CurveGeometry
        pc = s.ParentCurve
        if crv is None or pc is None:
            continue
        sil = pc.SilhouetteType
        if sil == ST.SectionCut:
            continue
        src = pc.SourceObject
        tag = src.Tag if src is not None else None
        try:
            idx = int(tag["i"])
        except Exception:
            idx = -1
        if is_hidden:
            cls = "hidden"
        elif s.IsSceneSilhouette or sil in OUTLINE:
            cls = "silhouette"
        else:
            cls = "edge"
        pts = _poly(crv, tol)
        if len(pts) < 2:
            continue
        # split by paper length so depth can change along receding lines
        runs = [pts]
        if len(pts) == 2 and split_mm > 0:
            a, b = pts
            n = int(math.hypot(b.X - a.X, b.Y - a.Y) * s_page / split_mm)
            if n > 1:
                n = min(n, 24)
                runs = [[a + (b - a) * (i / float(n)), a + (b - a) * ((i + 1) / float(n))] for i in range(n)]
        for run in runs:
            m = run[len(run) // 2] if len(run) > 2 else (run[0] + run[-1]) * 0.5
            w = G.Point3d(m)
            w.Transform(H2W)
            yield [(p.X, p.Y) for p in run], cls, depth_fn(w), idx
