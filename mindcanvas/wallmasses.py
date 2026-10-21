"""Wall masses (Phase 10): closed solids, pushed and pulled with the gumball, that drive wall drivers.

A wall mass carries user text
    mc.kind = mass      mc.type = wall      mc.assembly = <wall assembly>
    mc.wall = <wall driver id>
    mc.params = JSON: flip (exterior on the other face), side ([x, y]: the outward normal of the
                face the automatic rule chose last time), wall (params for the wall it creates)
and sits on MindCanvas::_Masses like an opening mass (masses.py). Its wall driver carries
mc.mass = <mass id> and mc.mass.line (where the last sync put the driver, see _sig).

From mass to wall
    The mass's plan is read from its flat bottom face: a STRIP (two long faces between two caps:
    a box, an L / polyline strip, a curved strip), a RING (an outer loop around one hole) or a
    PERIMETER (any solid block: a cube, an L-shaped / polygonal / round building; one closed wall
    along its whole outline, exterior outside). params["mode"] = auto (default: a strip when it is
    at most STRIP_RATIO as thick as it is long, a ring with one hole, else a perimeter) | strip |
    perimeter (holes ignored). The
    wall's finished EXTERIOR face lies on one long face of the mass; the wall grows inward by the
    assembly's thickness (the mass's own thickness does not matter). Base = mass bottom (the
    driver sits base_offset below it), height = mass top - mass bottom.
Which face is the exterior (auto, then `flip`)
    1. a ring or a perimeter: its outer loop (a perimeter ignores flip);
    2. a face whose outside is enclosed by the wall masses touching it (a closed ring of boxes)
       is interior; the other is exterior;
    3. in a group of touching masses: the face farther from the group's center;
    4. a lone mass: the side chosen last time (params["side"]), else the face toward the camera,
       else the left of the mass's axis.
Corners
    Each exterior face line is extended / trimmed at its ends so that the wall drivers meet the
    way joins (mindcanvas/joins) detect them: two masses meeting near their ends -> both lines to
    the crossing of their exterior face lines (L); a mass ending against the middle of another ->
    to the near face of that other WALL (T: its interior face, or its exterior face from outside).

Two-way
    sync(doc, mass)   mass -> wall drivers of its group (curves + params) -> wall builds. Live mode
                      runs it on every gumball edit of a mass (masses.sync dispatches on mc.type).
    follow(doc, ctx)  engine.build of a mass-driven wall: the mass moves / resizes to the wall's
                      base and height (MCEdit, the panel) and follows a moved driver line.
    after_params      flip / reference / layer changes of the wall re-derive it from its mass.
    release           a deleted mass deletes its wall (and that wall's openings / opening masses);
                      a deleted wall deletes its mass; the neighbors' corners are re-derived.
Openings hosted by a mass-driven wall keep their place along the wall: when the mass moves they
keep their distance from the mass's end; when only the line changes (a corner, a flip) they are
projected onto the new line. Opening masses with one opening follow their opening (masses.follow).
"""

import json
import math
import time

import System
import Rhino
import scriptcontext

from . import docutil, geo, library, meta, units

G = Rhino.Geometry
WALL = "mc.wall"                 # wall mass -> its wall driver id
LINE = "mc.mass.line"            # wall driver -> where the last sync put it
GAP_IN = 1.0                     # masses closer than this touch (groups, corners)
MODES = ("auto", "strip", "perimeter")
STRIP_RATIO = 1.0 / 3.0          # auto: a strip at most this thick for its length, else a perimeter
RAYS = 72
SIN_MIN = math.sin(math.radians(15.0))
DEFAULT_REFERENCE = "exterior_face"
ARROW_IN = 18.0
ARROW_COLOR = (0, 120, 230)
ARROWS_KEY = "mindcanvas.wallmass.arrows"

_STATE = {"driving": 0}


class _driving(object):
    """Inside: wall builds come from a mass sync (follow() leaves the masses alone)."""

    def __enter__(self):
        _STATE["driving"] += 1
        return self

    def __exit__(self, *exc):
        _STATE["driving"] -= 1
        return False


def _quiet():
    from . import live
    return live.quiet()


def _masses():
    from . import masses
    return masses


# -- objects -------------------------------------------------------------------------------------
def is_wall_mass(obj):
    return meta.is_mass(obj) and meta.get(obj, meta.TYPE) == "wall"


def all_wall_masses(doc):
    return [m for m in _masses().all_masses(doc) if meta.get(m, meta.TYPE) == "wall"]


def _find(doc, oid):
    try:
        o = doc.Objects.FindId(oid if isinstance(oid, System.Guid) else System.Guid(str(oid)))
    except Exception:
        return None
    return o if (o is not None and not o.IsDeleted) else None


def wall_of(doc, mass_obj):
    """The wall driver of a wall mass (by its mc.mass link), else None."""
    found = doc.Objects.FindByUserString(_masses().MASS, str(mass_obj.Id), True) or []
    for o in found:
        if not o.IsDeleted and meta.is_driver(o) and meta.get(o, meta.TYPE) == "wall":
            return o
    return None


def mass_of(doc, wall_obj):
    """The wall mass of a wall driver, else None."""
    if wall_obj is None or meta.get(wall_obj, meta.TYPE) != "wall":
        return None
    m = _masses().mass_of(doc, wall_obj)
    return m if is_wall_mass(m) else None


def pick_mass(doc, obj):
    """A wall mass from the mass itself, its wall driver or a part of that wall."""
    if is_wall_mass(obj):
        return obj
    return mass_of(doc, meta.driver_of(doc, obj))


def _set_text(doc, obj, pairs):
    attrs = obj.Attributes.Duplicate()
    for k, v in pairs.items():
        attrs.SetUserString(k, v)
    with _quiet():
        doc.Objects.ModifyAttributes(obj, attrs, True)
    return doc.Objects.FindId(obj.Id)


def write_params(doc, mass_obj, prm):
    return _set_text(doc, mass_obj, {meta.PARAMS: json.dumps(prm, sort_keys=True)})


# -- 2D helpers ------------------------------------------------------------------------------------
def _p2(p):
    return (p.X, p.Y)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _len(a):
    return math.hypot(a[0], a[1])


def _unit(a):
    n = _len(a)
    return (a[0] / n, a[1] / n) if n > 1e-12 else (0.0, 0.0)


def _seg_hit(p, q, a, b):
    """Do segments p-q and a-b intersect?"""
    d1, d2 = _cross(_sub(q, p), _sub(a, p)), _cross(_sub(q, p), _sub(b, p))
    d3, d4 = _cross(_sub(b, a), _sub(p, a)), _cross(_sub(b, a), _sub(q, a))
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _pt_seg(p, a, b):
    ab = _sub(b, a)
    L2 = _dot(ab, ab)
    t = 0.0 if L2 < 1e-18 else max(0.0, min(1.0, _dot(_sub(p, a), ab) / L2))
    return _len(_sub(p, (a[0] + ab[0] * t, a[1] + ab[1] * t)))


def _seg_seg(p, q, a, b):
    if _seg_hit(p, q, a, b):
        return 0.0
    return min(_pt_seg(p, a, b), _pt_seg(q, a, b), _pt_seg(a, p, q), _pt_seg(b, p, q))


def _inside(p, poly):
    c = False
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if p[0] < x:
                c = not c
    return c


def _edges(poly):
    n = len(poly)
    return [(poly[i], poly[(i + 1) % n]) for i in range(n)]


def _poly_dist(pa, pb):
    if any(_inside(p, pb) for p in pa[:1]) or any(_inside(p, pa) for p in pb[:1]):
        return 0.0
    return min(_seg_seg(a, b, c, d) for a, b in _edges(pa) for c, d in _edges(pb))


def _seg_poly_dist(p, q, poly):
    if _inside(p, poly) or _inside(q, poly):
        return 0.0
    return min(_seg_seg(p, q, a, b) for a, b in _edges(poly))


def _polyline(curve, n_curved=16):
    """Points (2D) along a closed curve: segment start points, curved segments divided."""
    pts = []
    for s in _segments(curve, 1e-6):
        if s.IsLinear(1e-6):
            pts.append(_p2(s.PointAtStart))
        else:
            ts = s.DivideByCount(n_curved, True) or []
            pts.extend(_p2(s.PointAt(t)) for t in list(ts)[:-1])
    return pts


def _segments(curve, tol):
    segs = list(curve.DuplicateSegments() or []) or [curve.DuplicateCurve()]
    out = []
    for s in segs:
        ks = geo.kink_parameters(s)
        out.extend(list(s.Split(ks)) if ks else [s])
    merged = []
    for s in out:
        if merged and s.IsLinear(tol) and merged[-1].IsLinear(tol):
            a, b = merged[-1], s
            da = _unit(_sub(_p2(a.PointAtEnd), _p2(a.PointAtStart)))
            db = _unit(_sub(_p2(b.PointAtEnd), _p2(b.PointAtStart)))
            if abs(_cross(da, db)) < 1e-6 and _dot(da, db) > 0:
                merged[-1] = G.LineCurve(a.PointAtStart, b.PointAtEnd)
                continue
        merged.append(s)
    if len(merged) > 2 and curve.IsClosed and merged[0].IsLinear(tol) and merged[-1].IsLinear(tol):
        a, b = merged[-1], merged[0]
        da = _unit(_sub(_p2(a.PointAtEnd), _p2(a.PointAtStart)))
        db = _unit(_sub(_p2(b.PointAtEnd), _p2(b.PointAtStart)))
        if abs(_cross(da, db)) < 1e-6 and _dot(da, db) > 0:
            merged[0] = G.LineCurve(a.PointAtStart, b.PointAtEnd)
            merged.pop()
    return merged


def _closest(curve, p3):
    ok, t = curve.ClosestPoint(p3)
    return curve.PointAt(t), t


def _flat(curve, z):
    c = curve.DuplicateCurve()
    c.Translate(G.Vector3d(0, 0, z - c.PointAtStart.Z))
    return c


# -- footprints ------------------------------------------------------------------------------------
class Chain(object):
    """One long face of a mass (a curve at the mass bottom, running from cap i to cap j)."""

    def __init__(self, name, curve, other=None):
        self.name = name
        self.curve = curve
        ok, t = curve.LengthParameter(0.5 * curve.GetLength())
        P = curve.PointAt(t)
        T = curve.TangentAt(t)
        left = _unit((-T.Y, T.X))
        if other is None:       # a perimeter: the inside of the closed loop is inward
            inward = curve.ClosedCurveOrientation(G.Vector3d.ZAxis) == G.CurveOrientation.CounterClockwise
        else:
            Q, _ = _closest(other, P)
            inward = _dot(_sub(_p2(Q), _p2(P)), left) > 0     # the other face is on the left
        self.left = not inward                             # the outward normal is on the left
        self.o = left if self.left else (-left[0], -left[1])
        self.mid = _p2(P)


class Footprint(object):
    """A wall mass reduced to its plan (model units)."""

    def __init__(self, doc, obj):
        masses = _masses()
        tol = doc.ModelAbsoluteTolerance
        self.obj, self.id = obj, str(obj.Id)
        self.warnings = []
        brep = masses.to_brep(obj.Geometry)
        if brep is None or not brep.IsSolid:
            raise geo.GeometryError("A wall mass must be a closed solid.")
        bb = brep.GetBoundingBox(True)
        face, z0 = _bottom_face(brep, tol)
        self.z0, self.z1 = z0, bb.Max.Z
        if self.z1 - self.z0 < 10 * tol:
            raise geo.GeometryError("A wall mass has no height.")
        outer, inner = None, []
        for lp in face.Loops:
            c = _flat(lp.To3dCurve(), z0)
            if lp.LoopType == G.BrepLoopType.Outer:
                outer = c
            else:
                inner.append(c)
        if outer is None:
            raise geo.GeometryError("A wall mass needs a flat, level bottom face.")
        mode = str(meta.params(obj).get("mode") or "auto").lower()
        if mode not in MODES:
            mode = "auto"
        self.perimeter = False
        found, segs = None, None
        if not inner and mode != "perimeter":
            segs = _segments(outer, tol)
            found = _strip(segs, tol)
            if found is not None and mode == "auto" and found[2] > STRIP_RATIO * _chain_min(segs, found):
                found = None        # a block (a cube, a room): its perimeter
        if mode == "perimeter" or (mode == "auto" and (len(inner) > 1 or (not inner and found is None))):
            if inner:
                self.warnings.append("A perimeter wall mass follows its outer outline; its holes are ignored.")
            inner = []
            self.perimeter = True
        elif inner and (mode == "strip" or len(inner) > 1):
            raise geo.GeometryError("A strip wall mass cannot have holes (a ring has one); use Mode=Perimeter "
                                    "or one mass per wall.")
        self.ring = bool(inner) or self.perimeter
        if self.ring:
            self.A = Chain("A", outer, inner[0] if inner else None)
            self.B = Chain("B", inner[0], outer) if inner else None
            if inner:
                Q, _ = _closest(outer, inner[0].PointAtStart)
                self.t = Q.DistanceTo(inner[0].PointAtStart)
            else:
                obb = outer.GetBoundingBox(True)
                self.t = 0.5 * min(obb.Max.X - obb.Min.X, obb.Max.Y - obb.Min.Y)
            self.caps = None
            self.polys = [_polyline(outer)] + ([_polyline(inner[0])] if inner else [])
            c = outer.GetBoundingBox(True).Center
            self.ci = self.cj = _p2(c)
        else:
            if found is None:
                self.warnings.append("A wall mass is not a strip (two long faces between two ends); "
                                     "its bounding rectangle is used.")
                segs = _segments(_min_rectangle(outer, z0), tol)
                found = _strip(segs, tol)
                if found is None:
                    raise geo.GeometryError("A wall mass could not be read as a wall.")
            i, j, t = found
            n = len(segs)
            a_idx = list(range(i + 1, j))
            b_idx = list(range(j + 1, n)) + list(range(0, i))
            ca = _join([segs[k] for k in a_idx], tol)
            cb = _join([segs[k] for k in b_idx], tol)
            end_i = segs[i].PointAtEnd
            if ca.PointAtEnd.DistanceTo(end_i) < ca.PointAtStart.DistanceTo(end_i):
                ca.Reverse()
            if cb.PointAtEnd.DistanceTo(segs[i].PointAtStart) < cb.PointAtStart.DistanceTo(segs[i].PointAtStart):
                cb.Reverse()
            self.A = Chain("A", ca, cb)
            self.B = Chain("B", cb, ca)
            self.t = t
            self.caps = (segs[i], segs[j])
            self.ci = _p2(segs[i].PointAtNormalizedLength(0.5))
            self.cj = _p2(segs[j].PointAtNormalizedLength(0.5))
            self.polys = [_polyline(outer)]
        pts = [p for poly in self.polys for p in poly]
        self.bb = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        self.center = _p2(outer.GetBoundingBox(True).Center)
        amp = G.AreaMassProperties.Compute(outer)
        if amp is not None:
            self.center = _p2(amp.Centroid)
            self.area = amp.Area
        else:
            self.area = (self.bb[2] - self.bb[0]) * (self.bb[3] - self.bb[1])
        # set by derive()
        self.side = None
        self.wall = None
        self.T = 0.0            # wall thickness (model units)
        self.y_ext = 0.0        # offset of the exterior face from the driver

    def chain(self, name):
        return self.A if name == "A" else self.B

    def touches(self, other, gap):
        if min(self.z1, other.z1) - max(self.z0, other.z0) <= gap:
            return False
        a, b = self.bb, other.bb
        if a[2] + gap < b[0] or b[2] + gap < a[0] or a[3] + gap < b[1] or b[3] + gap < a[1]:
            return False
        return any(_poly_dist(p, q) <= gap for p in self.polys for q in other.polys)


def _bottom_face(brep, tol):
    best = None
    flip = -1.0 if brep.SolidOrientation == G.BrepSolidOrientation.Inward else 1.0
    for f in brep.Faces:
        ok, pl = f.TryGetPlane(tol * 10)
        if not ok:
            continue
        nz = pl.ZAxis.Z * (-1.0 if f.OrientationIsReversed else 1.0) * flip
        if nz > -0.999:
            continue
        z = f.GetBoundingBox(True).Min.Z
        if best is None or z < best[1]:
            best = (f, z)
    if best is None:
        raise geo.GeometryError("A wall mass needs a flat, level bottom face.")
    return best


def _chain_min(segs, found):
    """Length of the shorter long face of a strip outline."""
    i, j, _ = found
    n = len(segs)
    la = sum(segs[k].GetLength() for k in range(i + 1, j))
    lb = sum(segs[k].GetLength() for k in list(range(j + 1, n)) + list(range(0, i)))
    return min(la, lb)


def _join(curves, tol):
    if len(curves) == 1:
        return curves[0].DuplicateCurve()
    j = G.Curve.JoinCurves(curves, tol * 10, True)
    if not j or len(j) != 1:
        raise geo.GeometryError("The faces of a wall mass do not join.")
    return j[0]


def _dist_to(p, segs, idx):
    return min(p.DistanceTo(_closest(segs[k], p)[0]) for k in idx)


def _strip(segs, tol):
    """(i, j, thickness): the two cap segments of a strip outline whose long chains stay a
    constant distance apart, shortest caps first; None if there is none."""
    n = len(segs)
    if n < 4:
        return None
    mids = [s.PointAtNormalizedLength(0.5) for s in segs]
    lens = [s.GetLength() for s in segs]
    best = None
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            A = list(range(i + 1, j))
            B = list(range(j + 1, n)) + list(range(0, i))
            ds = [_dist_to(mids[k], segs, B) for k in A] + [_dist_to(mids[k], segs, A) for k in B]
            ds.sort()
            t = ds[len(ds) // 2]
            if t <= 10 * tol or max(abs(d - t) for d in ds) > 0.15 * t + 10 * tol:
                continue
            if lens[i] > 3 * t or lens[j] > 3 * t:
                continue
            score = (round(lens[i] + lens[j], 6), -sum(lens[k] for k in A + B))
            if best is None or score < best[0]:
                best = (score, i, j, t)
    return None if best is None else best[1:]


def _min_rectangle(curve, z):
    pts = _polyline(curve, 32)
    best = None
    for k in range(len(pts)):
        d = _unit(_sub(pts[(k + 1) % len(pts)], pts[k]))
        if d == (0.0, 0.0):
            continue
        n = (-d[1], d[0])
        us = [_dot(p, d) for p in pts]
        vs = [_dot(p, n) for p in pts]
        area = (max(us) - min(us)) * (max(vs) - min(vs))
        if best is None or area < best[0]:
            best = (area, d, n, min(us), max(us), min(vs), max(vs))
    _, d, n, u0, u1, v0, v1 = best
    P = lambda u, v: G.Point3d(d[0] * u + n[0] * v, d[1] * u + n[1] * v, z)
    return G.PolylineCurve([P(u0, v0), P(u1, v0), P(u1, v1), P(u0, v1), P(u0, v0)])


def analyze(doc, objs, warnings):
    """{mass id: Footprint} for the given wall masses (unreadable ones are reported, skipped)."""
    out = {}
    for m in objs:
        try:
            f = Footprint(doc, m)
        except Exception as ex:
            warnings.append("Wall mass {}: {}".format(str(m.Id)[:8], ex))
            continue
        warnings.extend(f.warnings)
        out[f.id] = f
    return out


def groups(fps, gap):
    """Connected groups of touching footprints: {id: [Footprint, ...]} (shared lists)."""
    ids = list(fps)
    parent = dict((i, i) for i in ids)

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            if fps[ids[a]].touches(fps[ids[b]], gap):
                parent[root(ids[a])] = root(ids[b])
    comps = {}
    for i in ids:
        comps.setdefault(root(i), []).append(fps[i])
    return dict((i, comps[root(i)]) for i in ids)


# -- which face is exterior ------------------------------------------------------------------------
def _enclosed(p, polys, R):
    for k in range(RAYS):
        a = 2 * math.pi * (k + 0.5) / RAYS
        q = (p[0] + R * math.cos(a), p[1] + R * math.sin(a))
        if not any(_seg_hit(p, q, e0, e1) for poly in polys for e0, e1 in _edges(poly)):
            return False
    return True


def _camera_side(doc, f):
    try:
        vp = doc.Views.ActiveView.ActiveViewport
    except Exception:
        return None
    if vp.IsPerspectiveProjection:
        c = _p2(vp.CameraLocation)
        da = _dot(f.A.o, _sub(c, f.A.mid))
        db = _dot(f.B.o, _sub(c, f.B.mid))
        if abs(da - db) > 1e-9:
            return "A" if da > db else "B"
        return None
    d = vp.CameraDirection
    if math.hypot(d.X, d.Y) < 0.1 * max(abs(d.Z), 1e-9):
        return None             # a plan view: no preference
    da, db = _dot(f.A.o, (d.X, d.Y)), _dot(f.B.o, (d.X, d.Y))
    return "A" if da < db else "B"


def auto_side(doc, f, group, stored=None):
    """'A' or 'B': the face that is exterior before `flip` (see the module doc)."""
    if f.ring:
        return "A"
    eps = max(0.01 * f.t, doc.ModelAbsoluteTolerance * 4)
    polys = [p for g in group for p in g.polys]
    xs = [g.bb[0] for g in group] + [g.bb[2] for g in group]
    ys = [g.bb[1] for g in group] + [g.bb[3] for g in group]
    R = 2.0 * math.hypot(max(xs) - min(xs), max(ys) - min(ys)) + 10 * f.t
    pa = (f.A.mid[0] + f.A.o[0] * eps, f.A.mid[1] + f.A.o[1] * eps)
    pb = (f.B.mid[0] + f.B.o[0] * eps, f.B.mid[1] + f.B.o[1] * eps)
    ea, eb = _enclosed(pa, polys, R), _enclosed(pb, polys, R)
    if ea != eb:
        return "B" if ea else "A"
    tol = doc.ModelAbsoluteTolerance * 10
    if len(group) > 1:
        area = sum(g.area for g in group)
        c = (sum(g.center[0] * g.area for g in group) / area, sum(g.center[1] * g.area for g in group) / area)
        c3 = G.Point3d(c[0], c[1], f.z0)
        da = c3.DistanceTo(_closest(f.A.curve, c3)[0])
        db = c3.DistanceTo(_closest(f.B.curve, c3)[0])
        if abs(da - db) > tol:
            return "A" if da > db else "B"
    if stored:
        s = (float(stored[0]), float(stored[1]))
        return "A" if _dot(f.A.o, s) >= _dot(f.B.o, s) else "B"
    cam = _camera_side(doc, f)
    if cam:
        return cam
    left = (-(f.cj[1] - f.ci[1]), f.cj[0] - f.ci[0])
    return "A" if _dot(f.A.o, left) >= _dot(f.B.o, left) else "B"


def other(name):
    return "B" if name == "A" else "A"


# -- corners ---------------------------------------------------------------------------------------
def _extended(curve, R):
    if curve.IsClosed:
        return curve
    a, b = curve.PointAtStart, curve.PointAtEnd
    ta, tb = curve.TangentAtStart, curve.TangentAtEnd
    pieces = [G.LineCurve(a - ta * R, a), curve.DuplicateCurve(), G.LineCurve(b, b + tb * R)]
    j = G.Curve.JoinCurves(pieces, 1e-6, True)
    return j[0] if j and len(j) == 1 else curve


def _hit(P, u, crv, R, tol):
    """Point where the line P + s u (|s| <= R) crosses crv, nearest P: (X, s, tangent) or None."""
    z = crv.PointAtStart.Z
    line = G.LineCurve(G.Point3d(P[0] - u[0] * R, P[1] - u[1] * R, z), G.Point3d(P[0] + u[0] * R, P[1] + u[1] * R, z))
    ev = Rhino.Geometry.Intersect.Intersection.CurveCurve(line, crv, tol, tol)
    best = None
    for e in ev or []:
        X = _p2(e.PointA)
        s = _dot(_sub(X, P), u)
        T = crv.TangentAt(e.ParameterB)
        if best is None or abs(s) < abs(best[1]):
            best = (X, s, (T.X, T.Y))
    return best


def _end_cut(doc, f, key, group, gap):
    """(X, s): where the exterior face line of f should end at its cap `key` ('i' / 'j'), s = the
    signed extension (+ = longer), or None to keep it."""
    tol = doc.ModelAbsoluteTolerance
    E = f.chain(f.side).curve
    if key == "i":
        P3, T = E.PointAtStart, -E.TangentAtStart
        cap = f.caps[0]
    else:
        P3, T = E.PointAtEnd, E.TangentAtEnd
        cap = f.caps[1]
    P, u = _p2(P3), _unit((T.X, T.Y))
    c0, c1 = _p2(cap.PointAtStart), _p2(cap.PointAtEnd)
    best = None
    for m in group:
        if m is f or m.side is None or m.T < 0 or min(f.z1, m.z1) - max(f.z0, m.z0) <= gap:
            continue
        if min(_seg_poly_dist(c0, c1, poly) for poly in m.polys) > gap:
            continue
        Em = m.chain(m.side).curve
        R = 4 * (f.t + m.t + f.T + m.T) + 4 * gap
        h = _hit(P, u, _flat(_extended(Em, R), f.z0), R, tol)
        if h is None:
            continue
        X, s, Tm = h
        if abs(s) > f.t + m.t + gap or abs(_cross(u, _unit(Tm))) < SIN_MIN:
            continue
        kind = "T"
        if not Em.IsClosed:
            dend = min(_len(_sub(X, _p2(Em.PointAtStart))), _len(_sub(X, _p2(Em.PointAtEnd))))
            ok, tx = Em.ClosestPoint(G.Point3d(X[0], X[1], Em.PointAtStart.Z))
            off_end = tx <= Em.Domain.T0 + 1e-9 or tx >= Em.Domain.T1 - 1e-9
            if off_end or dend <= f.t + gap:
                kind = "L"
        if kind == "T":
            # the near face of the other WALL: its interior face seen from inside, else its exterior
            Q, tq = _closest(Em, G.Point3d(X[0], X[1], Em.PointAtStart.Z))
            Tq = Em.TangentAt(tq)
            left = _unit((-Tq.Y, Tq.X))
            o = left if m.chain(m.side).left else (-left[0], -left[1])
            if _dot(_sub(f.center, X), o) < 0:
                d = -m.T if m.chain(m.side).left else m.T
                try:
                    F = geo.offset(Em, d, tol)
                except Exception:
                    continue
                h2 = _hit(P, u, _flat(_extended(F, R), f.z0), R, tol)
                if h2 is None:
                    continue
                X, s = h2[0], h2[1]
        if best is None or abs(s) < abs(best[1]):
            best = (X, s, kind)
    return best


def _set_end(crv, key, X, s, z, tol):
    if abs(s) <= tol:
        return crv
    if s > 0:
        P = crv.PointAtStart if key == "i" else crv.PointAtEnd
        Xp = G.Point3d(X[0], X[1], z)
        pieces = [G.LineCurve(Xp, P), crv] if key == "i" else [crv, G.LineCurve(P, Xp)]
        j = G.Curve.JoinCurves(pieces, tol * 10, True)
        return j[0] if j and len(j) == 1 else crv
    L = crv.GetLength()
    if -s >= L - 10 * tol:
        return crv
    ok, t = crv.LengthParameter(-s if key == "i" else L + s)
    if not ok:
        return crv
    out = crv.Trim(t, crv.Domain.T1) if key == "i" else crv.Trim(crv.Domain.T0, t)
    return out or crv


# -- deriving the wall -----------------------------------------------------------------------------
class Derived(object):
    def __init__(self):
        self.curve = None       # the wall driver as it should be
        self.params = None      # wall params (merged)
        self.assembly = None
        self.sig = None
        self.ext = (0.0, 0.0)   # extension at cap i / cap j (model units)
        self.start = "i"        # the driver starts at cap i / j


def top_cut(mass_obj):
    """Inches the wall stops below the mass's top (a dressed story under a floor: the floor's
    depth down to its framing bottom, mindcanvas/dress.py); 0 otherwise."""
    try:
        return max(0.0, float(meta.params(mass_obj).get("top_cut", 0) or 0))
    except (TypeError, ValueError):
        return 0.0


def _wall_params(doc, f):
    """(assembly, params) of the wall a mass drives (its wall's, else the mass's create params)."""
    from .kinds import wall as wallkind
    mprm = meta.params(f.obj)
    if f.wall is not None:
        return meta.get(f.wall, meta.ASSEMBLY), meta.params(f.wall)
    prm = dict(wallkind.DEFAULTS)
    prm.update(mprm.get("wall") or {})
    prm.setdefault("reference", DEFAULT_REFERENCE)
    return meta.get(f.obj, meta.ASSEMBLY), prm


def prepare(doc, lib, f):
    """Wall thickness and exterior-face offset of the wall a footprint drives."""
    from .kinds import wall as wallkind
    f.wall = wall_of(doc, f.obj)
    asm_name, prm = _wall_params(doc, f)
    s = units.inch_scale(doc)
    offs = wallkind.stack_offsets(lib, lib.assembly(asm_name), prm, s)
    f.y_ext = max(o[1] for o in offs)
    f.T = max(o[1] for o in offs) - min(o[2] for o in offs)
    f.asm, f.prm = asm_name, prm


def derive(doc, f, group, gap):
    """The wall driver (curve + params) of footprint f (sides of the whole group already set)."""
    tol = doc.ModelAbsoluteTolerance
    s_in = units.inch_scale(doc)
    mprm = meta.params(f.obj)
    flip = bool(mprm.get("flip")) and not f.perimeter
    ch = f.chain(f.side)
    E = ch.curve.DuplicateCurve()
    out = Derived()
    ext = [0.0, 0.0]
    if not f.ring:
        for k, key in enumerate(("i", "j")):
            cut = _end_cut(doc, f, key, group, gap)
            if cut is not None and abs(cut[1]) > tol:
                E = _set_end(E, key, cut[0], cut[1], f.z0, tol)
                ext[k] = cut[1]
    out.ext = tuple(ext)
    # exterior on the left (flip: on the right); offset by the reference
    ok, pl = E.TryGetPolyline()
    D = G.PolylineCurve(pl) if ok else E.DuplicateCurve()
    if f.ring:
        if D.ClosedCurveOrientation(G.Vector3d.ZAxis) == G.CurveOrientation.CounterClockwise:
            D.Reverse()           # clockwise: left = outside
        if f.side == "B":
            D.Reverse()           # the hole is outside
        ext_left_start = True
    else:
        if not ch.left:
            D.Reverse()
        ext_left_start = ch.left
    if f.y_ext > tol:
        D = geo.offset(D, -f.y_ext, tol)
    if flip and not f.ring:
        D.Reverse()
    out.start = "i" if (ext_left_start != flip) else "j"
    base = units.parse_length(f.prm.get("base_offset", 0)) * s_in
    D.Translate(G.Vector3d(0, 0, f.z0 - base - D.PointAtStart.Z))
    out.curve = D
    prm = dict(f.prm)
    prm["height"] = round((f.z1 - f.z0) / s_in - top_cut(f.obj), 4)
    prm["flip"] = flip
    out.params = prm
    out.assembly = f.asm
    out.sig = {"p": [round(v, 6) for v in _p2(D.PointAtStart) + _p2(D.PointAtNormalizedLength(0.5))],
               "ci": [round(v, 6) for v in f.ci], "cj": [round(v, 6) for v in f.cj],
               "ext": [round(e, 6) for e in ext], "start": out.start}
    return out


def _same_curve(a, b, tol):
    if a is None or b is None or not isinstance(a, G.Curve) or a.IsClosed != b.IsClosed:
        return False
    if abs(a.GetLength() - b.GetLength()) > tol:
        return False
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        if a.PointAtNormalizedLength(t).DistanceTo(b.PointAtNormalizedLength(t)) > tol:
            return False
    return True


def _sig(obj):
    raw = meta.get(obj, LINE)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def _remap_openings(doc, wall, d, f, tol):
    """Keep the wall's openings in place along it when its driver is re-derived."""
    from .openings import core
    ops = core.hosted(doc, wall.Id)
    if not ops:
        return
    s_in = units.inch_scale(doc)
    old = wall.Geometry
    new = d.curve
    sig = _sig(wall)
    Lold, Lnew = old.GetLength(), new.GetLength()
    same_mass = (sig is None or old.IsClosed or new.IsClosed
                 or (_len(_sub(tuple(sig["ci"]), f.ci)) < tol and _len(_sub(tuple(sig["cj"]), f.cj)) < tol))
    for o in ops:
        prm = meta.params(o)
        st = units.parse_length(prm.get("station", 0)) * s_in
        if same_mass:
            ok, t = old.LengthParameter(min(max(st, 0.0), Lold))
            P = old.PointAt(t)
            new_st = core.station_of(new, P)
        else:
            from_i = st if sig.get("start") == "i" else Lold - st
            dist = from_i - float(sig.get("ext", [0, 0])[0])
            from_i_new = dist + d.ext[0]
            new_st = from_i_new if d.start == "i" else Lnew - from_i_new
        new_st = min(max(new_st, 0.0), Lnew)
        if abs(new_st - st) > units.to_model(doc, 1.0 / 64):
            ch = {"station": round(new_st / s_in, 4)}
            if prm.get("ro"):
                ch["ro"] = prm["ro"]
            core.update(doc, o, ch)


def _write(doc, f, d, tol):
    """Write a derived driver; returns the wall object if it changed (or is new), else None."""
    masses = _masses()
    w = f.wall
    if w is not None:
        cur = meta.params(w)
        same = (_same_curve(w.Geometry, d.curve, tol) and meta.get(w, meta.ASSEMBLY) == d.assembly
                and abs(float(cur.get("height", 0) or 0) - d.params["height"]) < 1e-3
                and bool(cur.get("flip")) == d.params["flip"])
        if same:
            if _sig(w) != d.sig:
                _set_text(doc, w, {LINE: json.dumps(d.sig)})
            return None
        _remap_openings(doc, w, d, f, tol)
        with _quiet():
            doc.Objects.Replace(w.Id, d.curve)
            w = doc.Objects.FindId(w.Id)
            meta.write_driver(doc, w, "wall", d.assembly, d.params)
        w = _set_text(doc, doc.Objects.FindId(w.Id), {LINE: json.dumps(d.sig)})
        return w
    with _quiet():
        attrs = Rhino.DocObjects.ObjectAttributes()
        attrs.LayerIndex = docutil.ensure_driver_layer(doc)
        oid = doc.Objects.AddCurve(d.curve, attrs)
        w = doc.Objects.FindId(oid)
        meta.write_driver(doc, w, "wall", d.assembly, d.params)
    w = _set_text(doc, doc.Objects.FindId(oid), {masses.MASS: str(f.obj.Id), LINE: json.dumps(d.sig)})
    f.obj = _set_text(doc, f.obj, {WALL: str(oid)})
    return w


# -- mass -> walls ---------------------------------------------------------------------------------
def sync(doc, mass_obj, lib=None):
    return sync_many(doc, [mass_obj], lib)


def sync_many(doc, objs, lib=None):
    """Re-derive the walls of the given wall masses and of every mass touching them now or joined
    to their walls at the last build; build the walls whose driver changed. Returns a
    masses.SyncResult (results = BuildResults of the walls built)."""
    from . import engine
    masses = _masses()
    t0 = time.time()
    lib = lib or library.get()
    out = masses.SyncResult()
    tol = doc.ModelAbsoluteTolerance * 10
    gap = units.to_model(doc, GAP_IN)
    fps = analyze(doc, all_wall_masses(doc), out.warnings)
    seeds = set()
    for o in objs:
        if o is None:
            continue
        seeds.add(str(o.Id))
        w = wall_of(doc, o)
        for pid in (meta.joined_ids(w) if w is not None else ()):
            pm = mass_of(doc, _find(doc, pid))
            if pm is not None:
                seeds.add(str(pm.Id))
    seeds &= set(fps)
    if not seeds:
        out.seconds = time.time() - t0
        return out
    grp = groups(fps, gap)
    affected, seen = [], set()
    for sid in sorted(seeds):
        for g in grp[sid]:
            if g.id not in seen:
                seen.add(g.id)
                affected.append(g)
    # sides need the whole group of each affected mass
    for f in affected:
        for g in grp[f.id]:
            if g.side is None:
                try:
                    prepare(doc, lib, g)
                except Exception as ex:
                    out.warnings.append("Wall mass {}: {}".format(g.id[:8], ex))
                    g.T = -1
                    continue
                mprm = meta.params(g.obj)
                auto = auto_side(doc, g, grp[g.id], mprm.get("side"))
                g.side = other(auto) if mprm.get("flip") else auto
                if g.perimeter:
                    g.side = "A"
                    if mprm.get("flip"):
                        out.warnings.append("A perimeter wall mass keeps its exterior outside (Flip ignored).")
                side = [round(v, 6) for v in g.chain(auto).o]
                if mprm.get("side") != side:
                    mprm["side"] = side
                    g.obj = write_params(doc, g.obj, mprm)
    changed = []
    with _driving():
        for f in affected:
            if f.T < 0:
                continue
            try:
                d = derive(doc, f, grp[f.id], gap)
                w = _write(doc, f, d, tol)
            except Exception as ex:
                out.warnings.append("Wall mass {} could not drive its wall: {}".format(f.id[:8], ex))
                continue
            if w is not None:
                changed.append(w)
            if f.wall is not None or w is not None:
                out.walls.append((w or f.wall).Id)
            _store_arrow(doc, f)
        if changed:
            out.results.extend(engine.build_many(doc, [doc.Objects.FindId(w.Id) for w in changed], lib))
    out.seconds = time.time() - t0
    return out


def _store_arrow(doc, f):
    ch = f.chain(f.side)
    zm = 0.5 * (f.z0 + f.z1)
    a = G.Point3d(ch.mid[0], ch.mid[1], zm)
    L = units.to_model(doc, ARROW_IN)
    b = G.Point3d(ch.mid[0] + ch.o[0] * L, ch.mid[1] + ch.o[1] * L, zm)
    _arrow_state()["arrows"][(doc.RuntimeSerialNumber, f.id)] = (a, b)


# -- walls -> mass ---------------------------------------------------------------------------------
def follow(doc, ctx, obj):
    """After a build of a mass-driven wall (not from a mass sync): the mass takes the wall's base
    and height, and follows a moved driver line (rigidly; then the group is re-derived)."""
    masses = _masses()
    if _STATE["driving"] or obj is None:
        return
    m = mass_of(doc, obj)
    if m is None:
        return
    tol = ctx.u(1.0 / 32)
    geom = m.Geometry
    bb = geom.GetBoundingBox(True)
    z0, z1 = bb.Min.Z, bb.Max.Z
    xf = G.Transform.Identity
    moved = False
    H = ctx.height + ctx.u(top_cut(m))       # the mass reaches past the wall by its top cut
    if abs(z0 - ctx.base_z) > tol or abs((z1 - z0) - H) > tol:
        sz = H / (z1 - z0) if z1 - z0 > ctx.tol else 1.0
        xf = (G.Transform.Translation(0, 0, ctx.base_z - z0)
              * G.Transform.Scale(G.Plane(G.Point3d(0, 0, z0), G.Vector3d.ZAxis), 1.0, 1.0, sz))
        moved = True
    sig = _sig(obj)
    plan = False
    raw = obj.Geometry
    if sig:
        a0, m0 = (sig["p"][0], sig["p"][1]), (sig["p"][2], sig["p"][3])
        a1, m1 = _p2(raw.PointAtStart), _p2(raw.PointAtNormalizedLength(0.5))
        if _len(_sub(a0, a1)) > tol or _len(_sub(m0, m1)) > tol:
            d0, d1 = _unit(_sub(m0, a0)), _unit(_sub(m1, a1))
            if d0 != (0.0, 0.0) and d1 != (0.0, 0.0):
                p0 = G.Plane(G.Point3d(a0[0], a0[1], 0), G.Vector3d(d0[0], d0[1], 0), G.Vector3d(-d0[1], d0[0], 0))
                p1 = G.Plane(G.Point3d(a1[0], a1[1], 0), G.Vector3d(d1[0], d1[1], 0), G.Vector3d(-d1[1], d1[0], 0))
                xf = G.Transform.PlaneToPlane(p0, p1) * xf
                moved = plan = True
    if not moved:
        return
    g = masses._transformed(geom, xf)
    if g is None:
        ctx.warn("A wall mass could not follow its wall.")
        return
    with _quiet():
        doc.Objects.Replace(m.Id, g)
    if plan:
        sr = sync(doc, doc.Objects.FindId(m.Id), ctx.lib)
        for w in sr.warnings:
            ctx.warn(w)
    else:
        _store_arrow_safe(doc, doc.Objects.FindId(m.Id))


def _store_arrow_safe(doc, m):
    try:
        f = Footprint(doc, m)
        stored = meta.params(m).get("side")
        f.side = auto_side(doc, f, [f], stored)
        if meta.params(m).get("flip") and not f.perimeter:
            f.side = other(f.side)
        _store_arrow(doc, f)
    except Exception:
        pass


PLAN_KEYS = ("flip", "reference", "layers", "overrides")


def after_params(doc, wall_id, old, new, lib=None, force=False):
    """A mass-driven wall's params changed (MCEdit, MCLayers, the panel, set_assembly): a flip goes
    to the mass; the face position / thickness re-derive the wall and its neighbors. Returns the
    wall's BuildResult from the sync, else None."""
    w = _find(doc, wall_id)
    m = mass_of(doc, w)
    if m is None:
        return None
    if not force and all(old.get(k) == new.get(k) for k in PLAN_KEYS):
        return None
    mprm = meta.params(m)
    if bool(mprm.get("flip")) != bool(new.get("flip")) and not is_perimeter(doc, m):
        mprm["flip"] = bool(new.get("flip"))
        m = write_params(doc, m, mprm)
    if meta.get(m, meta.ASSEMBLY) != meta.get(w, meta.ASSEMBLY):
        m = _set_text(doc, m, {meta.ASSEMBLY: meta.get(w, meta.ASSEMBLY)})
    sr = sync(doc, m, lib)
    mine = [r for r in sr.results if str(r.driver_id) == str(wall_id)]
    return mine[0] if mine else None


# -- deleting --------------------------------------------------------------------------------------
def release(doc, oid, lib=None, keep=False):
    """A deleted object: a wall mass takes its wall (and the wall's openings) along; a wall takes
    its mass along (keep: the mass stays as a plain solid on its own layer, engine.release). The
    neighbors are re-derived. Returns BuildResults."""
    from . import engine
    masses = _masses()
    lib = lib or library.get()
    key = str(oid)
    walls = [o for o in (doc.Objects.FindByUserString(masses.MASS, key, True) or [])
             if not o.IsDeleted and meta.is_driver(o) and meta.get(o, meta.TYPE) == "wall"]
    owned = [o for o in (doc.Objects.FindByUserString(WALL, key, True) or [])
             if not o.IsDeleted and is_wall_mass(o)]
    if not walls and not owned:
        return []
    neighbors, plain = [], set()
    for w in walls:
        for pid in meta.joined_ids(w):
            p = _find(doc, pid)
            pm = mass_of(doc, p)
            if pm is not None:
                neighbors.append(pm)
            elif p is not None:
                plain.add(pid)
        engine.delete_openings(doc, w.Id)
        engine.delete_parts(doc, w.Id)
        with _quiet():
            doc.Objects.Delete(w, True)
    if owned:
        warn = []
        fps = analyze(doc, all_wall_masses(doc), warn)
        grp = groups(fps, units.to_model(doc, GAP_IN))
        for m in owned:
            for g in grp.get(str(m.Id), []):
                if g.id != str(m.Id):
                    neighbors.append(g.obj)
            with _quiet():
                if keep:
                    from . import engine as _engine
                    meta.strip(doc, m, _engine.home_layer(doc, m))
                else:
                    doc.Objects.Delete(m, True)
            _arrow_state()["arrows"].pop((doc.RuntimeSerialNumber, str(m.Id)), None)
    _arrow_state()["arrows"].pop((doc.RuntimeSerialNumber, key), None)
    out = []
    alive = [doc.Objects.FindId(n.Id) for n in neighbors]
    alive = [n for n in alive if n is not None and not n.IsDeleted]
    if alive:
        out.extend(sync_many(doc, alive, lib).results)
    done = set(str(r.driver_id) for r in out)
    for pid in sorted(plain - done):
        try:
            out.append(engine.build(doc, System.Guid(pid), lib, joined=False))
        except Exception:
            pass
    return out


# -- creating --------------------------------------------------------------------------------------
def write(doc, solid_obj, assembly, params=None):
    """Tag a solid as a wall mass (not synced). params: flip, mode (auto | strip | perimeter), and
    params for the wall it creates (lod, reference, ...)."""
    prm = {"flip": bool((params or {}).get("flip", False))}
    mode = str((params or {}).get("mode") or "auto").lower()
    if mode != "auto":
        if mode not in MODES:
            raise ValueError("Unknown wall mass mode '{}'.".format(mode))
        prm["mode"] = mode
    wall = dict((k, v) for k, v in (params or {}).items() if k not in ("flip", "side", "mode"))
    if wall:
        prm["wall"] = wall
    return _masses().write(doc, solid_obj, assembly, prm, kind="wall")


def make(doc, solid_obj, assembly, params=None, lib=None):
    """Turn a closed solid into a wall mass and sync it. Returns (mass object, SyncResult)."""
    objs, sr = make_many(doc, [solid_obj], assembly, params, lib)
    return (objs[0] if objs else None), sr


def make_many(doc, solids, assembly, params=None, lib=None):
    """Several solids at once (their corners are resolved together)."""
    lib = lib or library.get()
    if lib.assembly(assembly).get("kind", "wall") != "wall":
        raise ValueError("'{}' is not a wall assembly.".format(assembly))
    show_arrows(True)
    objs = [write(doc, s, assembly, params) for s in solids]
    sr = sync_many(doc, objs, lib)
    return [doc.Objects.FindId(o.Id) for o in objs], sr


def from_wall(doc, wall_obj, lib=None):
    """A mass for an existing wall: its plan band (exterior to interior face) from its base to its
    top; the wall keeps its params and its openings. Returns the mass (or the existing one)."""
    masses = _masses()
    existing = mass_of(doc, wall_obj)
    if existing is not None:
        return existing
    if meta.get(wall_obj, meta.TYPE) != "wall":
        raise ValueError("Only walls can get a wall mass.")
    lib = lib or library.get()
    tol = doc.ModelAbsoluteTolerance
    info = masses.WallInfo(doc, lib, wall_obj)
    region = geo.band_region(info.curve, info.y_ext, info.y_int, tol)
    if len(region) != 1:
        raise ValueError("The wall's plan is not one region.")
    solid = geo.extrude_region(region[0], info.base_z, info.height, tol)
    with _quiet():
        mid = doc.Objects.AddBrep(solid)
    show_arrows(True)
    m = masses.write(doc, doc.Objects.FindId(mid), meta.get(wall_obj, meta.ASSEMBLY), {"flip": False}, kind="wall")
    _set_text(doc, doc.Objects.FindId(wall_obj.Id), {masses.MASS: str(m.Id)})
    m = _set_text(doc, m, {WALL: str(wall_obj.Id)})
    # keep the wall's exterior where it is: side / flip so that the rules pick that face
    f = Footprint(doc, m)
    ext_line = geo.offset(info.curve, info.y_ext, tol)
    P = ext_line.PointAtNormalizedLength(0.5)
    da = P.DistanceTo(_closest(f.A.curve, P)[0])
    db = P.DistanceTo(_closest(f.B.curve, P)[0])
    cur = "A" if da <= db else "B"
    warn = []
    fps = analyze(doc, all_wall_masses(doc), warn)
    grp = groups(fps, units.to_model(doc, GAP_IN))
    fc = fps.get(str(m.Id), f)
    stored = [round(v, 6) for v in fc.chain(cur).o]
    auto = auto_side(doc, fc, grp.get(str(m.Id), [fc]), stored)
    return write_params(doc, m, {"flip": auto != cur, "side": stored})


def convert(doc, walls, lib=None):
    """Give walls a mass each, then sync them together. Returns (masses, SyncResult, skipped)."""
    lib = lib or library.get()
    out, skipped = [], []
    for w in walls:
        try:
            out.append(from_wall(doc, w, lib))
        except Exception as ex:
            skipped.append("{}: {}".format(str(w.Id)[:8], ex))
    sr = sync_many(doc, out, lib)
    return [doc.Objects.FindId(m.Id) for m in out], sr, skipped


def is_perimeter(doc, mass_obj):
    try:
        return Footprint(doc, mass_obj).perimeter
    except Exception:
        return False


def flip(doc, mass_objs, lib=None):
    """Put the exterior on the other face of each mass (perimeter masses keep it outside).
    Returns the SyncResult."""
    objs, skipped = [], 0
    for m in mass_objs:
        if is_perimeter(doc, m):
            skipped += 1
            continue
        prm = meta.params(m)
        prm["flip"] = not bool(prm.get("flip"))
        objs.append(write_params(doc, m, prm))
    sr = sync_many(doc, objs, lib)
    if skipped:
        sr.warnings.append("{} perimeter mass(es) keep the exterior outside (not flipped).".format(skipped))
    return sr


def set_mode(doc, mass_objs, mode, lib=None):
    """Read masses as strips / perimeters / automatically from now on. Returns the SyncResult."""
    mode = str(mode).lower()
    if mode not in MODES:
        raise ValueError("Unknown wall mass mode '{}'.".format(mode))
    objs = []
    for m in mass_objs:
        prm = meta.params(m)
        if mode == "auto":
            prm.pop("mode", None)
        else:
            prm["mode"] = mode
        prm.pop("side", None)       # the old reading's side means nothing now
        objs.append(write_params(doc, m, prm))
    return sync_many(doc, objs, lib)


# -- flip arrows (display only) --------------------------------------------------------------------
def _arrow_state():
    st = scriptcontext.sticky.get(ARROWS_KEY)
    if st is None:
        st = {"arrows": {}, "handler": None, "on": False}
        scriptcontext.sticky[ARROWS_KEY] = st
    return st


def show_arrows(on=True):
    """An arrow out of the exterior face of every wall mass (drawn while the masses are visible)."""
    st = _arrow_state()
    st["on"] = bool(on)
    if on and st["handler"] is None:
        color = System.Drawing.Color.FromArgb(*ARROW_COLOR)

        def draw(sender, e):
            try:
                if not st["on"]:
                    return
                doc = e.RhinoDoc
                if doc is None:
                    return
                sn = doc.RuntimeSerialNumber
                for (dsn, mid), (a, b) in list(st["arrows"].items()):
                    if dsn != sn:
                        continue
                    o = doc.Objects.FindId(System.Guid(mid))
                    if o is None or o.IsDeleted or not o.Visible:
                        continue
                    if not doc.Layers[o.Attributes.LayerIndex].IsVisible:
                        continue
                    e.Display.DrawArrow(G.Line(a, b), color)
            except Exception:
                pass

        Rhino.Display.DisplayPipeline.DrawForeground += draw
        st["handler"] = draw
    return st["on"]
