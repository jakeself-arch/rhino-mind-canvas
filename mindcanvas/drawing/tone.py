"""Tonal hatching: parallel lines on planar faces turned away from the sun.

Lines come from an even-odd scanline fill of each face's loops in face-plane
coordinates (pure Python, ~60x faster than contouring). Spacing is a PAPER
distance per tone level, converted at the face centroid; where perspective packs
lines closer than `min_mm`, only every 2^m-th line is kept, so far faces do not
go black. Vertical faces get vertical lines; horizontal faces get lines along
the view direction, converging on the vanishing point. Back faces are culled.
"""

import math

import Rhino

G = Rhino.Geometry


def face_loops(face, tol):
    polys = []
    for lp in face.Loops:
        c = lp.To3dCurve()
        if c is None:
            continue
        ok, pl = c.TryGetPolyline()
        if not ok:
            pc = c.ToPolyline(tol, 0.05, 0.0, 0.0)
            pl = pc.ToPolyline() if pc else None
        if pl is not None:
            pts = list(pl)
            if pts and pts[0].DistanceTo(pts[-1]) > 1e-9:
                pts.append(pts[0])
            polys.append(pts)
    return polys


def scanlines(polys, o, u, p, spacing, max_lines=4000):
    """Even-odd fill: yields (k, a, b), lines parallel to u spaced along p."""
    edges = []
    amin, amax = 1e30, -1e30
    for poly in polys:
        q2 = [((q - o) * p, (q - o) * u) for q in poly]
        for i in range(len(q2) - 1):
            edges.append((q2[i], q2[i + 1]))
            amin = min(amin, q2[i][0])
            amax = max(amax, q2[i][0])
    if not edges:
        return
    k0 = int(math.floor(amin / spacing))
    k1 = int(math.ceil(amax / spacing))
    if k1 - k0 > max_lines:
        return
    for k in range(k0, k1 + 1):
        a = (k + 0.5) * spacing
        xs = []
        for (a0, b0), (a1, b1) in edges:
            if (a0 <= a < a1) or (a1 <= a < a0):
                xs.append(b0 + (a - a0) * (b1 - b0) / (a1 - a0))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            if xs[i + 1] - xs[i] > 1e-6:
                yield k, o + p * a + u * xs[i], o + p * a + u * xs[i + 1]


def level(levels, d):
    for lim, sp in levels:
        if d <= lim:
            return sp
    return None


def generate(scene, items, style, mm_per, view, cancel=None, inch=1.0):
    """World tone segments [(a, b, face_plane)] for the given items.
    mm_per(pt, dir) -> paper mm per model unit along dir at pt.
    view: dict(cam, dir, parallel)."""
    cfg = style.tone
    sun = G.Vector3d(*style.get("sun", [-0.55, -0.35, 0.76]))
    sun.Unitize()
    levels = cfg.get("levels", [[-0.35, 0.45], [0.05, 0.8], [0.25, 1.4]])
    min_mm = float(cfg.get("min_mm", 0.3))
    min_face = float(cfg.get("min_face_mm", 2.5))
    max_lines = int(cfg.get("max_lines", 60000))
    lift = float(cfg.get("lift_in", 0.1)) * inch
    tol = scene.doc.ModelAbsoluteTolerance
    cam, cdir, parallel = view["cam"], view["dir"], view["parallel"]
    horiz = G.Vector3d(cdir.X, cdir.Y, 0)
    if horiz.Length < 1e-6:
        horiz = G.Vector3d(view.get("x", G.Vector3d.XAxis))
    horiz.Unitize()
    out = []
    stats = {"faces": 0, "lines": 0, "capped": False}
    for it in items:
        if cancel is not None:
            cancel.check()
        if it.small or "notone" in it.flags or it.ground:
            continue
        if not style.material(it.material).get("tone", True):
            continue
        if it.size_mm < min_face * 2:
            continue
        b = scene.world_brep(it)
        if b is None:
            continue
        for f in b.Faces:
            ok, fpl = f.TryGetPlane(tol * 10)
            if not ok:
                continue
            n = f.NormalAt(f.Domain(0).Mid, f.Domain(1).Mid)
            if f.OrientationIsReversed:
                n = -n
            n.Unitize()
            spacing = level(levels, n * sun)
            if spacing is None:
                continue
            polys = face_loops(f, tol * 10)
            if not polys:
                continue
            p0 = polys[0][0]
            facing = (n * -cdir) if parallel else (n * (cam - p0))
            if facing <= 0:
                continue
            bb = G.BoundingBox(polys[0])
            ctr = bb.Center
            if bb.Diagonal.Length * mm_per(ctr, view.get("x", G.Vector3d.XAxis)) < min_face:
                continue
            ud = G.Vector3d.ZAxis if abs(n.Z) < 0.7 else G.Vector3d(horiz)
            ud = ud - n * (ud * n)
            if ud.Length < 1e-6:
                ud = G.Vector3d.XAxis - n * n.X
            ud.Unitize()
            pn = G.Vector3d.CrossProduct(n, ud)
            k_ = mm_per(ctr, pn)
            if k_ <= 1e-9:
                continue
            world_sp = spacing / k_
            off = n * lift
            stats["faces"] += 1
            for k, a, b2 in scanlines(polys, ctr, ud, pn, world_sp):
                p_mm = world_sp * mm_per((a + b2) * 0.5, pn)
                if p_mm < min_mm:
                    m = int(math.ceil(math.log(min_mm / max(p_mm, 1e-6), 2)))
                    if k % (2 ** m):
                        continue
                out.append((a + off, b2 + off, fpl))
                if len(out) >= max_lines:
                    stats["capped"] = True
                    stats["lines"] = len(out)
                    return out, stats
    stats["lines"] = len(out)
    return out, stats
