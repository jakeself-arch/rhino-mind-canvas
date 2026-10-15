"""Curtain-wall layout (model units).

The oriented driver (closed = clockwise, flip applied; exterior on the LEFT) is split at its
kinks into runs. Each run gets grid points by the grid mode, measured along the run (arcs are
divided by arc length); consecutive grid points make straight bays (arcs become faceted).
Grid points are vertices:

    start / end   open-curve ends: a jamb mullion whose outer face is on the end point
    inline        a mullion on the bisector of its two bays (straight runs and arc facets)
    corner        a kink turning more than corner_angle: an L-shaped corner mullion

Horizontals: sill (at the base), transoms, stack joints (unitized), head (at the top).
Rows are the spaces between consecutive horizontals, bottom -> top; cells are (bay, row).
"""

import math

import Rhino

from .. import geo, units

G = Rhino.Geometry


def _unit(v):
    v = G.Vector3d(v.X, v.Y, 0)
    v.Unitize()
    return v


def signed_turn(d_in, d_out):
    """Degrees from d_in to d_out about +Z (positive = left = concave on the exterior)."""
    cz = d_in.X * d_out.Y - d_in.Y * d_out.X
    dot = d_in.X * d_out.X + d_in.Y * d_out.Y
    return math.degrees(math.atan2(cz, dot))


class Vertex(object):
    def __init__(self, index, P, kink):
        self.index = index
        self.P = P
        self.kink = kink
        self.d_in = None
        self.d_out = None
        self.turn = 0.0
        self.kind = "inline"
        self.X = None           # mullion axis (inline / jambs)

    @property
    def Y(self):
        return G.Vector3d.CrossProduct(G.Vector3d.ZAxis, self.X)

    @property
    def convex(self):
        return self.turn < 0

    def __repr__(self):
        return "<V{} {} {:.1f}deg>".format(self.index, self.kind, self.turn)


class Bay(object):
    def __init__(self, index, va, vb):
        self.index = index
        self.va, self.vb = va, vb
        self.P0, self.P1 = va.P, vb.P
        d = self.P1 - self.P0
        d = G.Vector3d(d.X, d.Y, 0)
        self.c = d.Length
        d.Unitize()
        self.X = d
        self.Y = G.Vector3d.CrossProduct(G.Vector3d.ZAxis, d)

    def local(self, p):
        v = G.Point3d(p.X, p.Y, 0) - G.Point3d(self.P0.X, self.P0.Y, 0)
        return v * self.X, v * self.Y

    def world(self, u, y, z):
        p = self.P0 + self.X * u + self.Y * y
        return G.Point3d(p.X, p.Y, z)

    def frame(self, u=0.0, z=0.0):
        return G.Plane(self.world(u, 0.0, z), self.X, self.Y)

    def __repr__(self):
        return "<Bay {} {:.3f}>".format(self.index, self.c)


class Horizontal(object):
    def __init__(self, kind, z):
        self.kind = kind        # sill | transom | stack | head
        self.z = z              # nominal line: base, transom / stack centre, top

    def __repr__(self):
        return "<H {} {:.3f}>".format(self.kind, self.z)


def stations(L, mode, spacing, bays, min_last):
    """Positions (0..L) of the grid points along a run."""
    if L <= 1e-9:
        return [0.0]
    if mode == "equal" or (mode == "list" and not bays):
        n = max(1, int(math.ceil(L / spacing - 1e-6)))
        return [L * i / n for i in range(n + 1)]
    widths = bays if mode == "list" else [spacing]
    out, s, i = [0.0], 0.0, 0
    while True:
        w = widths[i % len(widths)]
        i += 1
        if w <= 1e-9:
            continue
        if s + w >= L - 1e-6:
            break
        s += w
        out.append(s)
    if len(out) > 1 and L - out[-1] < min_last:
        out.pop()           # a sliver: the last bay takes it
    out.append(L)
    return out


class Grid(object):
    def __init__(self, ctx, dims):
        self.ctx = ctx
        st = dims.st
        s = ctx.s
        crv = ctx.curve.DuplicateCurve()
        tol = ctx.tol
        self.closed = crv.IsClosed
        kinks = geo.kink_parameters(crv)
        if self.closed:
            seam = G.Vector3d.VectorAngle(crv.TangentAtStart, crv.TangentAtEnd) > 0.02
            if kinks and not seam:
                crv.ChangeClosedCurveSeam(kinks[0])
                kinks = geo.kink_parameters(crv)
        self.curve = crv
        Ltot = crv.GetLength()
        t0 = crv.Domain.T0
        bounds = [0.0] + sorted(crv.GetLength(G.Interval(t0, k)) for k in kinks) + [Ltot]
        mode = str(st.get("grid", "equal")).lower()
        spacing = units.parse_length(st.get("spacing", 60)) * s
        if spacing <= tol:
            raise ValueError("grid spacing must be positive")
        bays = [units.parse_length(b) * s for b in (st.get("bays") or [])]
        pos = []            # (station, kink)
        for a, b in zip(bounds, bounds[1:]):
            if b - a < tol:
                continue
            for i, r in enumerate(stations(b - a, mode, spacing, bays, 0.25 * spacing)):
                if pos and i == 0:
                    continue
                pos.append((a + r, i == 0 or a + r >= b - 1e-9))
        if self.closed:
            pos = pos[:-1]
            if not kinks and not seam:      # a smooth loop (circle): no corner at the seam
                pos[0] = (pos[0][0], False)
        self.vertices = []
        for i, (sv, kink) in enumerate(pos):
            P = crv.PointAtLength(min(sv, Ltot))
            self.vertices.append(Vertex(i, P, kink))
        n = len(self.vertices)
        if n < 2:
            raise ValueError("curtain wall curve too short")
        self.bays = []
        nb = n if self.closed else n - 1
        for i in range(nb):
            self.bays.append(Bay(i, self.vertices[i], self.vertices[(i + 1) % n]))
        ca = float(st.get("corner_angle", 25))
        for i, v in enumerate(self.vertices):
            bin_ = self.bays[i - 1] if (i > 0 or self.closed) else None
            bout = self.bays[i] if i < nb else None
            v.bay_in, v.bay_out = bin_, bout
            v.d_in = bin_.X if bin_ else None
            v.d_out = bout.X if bout else None
            if v.d_in is None:
                v.kind, v.X = "start", G.Vector3d(v.d_out)
            elif v.d_out is None:
                v.kind, v.X = "end", G.Vector3d(v.d_in)
            else:
                v.turn = signed_turn(v.d_in, v.d_out)
                if v.kink and abs(v.turn) > ca:
                    v.kind = "corner"
                else:
                    v.X = _unit(v.d_in + v.d_out)
        # horizontals
        self.base_z = ctx.base_z
        self.top_z = ctx.base_z + ctx.height
        hs = [Horizontal("sill", self.base_z)]
        lines = [("transom", z) for z in st.get("transoms") or []]
        if dims.style == "unitized":
            lines += [("stack", z) for z in st.get("stack") or []]
        wh = dims.tp["w"] * s
        seen = []
        for kind, z in sorted(lines, key=lambda kz: units.parse_length(kz[1])):
            zz = self.base_z + units.parse_length(z) * s
            if zz < self.base_z + 1.5 * wh or zz > self.top_z - 1.5 * wh:
                ctx.warn("A {} at {} is outside the curtain wall; skipped.".format(
                    kind, units.format_inches(units.parse_length(z))))
                continue
            if any(abs(zz - q) < 2 * wh for q in seen):
                ctx.warn("Two horizontals at {} are too close; one skipped.".format(
                    units.format_inches(units.parse_length(z))))
                continue
            seen.append(zz)
            hs.append(Horizontal(kind, zz))
        hs.append(Horizontal("head", self.top_z))
        self.horizontals = hs
        self.rows = list(zip(hs, hs[1:]))
        infill = st.get("infill") or {}
        self.row_types = [str(x).lower() for x in (infill.get("rows") or ["vision"])]
        self.cell_types = dict((str(k).replace(" ", ""), str(v).lower())
                               for k, v in (infill.get("cells") or {}).items())

    def infill(self, col, row):
        t = self.cell_types.get("{},{}".format(col, row))
        if t is None:
            t = self.row_types[min(row, len(self.row_types) - 1)]
        return t

    def cell_at(self, point):
        """(bay, row) of the cell nearest a world point, or None."""
        best = None
        for b in self.bays:
            u, y = b.local(point)
            uu = min(max(u, 0.0), b.c)
            d = math.hypot(u - uu, y)
            if best is None or d < best[0]:
                best = (d, b.index)
        if best is None:
            return None
        for r, (h0, h1) in enumerate(self.rows):
            if h0.z - 1e-9 <= point.Z <= h1.z + 1e-9:
                return best[1], r
        return best[1], (0 if point.Z < self.base_z else len(self.rows) - 1)
