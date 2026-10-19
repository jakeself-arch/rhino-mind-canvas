"""Curtain-wall layout (model units).

The oriented driver (closed = clockwise, flip applied; exterior on the LEFT) is split at its
kinks into runs. Each run gets grid points by the grid mode, measured along the run (arcs are
divided by arc length); consecutive grid points make straight bays (arcs become faceted).
Grid points are vertices:

    start / end   open-curve ends: a jamb mullion whose outer face is on the end point
    inline        a mullion on the bisector of its two bays (straight runs and arc facets)
    corner        a kink turning more than corner_angle: an L-shaped corner mullion

Grid mode "custom" (the visual grid editor writes it): `verticals` = interior grid lines as
stations in inches along the driver AS DRAWN (so a flip keeps them in place); run ends and kinks
are always grid points; a line closer than MIN_GAP mullion widths to another is dropped.

Horizontals: sill (at the base), transoms, stack joints (unitized), head (at the top). A transom
is a height (it crosses every bay) or {"z": height, "at": [stations]}: only the bays holding one
of those stations (inches along the driver as drawn) get it. Each bay has its own list
(`bay_hs[bay]`); `horizontals` / `rows` are the ones every bay shares.
Rows are the spaces between consecutive horizontals of a bay, bottom -> top; cells are
(bay, row) with the row counted in that bay.
"""

import math

import Rhino

from .. import geo, units

G = Rhino.Geometry
MIN_GAP = 2.0           # custom grid lines: closest spacing, in mullion widths


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
        self.raw = getattr(ctx, "raw_curve", None) or crv
        self.length = Ltot
        self.run_bounds = [x for i, x in enumerate(bounds) if i == 0 or x - bounds[i - 1] >= tol]
        custom = self._custom_u(st, Ltot) if mode == "custom" else None
        gap = MIN_GAP * dims.mp["w"] * s
        pos = []            # (station, kink)
        for a, b in zip(bounds, bounds[1:]):
            if b - a < tol:
                continue
            if custom is None:
                rs = stations(b - a, mode, spacing, bays, 0.25 * spacing)
            else:
                rs, last = [0.0], 0.0
                for u in custom:
                    r = u - a
                    if r <= -1e-9 or r >= (b - a) + 1e-9:
                        continue
                    if r - last < gap - 1e-9 or (b - a) - r < gap - 1e-9:
                        ctx.warn("A grid line at {} is too close to the next one; skipped.".format(
                            units.format_inches(u / s)))
                        continue
                    rs.append(r)
                    last = r
                rs.append(b - a)
            for i, r in enumerate(rs):
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
            v = Vertex(i, P, kink)
            v.u = sv
            self.vertices.append(v)
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
        wh = dims.tp["w"] * s
        lines = []          # (kind, height, stations or None)
        for t in st.get("transoms") or []:
            if isinstance(t, dict):
                at = t.get("at")
                lines.append(("transom", t.get("z", 0), list(at) if at is not None else None))
            else:
                lines.append(("transom", t, None))
        if dims.style == "unitized":
            lines += [("stack", z, None) for z in st.get("stack") or []]
        lines.sort(key=lambda l: units.parse_length(l[1]))
        hs = [Horizontal("sill", self.base_z)]
        partial = []
        seen = []
        for kind, z, at in lines:
            zz = self.base_z + units.parse_length(z) * s
            if zz < self.base_z + 1.5 * wh or zz > self.top_z - 1.5 * wh:
                ctx.warn("A {} at {} is outside the curtain wall; skipped.".format(
                    kind, units.format_inches(units.parse_length(z))))
                continue
            if at is not None:
                partial.append((kind, zz, at))
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
        self.bay_hs = dict((b.index, list(hs)) for b in self.bays)
        for kind, zz, at in partial:
            for bi in sorted(set(i for i in (self.bay_at_station(x) for x in at) if i is not None)):
                cur = self.bay_hs[bi]
                if any(abs(zz - h.z) < 2 * wh for h in cur):
                    ctx.warn("Two horizontals at {} in bay {} are too close; one skipped.".format(
                        units.format_inches((zz - self.base_z) / s), bi))
                    continue
                cur.append(Horizontal(kind, zz))
                cur.sort(key=lambda h: h.z)
        infill = st.get("infill") or {}
        self.row_types = [str(x).lower() for x in (infill.get("rows") or ["vision"])]
        self.cell_types = dict((str(k).replace(" ", ""), str(v).lower())
                               for k, v in (infill.get("cells") or {}).items())

    def _custom_u(self, st, Ltot):
        """Custom grid lines (stations, inches along the driver as drawn) -> sorted lengths
        along the grid curve."""
        out = []
        for sv in st.get("verticals") or []:
            P = self.point_at_station(units.parse_length(sv))
            if P is None:
                continue
            u = self.u_of(P)
            if self.closed and (u < 1e-9 or u > Ltot - 1e-9):
                continue
            out.append(u)
        return sorted(out)

    # -- stations -------------------------------------------------------------------------------
    def point_at_station(self, station_in):
        """Point on the driver at a station (inches along it as drawn), None past its ends."""
        raw, ctx = self.raw, self.ctx
        L = raw.GetLength()
        x = station_in * ctx.s
        if x < -ctx.tol or x > L + ctx.tol:
            return None
        P = raw.PointAtLength(min(max(x, 0.0), L))
        return G.Point3d(P.X, P.Y, self.curve.PointAtStart.Z)

    def station_of(self, point):
        """Station (inches along the driver as drawn) of the driver point nearest a point."""
        raw = self.raw
        ok, t = raw.ClosestPoint(G.Point3d(point.X, point.Y, raw.PointAtStart.Z))
        if t - raw.Domain.T0 < 1e-12:
            return 0.0
        return raw.GetLength(G.Interval(raw.Domain.T0, t)) / self.ctx.s

    def u_of(self, point):
        """Length along the grid curve to the curve point nearest a point (model units)."""
        crv = self.curve
        ok, t = crv.ClosestPoint(G.Point3d(point.X, point.Y, crv.PointAtStart.Z))
        if t - crv.Domain.T0 < 1e-12:
            return 0.0
        return crv.GetLength(G.Interval(crv.Domain.T0, t))

    def point_at_u(self, u):
        return self.curve.PointAtLength(min(max(u, 0.0), self.length))

    def bay_index_at(self, point):
        """Index of the bay nearest a point (plan distance to its chord)."""
        best = None
        for b in self.bays:
            u, y = b.local(point)
            uu = min(max(u, 0.0), b.c)
            d = math.hypot(u - uu, y)
            if best is None or d < best[0] - 1e-9:
                best = (d, b.index)
        return best[1] if best else None

    def bay_at_station(self, station_in):
        P = self.point_at_station(units.parse_length(station_in))
        return None if P is None else self.bay_index_at(P)

    # -- cells ------------------------------------------------------------------------------------
    def bay_rows(self, bay):
        hs = self.bay_hs[bay if isinstance(bay, int) else bay.index]
        return list(zip(hs, hs[1:]))

    def infill(self, col, row):
        t = self.cell_types.get("{},{}".format(col, row))
        if t is None:
            t = self.row_types[min(row, len(self.row_types) - 1)]
        return t

    def cell_at(self, point):
        """(bay, row) of the cell nearest a world point, or None. The row counts in that bay."""
        bi = self.bay_index_at(point)
        if bi is None:
            return None
        rows = self.bay_rows(bi)
        for r, (h0, h1) in enumerate(rows):
            if h0.z - 1e-9 <= point.Z <= h1.z + 1e-9:
                return bi, r
        return bi, (0 if point.Z < self.base_z else len(rows) - 1)
