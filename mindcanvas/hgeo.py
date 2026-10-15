"""Geometry for horizontal assemblies (floors, roofs).

Local frames: x = a horizontal direction (joist direction, or the slope direction of a roof face),
y = Z x x (left of x), z = world Z (frames sit at z = 0, so local z == world z).
Members are 2D section polygons in the local (x, z) plane extruded along y, which is fast, exact
and makes identical members share a block definition. Plan polygons are lists of (x, y) tuples
(no repeated closing point).
"""

import hashlib
import math

import Rhino

G = Rhino.Geometry


class Frame(object):
    def __init__(self, xdir, origin=None):
        x = G.Vector3d(xdir.X, xdir.Y, 0.0)
        x.Unitize()
        self.x = x
        self.y = G.Vector3d.CrossProduct(G.Vector3d.ZAxis, x)
        o = origin or G.Point3d(0, 0, 0)
        self.origin = G.Point3d(o.X, o.Y, 0.0)
        self.plane = G.Plane(self.origin, self.x, self.y)
        self.xform = G.Transform.PlaneToPlane(G.Plane.WorldXY, self.plane)
        self.inverse = G.Transform.PlaneToPlane(self.plane, G.Plane.WorldXY)

    def local(self, p):
        q = G.Point3d(p)
        q.Transform(self.inverse)
        return q

    def world(self, x, y, z=0.0):
        return self.origin + self.x * x + self.y * y + G.Vector3d(0, 0, z)

    def placed(self, y=0.0, x=0.0):
        """Transform placing local geometry shifted by (x, y)."""
        return self.xform * G.Transform.Translation(x, y, 0.0)

    def to_world(self, geom):
        g = geom.Duplicate()
        g.Transform(self.xform)
        return g

    def poly2d(self, pts3d):
        out = []
        for p in pts3d:
            q = self.local(p)
            out.append((q.X, q.Y))
        return out


# -- plan polygons -------------------------------------------------------------------------------
def curve_points(curve, tol, angle_deg=7.5):
    """Vertices of a closed plan curve (polylines exact, curves faceted), no closing duplicate."""
    ok, pl = curve.TryGetPolyline()
    if not ok:
        pc = curve.ToPolyline(tol, math.radians(angle_deg), 0.0, 0.0)
        ok, pl = pc.TryGetPolyline() if pc is not None else (False, None)
        if not ok:
            raise ValueError("Could not read the boundary as a polyline.")
    pts = [G.Point3d(p) for p in pl]
    if len(pts) > 1 and pts[0].DistanceTo(pts[-1]) < tol:
        pts = pts[:-1]
    return clean([(p.X, p.Y) for p in pts], tol, pts[0].Z if pts else 0.0)[0]


def clean(poly, tol, z=0.0):
    """Drop duplicate and collinear vertices."""
    pts = []
    for p in poly:
        if not pts or math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > tol:
            pts.append(p)
    if len(pts) > 2 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= tol:
        pts.pop()
    changed = True
    while changed and len(pts) > 3:
        changed = False
        for i in range(len(pts)):
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
            cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
            la = math.hypot(b[0] - a[0], b[1] - a[1])
            lc = math.hypot(c[0] - b[0], c[1] - b[1])
            if la * lc > 0 and abs(cr) / (la * lc) < 1e-6:
                pts.pop(i)
                changed = True
                break
    return pts, z


def area(poly):
    a = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i - 1]
        x1, y1 = poly[i]
        a += x0 * y1 - x1 * y0
    return 0.5 * a


def ccw(poly):
    return poly if area(poly) > 0 else list(reversed(poly))


def bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def is_rect(poly, tol):
    """Axis-aligned rectangle?"""
    if len(poly) != 4:
        return False
    for i in range(4):
        a, b = poly[i - 1], poly[i]
        if abs(a[0] - b[0]) > tol and abs(a[1] - b[1]) > tol:
            return False
    return True


def chords(poly, c, axis=1):
    """Intervals along the other axis where the line (axis coordinate = c) is inside poly."""
    xs = []
    o = 1 - axis
    n = len(poly)
    for i in range(n):
        p0, p1 = poly[i], poly[(i + 1) % n]
        y0, y1 = p0[axis], p1[axis]
        if (y0 <= c < y1) or (y1 <= c < y0):
            xs.append(p0[o] + (c - y0) * (p1[o] - p0[o]) / (y1 - y0))
    xs.sort()
    return list(zip(xs[0::2], xs[1::2]))


def offset_edges(poly, dists):
    """Offset every edge i (poly[i] -> poly[i+1]) of a CCW polygon outward by dists[i]."""
    n = len(poly)
    lines = []
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        L = math.hypot(x1 - x0, y1 - y0)
        ex, ey = (x1 - x0) / L, (y1 - y0) / L
        nx, ny = ey, -ex                       # outward for CCW
        d = dists[i]
        lines.append(((x0 + nx * d, y0 + ny * d), (ex, ey)))
    out = []
    for i in range(n):
        (pa, da), (pb, db) = lines[i - 1], lines[i]
        cr = da[0] * db[1] - da[1] * db[0]
        if abs(cr) < 1e-9:
            out.append(pb)
            continue
        t = ((pb[0] - pa[0]) * db[1] - (pb[1] - pa[1]) * db[0]) / cr
        out.append((pa[0] + da[0] * t, pa[1] + da[1] * t))
    return out


def clip_halfplane(poly, keep):
    """Sutherland-Hodgman clip by keep(p) -> signed value (>= 0 kept)."""
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i - 1], poly[i]
        fa, fb = keep(a), keep(b)
        if fb >= 0:
            if fa < 0:
                t = fa / (fa - fb)
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            out.append(b)
        elif fa >= 0:
            t = fa / (fa - fb)
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def inside(poly, p):
    x, y = p
    c = False
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i - 1], poly[i]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            c = not c
    return c


def thicken(path, t, side=1):
    """Closed polygon from an open 2D polyline thickened by t to its left (side 1) or right (-1)."""
    n = len(path)
    segs = []
    for i in range(n - 1):
        (x0, y0), (x1, y1) = path[i], path[i + 1]
        L = math.hypot(x1 - x0, y1 - y0)
        ex, ey = (x1 - x0) / L, (y1 - y0) / L
        nx, ny = -ey * side, ex * side
        segs.append(((x0 + nx * t, y0 + ny * t), (ex, ey)))
    off = [segs[0][0]]
    for i in range(1, n - 1):
        (pa, da), (pb, db) = segs[i - 1], segs[i]
        cr = da[0] * db[1] - da[1] * db[0]
        if abs(cr) < 1e-9:
            off.append(pb)
            continue
        s = ((pb[0] - pa[0]) * db[1] - (pb[1] - pa[1]) * db[0]) / cr
        off.append((pa[0] + da[0] * s, pa[1] + da[1] * s))
    (p, d) = segs[-1]
    L = math.hypot(path[-1][0] - path[-2][0], path[-1][1] - path[-2][1])
    off.append((p[0] + d[0] * L, p[1] + d[1] * L))
    return list(path) + list(reversed(off))


def rot(poly, ang, cx=0.0, cy=0.0):
    c, s = math.cos(ang), math.sin(ang)
    return [(cx + x * c - y * s, cy + x * s + y * c) for x, y in poly]


# -- solids --------------------------------------------------------------------------------------
def prism_xz(pts, y0, y1, tol):
    """Closed polygon [(x, z)] in the local XZ plane extruded from y0 to y1 -> capped Brep."""
    P = []
    for x, z in pts:
        q = G.Point3d(x, y0, z)
        if not P or q.DistanceTo(P[-1]) > tol * 0.5:
            P.append(q)
    if len(P) > 2 and P[0].DistanceTo(P[-1]) <= tol * 0.5:
        P.pop()
    if len(P) < 3:
        return None
    P.append(P[0])
    crv = G.PolylineCurve(P)
    srf = G.Surface.CreateExtrusion(crv, G.Vector3d(0, y1 - y0, 0))
    if srf is None:
        return None
    b = srf.ToBrep().CapPlanarHoles(tol)
    if b is None:
        return None
    if b.SolidOrientation == G.BrepSolidOrientation.Inward:
        b.Flip()
    return b


def prism_plan(poly, z0, z1, tol, z=0.0):
    """Plan polygon [(x, y)] extruded from z0 to z1 (world, or local if poly is local)."""
    P = [G.Point3d(x, y, z0) for x, y in poly]
    P.append(P[0])
    srf = G.Surface.CreateExtrusion(G.PolylineCurve(P), G.Vector3d(0, 0, z1 - z0))
    b = srf.ToBrep().CapPlanarHoles(tol) if srf is not None else None
    if b is not None and b.SolidOrientation == G.BrepSolidOrientation.Inward:
        b.Flip()
    return b


def keep_below(brep, plane_pt, normal_up, tol):
    """Part of a closed brep below the plane (opposite normal_up), capped. [] if nothing is left."""
    pl = G.Plane(plane_pt, normal_up)
    bb = brep.GetBoundingBox(True)
    ds = [pl.DistanceTo(c) for c in bb.GetCorners()]
    if max(ds) <= tol:
        return [brep]
    if min(ds) >= -tol:
        return []
    def below(c):
        mp = G.VolumeMassProperties.Compute(c)
        return mp is not None and pl.DistanceTo(mp.Centroid) < 0

    out = []
    for piece in brep.Trim(pl, tol) or []:
        c = piece.CapPlanarHoles(tol) if not piece.IsSolid else piece
        if c is not None and below(c):          # Brep.Trim sometimes keeps the wrong side
            out.append(c)
    if out:
        return out
    R = bb.Diagonal.Length * 2 + 1.0
    cutter = G.PlaneSurface(pl, G.Interval(-R, R), G.Interval(-R, R)).ToBrep()
    for piece in brep.Split(cutter, tol) or []:
        c = piece.CapPlanarHoles(tol) if not piece.IsSolid else piece
        if c is not None and below(c):
            out.append(c)
    return out or [brep]


def prism_between(poly, bot, top, tol):
    """Closed brep over a plan polygon between the lines (z = a + b x) bot and top, built from
    planar faces (no Booleans, no trims). None if it has no height."""
    P = lambda x, y, ln: G.Point3d(x, y, ln(x))
    faces = []
    n = len(poly)
    lo = [P(x, y, bot) for x, y in poly]
    hi = [P(x, y, top) for x, y in poly]
    if max(h.Z - l.Z for h, l in zip(hi, lo)) <= tol:
        return None
    faces.append(lo + [lo[0]])
    faces.append(hi + [hi[0]])
    for i in range(n):
        j = (i + 1) % n
        q = [lo[i], lo[j]]
        if hi[j].Z - lo[j].Z > tol:
            q.append(hi[j])
        if hi[i].Z - lo[i].Z > tol:
            q.append(hi[i])
        if len(q) >= 3:
            faces.append(q + [q[0]])
    breps = []
    for f in faces:
        res = G.Brep.CreatePlanarBreps(G.PolylineCurve(f), tol)
        if res:
            breps.extend(res)
    joined = G.Brep.JoinBreps(breps, tol)
    if not joined:
        return None
    b = max(joined, key=lambda x: x.Faces.Count)
    if not b.IsSolid:
        return None
    if b.SolidOrientation == G.BrepSolidOrientation.Inward:
        b.Flip()
    return b


def slab_between(poly, below, above, tol):
    """Solids over a plan polygon, under every line in `below` and over every line in `above`
    (lines z = a + b x). The polygon is split into x-strips where the envelopes change line, so every
    piece is a prism_between of two planes; neighbouring pieces are unioned when possible."""
    lines = list(below) + list(above)
    x0, y0, x1, y1 = bbox(poly)
    xs = {x0, x1}
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            l1, l2 = lines[i], lines[j]
            if abs(l1.b - l2.b) > 1e-12:
                x = (l2.a - l1.a) / (l1.b - l2.b)
                if x0 < x < x1:
                    xs.add(x)
    xs = sorted(xs)
    out = []
    for a, b in zip(xs, xs[1:]):
        if b - a < tol:
            continue
        sub = clip_halfplane(poly, lambda q, a=a: q[0] - a)
        sub = clip_halfplane(sub, lambda q, b=b: b - q[0]) if sub else sub
        if len(sub) < 3 or abs(area(sub)) < tol * tol:
            continue
        xm = 0.5 * (a + b)
        top = min(below, key=lambda ln: ln(xm))
        bot = max(above, key=lambda ln: ln(xm))
        if top(xm) - bot(xm) <= tol:
            continue
        s = prism_between(sub, bot, top, tol)
        if s is not None:
            out.append(s)
    if len(out) > 1:
        try:
            u = G.Brep.CreateBooleanUnion(out, tol)
            if u:
                return list(u)
        except Exception:
            pass
    return out


def intersect(breps, cutter, tol):
    """Boolean intersection of breps with one closed cutter (falls back to the input)."""
    breps = [b for b in breps if b is not None]
    if not breps:
        return []
    try:
        res = G.Brep.CreateBooleanIntersection(breps, [cutter], tol)
        if res is not None:
            return list(res)
    except Exception:
        pass
    return None


def tag(*vals):
    """Short hash of numbers / strings (block names must encode every dimension)."""
    def norm(v):
        if isinstance(v, float):
            return round(v, 4)
        if isinstance(v, (list, tuple)):
            return [norm(x) for x in v]
        return v
    return hashlib.md5(repr(norm(list(vals))).encode("utf-8")).hexdigest()[:8]


class Line(object):
    """z = a + b * x in a local section plane."""
    __slots__ = ("a", "b")

    def __init__(self, a, b):
        self.a, self.b = a, b

    def __call__(self, x):
        return self.a + self.b * x

    def up(self, d):
        """Parallel line offset d along its normal (upward)."""
        return Line(self.a + d * math.sqrt(1.0 + self.b * self.b), self.b)
