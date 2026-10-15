"""2D member profiles (cross-sections) built from library/profiles definitions.

All profiles are closed polylines in World XY, in MODEL units, with:
    X = profile "width"  (for a stud: along the wall face)
    Y = profile "depth"  (for a stud: through the wall thickness)
centered on the origin unless noted. Dimensions in the library are inches.

Types:
    rect    width, depth
    c_stud  depth (web), flange, lip, t      - web on -X side, opens toward +X
    track   depth (web), flange (leg), t     - web on -X side, legs toward +X
    angle   a (leg along X), b (leg along Y), t - corner at origin
    tube    width, depth, t                  - hollow rectangle (two loops)
    custom  points [[x, y], ...]             - any closed outline (inches)

To add a new shape type, add a function below and register it in BUILDERS.
"""

import Rhino

from . import units

G = Rhino.Geometry


def _pl(points, s):
    pts = [G.Point3d(x * s, y * s, 0) for x, y in points]
    if pts[0].DistanceTo(pts[-1]) > 1e-9:
        pts.append(pts[0])
    return G.PolylineCurve(pts)


def _L(p, key, default=None):
    v = p.get(key, default)
    return units.parse_length(v) if v is not None else None


def rect(p, s):
    w, d = _L(p, "width"), _L(p, "depth")
    return [_pl([(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)], s)]


def c_stud(p, s):
    d, f, t = _L(p, "depth"), _L(p, "flange"), _L(p, "t")
    lip = _L(p, "lip", 0) or 0.0
    x0, x1, y0, y1 = -f / 2, f / 2, -d / 2, d / 2
    if lip < t * 1.5:
        pts = [(x1, y0), (x0, y0), (x0, y1), (x1, y1),
               (x1, y1 - t), (x0 + t, y1 - t), (x0 + t, y0 + t), (x1, y0 + t)]
    else:
        pts = [(x1, y0 + lip), (x1, y0), (x0, y0), (x0, y1), (x1, y1), (x1, y1 - lip),
               (x1 - t, y1 - lip), (x1 - t, y1 - t), (x0 + t, y1 - t),
               (x0 + t, y0 + t), (x1 - t, y0 + t), (x1 - t, y0 + lip)]
    return [_pl(pts, s)]


def track(p, s):
    d, f, t = _L(p, "depth"), _L(p, "flange"), _L(p, "t")
    y0, y1 = -d / 2, d / 2
    pts = [(f, y0), (0, y0), (0, y1), (f, y1), (f, y1 - t), (t, y1 - t), (t, y0 + t), (f, y0 + t)]
    return [_pl(pts, s)]


def angle(p, s):
    a, b, t = _L(p, "a"), _L(p, "b"), _L(p, "t")
    return [_pl([(0, 0), (a, 0), (a, t), (t, t), (t, b), (0, b)], s)]


def tube(p, s):
    w, d, t = _L(p, "width"), _L(p, "depth"), _L(p, "t")
    outer = rect({"width": w, "depth": d}, s)[0]
    inner = rect({"width": w - 2 * t, "depth": d - 2 * t}, s)[0]
    return [outer, inner]


def custom(p, s):
    pts = [(units.parse_length(x), units.parse_length(y)) for x, y in p["points"]]
    return [_pl(pts, s)]


BUILDERS = {
    "rect": rect,
    "c_stud": c_stud,
    "track": track,
    "angle": angle,
    "tube": tube,
    "custom": custom,
}


def build(definition, scale):
    """Profile loops (first = outer) for a library profile definition."""
    kind = definition.get("type")
    fn = BUILDERS.get(kind)
    if fn is None:
        raise ValueError("Unknown profile type '{}'".format(kind))
    return fn(definition, scale)


def size(definition):
    """(width, depth) of a profile's bounding box, in inches."""
    loops = build(definition, 1.0)
    bb = loops[0].GetBoundingBox(True)
    return bb.Max.X - bb.Min.X, bb.Max.Y - bb.Min.Y
