"""3D curtain-wall parts from a Grid + the joint-style sections (model units).

Every member is a block instance. Block names read "MC CW <role> <dims> #<hash>": the hash is
taken over every number that shapes the geometry (section loops, length, end cuts), so
identical members share one definition and any change makes a new one.

Frames: verticals are placed in the mullion frame (X = mullion axis, Y = exterior, Z up) at
their bottom; horizontals and infill in the bay frame (X along the chord, Y exterior) at the
bay's first grid point. Section (a, q) inches -> local: vertical (u = a, y = yG - q),
horizontal (y = yG - q, z = a).
"""

import hashlib
import math

import Rhino

from .. import units
from ..components.base import Part
from . import sections as secs
from .settings import INFILLS

G = Rhino.Geometry


def _r(x):
    return round(x, 5)


def _hash(key):
    return hashlib.md5(repr(key).encode("utf-8")).hexdigest()[:10]


def _closed(pts3):
    pts = list(pts3)
    if pts[0].DistanceTo(pts[-1]) > 1e-12:
        pts.append(pts[0])
    return G.PolylineCurve(pts)


def _solid(b, tol):
    if b is None:
        return None
    if not b.IsSolid:
        b = b.CapPlanarHoles(tol) or b
    if b.IsSolid and b.SolidOrientation == G.BrepSolidOrientation.Inward:
        b.Flip()
    return b


def prism(loops3, vector, tol):
    """Planar region (first loop outline, others holes; 3D points) extruded by a vector."""
    curves = [_closed(lp) for lp in loops3]
    breps = G.Brep.CreatePlanarBreps(curves, tol)
    if not breps:
        return None
    path = G.LineCurve(G.Point3d(0, 0, 0), G.Point3d(vector.X, vector.Y, vector.Z))
    out = breps[0].Faces[0].CreateExtrusion(path, True)
    return _solid(out, tol)


class EndLine(object):
    """Vertical cut plane at a bay end, as a line in the bay's (u, y): u(y) = pu + (y - py) k."""

    def __init__(self, bay, point, direction):
        self.pu, self.py = bay.local(point)
        du, dy = direction * bay.X, direction * bay.Y
        if abs(dy) < 1e-9:
            dy = 1e-9
        self.k = du / dy

    def u(self, y):
        return self.pu + (y - self.py) * self.k

    @property
    def square(self):
        return abs(self.k) < 1e-7

    def key(self):
        return (_r(self.pu), _r(self.py), round(self.k, 7))


class BayEnd(object):
    """What a bay needs from the vertex at one of its ends."""

    def __init__(self, glass_u, struct, cover, miter):
        self.glass_u = glass_u      # u of the glass edge
        self.struct = struct        # EndLine for tubes, splines, gaskets, pans
        self.cover = cover          # EndLine for pressure plates and caps
        self.miter = miter          # EndLine on the vertex bisector (perimeter, safing)


def clip_halfplane(pts, o, n):
    """Keep the part of a 2D polygon with (p - o).n <= 0 (Sutherland-Hodgman)."""
    out = []
    m = len(pts)
    f = lambda p: (p[0] - o[0]) * n[0] + (p[1] - o[1]) * n[1]
    for i in range(m):
        a, b = pts[i], pts[(i + 1) % m]
        fa, fb = f(a), f(b)
        if fa <= 0:
            out.append(a)
        if (fa < 0 < fb) or (fb < 0 < fa):
            t = fa / (fa - fb)
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _line_x(p0, d0, p1, d1):
    """Intersection of two 2D lines (point, direction)."""
    den = d0[0] * d1[1] - d0[1] * d1[0]
    if abs(den) < 1e-12:
        return None
    t = ((p1[0] - p0[0]) * d1[1] - (p1[1] - p0[1]) * d1[0]) / den
    return (p0[0] + d0[0] * t, p0[1] + d0[1] * t)


class Builder(object):
    def __init__(self, ctx):
        self.ctx = ctx
        self.S = S = ctx.dims
        self.grid = ctx.grid
        self.s = ctx.s
        self.tol = ctx.tol
        self.lod = ctx.lod
        self.yG = ctx.yG
        self.parts = []
        self.vsec = dict((k, secs.vertical(S, k, self.lod)) for k in ("inline", "start", "end"))
        self.hsec = dict((k, secs.horizontal(S, k, self.lod)) for k in ("sill", "transom", "stack", "head"))
        self.wv = S.mp["w"] * self.s
        self.Dv = S.mp["D"] * self.s
        self.wh = S.tp["w"] * self.s
        v_style = S.v_style if S.v_style != "butt" else "captured"
        self.qt_v = S.q_tube(v_style, S.mp)
        self.qt_h = S.q_tube(S.h_style if S.h_style != "unit" else "split", S.tp)
        self.q_back = S.q_back()

    # -- coordinates ---------------------------------------------------------------
    def y(self, q):
        return self.yG - q * self.s

    def warn(self, msg):
        self.ctx.warn(msg)

    # -- parts -----------------------------------------------------------------------
    def emit(self, desc, key, make, plane, material, role, extra=None):
        name = "MC CW {} {} #{}".format(role, desc, _hash((role, material) + tuple(key)))
        doc = self.ctx.doc
        idef = doc.InstanceDefinitions.Find(name)
        if idef is None or idef.IsDeleted:
            try:
                geom = make()
            except Exception as ex:
                self.warn("Curtain wall: a '{}' failed ({}).".format(role, ex))
                return None
            if geom is None:
                self.warn("Curtain wall: a '{}' could not be built.".format(role))
                return None
            idx = self.ctx.block(name, [geom], material)
        else:
            idx = idef.Index
        xf = G.Transform.PlaneToPlane(G.Plane.WorldXY, plane)
        p = Part(material=material, role=role, block=idx, xform=xf, extra=dict(extra or {}))
        p.layer_name = "Curtain Wall"
        self.parts.append(p)
        return p

    def vprism(self, loops_uy, z0, z1, plane_origin, X, material, role, extra=None, desc=""):
        """Plan loops (local u, y; model units) extruded from z0 to z1 in a frame at
        plane_origin (X axis X)."""
        L = z1 - z0
        if L <= self.tol:
            return None
        key = (tuple(tuple((_r(u), _r(y)) for u, y in lp) for lp in loops_uy), _r(L))
        org = G.Point3d(plane_origin.X, plane_origin.Y, z0)
        plane = G.Plane(org, X, G.Vector3d.CrossProduct(G.Vector3d.ZAxis, X))
        tol = self.tol

        def make():
            loops3 = [[G.Point3d(u, y, 0) for u, y in lp] for lp in loops_uy]
            return prism(loops3, G.Vector3d(0, 0, L), tol)
        if extra is None:
            extra = {}
        return self.emit(desc or "L{}".format(units.format_inches(L / self.s)), key, make, plane, material,
                         role, extra)

    def hprism(self, bay, loops_yz, zc, endL, endR, material, role, extra=None, desc=""):
        """Section loops (local y, z rel. zc) swept along a bay between two end lines."""
        tol = self.tol
        ys = [y for lp in loops_yz for y, z in lp]
        uL = [endL.u(y) for y in ys]
        uR = [endR.u(y) for y in ys]
        if min(r - l for l, r in zip(uL, uR)) <= tol:
            return None
        key = (tuple(tuple((_r(y), _r(z)) for y, z in lp) for lp in loops_yz), endL.key(), endR.key())
        plane = bay.frame(0.0, zc)
        length = 0.5 * ((max(uR) + min(uR)) - (max(uL) + min(uL)))

        def make():
            if endL.square and endR.square:
                u0, u1 = uL[0], uR[0]
                loops3 = [[G.Point3d(u0, y, z) for y, z in lp] for lp in loops_yz]
                return prism(loops3, G.Vector3d(u1 - u0, 0, 0), tol)
            u0, u1 = min(uL) - 1.0, max(uR) + 1.0
            loops3 = [[G.Point3d(u0, y, z) for y, z in lp] for lp in loops_yz]
            b = prism(loops3, G.Vector3d(u1 - u0, 0, 0), tol)
            if b is None:
                return None
            for end, sgn in ((endL, -1.0), (endR, 1.0)):
                n = G.Vector3d(sgn * 1.0, -sgn * end.k, 0)
                n.Unitize()
                pl = G.Plane(G.Point3d(end.pu, end.py, 0), n)
                res = b.Trim(pl, tol)
                if not res:
                    return None
                b = _solid(res[0], tol)
            return b
        ex = dict(extra or {})
        if role in ("transom", "sill", "head", "stack_male", "stack_female", "starter_sill",
                    "head_receptor", "cap", "pressure_plate"):
            ex.setdefault("length", round(length / self.s, 3))
        return self.emit(desc or "L{}".format(units.format_inches(length / self.s)), key, make, plane,
                         material, role, ex)

    def box(self, bay, u0, u1, y0, y1, z0, z1, material, role, extra=None):
        """Box in a bay frame (block at the box's own corner, so equal boxes share a block)."""
        if u1 - u0 <= self.tol or abs(y1 - y0) <= self.tol or z1 - z0 <= self.tol:
            return None
        ya, yb = min(y0, y1), max(y0, y1)
        W, D, H = u1 - u0, yb - ya, z1 - z0
        key = (_r(W), _r(D), _r(H), _r(ya))
        plane = bay.frame(u0, z0)

        def make():
            return G.Box(G.Plane.WorldXY, G.Interval(0, W), G.Interval(ya, yb), G.Interval(0, H)).ToBrep()
        return self.emit("{}x{}".format(units.format_inches(W / self.s), units.format_inches(H / self.s)),
                         key, make, plane, material, role, extra)

    # -- section helpers ---------------------------------------------------------------------
    def loops_v(self, member, ca=0.0):
        """Vertical member loops in local (u, y), a shifted by ca (inches)."""
        s = self.s
        return [[((a + ca) * s, self.y(q)) for a, q in lp] for lp in member.loops]

    def loops_h(self, member):
        s = self.s
        return [[(self.y(q), a * s) for a, q in lp] for lp in member.loops]

    # -- vertical positions -------------------------------------------------------------------
    def vertical_segments(self):
        """z ranges of the verticals: full height, or unit by unit (unitized)."""
        g = self.grid
        if self.S.style != "unitized":
            return [(g.base_z, g.top_z)]
        s2 = 0.5 * self.S.split * self.s
        cs = [self.zc(h) for h in g.horizontals if h.kind in ("sill", "stack", "head")]
        return [(a + s2, b - s2) for a, b in zip(cs, cs[1:])]

    def zc(self, h):
        if h.kind == "sill":
            return h.z + 0.5 * self.wh
        if h.kind == "head":
            return h.z - 0.5 * self.wh
        return h.z

    def center(self, v):
        """(mullion centre point, axis, section) of a non-corner vertex."""
        S = self.S
        if v.kind == "start":
            return v.P + v.X * (0.5 * self.wv), v.X, self.vsec["start"]
        if v.kind == "end":
            return v.P - v.X * (0.5 * self.wv), v.X, self.vsec["end"]
        return v.P, v.X, self.vsec["inline"]

    def bay_end(self, bay, v, left):
        """BayEnd for bay at vertex v (left = v is the bay's first grid point)."""
        S, s = self.S, self.s
        ymid = self.yG - 0.5 * S.T * s
        if v.kind == "corner":
            return self._corner_end(bay, v, left)
        P, X, sec = self.center(v)
        Y = G.Vector3d.CrossProduct(G.Vector3d.ZAxis, X)
        sg = 1.0 if left else -1.0
        e = sec.edge_pos if left else sec.edge_neg
        if e is None:
            e = sg * sec.struct_half
        glass = EndLine(bay, P + X * (e * s), Y).u(ymid)
        struct = EndLine(bay, P + X * (sg * sec.struct_half * s), Y)
        cover = EndLine(bay, P + X * (sg * sec.cover_half * s), Y)
        if v.kind in ("start", "end"):
            miter = EndLine(bay, v.P, Y)
        else:
            miter = EndLine(bay, v.P, Y)
        return BayEnd(glass, struct, cover, miter)

    # -- corners -------------------------------------------------------------------------------
    def corner_geom(self, v):
        """Corner data: K (pocket-line intersection, world 2D) and the bisector direction."""
        if getattr(v, "_corner", None) is not None:
            return v._corner
        s = self.s
        a, b = v.bay_in, v.bay_out
        yK = self.y(self.qt_v)
        pa = a.world(0.0, yK, 0.0)
        pb = b.world(0.0, yK, 0.0)
        K = _line_x((pa.X, pa.Y), (a.X.X, a.X.Y), (pb.X, pb.Y), (b.X.X, b.X.Y))
        bis = a.Y + b.Y
        if bis.Length < 1e-9:
            bis = G.Vector3d(a.X)
        bis.Unitize()
        ext = self.wv / max(math.sin(math.radians(abs(v.turn))), 0.5)
        v._corner = {"K": K, "bis": bis, "yK": yK, "ext": 0.0 if v.convex else ext}
        return v._corner

    def _corner_end(self, bay, v, left):
        S, s = self.S, self.s
        c = self.corner_geom(v)
        K = G.Point3d(c["K"][0], c["K"][1], 0)
        uK, _ = bay.local(K)
        sg = 1.0 if left else -1.0
        D = self.Dv
        miter = EndLine(bay, v.P, c["bis"])
        legs = S.v_style != "butt"
        if S.v_style in ("captured", "split"):
            glass = uK + sg * (self.wv - S.bite * s)       # bears on the L's corner square
        else:
            yo, yi = self.yG, self.yG - S.T * s
            j = (S.j if S.v_style == "ssg" else S.jb) * s
            us = [miter.u(yo), miter.u(yi)]
            glass = (max(us) + 0.5 * j) if left else (min(us) - 0.5 * j)
        perp = bay.Y
        struct = EndLine(bay, bay.world(uK + sg * D, 0, 0), perp) if legs else miter
        if S.v_style in ("captured", "split"):
            cover = EndLine(bay, bay.world(uK + sg * self.wv, 0, 0), perp)
        else:
            cover = miter
        return BayEnd(glass, struct, cover, miter)

    def build_corner(self, v, z0, z1):
        S, s = self.S, self.s
        c = self.corner_geom(v)
        K = c["K"]
        P = v.P
        org = G.Point3d(P.X, P.Y, 0)
        Xw = G.Vector3d(1, 0, 0)
        loc = lambda p: (p.X - P.X, p.Y - P.Y)
        D, w = self.Dv, self.wv
        yK = c["yK"]
        legs = []
        if S.v_style != "butt":
            for bay, left in ((v.bay_in, False), (v.bay_out, True)):
                uK, _ = bay.local(G.Point3d(K[0], K[1], 0))
                if left:
                    u0, u1 = uK - c["ext"], uK + D
                else:
                    u0, u1 = uK - D, uK + c["ext"]
                legs.append([bay.world(u, yy, 0) for u, yy in ((u0, yK), (u1, yK), (u1, yK - w), (u0, yK - w))])
            # legs[0] ends at the corner on its interior corner [2], legs[1] starts at [3]
            tri = [G.Point3d(K[0], K[1], 0), legs[0][2], legs[1][3]]
            self._corner_tube(v, legs, tri, org, z0, z1)
        if self.lod == "schematic":
            return
        # per face: spline / web, gaskets, covers mitered on the bisector
        bis = c["bis"]
        for bay, left in ((v.bay_in, False), (v.bay_out, True)):
            sg = 1.0 if left else -1.0
            uK, _ = bay.local(G.Point3d(K[0], K[1], 0))
            ca = (uK + sg * 0.5 * w) / s          # inches: virtual mullion centre on the corner square
            # normal of the bisector line that points away from this bay (keep side <= 0)
            nx, ny = -bis.Y, bis.X
            mid = bay.world(0.5 * bay.c, 0, 0)
            if (mid.X - P.X) * nx + (mid.Y - P.Y) * ny > 0:
                nx, ny = -nx, -ny
            far = 4.0 * (D / s + S.cap_P + 4)

            def to_world(pts_aq, extend=False):
                out = []
                for a, q in pts_aq:
                    p = bay.world((ca + a) * s, self.y(q), 0)
                    out.append((p.X - P.X, p.Y - P.Y))
                return out
            if S.v_style in ("captured", "split"):
                hw = S.mp["w"] / 2
                e = hw - S.bite
                out_dir = sg        # a-direction away from the corner (glass side)
                members = []
                if S.v_style == "captured":
                    l = S.l
                    if not S.mp["solid"]:
                        members.append(("mullion", S.mp["material"],
                                        secs.rect(-l / 2, l / 2, 0.0, self.qt_v), False, False))
                    members.append(("isolator", S.iso_mat, secs.rect(-l / 2, l / 2, -S.g, 0.0), False, True))
                    hp = hw - S.cap_t - 1.0 / 32
                    members.append(("pressure_plate", S.material("pressure_plate"),
                                    secs.rect(out_dir * hp, -out_dir * far, -S.g - S.ppt, -S.g), True, False))
                    P_ = max(S.cap_P, S.g + S.ppt + S.cap_t + 1.0 / 16)
                    members.append(("cap", S.material("cap"),
                                    secs.rect(out_dir * hw, -out_dir * far, -P_, -P_ + S.cap_t), True, False))
                    members.append(("cap", S.material("cap"),
                                    secs.rect(out_dir * hw, out_dir * (hw - S.cap_t), -P_ + S.cap_t, -0.125),
                                    False, False))
                else:
                    members.append(("mullion", S.mp["material"],
                                    secs.rect(-0.125, 0.125, -S.g, self.qt_v), False, False))
                    members.append(("lip", S.mp["material"],
                                    secs.rect(out_dir * hw, -out_dir * far, -S.g - S.lip, -S.g), True, False))
                a0, a1 = out_dir * (e + 1.0 / 16), out_dir * (hw - 3.0 / 16)
                members.append(("gasket", S.gasket_mat, secs.rect(a0, a1, -S.g, 0.0), False, True))
                members.append(("gasket", S.gasket_mat, secs.rect(a0, a1, S.T, S.T + S.g), False, True))
                for role, mat, pts, miter, detail in members:
                    if detail and self.lod != "detail":
                        continue
                    poly = to_world(pts)
                    if miter:
                        poly = clip_halfplane(poly, (0.0, 0.0), (nx, ny))
                        if len(poly) < 3:
                            continue
                    self.vprism([poly], z0, z1, org, Xw, mat, "corner_" + role if role != "mullion" else
                                ("corner_spline" if S.v_style == "captured" else "corner_web"))
            elif self.lod == "detail" and S.v_style == "ssg":
                end = self._corner_end(bay, v, left)
                ge = end.glass_u / s
                for (a0, a1), role, mat in (((0.0, -S.sb), "structural_silicone", S.silicone),
                                            ((-S.sb, -S.sb - 0.25), "spacer_tape", S.tape_mat)):
                    pts = [(ge + sg * -a0, S.T), (ge + sg * -a1, S.T), (ge + sg * -a1, self.qt_v),
                           (ge + sg * -a0, self.qt_v)]
                    poly = []
                    for u_in, q in pts:
                        p = bay.world(u_in * s, self.y(q), 0)
                        poly.append((p.X - P.X, p.Y - P.Y))
                    self.vprism([poly], z0, z1, org, Xw, mat, role)
        # glass-to-glass corner joint (SSG / butt)
        if S.v_style in ("ssg", "butt") and self.lod == "detail":
            self._corner_seal(v, z0, z1, org, Xw)

    def _corner_tube(self, v, legs, tri, org, z0, z1):
        S, tol = self.S, self.tol
        P = v.P
        crvs = [_closed(lp) for lp in legs]
        tri_c = _closed(tri)
        try:
            u = G.Curve.CreateBooleanUnion(crvs + [tri_c], tol)
        except Exception:
            u = None
        if not u or len(u) != 1:
            u = G.Curve.CreateBooleanUnion(crvs, tol)
        if not u:
            self.warn("Corner mullion outline failed; two legs used.")
            outlines = crvs
        else:
            outlines = list(u)
        loops = []
        for crv in outlines:
            ok, pl = crv.TryGetPolyline()
            if not ok:
                continue
            pts = [(p.X - P.X, p.Y - P.Y) for p in list(pl)[:-1]]
            lp = [pts]
            if not S.mp["solid"] and self.lod != "schematic":
                inner = self._inset(crv, S.mp["t"] * self.s)
                if inner is not None:
                    lp.append([(p.X - P.X, p.Y - P.Y) for p in list(inner)[:-1]])
            loops.append(lp)
        for lp in loops:
            self.vprism(lp, z0, z1, org, G.Vector3d(1, 0, 0), S.mp["material"], "corner_mullion",
                        {"length": round((z1 - z0) / self.s, 3)})

    def _inset(self, crv, t):
        pl = G.Plane.WorldXY
        area = G.AreaMassProperties.Compute(crv).Area
        for d in (t, -t):
            res = crv.Offset(pl, d, self.tol, G.CurveOffsetCornerStyle.Sharp)
            if res and len(res) == 1 and res[0].IsClosed:
                a = G.AreaMassProperties.Compute(res[0])
                if a is not None and a.Area < area:
                    ok, poly = res[0].TryGetPolyline()
                    if ok:
                        return poly
        return None

    def _corner_seal(self, v, z0, z1, org, Xw):
        S, s = self.S, self.s
        P = v.P
        a, b = v.bay_in, v.bay_out
        ea = self._corner_end(a, v, False).glass_u
        eb = self._corner_end(b, v, True).glass_u
        yo, yi = self.yG, self.yG - S.T * s
        def x2(p0, d0, p1, d1):
            return _line_x((p0.X, p0.Y), (d0.X, d0.Y), (p1.X, p1.Y), (d1.X, d1.Y))
        outer_x = x2(a.world(0, yo, 0), a.X, b.world(0, yo, 0), b.X)
        inner_x = x2(a.world(0, yi, 0), a.X, b.world(0, yi, 0), b.X)
        if outer_x is None or inner_x is None:
            return
        pts = [a.world(ea, yo, 0), G.Point3d(outer_x[0], outer_x[1], 0), b.world(eb, yo, 0),
               b.world(eb, yi, 0), G.Point3d(inner_x[0], inner_x[1], 0), a.world(ea, yi, 0)]
        poly = [(p.X - P.X, p.Y - P.Y) for p in pts]
        self.vprism([poly], z0, z1, org, Xw, S.sealant, "corner_seal")

    # -- build ----------------------------------------------------------------------------------
    def run(self):
        g, S = self.grid, self.S
        segs = self.vertical_segments()
        self.ends = {}
        for b in g.bays:
            self.ends[(b.index, 0)] = self.bay_end(b, b.va, True)
            self.ends[(b.index, 1)] = self.bay_end(b, b.vb, False)
        self._openings()
        for v in g.vertices:
            for z0, z1 in segs:
                if v.kind == "corner":
                    self.build_corner(v, z0, z1)
                else:
                    self.build_vertical(v, z0, z1)
        for b in g.bays:
            self.build_bay(b)
        if self.lod == "detail":
            self.perimeter()
            self.anchors()
        for op in getattr(self.ctx, "openings", None) or []:
            from ..openings import units as opening_units
            for p in opening_units.build(self.ctx, op):
                p.layer_name = "Opening"
                self.parts.append(p)
        return self.parts

    def build_vertical(self, v, z0, z1):
        P, X, sec = self.center(v)
        for m in sec.for_lod(self.lod):
            extra = {}
            role = m.role
            if role.startswith("mullion"):
                extra["length"] = round((z1 - z0) / self.s, 3)
            if role == "cap":
                extra["length"] = round((z1 - z0) / self.s, 3)
            self.vprism(self.loops_v(m), z0, z1, P, X, m.material, role, extra)

    def bay_horizontals(self, b):
        hs = self.op_h.get(b.index)
        return hs if hs is not None else self.grid.bay_hs[b.index]

    def build_bay(self, b):
        S, s = self.S, self.s
        eL, eR = self.ends[(b.index, 0)], self.ends[(b.index, 1)]
        hs = self.bay_horizontals(b)
        for h in hs:
            if getattr(h, "skip", False):
                continue
            sec = self.hsec[h.kind]
            zc = self.zc(h)
            for m in sec.for_lod(self.lod):
                ends = (eL.cover, eR.cover) if m.cover else (eL.struct, eR.struct)
                self.hprism(b, self.loops_h(m), zc, ends[0], ends[1], m.material, m.role)
        # cells
        for r, (h0, h1) in enumerate(zip(hs, hs[1:])):
            if getattr(h0, "door", False):
                continue
            row = self.grid_row(b, h0, h1)
            kind = self.grid.infill(b.index, row)
            if kind not in INFILLS:
                self.warn("Unknown infill '{}'; vision used.".format(kind))
                kind = "vision"
            z0 = self.zc(h0) + self.hsec[h0.kind].edge_pos * s
            z1 = self.zc(h1) + self.hsec[h1.kind].edge_neg * s
            self.cell(b, row, kind, eL, eR, h0, h1, z0, z1)

    def grid_row(self, b, h0, h1):
        """Row (in the bay's own grid rows) of a space between two of its horizontals."""
        zm = 0.5 * (h0.z + h1.z)
        for r, (a, c) in enumerate(self.grid.bay_rows(b)):
            if a.z - 1e-9 <= zm <= c.z + 1e-9:
                return r
        return 0

    # -- infill ----------------------------------------------------------------------------------
    def cell(self, b, row, kind, eL, eR, h0, h1, z0, z1):
        S, s = self.S, self.s
        u0, u1 = eL.glass_u, eR.glass_u
        if u1 - u0 <= self.tol or z1 - z0 <= self.tol:
            self.warn("Bay {} row {} is too small for glass.".format(b.index, row))
            return
        info = {"panel": kind, "cell": "{},{}".format(b.index, row)}
        area = round((u1 - u0) * (z1 - z0) / (s * s), 2)
        yG = self.yG
        if kind == "spandrel" and str(S.st["spandrel"].get("panel", "glass")).lower() == "metal":
            self.metal_panel(b, u0, u1, z0, z1, dict(info, area=area))
        else:
            mat = S.st["spandrel"].get("material", "Spandrel Glass") if kind == "spandrel" else S.glass_mat
            self.igu(b, u0, u1, z0, z1, mat, dict(info, area=area))
        if kind in ("spandrel", "shadow_box") and self.lod != "schematic":
            self.back_pan(b, kind, eL, eR, h0, h1)
        if self.lod == "detail" and self.hsec[h0.kind].setting is not None:
            sec = self.hsec[h0.kind]
            za = self.zc(h0) + sec.setting * s
            zb = z0
            if zb - za > self.tol:
                Lb = units.parse_length(S.st["setting_blocks"].get("length", 4)) * s
                W = u1 - u0
                for uc in (u0 + 0.25 * W, u1 - 0.25 * W):
                    self.box(b, uc - 0.5 * Lb, uc + 0.5 * Lb, yG - S.T * s, yG, za, zb,
                             S.st["setting_blocks"].get("material", "Setting Block"), "setting_block")

    def igu(self, b, u0, u1, z0, z1, material, extra):
        S, s = self.S, self.s
        yG = self.yG
        T = S.T * s
        role = "glass" if material == S.glass_mat else "spandrel_glass"
        if self.lod != "detail" or S.lites == 1:
            self.box(b, u0, u1, yG - T, yG, z0, z1, material, role, dict(extra, lites=S.lites))
            return
        y = yG
        tg, sp = S.glass * s, S.space * s
        sw, ins = 0.375 * s, (1.0 / 16) * s
        for i in range(S.lites):
            ex = dict(extra, lite=i + 1) if i == 0 else {"lite": i + 1, "cell": extra["cell"]}
            self.box(b, u0, u1, y - tg, y, z0, z1, material, role, ex)
            y -= tg
            if i < S.lites - 1:
                a_, c_ = y - sp, y
                xa, xb, za, zb = u0 + ins, u1 - ins, z0 + ins, z1 - ins
                sm = S.spacer_mat
                self.box(b, xa, xb, a_, c_, zb - sw, zb, sm, "spacer")
                self.box(b, xa, xb, a_, c_, za, za + sw, sm, "spacer")
                self.box(b, xa, xa + sw, a_, c_, za + sw, zb - sw, sm, "spacer")
                self.box(b, xb - sw, xb, a_, c_, za + sw, zb - sw, sm, "spacer")
                y -= sp

    def metal_panel(self, b, u0, u1, z0, z1, extra):
        S, s = self.S, self.s
        sp = S.st["spandrel"]
        yG, T = self.yG, S.T * s
        if self.lod != "detail":
            self.box(b, u0, u1, yG - T, yG, z0, z1, sp.get("metal", "Metal Panel"), "panel", extra)
            return
        sk = units.parse_length(sp.get("skin", "1/16")) * s
        self.box(b, u0, u1, yG - sk, yG, z0, z1, sp.get("metal", "Metal Panel"), "panel", extra)
        self.box(b, u0, u1, yG - T + sk, yG - sk, z0, z1, sp.get("core", "Panel Core"), "panel_core")
        self.box(b, u0, u1, yG - T, yG - T + sk, z0, z1, sp.get("metal", "Metal Panel"), "panel_skin")

    def back_pan(self, b, kind, eL, eR, h0, h1):
        S, s = self.S, self.s
        L = units.parse_length
        hb0, hb1 = self.hsec[h0.kind], self.hsec[h1.kind]
        za = self.zc(h0) + hb0.struct_half * s
        zb = self.zc(h1) - hb1.struct_half * s
        qb = self.q_back
        if kind == "spandrel":
            sp = S.st["spandrel"]
            bp = L(sp.get("back_pan_t", "1/32"))
            q_ins = S.T + L(sp.get("air", 1))
            ins = L(sp.get("insulation", 3))
            if q_ins + ins + bp > qb:
                ins = max(0.0, qb - bp - q_ins)
            q_pan = q_ins + ins
            ins_mat = sp.get("insulation_material", "Mineral Wool Board")
            pan_mat = sp.get("back_pan", "Back Pan")
        else:
            sb = S.st["shadow_box"]
            bp = L(sb.get("back_pan_t", "1/32"))
            ins = L(sb.get("insulation", 2))
            q_ins = qb - ins
            q_pan = q_ins - bp
            ins_mat = sb.get("insulation_material", "Mineral Wool Board")
            pan_mat = sb.get("back_pan", "Shadow Box Pan")
        clr = (1.0 / 8) * s
        if ins > 0:
            y0, y1 = self.y(q_ins + ins), self.y(q_ins)
            ym = 0.5 * (y0 + y1)
            self.box(b, eL.struct.u(ym) + clr, eR.struct.u(ym) - clr, y0, y1, za, zb, ins_mat, "insulation")
        y0, y1 = self.y(q_pan + bp), self.y(q_pan)
        ym = 0.5 * (y0 + y1)
        self.box(b, eL.struct.u(ym), eR.struct.u(ym), y0, y1, za, zb, pan_mat, "back_pan")

    # -- perimeter + anchors -----------------------------------------------------------------------
    def perimeter(self):
        S, s, g = self.S, self.s, self.grid
        pr = S.st["perimeter"]
        pj = units.parse_length(pr.get("joint", "1/2")) * s
        seal, back = pr.get("sealant", "Sealant"), pr.get("backer", "Backer Rod")
        qt, qb = self.qt_h, self.q_back
        r = 0.45 * pj
        for b in g.bays:
            eL, eR = self.ends[(b.index, 0)].miter, self.ends[(b.index, 1)].miter
            for zj, up in ((g.base_z - pj, False), (g.top_z, True)):
                bead = lambda q0, q1: [[(self.y(q0), zj), (self.y(q1), zj), (self.y(q1), zj + pj),
                                        (self.y(q0), zj + pj)]]
                zc = zj + 0.5 * pj
                self.hprism(b, bead(qt, qt + 0.5), 0.0, eL, eR, seal, "perimeter_sealant")
                self.hprism(b, bead(qb - 0.5, qb), 0.0, eL, eR, seal, "perimeter_sealant")
                circ = [[(self.y(qt + 0.5) - r * (1 + math.cos(2 * math.pi * i / 16)) - 0.02 * s,
                          zc + r * math.sin(2 * math.pi * i / 16)) for i in range(16)]]
                self.hprism(b, circ, 0.0, eL, eR, back, "backer_rod")
        for v in g.vertices:
            if v.kind not in ("start", "end"):
                continue
            sg = -1.0 if v.kind == "start" else 1.0
            X = v.X
            u0, u1 = sorted((0.0, sg * pj))
            loops = lambda q0, q1: [[(u0, self.y(q0)), (u1, self.y(q0)), (u1, self.y(q1)), (u0, self.y(q1))]]
            qv = self.qt_v
            self.vprism(loops(qv, qv + 0.5), g.base_z, g.top_z, v.P, X, seal, "perimeter_sealant")
            self.vprism(loops(qb - 0.5, qb), g.base_z, g.top_z, v.P, X, seal, "perimeter_sealant")
            uc = 0.5 * (u0 + u1)
            circ = [[(uc + r * math.cos(2 * math.pi * i / 16),
                      self.y(qv + 0.5) - r * (1 + math.sin(2 * math.pi * i / 16)) - 0.02 * s) for i in range(16)]]
            self.vprism(circ, g.base_z, g.top_z, v.P, X, back, "backer_rod")

    def anchors(self):
        S, s, g = self.S, self.s, self.grid
        slabs = [g.base_z + units.parse_length(z) * s for z in (S.st.get("slabs") or [])]
        if not slabs:
            return
        an = S.st["anchors"]
        L = units.parse_length
        ta, leg, hgt = L(an.get("t", "3/8")) * s, L(an.get("leg", 4)) * s, L(an.get("height", 5)) * s
        gap, slab_t = L(an.get("slab_gap", "1-1/2")), L(an.get("slab_thickness", 8)) * s
        mat = an.get("material", "Steel Angle")
        qb = self.q_back
        for zs in slabs:
            if not (g.base_z <= zs <= g.top_z):
                self.warn("A slab at {} is outside the curtain wall; no anchors.".format(
                    units.format_inches((zs - g.base_z) / s)))
                continue
            for v in g.vertices:
                if v.kind == "corner" or (v.kind == "inline" and S.v_style == "butt"):
                    continue
                P, X, sec = self.center(v)
                hw = 0.5 * self.wv
                ya, yb = self.y(qb - 2.0), self.y(qb + gap + L(an.get("leg", 4)))
                yc = self.y(qb + gap)
                for sg in (-1.0, 1.0):
                    ua, ub = sorted((sg * hw, sg * (hw + ta)))
                    plate = [[(ua, ya), (ub, ya), (ub, yb), (ua, yb)]]
                    self.vprism(plate, zs, zs + hgt, P, X, mat, "anchor")
                    ua, ub = sorted((sg * (hw + ta), sg * (hw + leg)))
                    foot = [[(ua, yc), (ub, yc), (ub, yb), (ua, yb)]]
                    self.vprism(foot, zs, zs + ta, P, X, mat, "anchor")
            for b in g.bays:
                eL, eR = self.ends[(b.index, 0)], self.ends[(b.index, 1)]
                y0, y1 = self.y(qb + gap), self.y(qb)
                sec = [[(y0, -slab_t), (y1, -slab_t), (y1, 0.0), (y0, 0.0)]]
                self.hprism(b, sec, zs, eL.miter, eR.miter, an.get("safing", "Fire Safing"), "fire_safing")
                sm = [[(y0, 0.0), (y1, 0.0), (y1, 0.25 * s), (y0, 0.25 * s)]]
                # smoke seal between the anchors
                inset = lambda e, sg: EndLineOffset(e.struct, sg * (ta + 0.0625 * s))
                self.hprism(b, sm, zs, inset(eL, 1.0), inset(eR, -1.0), an.get("smoke_seal", "Sealant"),
                            "smoke_seal")

    # -- openings (doors in a bay) ------------------------------------------------------------------
    def _openings(self):
        """A hosted opening takes over the lower part of its bay: the unit fills the clear width
        between the verticals, a transom goes over its head, there is no sill under a door and
        no infill below the head."""
        self.op_h = {}
        from .grid import Horizontal
        g = self.grid
        for op in getattr(self.ctx, "openings", None) or []:
            hit = g.cell_at(op.plane.Origin)
            if hit is None:
                continue
            b = g.bays[hit[0]]
            if b.index in self.op_h:
                self.warn("Only one opening per curtain wall bay; '{}' skipped.".format(op.name))
                self.ctx.openings.remove(op)
                continue
            head = op.rz1 + 0.5 * self.wh
            if head > g.top_z - 2.0 * self.wh:
                self.warn("Opening '{}' is too tall for its curtain wall.".format(op.name))
            sill = Horizontal("sill", g.base_z)
            sill.door = True                # the row below the head transom is the opening
            sill.skip = op.door             # doors run to the floor
            hs = [sill, Horizontal("transom", head)]
            hs += [h for h in g.bay_hs[b.index][1:] if h.kind == "head" or h.z >= head + 1.5 * self.wh]
            self.op_h[b.index] = hs
            eL, eR = self.ends[(b.index, 0)], self.ends[(b.index, 1)]
            ym = 0.5 * (op.y_ext + op.y_int)
            u0, u1 = eL.struct.u(ym), eR.struct.u(ym)
            op.W = (u1 - u0) - 2 * op.shim
            op.rx = 0.5 * op.W + op.shim
            op.plane = b.frame(0.5 * (u0 + u1), 0.0)
            op.cw_bay = b.index
            # frame face on the glass line, not on the caps
            D = op.y_fe - op.y_fi
            op.y_fe = min(self.yG, op.y_ext)
            op.y_fi = max(op.y_fe - D, op.y_int)


class EndLineOffset(object):
    """An EndLine shifted along u."""

    def __init__(self, base, du):
        self.base, self.du = base, du
        self.k = base.k
        self.pu, self.py = base.pu + du, base.py

    def u(self, y):
        return self.base.u(y) + self.du

    @property
    def square(self):
        return self.base.square

    def key(self):
        return (_r(self.pu), _r(self.py), round(self.k, 7))


