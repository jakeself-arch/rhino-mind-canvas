"""Stipple: ground beyond the cut (screen-space jittered grid, depth-weighted) and
2D stipple inside cut regions.

Ground beyond the cut: one candidate per jittered grid cell over the PAGE area
(uniform paper density, no pile-up at the horizon). The z-buffer says which
surface a pixel shows; a candidate is kept when that surface is a ground face
(plane test + point-on-face of the exact ray hit). Candidate counts are capped
(the spike hung for >5 min sampling an off-page region), and the sampling area
is always clipped to the page.
"""

import math
import random

import Rhino
from Rhino.Geometry.Intersect import Intersection

G = Rhino.Geometry


def ground_faces(scene, items, tol):
    """[(face_brep_face, plane)] of upward-facing planar faces of ground items."""
    out = []
    for it in items:
        if not it.ground:
            continue
        b = scene.world_brep(it)
        if b is None:
            continue
        for f in b.Faces:
            ok, pl = f.TryGetPlane(tol * 10)
            if not ok:
                continue
            n = f.NormalAt(f.Domain(0).Mid, f.Domain(1).Mid)
            if f.OrientationIsReversed:
                n = -n
            if n.Z < 0.2:
                continue
            out.append((f, pl))
    return out


def ground_dots(zv, faces, rect_px, mm_per_px, cfg, cancel=None, seed=7):
    """World points of visible ground. rect_px = (x0, y0, x1, y1) screen pixels to
    sample (already clipped to the page)."""
    if not faces:
        return [], {"candidates": 0}
    density = float(cfg.get("density", 1.8))
    cap = int(cfg.get("max_samples", 90000))
    x0, y0, x1, y1 = rect_px
    x0, y0 = max(0.0, x0), max(0.0, y0)
    x1, y1 = min(float(zv.W), x1), min(float(zv.H), y1)
    if x1 <= x0 or y1 <= y0:
        return [], {"candidates": 0}
    cell = (1.0 / math.sqrt(density)) / mm_per_px      # px per cell
    n = ((x1 - x0) / cell) * ((y1 - y0) / cell)
    if n > cap:
        cell *= math.sqrt(n / cap)
    nx, ny = int((x1 - x0) / cell) + 1, int((y1 - y0) / cell) + 1
    rnd = random.Random(seed)
    PFR = G.PointFaceRelation
    out = []
    for j in range(ny):
        if cancel is not None:
            cancel.check()
        for i in range(nx):
            sx = x0 + (i + rnd.random()) * cell
            sy = y0 + (j + rnd.random()) * cell
            if sx >= x1 or sy >= y1:
                continue
            w = zv.world_at(sx, sy)
            if w is None:
                continue
            for f, pl in faces:
                ok, r = zv.on_plane(w, pl)
                if not ok:
                    continue
                ln = zv.ray(sx, sy)
                if ln is None:
                    break
                rc, t = Intersection.LinePlane(ln, pl)
                p = ln.PointAt(t) if rc else w
                okc, u, v = f.ClosestPoint(p)
                if okc and f.IsPointOnFace(u, v) != PFR.Exterior:
                    out.append(p)
                break
    return out, {"candidates": nx * ny, "cell_px": cell}


def keep_by_depth(points, depths, cfg, seed=11):
    """Thin dots with distance: keep probability near_p -> far_p."""
    if not points:
        return []
    rnd = random.Random(seed)
    lo, hi = min(depths), max(depths)
    near, far = float(cfg.get("near_p", 0.85)), float(cfg.get("far_p", 0.1))
    gam = float(cfg.get("gamma", 0.9))
    out = []
    for p, d in zip(points, depths):
        k = ((d - lo) / (hi - lo + 1e-9)) ** gam
        if rnd.random() < near + (far - near) * k:
            out.append((p, d))
    return out


# -- 2D ----------------------------------------------------------------------
def pip(pt, poly):
    x, y = pt
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def in_loops(pt, loops):
    """Even-odd over several loops (outer + holes)."""
    c = 0
    for lp in loops:
        if pip(pt, lp):
            c += 1
    return c % 2 == 1


def region_dots(loops, density, box, cap=60000, seed=3, fade=None):
    """Jittered-grid dots inside loops (page mm), limited to box = (x0, y0, x1, y1).
    fade(x, y) -> keep probability, optional."""
    xs = [p[0] for lp in loops for p in lp]
    ys = [p[1] for lp in loops for p in lp]
    if not xs or density <= 0:
        return []
    x0, x1 = max(min(xs), box[0]), min(max(xs), box[2])
    y0, y1 = max(min(ys), box[1]), min(max(ys), box[3])
    if x1 <= x0 or y1 <= y0:
        return []
    cell = 1.0 / math.sqrt(density)
    n = (x1 - x0) * (y1 - y0) / (cell * cell)
    if n > cap:
        cell *= math.sqrt(n / cap)
    rnd = random.Random(seed)
    out = []
    y = y0
    while y < y1:
        x = x0
        while x < x1:
            p = (x + rnd.random() * cell, y + rnd.random() * cell)
            if in_loops(p, loops) and (fade is None or rnd.random() < fade(p[0], p[1])):
                out.append(p)
            x += cell
        y += cell
    return out
