"""Profile capture: curves drawn in Rhino -> library entries (MCProfileCapture).

Curves are read in a plane (the active construction plane by default) relative to a base point
and written in INCHES: plane x -> X, plane y -> Y. Arcs and splines are turned into polylines
(1/64" tolerance, 5 degree angle steps).

    profile_definition(...)    {"type": "custom", "points" | "loops": ...}  -> library/profiles

A profile's first loop is its outline (the largest), the others are holes.
"""

import math

import Rhino

from . import units

G = Rhino.Geometry
ROUND = 4


def _poly(crv, doc):
    s = units.inch_scale(doc)
    ok, pl = crv.TryGetPolyline()
    if ok:
        pts = list(pl)
    else:
        pc = crv.ToPolyline(s / 64.0, math.radians(5), 0.0, 0.0)
        pts = list(pc.ToPolyline()) if pc is not None else [crv.PointAtStart, crv.PointAtEnd]
    return pts


def _uv(plane, base, p, s):
    ok, u, v = plane.ClosestParameter(p)
    ok, u0, v0 = plane.ClosestParameter(base)
    return (round((u - u0) / s, ROUND), round((v - v0) / s, ROUND))


def _area(pts):
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                     for i in range(len(pts)))


def read(doc, curves, plane=None, base=None):
    """(loops, lines) in inches. Loops are counter-clockwise, largest first, without the repeated
    end point; curves out of the plane are projected onto it."""
    plane = G.Plane(plane) if plane is not None else G.Plane.WorldXY
    base = base if base is not None else plane.Origin
    s = units.inch_scale(doc)
    loops, lines = [], []
    for c in curves:
        pts = [_uv(plane, base, p, s) for p in _poly(c, doc)]
        if c.IsClosed and len(pts) >= 4:
            pts = pts[:-1] if pts[0] == pts[-1] else pts
            if _area(pts) < 0:
                pts.reverse()
            loops.append([list(p) for p in pts])
        elif len(pts) >= 2:
            lines.append([list(p) for p in pts])
    loops.sort(key=lambda lp: -abs(_area(lp)))
    return loops, lines


def profile_definition(doc, curves, plane=None, base=None, family=None, material=None):
    loops, lines = read(doc, curves, plane, base)
    if not loops:
        raise ValueError("Select at least one closed planar curve for a profile.")
    d = {"type": "custom"}
    if len(loops) == 1:
        d["points"] = loops[0]
    else:
        d["loops"] = [loops[0]] + [list(reversed(lp)) for lp in loops[1:]]
    if family:
        d["family"] = family
    if material:
        d["material"] = material
    d["captured"] = True
    return d

