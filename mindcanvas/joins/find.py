"""Finding joins in the document (see joins/__init__.py, joins/plan.py).

Walls
    L   two wall ends whose end lines cross near both ends (within the other wall's thickness +
        1"), at 15..165 degrees; both ends must find each other. The primary wall (higher
        join_priority, then the thicker core, then the larger id) runs through.
    T   a wall end inside another wall (between its faces +- 1"), away from that wall's ends,
        at 15..165 degrees. The host gets notches (its layers on that side, around the joining
        wall's core) and backer studs.
    Wall ends set to "none" (params["joins"]) never join. Walls must overlap in height.
Floors
    A wall whose top is at the floor's framing bottom (+- 1/2") and that runs along a boundary
    edge (the edge lies within the wall's thickness + 1") is below the floor: its layers outside
    the core on the side away from the floor go up over the rim to the bottom of the wall above
    (or the top of the floor's structure). A wall whose base lies between the framing top and the
    floor's top is above it. Floor layers with an `inset` option get per-edge insets to the
    interior face of the wall on that edge (layers above the framing: the wall above, else below;
    layers below the framing: the wall below, else above).
Roofs
    A wall whose top is at the roof's plate height (+- 1/2") along a plate edge bears the roof:
    the roof takes wall_depth / wall_ext / wall_int from it (unless set in the roof's params);
    the wall's layers outside its core stop under the rafters, and every layer is filled up to
    the rafter bottom line where the roof rises above the wall (gable ends, shed walls).
"""

import contextlib
import math

import System
import Rhino

from .. import geo, hgeo, meta, units
from . import plan

G = Rhino.Geometry
SNAP_IN = 1.0
ZTOL_IN = 0.5
PARALLEL = math.sin(math.radians(5.0))

_STATE = {"depth": 0, "cache": None, "light": 0}


@contextlib.contextmanager
def session():
    """Share wall / floor / roof analyses between nested lookups of one build."""
    if _STATE["depth"] == 0:
        _STATE["cache"] = {}
    _STATE["depth"] += 1
    try:
        yield _STATE["cache"]
    finally:
        _STATE["depth"] -= 1
        if _STATE["depth"] == 0:
            _STATE["cache"] = None


@contextlib.contextmanager
def _light():
    """Contexts made only to read their geometry skip their own joins where they can."""
    _STATE["light"] += 1
    try:
        yield
    finally:
        _STATE["light"] -= 1


def _p2(p):
    return (p.X, p.Y)


def _v2(v):
    return plan.unit((v.X, v.Y))


class Joins(object):
    """ctx.joins of a wall."""

    def __init__(self):
        self.ends = {}          # "start" / "end" -> plan.EndCut
        self.notches = []       # (plan polygon, d_lo, d_hi, z0, z1): host layers cut around a T
        self.backers = []       # plan.Backer: extra studs in this wall's framing
        self.z_top = {}         # band index -> model units added to the band's top (no explicit extend_top)
        self.roofs = []         # roof contexts this wall is filled up to
        self.partners = set()   # ids of the assemblies joined to this one
        self.notes = []         # human-readable list (MCJoin)

    @property
    def reach(self):
        return max([c.reach() for c in self.ends.values()] + [0.0])


# -- walls ---------------------------------------------------------------------------------------
class WallInfo(object):
    """A wall driver reduced to what joins need: oriented curve, height range, face offsets."""

    def __init__(self, doc, lib, obj):
        from ..kinds import wall as wallkind
        self.obj = obj
        self.id = str(obj.Id)
        params = meta.params(obj)
        assembly = lib.assembly(meta.get(obj, meta.ASSEMBLY))
        s = units.inch_scale(doc)
        crv = obj.Geometry
        geo.check_horizontal(crv, doc.ModelAbsoluteTolerance)
        crv = geo.orient_driver(crv)
        if params.get("flip"):
            crv.Reverse()
        self.curve = crv
        self.closed = crv.IsClosed
        height = units.parse_length(params.get("height", assembly.get("default_height", "10'"))) * s
        self.z0 = crv.PointAtStart.Z + units.parse_length(params.get("base_offset", 0)) * s
        self.z1 = self.z0 + height
        self.bands = []
        core = []
        for i, (spec, de, di) in enumerate(wallkind.stack_offsets(lib, assembly, params, s)):
            row = (i, wallkind.layer_name(spec, i), spec.get("component", "solid"), de, di)
            self.bands.append(row)
            if spec.get("core"):
                core.append(row)
        self.ext = max(b[3] for b in self.bands)
        self.int = min(b[4] for b in self.bands)
        self.cext = max(b[3] for b in core) if core else self.ext
        self.cint = min(b[4] for b in core) if core else self.int
        try:
            self.priority = float(params.get("join_priority", 0) or 0)
        except (TypeError, ValueError):
            self.priority = 0.0
        self.styles = params.get("joins") or {}

    @property
    def thickness(self):
        return self.ext - self.int

    def key(self):
        return (self.priority, round(self.cext - self.cint, 9), self.id)

    def ends(self):
        return [] if self.closed else ["start", "end"]

    def style(self, name):
        v = str(self.styles.get(name, "auto")).lower()
        return v if v in plan.STYLES else "auto"

    def side(self, name):
        c = self.curve
        if name == "start":
            return plan.Side(_p2(c.PointAtStart), _v2(c.TangentAtStart), -1, self.ext, self.cext, self.cint, self.int)
        return plan.Side(_p2(c.PointAtEnd), _v2(c.TangentAtEnd), 1, self.ext, self.cext, self.cint, self.int)

    def side_at(self, p2):
        """(Side linearized at the closest point of the driver to p2, curve parameter, distances
        along the curve to its start and end)."""
        c = self.curve
        ok, t = c.ClosestPoint(G.Point3d(p2[0], p2[1], c.PointAtStart.Z))
        P, T = c.PointAt(t), c.TangentAt(t)
        t0 = c.Domain.T0
        La = c.GetLength(G.Interval(t0, t)) if t - t0 > 1e-12 else 0.0
        Lb = c.GetLength() - La
        return plan.Side(_p2(P), _v2(T), 0, self.ext, self.cext, self.cint, self.int), t, La, Lb

    def z_overlap(self, other, gap):
        return min(self.z1, other.z1) - max(self.z0, other.z0) > gap

    def zone_bands(self, sigma, which):
        """Band rows outside the core on the side sigma (+1 = exterior) ('outer'), or on the other
        side ('inner')."""
        if which == "inner":
            sigma = -sigma
        tol = 1e-9
        if sigma > 0:
            return [b for b in self.bands if b[4] >= self.cext - tol and b[3] > self.cext + tol]
        return [b for b in self.bands if b[3] <= self.cint + tol and b[4] < self.cint - tol]


def wall_infos(doc, lib):
    cache = _STATE["cache"]
    key = ("walls", doc.RuntimeSerialNumber)
    if cache is not None and key in cache:
        return cache[key]
    out = []
    for o in meta.all_drivers(doc, "wall"):
        try:
            out.append(WallInfo(doc, lib, o))
        except Exception:
            pass
    if cache is not None:
        cache[key] = out
    return out


def _l_candidate(w, name, walls, snap, gap):
    a = w.side(name)
    best = None
    for o in walls:
        if o.id == w.id or not w.z_overlap(o, gap):
            continue
        for on in o.ends():
            if o.style(on) == "none":
                continue
            m = plan.l_meeting(a, o.side(on), snap)
            if m is not None and (best is None or m[0] < best[0]):
                best = (m[0], o, on)
    return best


def resolve_end(w, name, walls, snap, gap):
    """("L", other, other end) | ("T", host, host Side) | None for one end of wall w."""
    if w.closed or w.style(name) == "none":
        return None
    best = _l_candidate(w, name, walls, snap, gap)
    if best is not None:
        back = _l_candidate(best[1], best[2], walls, snap, gap)
        if back is not None and back[1].id == w.id and back[2] == name:
            return ("L", best[1], best[2])
    a = w.side(name)
    bestT = None
    for o in walls:
        if o.id == w.id or not w.z_overlap(o, gap):
            continue
        h, t, La, Lb = o.side_at(a.P)
        if not o.closed:
            margin = 0.5 * w.thickness
            if La < margin or Lb < margin:
                continue
        sc = plan.t_meeting(a, h, snap)
        if sc is not None and (bestT is None or sc < bestT[0]):
            bestT = (sc, o, h)
    if bestT is not None:
        return ("T", bestT[1], bestT[2])
    return None


def _masonry_lap(a_info, a, b_info, b, cut, primary):
    """Brick on both walls on the outer side of a square corner: alternate courses lap."""
    if abs(plan.dot(a.t, b.t)) > 0.02 or cut.style != "wrap":
        return
    sa, sb = plan.corner_sides(a, b)
    mine = [r for r in a_info.zone_bands(-sa, "outer") if r[2] == "masonry"]
    theirs = [r for r in b_info.zone_bands(-sb, "outer") if r[2] == "masonry"]
    if not mine or not theirs:
        return
    r = max(theirs, key=lambda q: abs(q[3] - q[4]))
    front, back = (r[3], r[4]) if sb < 0 else (r[4], r[3])     # outer face first
    cut.lap = (b.line(front), b.line(back), primary)


def _wall_walls(ctx, me, walls, J):
    snap, gap = ctx.u(SNAP_IN), ctx.u(1)
    for name in me.ends():
        r = resolve_end(me, name, walls, snap, gap)
        if r is None:
            continue
        if r[0] == "L":
            other, on = r[1], r[2]
            primary = plan.primary_of(me.key(), other.key())
            style = plan.resolve_style(me.style(name), other.style(on), primary)
            if style == "none":
                continue
            a, b = me.side(name), other.side(on)
            cut = plan.l_cut(a, b, style, primary, other.id)
            if cut is None:
                continue
            cut.lap = None
            _masonry_lap(me, a, other, b, cut, primary)
            J.ends[name] = cut
            J.partners.add(other.id)
            bk = plan.l_backer(a, b, primary, style)
            if bk is not None:
                J.backers.append(bk)
            J.notes.append("{}: L join ({}, {}) with {}".format(name, style, cut.role, other.id[:8]))
        else:
            host, h = r[1], r[2]
            style = "butt" if me.style(name) == "butt" else "core"
            cut = plan.t_cut(me.side(name), h, style, host.id)
            if cut is None:
                continue
            cut.lap = None
            J.ends[name] = cut
            J.partners.add(host.id)
            J.notes.append("{}: T join ({}) into {}".format(name, style, host.id[:8]))
    # walls ending on this one (T)
    eps = ctx.u(1.0 / 16)
    for w in walls:
        if w.id == me.id:
            continue
        for on in w.ends():
            r = resolve_end(w, on, walls, snap, gap)
            if r is None or r[0] != "T" or r[1].id != me.id:
                continue
            b, h = w.side(on), r[2]
            J.partners.add(w.id)
            J.backers.extend(plan.t_backers(b, h))
            J.notes.append("T join from {} ({})".format(w.id[:8], on))
            if w.style(on) == "butt":
                continue
            nt = plan.t_notch(b, h, eps)
            if nt is None:
                continue
            poly, (lo, hi) = nt
            z0 = w.z0 if w.z0 > me.z0 + ctx.tol else me.z0 - ctx.u(48)
            z1 = w.z1 if w.z1 < me.z1 - ctx.tol else me.z1 + ctx.u(48)
            J.notches.append((poly, lo, hi, z0, z1))


# -- floors ----------------------------------------------------------------------------------------
class Edge(object):
    __slots__ = ("index", "sigma", "inset", "wall")

    def __init__(self, index, sigma, inset, wall):
        self.index, self.sigma, self.inset, self.wall = index, sigma, inset, wall


def aligned_edges(w, poly, snap):
    """Edges of a CCW plan polygon that run along wall w (within its thickness + snap).
    Edge.sigma: +1 when the wall's exterior faces away from the polygon; Edge.inset: distance
    from the edge inward to the wall's interior finish face."""
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        L = plan.dist(a, b)
        if L < snap:
            continue
        e = plan.unit(plan.sub(b, a))
        ni = plan.left(e)
        for f in (0.5, 0.25, 0.75):
            M = plan.add(a, plan.mul(e, f * L))
            h, t, La, Lb = w.side_at(M)
            if abs(plan.cross(h.t, e)) > PARALLEL:
                continue
            if not w.closed and (La < 1e-9 or Lb < 1e-9):
                continue
            dM = h.offset_of(M)
            if not (w.int - snap <= dM <= w.ext + snap):
                continue
            sigma = plan.sign(plan.dot(h.n, plan.neg(ni)))
            if sigma == 0:
                continue
            d_in = w.int if sigma > 0 else w.ext
            inset = plan.dot(plan.sub(h.point(d_in), M), ni)
            out.append(Edge(i, sigma, inset, w))
            break
    return out


class FloorInfo(object):
    def __init__(self, doc, lib, obj):
        from ..kinds import floor as floorkind
        self.obj, self.id = obj, str(obj.Id)
        with _light():
            ctx = floorkind.make_context(doc, lib, obj, meta.get(obj, meta.ASSEMBLY), meta.params(obj))
        self.ctx = ctx
        self.poly = hgeo.ccw(list(ctx.poly_world))
        fb = floorkind.framing_band(ctx)
        self.z_top = ctx.base_z + ctx.height
        self.z_bot = ctx.base_z
        if fb is None:
            self.z_fb = self.z_ft = self.z_cover = ctx.base_z
            return
        self.z_fb, self.z_ft = fb.d_int, fb.d_ext
        z = fb.d_ext
        for i in range(fb.index - 1, -1, -1):
            b = ctx.bands[i]
            if ctx.option(b, "inset"):
                break
            z = b.d_ext
        self.z_cover = z


def floor_infos(doc, lib):
    cache = _STATE["cache"]
    key = ("floors", doc.RuntimeSerialNumber)
    if cache is not None and key in cache:
        return cache[key]
    out = []
    for o in meta.all_drivers(doc, "floor"):
        try:
            out.append(FloorInfo(doc, lib, o))
        except Exception:
            pass
    if cache is not None:
        cache[key] = out
    return out


def _wall_floors(ctx, me, walls, J):
    snap, zt = ctx.u(SNAP_IN), ctx.u(ZTOL_IN)
    top = ctx.base_z + ctx.height
    for F in floor_infos(ctx.doc, ctx.lib):
        below = abs(me.z1 - F.z_fb) <= zt
        above = F.z_ft - zt <= me.z0 <= F.z_top + zt
        if not (below or above):
            continue
        edges = aligned_edges(me, F.poly, snap)
        if not edges:
            continue
        J.partners.add(F.id)
        J.notes.append("{} floor {}".format("under" if below else "on", F.id[:8]))
        if not below:
            continue
        # the wall above on the same edge (its base), else the top of the floor's structure
        target = F.z_cover
        idx = set(e.index for e in edges)
        ups = [w.z0 for w in walls if w.id != me.id and F.z_ft - zt <= w.z0 <= F.z_top + zt
               and any(e.index in idx for e in aligned_edges(w, F.poly, snap))]
        if ups:
            target = min(ups)
        dz = target - top
        if dz <= ctx.tol:
            continue
        sigma = edges[0].sigma
        for row in me.zone_bands(sigma, "outer"):
            J.z_top[row[0]] = max(J.z_top.get(row[0], 0.0), dz)


def attach_floor(ctx, driver_obj):
    """Per-edge insets of the floor's inset layers from the walls along its boundary."""
    ctx.join_insets, ctx.join_partners = {}, set()
    if _STATE["light"]:
        return
    try:
        with session():
            _attach_floor(ctx)
    except Exception as ex:
        ctx.warn("Floor joins skipped ({}).".format(ex))


def _attach_floor(ctx):
    from ..kinds import floor as floorkind
    fb = floorkind.framing_band(ctx)
    if fb is None:
        return
    snap, zt = ctx.u(SNAP_IN), ctx.u(ZTOL_IN)
    poly = hgeo.ccw(list(ctx.poly_world))
    z_top = ctx.base_z + ctx.height
    lower, upper = {}, {}
    for w in wall_infos(ctx.doc, ctx.lib):
        is_low = abs(w.z1 - fb.d_int) <= zt
        is_up = fb.d_ext - zt <= w.z0 <= z_top + zt
        if not (is_low or is_up):
            continue
        es = aligned_edges(w, poly, snap)
        for e in es:
            (lower if is_low else upper).setdefault(e.index, e)
        if es:
            ctx.join_partners.add(w.id)
    if not lower and not upper:
        return
    for band in ctx.bands:
        if band.component not in ("solid", "membrane") or band is fb:
            continue
        own = ctx.option(band, "inset")
        if not own:
            continue
        first, second = (upper, lower) if band.d_int >= fb.d_ext - ctx.tol else (lower, upper)
        dists = []
        for i in range(len(poly)):
            e = first.get(i) or second.get(i)
            dists.append(max(0.0, e.inset) if e is not None else ctx.u(own))
        ctx.join_insets[band.index] = (poly, dists)


# -- roofs -----------------------------------------------------------------------------------------------
def roof_contexts(doc, lib):
    from ..kinds import roof as roofkind
    cache = _STATE["cache"]
    key = ("roofs", doc.RuntimeSerialNumber)
    if cache is not None and key in cache:
        return cache[key]
    out = []
    for o in meta.all_drivers(doc, "roof"):
        try:
            rc = roofkind.make_context(doc, lib, o, meta.get(o, meta.ASSEMBLY), meta.params(o))
            rc.join_id = str(o.Id)
            rc.plate_poly = hgeo.ccw(list(rc.poly_world))
            out.append(rc)
        except Exception:
            pass
    if cache is not None:
        cache[key] = out
    return out


def zb_at(rctx, p2):
    """Rafter bottom z of the roof face over a plan point (None when no face covers it)."""
    for f in rctx.faces:
        q = f.frame.local(G.Point3d(p2[0], p2[1], 0.0))
        if f.v_ridge is not None and q.X > f.v_ridge + rctx.tol:
            continue
        return f.zb(q.X)
    return None


def _wall_roofs(ctx, me, J):
    from . import geom
    snap, zt = ctx.u(SNAP_IN), ctx.u(ZTOL_IN)
    top = ctx.base_z + ctx.height
    for rc in roof_contexts(ctx.doc, ctx.lib):
        if abs(me.z1 - rc.base_z) > zt:
            continue
        edges = aligned_edges(me, rc.plate_poly, snap)
        if not edges:
            continue
        J.partners.add(rc.join_id)
        J.roofs.append(rc)
        J.notes.append("under roof {}".format(rc.join_id[:8]))
        # layers outside the core stop under the rafters (eaves)
        outer = set(r[0] for r in me.zone_bands(edges[0].sigma, "outer"))
        for band in ctx.bands:
            if band.index not in outer:
                continue
            zs = []
            for poly in geom.band_polys(ctx, band):
                for p in poly:
                    z = zb_at(rc, p)
                    if z is not None:
                        zs.append(z)
            if zs and min(zs) < top - ctx.tol:
                J.z_top[band.index] = min(J.z_top.get(band.index, 0.0), min(zs) - top)


def attach_roof(ctx, driver_obj):
    """Bearing-wall dimensions of a roof from the walls under its plate line."""
    ctx.join_partners = set()
    try:
        with session():
            _attach_roof(ctx)
    except Exception as ex:
        ctx.warn("Roof joins skipped ({}).".format(ex))


def _attach_roof(ctx):
    snap, zt = ctx.u(SNAP_IN), ctx.u(ZTOL_IN)
    poly = hgeo.ccw(list(ctx.poly_world))
    found = []
    for w in wall_infos(ctx.doc, ctx.lib):
        if abs(w.z1 - ctx.base_z) > zt:
            continue
        es = aligned_edges(w, poly, snap)
        if es:
            ctx.join_partners.add(w.id)
            for e in es:
                found.append((plan.dist(poly[e.index], poly[(e.index + 1) % len(poly)]), e))
    if not found:
        return
    e = max(found, key=lambda q: q[0])[1]
    w, sg = e.wall, e.sigma
    outer = (w.ext - w.cext) if sg > 0 else (w.cint - w.int)
    inner = (w.cint - w.int) if sg > 0 else (w.ext - w.cext)
    dims = {"wall_depth": w.cext - w.cint, "wall_ext": outer, "wall_int": inner}
    for k, v in dims.items():
        if k not in ctx.params:
            ctx.st[k] = round(v / ctx.s, 4)


# -- walls: entry point --------------------------------------------------------------------------------
def attach_wall(ctx, driver_obj):
    """Fill ctx.joins for a wall: its joined ends, notches and backers as a T host, top changes
    under floors / roofs."""
    J = Joins()
    ctx.joins = J
    ctx.join_partners = J.partners
    try:
        with session():
            walls = wall_infos(ctx.doc, ctx.lib)
            me = None
            for w in walls:
                if w.id == str(driver_obj.Id):
                    me = w
            if me is None:
                me = WallInfo(ctx.doc, ctx.lib, driver_obj)
                walls = walls + [me]
            _wall_walls(ctx, me, walls, J)
            _wall_floors(ctx, me, walls, J)
            _wall_roofs(ctx, me, J)
    except Exception as ex:
        ctx.warn("Wall joins skipped ({}).".format(ex))
        partners = J.partners
        J = Joins()
        J.partners = partners
        ctx.joins = J
        ctx.join_partners = partners


def describe(ctx):
    J = getattr(ctx, "joins", None)
    return list(J.notes) if J is not None else []


def partner_objects(doc, ids):
    out = []
    for pid in ids:
        try:
            o = doc.Objects.FindId(System.Guid(pid))
        except Exception:
            o = None
        if o is not None and not o.IsDeleted and meta.is_driver(o):
            out.append(o)
    return out
