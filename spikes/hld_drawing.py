"""Spike Q3-Q6: full 2D section-perspective drawing via HiddenLineDrawing.

Pipeline
  1. collect_scene()            model breps + exploded block geometry (tag = id/layer)
  2. tone_hatch_items()         3D hatch lines on faces turned away from the sun (Q4)
  3. stipple_points()           ground points sampled in SCREEN space, back-projected (Q5)
  4. HiddenLineDrawing          one compute: geometry + hatch curves + stipple points, user
                                clip plane (FLIPPED vs the display clipping plane), Flatten=False
  5. classify segments          cut / outline / edge / tone / frustum ; depth from H2W (Q3)
  6. cut loops                  Intersection.BrepPlane per straddling solid -> projected to 2D
                                -> white fill + paper-space hatch (Rhino Hatch.Create+Explode)
  7. write_svg()                stroke widths per class x depth falloff, grey with depth (Q6)
  8. bake()                     optional: 2D curves into the doc with per-object PlotWeight (Q6)

Requires hld_core.py exec'd into the same globals. Style dict STYLE mimics a
library/styles/*.json entry.
"""
import math
import random
import time
import Rhino
import System
from Rhino.Geometry import (Point3d, Vector3d, Plane, Transform, Brep, Curve, PolylineCurve, Polyline,
                            Point, Hatch, Line, LineCurve)
from Rhino.Geometry.Intersect import Intersection

doc = __rhino_doc__
D = Rhino.DocObjects
VIS = Rhino.Geometry.HiddenLineDrawingSegment.Visibility
ST = Rhino.Geometry.SilhouetteType

STYLE = {
    "page_mm": [420.0, 297.0], "margin_mm": 12.0,
    "classes": {                    # stroke width mm at depth 0, plot order
        "cut":      {"w": 0.70, "order": 50},   # outer outline of the union of all cut loops
        "cut_inner": {"w": 0.25, "order": 48},  # each material loop (layer boundaries)
        "outline":  {"w": 0.35, "order": 30},   # scene silhouettes / creases between front & back faces
        "edge":     {"w": 0.18, "order": 20},   # non-silhouette creases
        "boundary": {"w": 0.18, "order": 20},
        "tone":     {"w": 0.08, "order": 10},
        "cut_hatch": {"w": 0.08, "order": 45},
    },
    "depth": {"width_far": 0.45, "grey_far": 0.55, "gamma": 0.8},   # far lines thinner & greyer
    "sun": [-0.55, -0.35, 0.76],    # vector TOWARD the sun (from up-left-front)
    "tone": [                       # (max n.sun, PAPER spacing mm) darkest first
        [-0.35, 0.55], [0.05, 0.95], [0.25, 1.7]],
    "tone_min_world": 0.25,
    "tone_lift": 0.1,
    "zbuffer_tol": 0.003, "zbuffer_step_px": 4.0,
    "tone_min_mm": 0.4,             # thinning threshold
    "lod_min_mm": 1.2,              # cut loops smaller than this on paper: no inner outline / hatch
    "tone_min_face_area": 36.0,     # sq in; skip tiny faces (bricks)
    "tone_skip_layers": ["Ground"],
    "stipple": {"step": 0.0032, "near_p": 0.55, "far_p": 0.12, "dot_mm": 0.16},
    "cut_styles": {                 # per material layer: paper-space hatch (pattern, scale, rot)
        "Brick":      {"hatch": "Hatch1", "scale": 6.0, "rot": 45},   # Hatch1 = 0.125 units -> 0.75 mm
        "Insulation": {"hatch": "Hatch1", "scale": 4.0, "rot": 0},
        "Ground":     {"stipple": 0.9},
        "Concrete":   {"hatch": None},
    },
}


# ------------------------------------------------------------------ helpers
def _to_brep(g):
    if isinstance(g, Brep):
        return g
    if isinstance(g, Rhino.Geometry.Extrusion):
        return g.ToBrep()
    return None


def _layer_name(idx):
    try:
        return doc.Layers[idx].Name
    except Exception:
        return ""


def _poly(crv, tol=0.05):
    ok, pl = crv.TryGetPolyline()
    if ok:
        return list(pl)
    pc = crv.ToPolyline(tol, 0.05, 0.0, 0.0)
    return list(pc.ToPolyline()) if pc else [crv.PointAtStart, crv.PointAtEnd]


# ------------------------------------------------------------------ Q4 tone hatch
# FINDING: running tone-hatch CURVES through HiddenLineDrawing gives visibility transitions that
# are off by ~2-3 % of the camera distance for long receding curves near surfaces (ragged ends),
# and results differ between IncludeHiddenCurves on/off. A z-buffer test (ZBufferCapture) is
# deterministic, accurate to ~1 px and much faster, so tone lines + stipple use the z-buffer and
# HLD is used only for model edges / silhouettes.
def _face_loops(face):
    polys = []
    for lp in face.Loops:
        c = lp.To3dCurve()
        ok, pl = c.TryGetPolyline()
        if not ok:
            pc = c.ToPolyline(0.05, 0.05, 0.0, 0.0)
            pl = pc.ToPolyline() if pc else None
        if pl is not None:
            pts = list(pl)
            if pts[0].DistanceTo(pts[-1]) > 1e-9:
                pts.append(pts[0])
            polys.append(pts)
    return polys


def _scanlines(polys, o, u, p, spacing):
    """even-odd scanline fill of planar loops: yields (k, Point3d a, Point3d b) for lines parallel
    to u, spaced `spacing` along p (k = global line index, stable for thinning)."""
    edges = []
    amin, amax = 1e30, -1e30
    for poly in polys:
        q2 = [((q - o) * p, (q - o) * u) for q in poly]
        for i in range(len(q2) - 1):
            edges.append((q2[i], q2[i + 1]))
            amin = min(amin, q2[i][0]); amax = max(amax, q2[i][0])
    k0 = int(math.floor(amin / spacing))
    k1 = int(math.ceil(amax / spacing))
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


def tone_hatch_lines(items, style, mm_per_world=None, cam=None):
    """Returns list of (Point3d a, Point3d b, tag) world-space hatch segments on faces turned away
    from the sun. Tone levels are PAPER spacings (mm) converted at the face centroid; perspective
    compression below tone_min_mm is thinned by keeping every 2^m-th line."""
    sun = Vector3d(*style["sun"])
    sun.Unitize()
    eps = style.get("tone_lift", 0.1)
    levels = style["tone"]
    min_mm = style.get("tone_min_mm", 0.4)
    skip = set(style.get("tone_skip_layers", []))
    out = []
    n_faces = 0
    t0 = time.time()
    for geom, xf, tag in items:
        if tag.get("block") or _layer_name(tag["layer"]) in skip:
            continue
        b = _to_brep(geom)
        if b is None:
            continue
        b = b.DuplicateBrep()
        b.Transform(xf)
        for f in b.Faces:
            ok, fpl = f.TryGetPlane(0.01)
            if not ok:
                continue          # spike: planar faces only (curved faces -> contour approach)
            n = f.NormalAt(f.Domain(0).Mid, f.Domain(1).Mid)
            if f.OrientationIsReversed:
                n = -n
            d = n * sun
            spacing = None
            for lim, sp in levels:
                if d <= lim:
                    spacing = sp
                    break
            if spacing is None:
                continue
            polys = _face_loops(f)
            if not polys:
                continue
            if cam is not None and n * (cam - polys[0][0]) <= 0:
                continue          # back-facing: can never be seen
            bb = Rhino.Geometry.BoundingBox(polys[0])
            if bb.Diagonal.Length ** 2 / 2 < style["tone_min_face_area"]:
                continue
            ctr = bb.Center
            # vertical faces -> vertical lines; horizontal faces -> lines along world Y (the
            # depth axis, so they converge on the vanishing point like the reference drawing)
            ud = Vector3d.ZAxis if abs(n.Z) < 0.7 else Vector3d.YAxis
            ud = ud - n * (ud * n)
            if ud.Length < 1e-6:
                ud = Vector3d.XAxis
            ud.Unitize()
            pn = Vector3d.CrossProduct(n, ud)
            if mm_per_world is not None:
                k_ = mm_per_world(ctr, pn)
                if k_ <= 1e-9:
                    continue
                spacing = max(spacing / k_, style.get("tone_min_world", 0.25))
            lift = n * eps
            for k, a, bpt in _scanlines(polys, ctr, ud, pn, spacing):
                if mm_per_world is not None:
                    p_mm = spacing * mm_per_world((a + bpt) * 0.5, pn)
                    if p_mm < min_mm:
                        m = int(math.ceil(math.log(min_mm / max(p_mm, 1e-6), 2)))
                        if k % (2 ** m):
                            continue
                out.append((a + lift, bpt + lift, {"id": tag["id"], "layer": tag["layer"], "cls": "tone", "plane": fpl}))
            n_faces += 1
    return out, n_faces, time.time() - t0


class ZVis(object):
    """Visibility oracle from the viewport z-buffer (respects clipping planes)."""

    def __init__(self, vp, tol_rel=0.002, clip_planes=(), slack=0.3):
        self.vp = vp
        self.clips = list(clip_planes)   # DISPLAY convention: keep side = normal side
        self.slack = slack
        self.mesh = None
        self.n_rays = 0
        self.plane_tol = 0.15
        self.plane_tol_rel = 0.0015
        self.zb = Rhino.Display.ZBufferCapture(vp)
        for fn in ("ShowCurves", "ShowPoints", "ShowIsocurves", "ShowAnnotations", "ShowText", "ShowMeshWires", "ShowLights"):
            getattr(self.zb, fn)(False)
        self.W2S = vp.GetTransform(D.CoordinateSystem.World, D.CoordinateSystem.Screen)
        self.cam = vp.CameraLocation
        self.W, self.H = vp.Size.Width, vp.Size.Height
        self.tol = tol_rel
        self.n = 0

    def screen(self, p):
        s = Point3d(p)
        s.Transform(self.W2S)
        return s

    def vis(self, p, plane=None):
        s = self.screen(p)
        x, y = int(s.X), int(s.Y)
        if x < 0 or y < 0 or x >= self.W or y >= self.H:
            return False
        self.n += 1
        w = self.zb.WorldPointAt(x, y)
        if plane is not None:
            # surface-membership test: the z-buffer point at this pixel must lie on the hatch
            # line's own face plane (robust at grazing angles, rejects hidden parallel layers)
            # GOTCHA: ZBufferCapture depth precision is poor (near plane is auto-fit to the whole
            # scene; ~0.5-1 % of distance error) and SetViewProjection near/far is ignored -> scale
            # the tolerance with distance.
            r = abs(plane.DistanceTo(w))
            dist = w.DistanceTo(self.cam)
            if r <= self.plane_tol + self.plane_tol_rel * dist:
                return True
            if r > 0.03 * dist or self.mesh is None:
                return False
            return self.ray_vis(p)       # ambiguous band -> exact ray cast
        dz = w.DistanceTo(self.cam)
        # two-sided: the sample must lie ON the nearest surface (within tolerance), not merely in
        # front of it - otherwise anything in the clipped-away half space counts as visible.
        return abs(p.DistanceTo(self.cam) - dz) <= dz * self.tol + self.slack

    def set_scene_mesh(self, items):
        m = Rhino.Geometry.Mesh()
        mp = Rhino.Geometry.MeshingParameters.FastRenderMesh
        for geom, xf, tag in items:
            b = _to_brep(geom)
            if b is None:
                continue
            for part in Rhino.Geometry.Mesh.CreateFromBrep(b, mp) or []:
                part.Transform(xf)
                m.Append(part)
        self.mesh = m

    def ray_vis(self, p):
        self.n_rays += 1
        d = p - self.cam
        L = d.Length
        d.Unitize()
        t0 = 0.0
        for pl in self.clips:        # start the ray where it enters the kept half space
            dn = pl.Normal * d
            if abs(dn) > 1e-9:
                t = -pl.DistanceTo(self.cam) / dn
                if 0 < t < L:
                    t0 = max(t0, t)
        hit = Intersection.MeshRay(self.mesh, Rhino.Geometry.Ray3d(self.cam + d * t0, d))
        return hit < 0 or hit + t0 >= L - (self.plane_tol + 0.002 * L)

    def clip_to_planes(self, a, b):
        for pl in self.clips:
            da, db = pl.DistanceTo(a), pl.DistanceTo(b)
            if da < 0 and db < 0:
                return None
            if da < 0 or db < 0:
                t = da / (da - db)
                m = a + (b - a) * t
                a, b = (m, b) if da < 0 else (a, m)
        return a, b

    def clip_segment(self, a, b, step_px=3.0, plane=None, exact=False):
        ab = self.clip_to_planes(a, b)
        if ab is None:
            return []
        a, b = ab
        sa, sb = self.screen(a), self.screen(b)
        n = max(2, int(math.hypot(sb.X - sa.X, sb.Y - sa.Y) / step_px) + 1)
        P = lambda t: a + (b - a) * t
        test = (lambda p, pl: self.ray_vis(p)) if exact else self.vis
        flags = [test(P(i / float(n)), plane) for i in range(n + 1)]

        def refine(t_in, t_out, iters=4):
            # bisection between a visible and a hidden sample -> crisp line ends
            for _ in range(iters):
                tm = 0.5 * (t_in + t_out)
                if test(P(tm), plane):
                    t_in = tm
                else:
                    t_out = tm
            return t_in

        pieces, s = [], None
        for i, f in enumerate(flags):
            if f and s is None:
                s = 0.0 if i == 0 else refine(i / float(n), (i - 1) / float(n))
            if (not f or i == n) and s is not None:
                e = 1.0 if f else refine((i - 1) / float(n), i / float(n))
                if e > s:
                    pieces.append((P(s), P(e)))
                s = None
        return pieces

    def dispose(self):
        self.zb.Dispose()

def junction_lines(items, tol):
    """Intersection curves between interpenetrating / abutting solids (e.g. slab running into a
    wall). HLD only draws each object's own edges, so such junctions are otherwise missing."""
    breps = []
    for geom, xf, tag in items:
        if tag.get("block"):
            continue
        b = _to_brep(geom)
        if b is None:
            continue
        b = b.DuplicateBrep()
        b.Transform(xf)
        breps.append((b, b.GetBoundingBox(True), tag))
    out = []
    for i in range(len(breps)):
        bi, bbi, ti = breps[i]
        for j in range(i + 1, len(breps)):
            bj, bbj, tj = breps[j]
            ix = Rhino.Geometry.BoundingBox.Intersection(bbi, bbj)
            if not ix.IsValid:
                continue
            rc, crvs, pts = Intersection.BrepBrep(bi, bj, tol)
            if rc and crvs:
                for c in crvs:
                    out.append((c, ti))
    return out


# ------------------------------------------------------------------ Q5 stipple
def stipple_points(vp, ground_z, keep_fn, style, seed=7):
    """jittered grid in normalized SCREEN space -> back-project to ground plane."""
    rnd = random.Random(seed)
    st = style["stipple"]
    W, H = vp.Size.Width, vp.Size.Height
    step = st["step"]
    pts = []
    gp = Plane(Point3d(0, 0, ground_z), Vector3d.ZAxis)
    cam = vp.CameraLocation
    ny = int(1.0 / step)
    nx = int(1.0 / step * W / float(H))
    dists = []
    cand = []
    for j in range(ny):
        for i in range(nx):
            sx = (i + rnd.random()) / nx * W
            sy = (j + rnd.random()) / ny * H
            ok, ln = vp.GetFrustumLine(sx, sy)
            if not ok:
                continue
            rc, t = Intersection.LinePlane(ln, gp)
            if not rc:
                continue
            p = ln.PointAt(t)
            if not keep_fn(p):
                continue
            cand.append(p)
            dists.append(p.DistanceTo(cam))
    if not cand:
        return []
    lo, hi = min(dists), max(dists)
    for p, d in zip(cand, dists):
        k = (d - lo) / (hi - lo + 1e-9)
        prob = st["near_p"] + (st["far_p"] - st["near_p"]) * k
        if rnd.random() < prob:
            pts.append(p + Vector3d(0, 0, 0.05))
    return pts


# ------------------------------------------------------------------ cut loops (Q3)
def cut_loops(items, plane, tol):
    loops = []
    for geom, xf, tag in items:
        if tag.get("cls"):
            continue
        b = _to_brep(geom)
        if b is None:
            continue
        bb = b.GetBoundingBox(xf)
        # quick reject: does bbox straddle the plane?
        ds = [plane.DistanceTo(c) for c in bb.GetCorners()]
        if min(ds) > 0 or max(ds) < 0:
            continue
        bt = b.DuplicateBrep()
        bt.Transform(xf)
        rc, crvs, pts = Intersection.BrepPlane(bt, plane, tol)
        if not rc or not crvs:
            continue
        for c in Curve.JoinCurves(crvs, tol * 2):
            if c.IsClosed:
                loops.append((c, tag))
    return loops


# ------------------------------------------------------------------ main build
def build_drawing(doc, view, display_clip_plane, style=STYLE, tone=True, stipple=True, ground_keep=None):
    T = {}
    vp = view.ActiveViewport
    hld_plane = Plane(display_clip_plane)
    hld_plane.Flip()          # GOTCHA: HLD keeps the side OPPOSITE the normal; display keeps the normal side
    tol = doc.ModelAbsoluteTolerance

    t = time.time()
    items = collect_scene(doc)
    T["collect"] = time.time() - t

    # world -> hidden-line transform is only exposed on a computed HLD: run a trivial one first
    probe, _, _ = compute_hld(vp, [(Point(vp.CameraTarget), Transform.Identity, {})], [])
    W2H0 = probe.WorldToHiddenLine
    sz = vp.Size
    frame = []
    for sx, sy in ((0, 0), (sz.Width, 0), (sz.Width, sz.Height), (0, sz.Height)):
        ok, ln = vp.GetFrustumLine(sx, sy)
        q = Point3d(ln.PointAt(0.5))
        q.Transform(W2H0)
        frame.append((q.X, q.Y))
    dwg0 = {"frame": frame}
    _, s_page = page_mapping(dwg0, style)

    def mm_per_world(pt, d):
        a = Point3d(pt); b = pt + d
        a.Transform(W2H0); b.Transform(W2H0)
        return math.hypot(b.X - a.X, b.Y - a.Y) * s_page

    extra = []
    zv = ZVis(vp, style.get("zbuffer_tol", 0.002), [display_clip_plane], style.get("tone_lift", 0.1) * 3)
    t = time.time()
    zv.set_scene_mesh(items)
    T["scene_mesh"] = time.time() - t
    tone_lines = []
    if tone:
        th, nf, T["tone_gen"] = tone_hatch_lines(items, style, mm_per_world, vp.CameraLocation)
        T["tone_faces"] = nf
        T["tone_segments_3d"] = len(th)
        t = time.time()
        for a, b, tag in th:
            for pa, pb in zv.clip_segment(a, b, style.get("zbuffer_step_px", 3.0), tag["plane"]):
                tone_lines.append((pa, pb, tag))
        T["tone_zclip"] = time.time() - t
        T["tone_visible_pieces"] = len(tone_lines)
    junction = []
    if style.get("junction_lines", True):
        t = time.time()
        jl = junction_lines(items, tol)
        for crv, tag in jl:
            pl_ = _poly(crv, tol)
            for i in range(len(pl_) - 1):
                for pa, pb in zv.clip_segment(pl_[i], pl_[i + 1], 4.0, None, exact=True):
                    junction.append((pa, pb, tag))
        T["junction_curves"] = len(jl)
        T["junction"] = time.time() - t
    pts = []
    if stipple:
        t = time.time()
        cand = stipple_points(vp, 0.0, ground_keep or (lambda p: True), style)
        gpl = Plane(Point3d(0, 0, 0), Vector3d.ZAxis)
        pts = [p for p in cand if zv.vis(p, gpl)]
        T["stipple_gen"] = time.time() - t
        T["stipple_candidates"] = len(cand)
    T["zbuffer_samples"] = zv.n
    T["exact_rays"] = zv.n_rays
    zv.dispose()
    hld, T["hld_compute"], T["hld_added"] = compute_hld(vp, items + extra, [hld_plane], flatten=False)
    T["hld_items"] = len(items) + len(extra)
    W2H = hld.WorldToHiddenLine
    ok, H2W = W2H.TryGetInverse()
    cam = vp.CameraLocation

    t = time.time()
    lines = []        # dict(pts=[(x,y)], cls, depth, layer)
    n_frustum = 0
    for s in hld.Segments:
        if s.SegmentVisibility != VIS.Visible:
            continue
        crv = s.CurveGeometry
        if crv is None:
            continue
        pc = s.ParentCurve
        tag = pc.SourceObject.Tag if pc.SourceObject is not None else {}
        sil = pc.SilhouetteType
        mid = crv.PointAt(crv.Domain.Mid)
        w = Point3d(mid)
        w.Transform(H2W)
        depth = w.DistanceTo(cam)
        if tag.get("cls") == "tone":
            cls = "tone"
        elif sil == ST.SectionCut:
            if abs(display_clip_plane.DistanceTo(w)) > 10 * tol:
                n_frustum += 1      # cut produced by the view frustum, not our section plane
                continue
            continue                # real cut outlines are drawn from cut_loops (closed, fillable)
        elif s.IsSceneSilhouette or sil in (ST.Crease, ST.Projecting, ST.Tangent, ST.TangentProjects):
            cls = "outline"
        elif sil == ST.Boundary:
            cls = "boundary"
        else:
            cls = "edge"
        lines.append({"pts": [(p.X, p.Y) for p in _poly(crv)], "cls": cls, "depth": depth,
                      "layer": tag.get("layer", -1)})
    dots = []
    for hp in hld.Points:
        # GOTCHA: HiddenLineDrawingPoint.PointVisibility is a different enum type than
        # HiddenLineDrawingSegment.Visibility - comparing with VIS.Visible is always False.
        if str(hp.PointVisibility) == "Visible":
            # GOTCHA: HiddenLineDrawingPoint.Location is in WORLD coordinates (segments are in
            # hidden-line coordinates) -> transform with W2H for the 2D position.
            w = hp.Location
            q = Point3d(w)
            q.Transform(W2H)
            dots.append({"pt": (q.X, q.Y), "depth": w.DistanceTo(cam)})
    # z-buffer-clipped tone lines and stipple points -> hidden-line 2D space
    for pa, pb, tag in tone_lines + [(x[0], x[1], dict(x[2], cls="edge")) for x in junction]:
        qa, qb = Point3d(pa), Point3d(pb)
        qa.Transform(W2H)
        qb.Transform(W2H)
        lines.append({"pts": [(qa.X, qa.Y), (qb.X, qb.Y)], "cls": tag.get("cls", "tone"),
                      "depth": ((pa + pb) * 0.5).DistanceTo(cam), "layer": tag["layer"]})
    for p in pts:
        q = Point3d(p)
        q.Transform(W2H)
        dots.append({"pt": (q.X, q.Y), "depth": p.DistanceTo(cam)})
    T["classify"] = time.time() - t
    T["frustum_cut_segments_dropped"] = n_frustum

    # cut fills
    t = time.time()
    fills = []
    for c, tag in cut_loops(items, display_clip_plane, tol):
        pl = _poly(c, tol)
        p2 = []
        for p in pl:
            q = Point3d(p)
            q.Transform(W2H)
            p2.append((q.X, q.Y))
        fills.append({"pts": p2, "layer": tag["layer"], "lname": _layer_name(tag["layer"])})
    T["cut_loops"] = time.time() - t
    T["n_fills"] = len(fills)

    # depth normalisation
    ds = [l["depth"] for l in lines] + [d["depth"] for d in dots]
    lo, hi = (min(ds), max(ds)) if ds else (0, 1)
    for l in lines + dots:
        l["dn"] = (l["depth"] - lo) / (hi - lo + 1e-9)
    T["n_lines"] = len(lines)
    T["n_dots"] = len(dots)
    return {"lines": lines, "fills": fills, "dots": dots, "timing": T, "frame": frame}


# ------------------------------------------------------------------ 2D post: page mapping, hatches
def page_mapping(dwg, style=STYLE):
    xs, ys = [], []
    if dwg.get("frame"):            # crop to the viewport frame
        xs = [p[0] for p in dwg["frame"]]
        ys = [p[1] for p in dwg["frame"]]
    else:
        for f in dwg["fills"]:
            for x, y in f["pts"]:
                xs.append(x); ys.append(y)
        for l in dwg["lines"]:
            for x, y in l["pts"]:
                xs.append(x); ys.append(y)
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    pw, ph = style["page_mm"]
    m = style["margin_mm"]
    s = min((pw - 2 * m) / (x1 - x0), (ph - 2 * m) / (y1 - y0))
    ox = m + ((pw - 2 * m) - s * (x1 - x0)) / 2
    oy = m + ((ph - 2 * m) - s * (y1 - y0)) / 2

    def f(x, y):
        return (ox + (x - x0) * s, ph - (oy + (y - y0) * s))   # SVG y down
    return f, s


def _hatch_pattern_index(name):
    hp = doc.HatchPatterns.FindName(name)
    if hp is None and hasattr(D.HatchPattern.Defaults, name):
        doc.HatchPatterns.Add(getattr(D.HatchPattern.Defaults, name))
        hp = doc.HatchPatterns.FindName(name)
    return hp.Index if hp else -1


def paper_hatch(poly_mm, pattern, scale, rot_deg):
    """Hatch a closed page-space polygon with a Rhino pattern; returns list of line segments (mm)."""
    pts = [Point3d(x, y, 0) for x, y in poly_mm]
    if pts[0].DistanceTo(pts[-1]) > 1e-6:
        pts.append(pts[0])
    crv = PolylineCurve(pts)
    idx = _hatch_pattern_index(pattern)
    hs = Hatch.Create([crv], idx, math.radians(rot_deg), scale, 0.001)
    segs = []
    for h in hs or []:
        for piece in h.Explode():
            if isinstance(piece, Curve):
                segs.append([(piece.PointAtStart.X, piece.PointAtStart.Y), (piece.PointAtEnd.X, piece.PointAtEnd.Y)])
    return segs


def _pip(pt, poly):
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


def section_stipple(poly_mm, density_per_mm2, seed=3, page=(420.0, 297.0)):
    rnd = random.Random(seed)
    xs = [p[0] for p in poly_mm]
    ys = [p[1] for p in poly_mm]
    # clip the sampling box to the page: a cut loop (e.g. the ground) can project far off-page,
    # which previously generated millions of candidate dots (> 5 min hang)
    x0, x1 = max(min(xs), 0.0), min(max(xs), page[0])
    y0, y1 = max(min(ys), 0.0), min(max(ys), page[1])
    if x1 <= x0 or y1 <= y0:
        return []
    n = int((x1 - x0) * (y1 - y0) * density_per_mm2)
    out = []
    for _ in range(n):
        p = (rnd.uniform(x0, x1), rnd.uniform(y0, y1))
        if _pip(p, poly_mm):
            out.append(p)
    return out


# ------------------------------------------------------------------ Q6 SVG writer
def write_svg(dwg, path, style=STYLE):
    f, s = page_mapping(dwg, style)
    pw, ph = style["page_mm"]
    dep = style["depth"]
    C = style["classes"]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="0 0 %g %g">' % (pw, ph, pw, ph),
           '<rect x="0" y="0" width="%g" height="%g" fill="#FFFFFF"/>' % (pw, ph)]
    if dwg.get("frame"):
        fr = [f(x, y) for x, y in dwg["frame"]]
        out.append('<clipPath id="frame"><path d="M%s Z"/></clipPath><g clip-path="url(#frame)">' % " L".join("%.3f,%.3f" % p for p in fr))

    def grey(dn):
        g = int(255 * dep["grey_far"] * (dn ** dep["gamma"]))
        return "#%02X%02X%02X" % (g, g, g)

    def width(cls, dn):
        return C[cls]["w"] * (1.0 - (1.0 - dep["width_far"]) * dn)

    def pathd(pts):
        return "M" + " L".join("%.3f,%.3f" % f(x, y) for x, y in pts)

    # 1. projected lines (sorted by class order, then far -> near)
    groups = {}
    for l in sorted(dwg["lines"], key=lambda l: (C[l["cls"]]["order"], -l["dn"])):
        out.append('<path d="%s" fill="none" stroke="%s" stroke-width="%.3f" stroke-linecap="round"/>' % (
            pathd(l["pts"]), grey(l["dn"]), width(l["cls"], l["dn"])))
    # 2. stipple dots
    r = style["stipple"]["dot_mm"] / 2
    for d in dwg["dots"]:
        x, y = f(*d["pt"])
        out.append('<circle cx="%.3f" cy="%.3f" r="%.3f" fill="%s"/>' % (x, y, r * (1 - 0.4 * d["dn"]), grey(d["dn"] * 0.6)))
    # 3. cut fills (white) + paper hatch + outlines
    cs = style["cut_styles"]
    hatch_lines = []
    cut_dots = []
    for fl in dwg["fills"]:
        mm = [f(x, y) for x, y in fl["pts"]]
        out.append('<path d="M%s Z" fill="#FFFFFF" stroke="none"/>' % " L".join("%.3f,%.3f" % p for p in mm))
        st = cs.get(fl["lname"], {})
        xs_ = [p[0] for p in mm]; ys_ = [p[1] for p in mm]
        fl["small"] = min(max(xs_) - min(xs_), max(ys_) - min(ys_)) < style.get("lod_min_mm", 0)
        if st.get("hatch") and not fl["small"]:
            # hatch in a y-up frame then flip back (Rhino hatch is fine with either)
            hatch_lines += paper_hatch(mm, st["hatch"], st["scale"], st["rot"])
        if st.get("stipple"):
            cut_dots += section_stipple(mm, st["stipple"])
    for seg in hatch_lines:
        out.append('<path d="M%.3f,%.3f L%.3f,%.3f" stroke="#000000" stroke-width="%.3f" fill="none"/>' % (
            seg[0][0], seg[0][1], seg[1][0], seg[1][1], C["cut_hatch"]["w"]))
    for x, y in cut_dots:
        out.append('<circle cx="%.3f" cy="%.3f" r="%.3f" fill="#000000"/>' % (x, y, r))
    loops = []
    for fl in dwg["fills"]:
        mm = [f(x, y) for x, y in fl["pts"]]
        loops.append(PolylineCurve([Point3d(x, y, 0) for x, y in mm + [mm[0]]]))
        if fl.get("small"):
            continue   # paper-size LOD: tiny parts (bricks at 1/8") only contribute to the union outline
        out.append('<path d="M%s Z" fill="none" stroke="#000000" stroke-width="%.3f" stroke-linejoin="round"/>' % (
            " L".join("%.3f,%.3f" % p for p in mm), C["cut_inner"]["w"]))
    # heavy outline = boundary of the union of all cut loops (assembly outline, not every layer)
    t = time.time()
    union = Curve.CreateBooleanUnion(loops, 0.01) if loops else []
    t_union = time.time() - t
    for u in union or []:
        pts = _poly(u, 0.01)
        out.append('<path d="M%s Z" fill="none" stroke="#000000" stroke-width="%.3f" stroke-linejoin="round"/>' % (
            " L".join("%.3f,%.3f" % (p.X, p.Y) for p in pts), C["cut"]["w"]))
    if dwg.get("frame"):
        out.append("</g>")
    out.append("</svg>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    return {"svg_elements": len(out), "hatch_lines": len(hatch_lines), "cut_dots": len(cut_dots), "scale": s,
            "union_loops": len(union or []), "union_s": t_union}


# ------------------------------------------------------------------ Q6 bake into the Rhino doc
def bake(dwg, doc, origin=(5000.0, 0.0), style=STYLE, layer_root="MC Drawing"):
    """2D drawing as doc curves: one sublayer per line class (layer PlotWeight = class width) and
    per-object PlotWeight/PlotColor for depth falloff. Cut fills as Rhino Hatch objects."""
    f, s = page_mapping(dwg, style)
    ox, oy = origin
    C = style["classes"]
    dep = style["depth"]
    root = doc.Layers.FindByFullPath(layer_root, -1)
    if root < 0:
        L = D.Layer(); L.Name = layer_root
        root = doc.Layers.Add(L)
    lidx = {}
    for cls, cfg in list(C.items()) + [("fill", {"w": 0.0}), ("stipple", {"w": 0.0})]:
        full = layer_root + "::" + cls
        i = doc.Layers.FindByFullPath(full, -1)
        if i < 0:
            L = D.Layer(); L.Name = cls; L.ParentLayerId = doc.Layers[root].Id
            L.PlotWeight = cfg["w"]
            L.Color = System.Drawing.Color.Black
            L.PlotColor = System.Drawing.Color.Black
            i = doc.Layers.Add(L)
        lidx[cls] = i

    def P(x, y):
        X, Y = f(x, y)
        return Point3d(ox + X, oy + (style["page_mm"][1] - Y), 0)   # back to y-up, mm-as-model-units

    n = 0
    for l in dwg["lines"]:
        a = D.ObjectAttributes()
        a.LayerIndex = lidx[l["cls"]]
        a.PlotWeightSource = D.ObjectPlotWeightSource.PlotWeightFromObject
        a.PlotWeight = C[l["cls"]]["w"] * (1.0 - (1.0 - dep["width_far"]) * l["dn"])
        g = int(255 * dep["grey_far"] * (l["dn"] ** dep["gamma"]))
        a.PlotColorSource = D.ObjectPlotColorSource.PlotColorFromObject
        a.PlotColor = System.Drawing.Color.FromArgb(g, g, g)
        a.ColorSource = D.ObjectColorSource.ColorFromObject
        a.ObjectColor = a.PlotColor
        pts = [P(x, y) for x, y in l["pts"]]
        doc.Objects.AddCurve(PolylineCurve(pts) if len(pts) > 2 else LineCurve(pts[0], pts[-1]), a)
        n += 1
    solid = _hatch_pattern_index("Solid")
    for fl in dwg["fills"]:
        pts = [P(x, y) for x, y in fl["pts"]]
        if pts[0].DistanceTo(pts[-1]) > 1e-6:
            pts.append(pts[0])
        crv = PolylineCurve(pts)
        a = D.ObjectAttributes(); a.LayerIndex = lidx["fill"]
        a.ColorSource = D.ObjectColorSource.ColorFromObject
        a.ObjectColor = System.Drawing.Color.White
        a.PlotColorSource = D.ObjectPlotColorSource.PlotColorFromObject
        a.PlotColor = System.Drawing.Color.White
        for h in Hatch.Create([crv], solid, 0, 1, 0.001) or []:
            doc.Objects.AddHatch(h, a)
        a2 = D.ObjectAttributes(); a2.LayerIndex = lidx["cut"]
        doc.Objects.AddCurve(crv, a2)
        n += 1
    return n
