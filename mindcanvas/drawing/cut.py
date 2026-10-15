"""Cut poche: closed section loops per part, their material decoration and the
heavy outline of the union of all cut regions.

Loops come from Intersection.BrepPlane per item whose box straddles the plane
(block parts intersect their cached definition Brep with the plane moved into
definition space), never from stitched HLD SectionCut segments. Cut faces lie
on the plane, so nothing can hide them: they are painted last.
"""

import math

import Rhino
from Rhino.Geometry.Intersect import Intersection

from . import stipple

G = Rhino.Geometry


class Region(object):
    __slots__ = ("loops", "material", "spec", "item", "area", "bbox", "small", "ground", "hatch", "dots")

    def __init__(self, loops, material, spec, item, ground):
        self.loops = loops
        self.material = material
        self.spec = spec
        self.item = item
        self.ground = ground
        self.area = sum(abs(shoelace(lp)) for lp in loops[:1]) if loops else 0.0
        xs = [p[0] for lp in loops for p in lp]
        ys = [p[1] for lp in loops for p in lp]
        self.bbox = (min(xs), min(ys), max(xs), max(ys))
        self.small = False
        self.hatch = []
        self.dots = []

    def translate(self, dx, dy):
        self.loops = [[(x + dx, y + dy) for x, y in lp] for lp in self.loops]
        self.hatch = [[(x + dx, y + dy) for x, y in pl] for pl in self.hatch]
        self.dots = [(x + dx, y + dy) for x, y in self.dots]
        b = self.bbox
        self.bbox = (b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy)


# -- geometry helpers ----------------------------------------------------------
def shoelace(loop):
    a = 0.0
    for i in range(len(loop) - 1):
        a += loop[i][0] * loop[i + 1][1] - loop[i + 1][0] * loop[i][1]
    if loop and loop[0] != loop[-1]:
        a += loop[-1][0] * loop[0][1] - loop[0][0] * loop[-1][1]
    return 0.5 * a


def poly3d(crv, tol):
    ok, pl = crv.TryGetPolyline()
    if ok:
        pts = list(pl)
    else:
        pc = crv.ToPolyline(tol, 0.05, 0.0, 0.0)
        pts = list(pc.ToPolyline()) if pc else [crv.PointAtStart, crv.PointAtEnd]
    return pts


def clip_plane3d(pts, plane, closed=True):
    """Sutherland-Hodgman: keep the part of a 3D polygon on the plane's normal side."""
    if not pts:
        return pts
    ds = [plane.DistanceTo(p) for p in pts]
    if min(ds) >= 0:
        return pts
    if max(ds) < 0:
        return []
    out = []
    n = len(pts)
    rng = range(n) if closed else range(n - 1)
    for i in rng:
        j = (i + 1) % n
        a, b, da, db = pts[i], pts[j], ds[i], ds[j]
        if da >= 0:
            out.append(a)
        if (da >= 0) != (db >= 0):
            out.append(a + (b - a) * (da / (da - db)))
    if not closed and ds[-1] >= 0:
        out.append(pts[-1])
    return out


def clip_rect(poly, box):
    """Sutherland-Hodgman against an axis-aligned box (x0, y0, x1, y1), 2D."""
    x0, y0, x1, y1 = box
    edges = ((0, x0, 1), (0, x1, -1), (1, y0, 1), (1, y1, -1))
    out = list(poly)
    if out and out[0] == out[-1]:
        out = out[:-1]
    for axis, val, sgn in edges:
        if not out:
            break
        src, out = out, []
        for i in range(len(src)):
            a, b = src[i], src[(i + 1) % len(src)]
            ia = (a[axis] - val) * sgn >= 0
            ib = (b[axis] - val) * sgn >= 0
            if ia:
                out.append(a)
            if ia != ib:
                t = (val - a[axis]) / (b[axis] - a[axis])
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    if len(out) >= 3:
        out.append(out[0])
        return out
    return []


def _dedupe(pts, eps=1e-6):
    out = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) > eps or abs(p[1] - out[-1][1]) > eps:
            out.append(p)
    return out


# -- cutting -------------------------------------------------------------------
def straddles(bb, plane):
    ds = [plane.DistanceTo(c) for c in bb.GetCorners()]
    return min(ds) < 0 < max(ds)


def cut_item(scene, it, plane, tol):
    """World (closed loops, open polylines) of one item cut by plane."""
    closed, opened = [], []
    g = scene._geo[it.key][0]
    if isinstance(g, G.Mesh):
        m = scene.mesh(it.key)
        if m is None:
            return closed, opened
        if not it.ixf.IsIdentity:
            m = m.DuplicateMesh()
            m.Transform(it.ixf)
        for pl in Intersection.MeshPlane(m, plane) or []:
            pts = list(pl)
            (closed if pl.IsClosed else opened).append(pts)
        return closed, opened
    b = scene.brep(it.key)
    if b is None:
        return closed, opened
    pl = plane
    if not it.ixf.IsIdentity:
        ok, inv = it.ixf.TryGetInverse()
        if not ok:
            return closed, opened
        pl = G.Plane(plane)
        pl.Transform(inv)
    rc, crvs, pts = Intersection.BrepPlane(b, pl, tol)
    if not rc or not crvs:
        return closed, opened
    for c in G.Curve.JoinCurves(crvs, tol * 2):
        if not it.ixf.IsIdentity:
            c.Transform(it.ixf)
        poly = poly3d(c, tol)
        (closed if c.IsClosed else opened).append(poly)
    return closed, opened


def regions(scene, items, plane, others, tol, project, style, cancel=None):
    """Cut regions (page coords via project) and open cut polylines [(pts, item)]."""
    out, lines = [], []
    for it in items:
        if cancel is not None:
            cancel.check()
        if "nocut" in it.flags or not straddles(it.bbox, plane):
            continue
        closed, opened = cut_item(scene, it, plane, tol)
        loops = []
        for pts in closed:
            for o in others:
                pts = clip_plane3d(pts, o)
            if len(pts) >= 3:
                lp = _dedupe([project(p) for p in pts])
                if len(lp) >= 3:
                    if lp[0] != lp[-1]:
                        lp.append(lp[0])
                    loops.append(lp)
        if loops:
            loops.sort(key=lambda lp: -abs(shoelace(lp)))
            spec = style.material(it.material)
            out.append(Region(loops, it.material, spec, it.index, it.ground or spec.get("ground", False)))
        for pts in opened:
            for o in others:
                pts = clip_plane3d(pts, o, closed=False)
            if len(pts) >= 2:
                lines.append(([project(p) for p in pts], it))
    return out, lines


# -- union outline -----------------------------------------------------------
def _clusters(regs, pad):
    order = sorted(range(len(regs)), key=lambda i: regs[i].bbox[0])
    parent = list(range(len(regs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    active = []
    for i in order:
        bi = regs[i].bbox
        active = [j for j in active if regs[j].bbox[2] >= bi[0] - pad]
        for j in active:
            bj = regs[j].bbox
            if bj[1] <= bi[3] + pad and bi[1] <= bj[3] + pad:
                parent[find(i)] = find(j)
        active.append(i)
    groups = {}
    for i in range(len(regs)):
        groups.setdefault(find(i), []).append(regs[i])
    return list(groups.values())


def _curve(loop):
    return G.PolylineCurve([G.Point3d(x, y, 0) for x, y in loop])


def union_outlines(regs, tol=0.002, max_cluster=1500):
    """Outer boundary of the union of all (non-ground) cut regions, page mm."""
    out = []
    stats = {"clusters": 0, "failed": 0}
    for group in _clusters(regs, 0.05):
        stats["clusters"] += 1
        loops = [lp for r in group for lp in r.loops[:1]]
        if len(loops) == 1:
            out.append(loops[0])
            continue
        res = None
        if len(loops) <= max_cluster:
            try:
                res = G.Curve.CreateBooleanUnion([_curve(lp) for lp in loops], tol)
            except Exception:
                res = None
        if not res:
            stats["failed"] += 1
            out += loops
            continue
        for c in res:
            out.append([(p.X, p.Y) for p in poly3d(c, tol)])
    return out, stats


# -- decoration ----------------------------------------------------------------
def obb(loop):
    """Min-area oriented box over the loop's edge directions: (o, u, v, lu, lv)."""
    best = None
    pts = loop[:-1] if loop[0] == loop[-1] else loop
    seen = set()
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        if L < 1e-9:
            continue
        ang = round(math.atan2(dy, dx) % (math.pi / 2), 3)
        if ang in seen:
            continue
        seen.add(ang)
        u = (dx / L, dy / L)
        v = (-u[1], u[0])
        us = [p[0] * u[0] + p[1] * u[1] for p in pts]
        vs = [p[0] * v[0] + p[1] * v[1] for p in pts]
        area = (max(us) - min(us)) * (max(vs) - min(vs))
        if best is None or area < best[0]:
            best = (area, u, v, min(us), max(us), min(vs), max(vs))
    if best is None:
        return None
    area, u, v, u0, u1, v0, v1 = best
    if u1 - u0 < v1 - v0:          # u = long axis
        u, v = v, (-u[0], -u[1])
        u0, u1, v0, v1 = v0, v1, -u1, -u0
    o = (u[0] * u0 + v[0] * v0, u[1] * u0 + v[1] * v0)
    return o, u, v, u1 - u0, v1 - v0


def batt(loops, min_mm=1.0):
    """Classic batt insulation: a looping curve (prolate cycloid) along the long axis."""
    box = obb(loops[0])
    if box is None:
        return []
    o, u, v, lu, lv = box
    if lv < min_mm:
        return []
    d, r = 0.46 * lv, 0.16 * lv
    step = math.pi / 10
    n = int(lu / r / step) + 1
    runs, cur = [], []
    for i in range(n + 1):
        th = i * step
        x = r * th - d * math.sin(th)
        y = 0.5 * lv + d * math.cos(th)
        p = (o[0] + u[0] * x + v[0] * y, o[1] + u[1] * x + v[1] * y)
        if 0 <= x <= lu and stipple.in_loops(p, loops):
            cur.append(p)
        elif cur:
            if len(cur) > 1:
                runs.append(cur)
            cur = []
    if len(cur) > 1:
        runs.append(cur)
    return runs


def cross(loops):
    """X through a rectangular member (wood framing / blocking in section)."""
    box = obb(loops[0])
    if box is None:
        return []
    o, u, v, lu, lv = box
    if abs(shoelace(loops[0])) < 0.85 * lu * lv:
        return []
    P = lambda a, b: (o[0] + u[0] * a + v[0] * b, o[1] + u[1] * a + v[1] * b)
    return [[P(0, 0), P(lu, lv)], [P(0, lv), P(lu, 0)]]


def paper_hatch(doc, loops, hatch, tol=0.001):
    """Rhino pattern lines inside page-space loops; returns (polylines, dots)."""
    from . import patterns
    idx = patterns.index(doc, hatch.get("pattern"))
    if idx < 0:
        return [], []
    crvs = [_curve(lp) for lp in loops if len(lp) >= 4]
    if not crvs:
        return [], []
    hs = G.Hatch.Create(crvs, idx, math.radians(float(hatch.get("rot", 0.0))), float(hatch.get("mm", 1.0)), tol)
    segs, dots = [], []
    for h in hs or []:
        for piece in h.Explode() or []:
            if isinstance(piece, G.Point):
                dots.append((piece.Location.X, piece.Location.Y))
            elif isinstance(piece, G.Curve):
                a, b = piece.PointAtStart, piece.PointAtEnd
                if a.DistanceTo(b) < 1e-4:
                    dots.append((a.X, a.Y))
                else:
                    segs.append([(p.X, p.Y) for p in poly3d(piece, tol)])
    return segs, dots


def decorate(doc, regs, style, box, cancel=None):
    """Fill each region's hatch / dots for its material, clipped to the page box."""
    min_cut = float(style.get("min_cut_mm", 0.8))
    cfg = style.stipple
    cap = int(cfg.get("max_cut_dots", 60000))
    total_dots = 0
    for k, r in enumerate(regs):
        if cancel is not None:
            cancel.check()
        b = r.bbox
        r.small = min(b[2] - b[0], b[3] - b[1]) < min_cut
        if b[2] < box[0] or b[0] > box[2] or b[3] < box[1] or b[1] > box[3]:
            continue
        spec = r.spec
        inside = b[0] >= box[0] and b[1] >= box[1] and b[2] <= box[2] and b[3] <= box[3]
        loops = r.loops if inside else [c for c in (clip_rect(lp, box) for lp in r.loops) if c]
        if not loops:
            continue
        density = float(spec.get("stipple", 0) or (cfg.get("cut_density", 2.4) if r.ground else 0))
        if density > 0 and total_dots < cap:
            r.dots = stipple.region_dots(loops, density, box, cap=cap - total_dots, seed=k + 3)
            total_dots += len(r.dots)
        if r.ground or r.small or spec.get("fill") in ("black", "grey"):
            continue
        if spec.get("hatch"):
            segs, dots = paper_hatch(doc, loops, spec["hatch"])
            r.hatch += segs
            r.dots += dots
        if spec.get("batt"):
            r.hatch += batt(loops)
        if spec.get("cross"):
            r.hatch += cross(loops)
    return total_dots


def ground_band(pts, band_mm, density, box, seed=5):
    """Stippled band under an open ground cut line (a ground surface cut by the plane)."""
    if len(pts) < 2 or band_mm <= 0:
        return []
    pts = sorted(pts, key=lambda p: p[0])
    poly = pts + [(x, y - band_mm) for x, y in reversed(pts)] + [pts[0]]

    def y_at(x):
        for i in range(len(pts) - 1):
            (x0, y0), (x1, y1) = pts[i], pts[i + 1]
            if x0 <= x <= x1:
                return y0 + (y1 - y0) * ((x - x0) / (x1 - x0) if x1 > x0 else 0.0)
        return pts[0][1]

    fade = lambda x, y: max(0.0, 1.0 - (y_at(x) - y) / band_mm) ** 1.3
    return stipple.region_dots([poly], density, box, seed=seed, fade=fade)
