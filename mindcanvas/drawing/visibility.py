"""Visibility oracle for decoration lines and dots (tone, junctions, stipple).

The HLD is accurate for model edges but places visibility transitions of free
curves 2-3 % off, so decoration uses the viewport z-buffer: a sample is visible
when the z-buffer point at its pixel lies on the sample's own face plane.
GOTCHA: ZBufferCapture depth precision is poor (near plane auto-fit, ~0.5-1 % of
distance) and ignores SetViewProjection near/far; samples in the ambiguous band
fall back to an exact MeshRay against the scene mesh, started where the ray
enters the kept half-space of the clipping planes.
"""

import math

import Rhino
from Rhino.Geometry.Intersect import Intersection as X

G = Rhino.Geometry
D = Rhino.DocObjects


class ZVis(object):
    def __init__(self, vp, clips=(), inch=1.0):
        self.vp = vp
        self.clips = list(clips)          # display convention: keep the normal side
        self.zb = Rhino.Display.ZBufferCapture(vp)
        for fn in ("ShowCurves", "ShowPoints", "ShowIsocurves", "ShowAnnotations", "ShowText",
                   "ShowMeshWires", "ShowLights"):
            try:
                getattr(self.zb, fn)(False)
            except Exception:
                pass
        self.W2S = vp.GetTransform(D.CoordinateSystem.World, D.CoordinateSystem.Screen)
        ok, self.S2W = self.W2S.TryGetInverse()
        self.cam = vp.CameraLocation
        self.dir = vp.CameraDirection
        self.dir.Unitize()
        self.parallel = vp.IsParallelProjection
        self.W, self.H = vp.Size.Width, vp.Size.Height
        self.plane_tol = 0.15 * inch
        self.plane_tol_rel = 0.0015
        self.mesh = None
        self.mesh_fn = None
        self.n = 0
        self.n_rays = 0

    def dispose(self):
        try:
            self.zb.Dispose()
        except Exception:
            pass

    def screen(self, p):
        s = G.Point3d(p)
        s.Transform(self.W2S)
        return s

    def dist(self, p):
        return (p - self.cam) * self.dir if self.parallel else p.DistanceTo(self.cam)

    def world_at(self, sx, sy):
        x, y = int(sx), int(sy)
        if x < 0 or y < 0 or x >= self.W or y >= self.H:
            return None
        self.n += 1
        return self.zb.WorldPointAt(x, y)

    def ray(self, sx, sy):
        """World line through a (sub-pixel) screen point."""
        a = G.Point3d(sx, sy, 0.0)
        b = G.Point3d(sx, sy, 1.0)
        a.Transform(self.S2W)
        b.Transform(self.S2W)
        if a.DistanceTo(b) < 1e-12:
            ok, ln = self.vp.GetFrustumLine(sx, sy)
            return ln if ok else None
        return G.Line(a, b)

    def on_plane(self, w, plane):
        r = abs(plane.DistanceTo(w))
        return r <= self.plane_tol + self.plane_tol_rel * abs(self.dist(w)), r

    def vis(self, p, plane):
        s = self.screen(p)
        w = self.world_at(s.X, s.Y)
        if w is None:
            return False
        ok, r = self.on_plane(w, plane)
        if ok:
            return True
        if r > 0.03 * abs(self.dist(w)):
            return False
        return self.ray_vis(p)

    def _ensure_mesh(self):
        if self.mesh is None and self.mesh_fn is not None:
            self.mesh = self.mesh_fn()
            self.mesh_fn = None
        return self.mesh

    def ray_vis(self, p):
        mesh = self._ensure_mesh()
        if mesh is None:
            return False
        self.n_rays += 1
        if self.parallel:
            d = G.Vector3d(self.dir)
            L = (p - self.cam) * d
            start = p - d * L
        else:
            d = p - self.cam
            L = d.Length
            d.Unitize()
            start = self.cam
        t0 = 0.0
        for pl in self.clips:
            dn = pl.Normal * d
            if abs(dn) > 1e-12:
                t = -pl.DistanceTo(start) / dn
                if 0 < t < L:
                    t0 = max(t0, t)
        hit = X.MeshRay(mesh, G.Ray3d(start + d * t0, d))
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

    def clip_segment(self, a, b, plane, step_px=4.0, exact=False):
        """Visible pieces [(a, b)] of a world segment lying on `plane`."""
        ab = self.clip_to_planes(a, b)
        if ab is None:
            return []
        a, b = ab
        sa, sb = self.screen(a), self.screen(b)
        n = max(2, int(math.hypot(sb.X - sa.X, sb.Y - sa.Y) / step_px) + 1)
        n = min(n, 400)
        P = lambda t: a + (b - a) * t
        test = (lambda q: self.ray_vis(q)) if exact else (lambda q: self.vis(q, plane))
        flags = [test(P(i / float(n))) for i in range(n + 1)]

        def refine(t_in, t_out):
            for _ in range(4):
                tm = 0.5 * (t_in + t_out)
                if test(P(tm)):
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
