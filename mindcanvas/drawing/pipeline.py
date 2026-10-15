"""MCDrawing pipeline: active view + its clipping planes + a scale style -> Drawing.

1. probe the HLD for WorldToHiddenLine; page scale = style scale at the cut plane
   (perspective: where the view axis meets the plane)
2. collect the scene (blocks exploded, clipped-away items dropped, parts smaller
   than min_part_mm on paper flagged small)
3. HLD for model edges (small parts skipped)
4. cut regions from BrepPlane; crop the page to the content
5. z-buffer: tone lines and ground stipple, limited to the page
6. material decoration of cuts, union outline, depth normalisation
Everything stays 3D world data until projected; each primitive carries depth.
"""

import math
import time

import Rhino

from .. import engine, meta, units
from . import cut, hld, junction, model2d, stipple, styles, tone, visibility
from . import scene as scenemod

G = Rhino.Geometry
D = Rhino.DocObjects
CLIP_KEY = "mc.clip"        # "cut" (default) | "depth" (limits depth, makes no poche)


class Cancelled(Exception):
    pass


class Cancel(object):
    """Esc check, throttled; only in interactive commands (it pumps messages)."""

    def __init__(self, interactive=False):
        self.interactive = interactive
        self.t = 0.0

    def check(self):
        if not self.interactive:
            return
        now = time.time()
        if now - self.t < 0.25:
            return
        self.t = now
        import scriptcontext
        if scriptcontext.escape_test(False):
            raise Cancelled("Drawing cancelled (Esc).")


def clip_planes(doc, vp):
    """[(plane, role)] of the clipping planes that clip this viewport."""
    out = []
    for o in doc.Objects.FindByObjectType(D.ObjectType.ClipPlane) or []:
        if o.IsDeleted or not o.Visible or not doc.Layers[o.Attributes.LayerIndex].IsVisible:
            continue        # hidden clipping planes do not clip
        g = o.ClippingPlaneGeometry
        if not getattr(g, "Enabled", True):
            continue
        if not any(i == vp.Id for i in g.ViewportIds()):
            continue
        out.append((G.Plane(g.Plane), o.Attributes.GetUserString(CLIP_KEY) or "cut"))
    out.sort(key=lambda pr: pr[1] != "cut")
    return out


def set_lod(doc, style, say=None):
    """Rebuild walls whose LOD differs from the style's. Returns the number rebuilt."""
    st = styles.get(style)
    n = 0
    for d in meta.all_drivers(doc, "wall"):
        if meta.params(d).get("lod", "detail") != st.lod:
            engine.update_params(doc, d, {"lod": st.lod})
            n += 1
    if say and n:
        say("Rebuilt {} wall(s) at {} LOD.".format(n, st.lod))
    return n


def _percentile(vals, q):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, max(0, int(q * (len(s) - 1))))]


def _bbox_add(bb, pts):
    for x, y in pts:
        if x < bb[0]:
            bb[0] = x
        if y < bb[1]:
            bb[1] = y
        if x > bb[2]:
            bb[2] = x
        if y > bb[3]:
            bb[3] = y


class _Proj(object):
    """World -> page-mm projection (before cropping) for one viewport."""

    def __init__(self, vp, W2H, k_ref, ref, inch):
        self.vp = vp
        self.inch = inch
        self.set(W2H, k_ref, ref)

    def set(self, W2H, k_ref, ref):
        self.W2H = W2H
        x = G.Vector3d(self.vp.CameraX)
        x.Unitize()
        a, b = self.hl(ref), self.hl(ref + x * self.inch)
        d_hl = math.hypot(b.X - a.X, b.Y - a.Y) / self.inch
        self.s = k_ref / d_hl if d_hl > 1e-12 else 1.0
        sz = self.vp.Size
        self.W, self.H = sz.Width, sz.Height
        self.frame = []
        for sx, sy in ((0, 0), (self.W, 0), (self.W, self.H), (0, self.H)):
            ok, ln = self.vp.GetFrustumLine(sx, sy)
            self.frame.append(self.page(ln.PointAt(0.5)))

    def hl(self, p):
        q = G.Point3d(p)
        q.Transform(self.W2H)
        return q

    def page(self, p):
        q = self.hl(p)
        return (q.X * self.s, q.Y * self.s)

    def mm_per(self, p, d):
        d = G.Vector3d(d)
        d.Unitize()
        a, b = self.hl(p), self.hl(p + d * self.inch)
        return math.hypot(b.X - a.X, b.Y - a.Y) * self.s / self.inch

    def screen_rect(self, box):
        """Page box -> screen pixel rect (page is affine in screen coordinates)."""
        f0, f1, f3 = self.frame[0], self.frame[1], self.frame[3]
        ax, ay = (f1[0] - f0[0]) / self.W, (f1[1] - f0[1]) / self.W
        bx, by = (f3[0] - f0[0]) / self.H, (f3[1] - f0[1]) / self.H
        det = ax * by - bx * ay
        if abs(det) < 1e-12:
            return (0, 0, self.W, self.H)
        xs, ys = [], []
        for px, py in ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])):
            dx, dy = px - f0[0], py - f0[1]
            xs.append((dx * by - dy * bx) / det)
            ys.append((ax * dy - ay * dx) / det)
        return (min(xs), min(ys), max(xs), max(ys))

    def mm_per_px(self):
        f0, f1 = self.frame[0], self.frame[1]
        return math.hypot(f1[0] - f0[0], f1[1] - f0[1]) / max(self.W, 1)


def make(doc, view=None, style=None, tone_on=None, stipple_on=None, say=None, interactive=False,
         window=None):
    """Build the 2D drawing of `view` (default: active view) at `style`'s scale.
    `window`: optional world points; the page is cropped to their projected box."""
    say = say or (lambda m: None)
    cancel = Cancel(interactive)
    T = {}
    t_all = time.time()
    st = styles.get(style)
    view = view or doc.Views.ActiveView
    vp = view.ActiveViewport
    tol = doc.ModelAbsoluteTolerance
    inch = units.inch_scale(doc)
    tone_on = st.tone.get("on", True) if tone_on is None else tone_on
    stipple_on = st.stipple.get("on", True) if stipple_on is None else stipple_on
    dwg = model2d.Drawing(st)
    dwg.title = "{} - {}".format(vp.Name, st.name)

    cps = clip_planes(doc, vp)
    planes = [p for p, r in cps]
    cut_planes = [p for p, r in cps if r != "depth"]
    cam = vp.CameraLocation
    cdir = G.Vector3d(vp.CameraDirection)
    cdir.Unitize()
    parallel = vp.IsParallelProjection
    depth = lambda p: (p - cam) * cdir

    # 1. scale reference: where the view axis meets the cut plane
    ref = vp.CameraTarget
    if cut_planes:
        pl = cut_planes[0]
        dn = pl.Normal * cdir
        if abs(dn) > 1e-9:
            t = ((pl.Origin - cam) * pl.Normal) / dn
            if t > 0:
                ref = cam + cdir * t
        if parallel:
            ref = pl.ClosestPoint(ref)
    k_ref = st.mm_per_unit(doc)
    d_ref = max(depth(ref), 1e-9)
    t = time.time()
    proj = _Proj(vp, hld.probe(vp, tol), k_ref, ref, inch)
    T["probe"] = time.time() - t

    def size_fn(bb):
        k = k_ref if parallel else k_ref * d_ref / max(depth(bb.Center), d_ref * 1e-3)
        return bb.Diagonal.Length * k

    # 2. scene
    t = time.time()
    sc = scenemod.Scene(doc)
    items = sc.collect(planes, size_fn, float(st.get("min_part_mm", 0.5)), visible=vp.IsVisible)
    for it in items:
        if not it.ground and st.material(it.material).get("ground"):
            it.flags = set(it.flags) | {"ground"}
            it.small = False
    vis_items = [it for it in items if not it.small]
    T["collect"] = time.time() - t
    say("MCDrawing: {} items ({} below {} mm skipped), {} clipping plane(s).".format(
        len(items), sc.stats["small"], st.get("min_part_mm"), len(planes)))
    cancel.check()

    # 3. hidden line drawing
    t = time.time()
    hidden = bool(st.get("hidden_lines", False))
    lines = []          # (pts, cls, depth, ground)
    if vis_items:
        H, added, T["hld_compute"] = hld.compute(vp, vis_items, planes, tol, hidden)
        if H is not None:
            proj.set(H.WorldToHiddenLine, k_ref, ref)
            s = proj.s
            split = float(st.depth.get("split_mm", 12))
            for pts, cls, d, idx in hld.segments(H, depth, s, split, hidden, tol):
                g = 0 <= idx < len(items) and items[idx].ground
                lines.append(([(x * s, y * s) for x, y in pts], cls, d, g))
        T["hld_items"] = added
    T["hld"] = time.time() - t
    say("MCDrawing: hidden lines {:.1f}s ({} segments).".format(T["hld"], len(lines)))
    cancel.check()

    # 4. cut regions
    t = time.time()
    regs, open_lines = [], []
    for pl in cut_planes:
        others = [p for p in planes if p is not pl]
        r, ol = cut.regions(sc, items, pl, others, tol, proj.page, st, cancel)
        regs += r
        open_lines += ol
    T["cut"] = time.time() - t

    # crop: content (minus ground) + a ground margin, inside the view frame
    fr = proj.frame
    frame_box = [min(p[0] for p in fr), min(p[1] for p in fr), max(p[0] for p in fr), max(p[1] for p in fr)]
    if window:
        wp = [proj.page(p) for p in window]
        frame_box = [max(frame_box[0], min(p[0] for p in wp)), max(frame_box[1], min(p[1] for p in wp)),
                     min(frame_box[2], max(p[0] for p in wp)), min(frame_box[3], max(p[1] for p in wp))]
    bb = [1e30, 1e30, -1e30, -1e30]
    for pts, cls, d, g in lines:
        if not g:
            _bbox_add(bb, pts)
    for r in regs:
        if not r.ground:
            _bbox_add(bb, [(r.bbox[0], r.bbox[1]), (r.bbox[2], r.bbox[3])])
    for pts, it in open_lines:
        if not it.ground:
            _bbox_add(bb, pts)
    if bb[0] > bb[2]:
        box = list(frame_box)
    else:
        gm = float(st.page.get("ground_margin_mm", 22))
        box = [max(bb[0] - gm, frame_box[0]), max(bb[1] - gm, frame_box[1]),
               min(bb[2] + gm, frame_box[2]), min(bb[3] + gm * 0.5, frame_box[3])]
    mx = st.page.get("max_mm", [1189, 841])
    if box[2] - box[0] > max(mx) or box[3] - box[1] > max(mx):
        dwg.warnings.append("Drawing is {:.0f} x {:.0f} mm at {} - zoom in or pick a smaller scale.".format(
            box[2] - box[0], box[3] - box[1], st.name))
    box = tuple(box)
    inbox = lambda pts: not (max(p[0] for p in pts) < box[0] or min(p[0] for p in pts) > box[2]
                             or max(p[1] for p in pts) < box[1] or min(p[1] for p in pts) > box[3])

    # 5. z-buffer decoration
    dots = []           # (x, y, depth)
    if tone_on or stipple_on or st.get("junction", {}).get("on"):
        t = time.time()
        zv = visibility.ZVis(vp, planes, inch)
        zv.mesh_fn = lambda: sc.scene_mesh(vis_items)
        view_info = {"cam": cam, "dir": cdir, "parallel": parallel, "x": vp.CameraX}
        try:
            if tone_on:
                segs, ts = tone.generate(sc, vis_items, st, proj.mm_per, view_info, cancel, inch)
                T["tone_gen"] = time.time() - t
                step = float(st.tone.get("step_px", 4))
                n_in = 0
                for a, b, plane in segs:
                    pa2, pb2 = proj.page(a), proj.page(b)
                    if not inbox((pa2, pb2)):
                        continue
                    n_in += 1
                    if n_in % 200 == 0:
                        cancel.check()
                    for pa, pb in zv.clip_segment(a, b, plane, step):
                        lines.append(([proj.page(pa), proj.page(pb)], "tone", depth((pa + pb) * 0.5), False))
                T["tone"] = time.time() - t
                T["tone_faces"] = ts["faces"]
                T["tone_lines_3d"] = ts["lines"]
                if ts["capped"]:
                    dwg.warnings.append("Tone capped at {} lines.".format(ts["lines"]))
                say("MCDrawing: tone {:.1f}s ({} faces).".format(T["tone"], ts["faces"]))
            if st.get("junction", {}).get("on"):
                t1 = time.time()
                jl, pairs = junction.lines(sc, vis_items, tol, int(st.get("junction", {}).get("max_pairs", 3000)), cancel)
                for pts, it in jl:
                    for i in range(len(pts) - 1):
                        for pa, pb in zv.clip_segment(pts[i], pts[i + 1], None, 4.0, exact=True):
                            lines.append(([proj.page(pa), proj.page(pb)], "junction", depth((pa + pb) * 0.5), False))
                T["junction"] = time.time() - t1
            if stipple_on:
                t1 = time.time()
                faces = stipple.ground_faces(sc, items, tol)
                pts, info = stipple.ground_dots(zv, faces, proj.screen_rect(box), proj.mm_per_px(), st.stipple, cancel)
                kept = stipple.keep_by_depth(pts, [depth(p) for p in pts], st.stipple)
                for p, d in kept:
                    x, y = proj.page(p)
                    if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                        dots.append((x, y, d))
                T["stipple"] = time.time() - t1
                T["stipple_candidates"] = info.get("candidates", 0)
                say("MCDrawing: stipple {:.1f}s ({} dots).".format(T["stipple"], len(dots)))
            T["zbuffer_samples"] = zv.n
            T["exact_rays"] = zv.n_rays
        finally:
            zv.dispose()

    # 6. cut decoration, outlines, ground lines
    t = time.time()
    T["cut_dots"] = cut.decorate(doc, regs, st, box, cancel)
    outlines, ust = cut.union_outlines([r for r in regs if not r.ground])
    T["union_clusters"] = ust["clusters"]
    if ust["failed"]:
        dwg.warnings.append("Outline union failed for {} cluster(s); drew their loops.".format(ust["failed"]))
    band = float(st.stipple.get("band_mm", 6.0))
    dens = float(st.stipple.get("cut_density", 2.4))
    for r in regs:
        if r.ground:
            dwg.ground.append((r.loops[0], []))
    for pts, it in open_lines:
        if it.ground:
            dwg.ground.append((pts, cut.ground_band(pts, band, dens, box) if stipple_on else []))
        else:
            dwg.cut_lines.append(pts)
    T["outline"] = time.time() - t

    # depth normalisation: 0 at the cut (or nearest), 1 at the far percentile
    ds = [d for _, c, d, _ in lines if c != "tone"] or [d for _, _, d, _ in lines] or [0.0]
    lo = d_ref if cut_planes else _percentile(ds, 0.02)
    hi = _percentile(ds, float(st.depth.get("far_percentile", 0.92)))
    if hi - lo < 1e-9:
        hi = lo + 1.0
    nd = lambda d: max(0.0, min(1.0, (d - lo) / (hi - lo)))
    dwg.lines = [(pts, cls, nd(d)) for pts, cls, d, g in lines if inbox(pts)]
    dwg.dots = [(x, y, nd(d)) for x, y, d in dots]
    dwg.regions = regs
    dwg.outlines = outlines

    # page: crop box + margin, origin bottom-left
    m = float(st.page.get("margin_mm", 8))
    dwg.translate(m - box[0], m - box[1])
    dwg.size = (box[2] - box[0] + 2 * m, box[3] - box[1] + 2 * m)
    dwg.clip = (m, m, dwg.size[0] - m, dwg.size[1] - m)
    T["total"] = time.time() - t_all
    dwg.timing = dict((k, round(v, 3) if isinstance(v, float) else v) for k, v in T.items())
    dwg.stats = dict(sc.stats)
    dwg.stats.update(dwg.summary())
    dwg.stats["scale"] = st.name
    dwg.stats["perspective"] = not parallel
    return dwg


def write(dwg, base_path, svg=True, png=True, px_per_mm=None):
    """Write <base>.svg and/or <base>.png. Returns the paths written."""
    from .writers import png as pngw
    from .writers import svg as svgw
    out = []
    if svg:
        out.append(svgw.write(dwg, base_path + ".svg"))
    if png:
        out.append(pngw.write(dwg, base_path + ".png", px_per_mm))
    return out
