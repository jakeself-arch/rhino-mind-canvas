"""Framed walls: wood or cold-formed steel studs, plates/tracks, corners,
blocking/bridging and cavity insulation.

Layer options (overridable per wall; lengths in inches):
    system        framing system in library/framing: "wood" | "metal"
    stud          stud profile; default: the system's stud matching the layer
                  thickness (by nominal size, 2x4 <-> 3-5/8", 2x6 <-> 6"),
                  else the nearest smaller one
    spacing       stud spacing on center (default 16)
    cavity_fill   insulation material between the members (detail LOD), or null
    fit           "stud" (default): the layer thickness follows the stud depth;
                  "layer": keep the assembly thickness
    gauge                              metal: 20 | 18 | 16
    deflection_track, deflection_gap   metal: deep-leg top track, studs cut short
    bridging_spacing                   metal: cold-rolled channel rows (0 = none)
    blocking, double_end_studs         wood

Studs sit on the band centerline: at each end, every `spacing` from the start
of each run between corners, and in corner sets at every kink. Square corners
get a full corner (wood: end stud + flat corner stud + backer; metal: two
studs, webs toward the corner); oblique corners get a stud on each side.
stud_stations(ctx, band) gives their distances along ctx.curve.
"""

import math
import re

import Rhino

from .. import geo, profiles, units
from .base import Component, Part, register

G = Rhino.Geometry
FIT_IN = 1.0 / 64
DEFAULT_SYSTEM = "wood"
SQUARE_TOL = math.radians(2.0)


# -- member selection ---------------------------------------------------
def _gauge(value):
    if value is None:
        return None
    m = re.search(r"\d+", str(value))
    return int(m.group()) if m else None


def _family(lib, family, gauge=None):
    """[(depth_in, name, definition)] of a profile family, shallowest first."""
    out = []
    for name, p in lib.data["profiles"].items():
        if family and p.get("family") == family and (gauge is None or p.get("gauge") == gauge):
            out.append((units.parse_length(p.get("depth", 0)), name, p))
    return sorted(out, key=lambda c: (c[0], c[1]))


def select_stud(lib, system, opts, thickness_in):
    """(profile name, definition, warning or None) for a framing layer."""
    name = opts.get("stud")
    if name:
        for cand in (name, re.sub(r"\s+Wood Stud$", "", name)):
            if cand in lib.data["profiles"]:
                return cand, lib.data["profiles"][cand], None
        lib.profile(name)  # raises a clear "not found"
    fam = system.get("stud_family")
    gauge = _gauge(opts.get("gauge", system.get("gauge"))) if system.get("type") == "metal" else None
    cands = _family(lib, fam, gauge)
    msg = None
    if not cands and gauge is not None:
        cands = _family(lib, fam)
        msg = "No {} ga studs in the library; using another gauge.".format(gauge)
    if not cands:
        raise ValueError("Framing system has no '{}' stud profiles.".format(fam))
    T = thickness_in
    exact = [c for c in cands if abs(c[0] - T) < FIT_IN]
    if exact:
        return exact[0][1], exact[0][2], msg
    # same nominal size as a stud of another system that fits exactly (2x6 -> 6")
    nominal = None
    for sysdef in lib.data["framing"].values():
        for d, _, p in _family(lib, sysdef.get("stud_family")):
            if abs(d - T) < FIT_IN and p.get("nominal") is not None:
                nominal = p.get("nominal")
    same = [c for c in cands if nominal is not None and c[2].get("nominal") == nominal]
    if same:
        return same[0][1], same[0][2], msg
    below = [c for c in cands if c[0] <= T + FIT_IN]
    pick = below[-1] if below else cands[0]
    return pick[1], pick[2], "Framing layer is {} thick; using {} ({} deep).".format(
        units.format_inches(T), pick[1], units.format_inches(pick[0]))


def _companion(lib, stud, family):
    """Track / deflection track matching a metal stud (nominal + gauge)."""
    for _, name, p in _family(lib, family):
        if p.get("nominal") == stud.get("nominal") and p.get("gauge") == stud.get("gauge"):
            return name, p
    for _, name, p in _family(lib, family):
        if p.get("nominal") == stud.get("nominal"):
            return name, p
    return None, None


# -- layout ---------------------------------------------------------------
def _turn(a, b):
    """Signed plan angle (radians) from direction a to direction b."""
    return math.atan2(a.X * b.Y - a.Y * b.X, a.X * b.X + a.Y * b.Y)


def _area(curve):
    amp = G.AreaMassProperties.Compute(curve)
    return amp.Area if amp else 0.0


class _Stud(object):
    __slots__ = ("seg", "s", "facing", "kind")

    def __init__(self, seg, s, facing, kind):
        self.seg, self.s, self.facing, self.kind = seg, s, facing, kind


class Layout(object):
    """Member sizes and stud positions of one framing band (cached per build)."""

    def __init__(self, ctx, band):
        self.ctx, self.band = ctx, band
        o = self.opts = ctx.options(band)
        self.system_name = o.get("system") or DEFAULT_SYSTEM
        self.sys = ctx.lib.framing_system(self.system_name)
        self.metal = self.sys.get("type") == "metal"
        self.material = self.sys.get("material") or band.material
        self.stud_name, self.stud, msg = select_stud(ctx.lib, self.sys, o, band.thickness / ctx.s)
        if msg:
            ctx.warn(msg)
        w_in, d_in = profiles.size(self.stud)
        self.w, self.D = w_in * ctx.s, d_in * ctx.s
        self.spacing = ctx.u(o.get("spacing", self.sys.get("spacing", 16)))
        if self.spacing < 2 * self.w:
            ctx.warn("Stud spacing too small; using {}.".format(units.format_inches(4 * w_in)))
            self.spacing = 4 * self.w
        self.center = geo.offset(ctx.curve, band.d_mid, ctx.tol)
        self.length_in = self.center.GetLength() / ctx.s
        self._split()
        self._place()

    def opt(self, key, default=None):
        return self.opts.get(key, self.sys.get(key, default))

    def name(self, role, profile):
        return self.sys.get("names", {}).get(role, "{profile}").format(profile=profile)

    def _split(self):
        c = self.center
        kinks = geo.kink_parameters(c)
        seam = c.IsClosed and abs(_turn(c.TangentAtEnd, c.TangentAtStart)) > math.radians(1.0)
        if c.IsClosed and kinks and not seam:
            c = c.DuplicateCurve()
            c.ChangeClosedCurveSeam(kinks[0])
            kinks = geo.kink_parameters(c)
            seam = True
        ts = [c.Domain.T0] + kinks + [c.Domain.T1]
        self.segs = [c.Trim(G.Interval(a, b)) for a, b in zip(ts[:-1], ts[1:])]
        n = len(self.segs)
        self.starts = [("end", 0.0)] * n
        self.ends = [("end", 0.0)] * n
        joints = [(i, i + 1) for i in range(n - 1)]
        if c.IsClosed:
            if seam:
                joints.append((n - 1, 0))
            else:
                self.starts[0] = self.ends[-1] = ("loop", 0.0)
        for a, b in joints:
            th = abs(_turn(self.segs[a].TangentAtEnd, self.segs[b].TangentAtStart))
            if abs(th - math.pi / 2) < SQUARE_TOL:
                kind = ("square", 1.0)
            else:
                kind = ("oblique", min(math.tan(th / 2), 4.0))
            self.ends[a] = kind
            self.starts[b] = kind

    def _place(self):
        w, D, sp = self.w, self.D, self.spacing
        three = self.sys.get("corner") == "three_stud"
        double = bool(self.opt("double_end_studs", False))
        self.studs = []
        for i, seg in enumerate(self.segs):
            Ls = seg.GetLength()
            fixed = []
            st, k = self.starts[i]
            if st == "end":
                fixed.append((0.5 * w, 1, "end"))
                if double:
                    fixed.append((1.5 * w, 1, "end"))
            elif st == "square":
                fixed.append((-0.5 * D + 0.5 * w, 1, "corner"))
                if three:
                    fixed.append((0.5 * D + 0.5 * w, 1, "corner"))
            elif st == "oblique":
                fixed.append((0.5 * D * k + 0.5 * w, 1, "corner"))
            else:
                fixed.append((0.0, 1, "field"))
            et, k = self.ends[i]
            if et == "end":
                fixed.append((Ls - 0.5 * w, -1, "end"))
                if double:
                    fixed.append((Ls - 1.5 * w, -1, "end"))
            elif et == "square":
                fixed.append((Ls - 0.5 * D - 0.5 * w, -1, "corner"))
            elif et == "oblique":
                fixed.append((Ls - 0.5 * D * k - 0.5 * w, -1, "corner"))
            kept = []
            for f in fixed:
                if all(abs(f[0] - g[0]) > 0.5 * w for g in kept):
                    kept.append(f)
            if len(kept) < len(fixed):
                self.ctx.warn("A wall run is too short for its end/corner studs.")
            lo = min(f[0] for f in kept)
            hi = Ls if et == "loop" else max(f[0] for f in kept)
            blocked = [f[0] for f in kept] + ([Ls] if et == "loop" else [])
            n = 1
            while n * sp < Ls - 1e-9:
                s = n * sp
                n += 1
                if lo < s < hi and all(abs(s - b) >= w - 1e-9 for b in blocked):
                    kept.append((s, 1, "field"))
            for s, facing, kind in sorted(kept):
                self.studs.append(_Stud(i, s, facing, kind))

    def frame(self, stud, z):
        """Plane at a stud: origin on the centerline at z, X along the wall
        (flipped for studs facing back), Y toward the exterior."""
        seg = self.segs[stud.seg]
        Ls = seg.GetLength()
        sc = min(max(stud.s, 0.0), Ls)
        ok, t = seg.NormalizedLengthParameter(sc / Ls if Ls > 0 else 0.0)
        f = geo.frame_at(seg, t, z)
        o = f.Origin + f.XAxis * (stud.s - sc)
        if stud.facing < 0:
            return G.Plane(o, -f.XAxis, -f.YAxis)
        return G.Plane(o, f.XAxis, f.YAxis)

    def points(self):
        z = self.center.PointAtStart.Z
        return [self.frame(st, z).Origin for st in self.studs]

    def cavity_pieces(self):
        """Closed plan curves of the cavity between the members (cached)."""
        if hasattr(self, "_pieces"):
            return self._pieces
        ctx, band = self.ctx, self.band
        tol = ctx.tol
        d_hi, d_lo = band.d_mid + 0.5 * self.D, band.d_mid - 0.5 * self.D
        eps = max(ctx.u(1.0 / 16), tol * 20)
        cutters = []
        if ctx.curve.IsClosed:
            a, b = geo.offset(ctx.curve, d_hi, tol), geo.offset(ctx.curve, d_lo, tol)
            outer, inner = (a, b) if _area(a) > _area(b) else (b, a)
            cutters.append(inner)
        else:
            outer = geo.band_outline_open(ctx.curve, d_hi, d_lo, tol)
        z = self.center.PointAtStart.Z
        hw, hd = 0.5 * self.w, 0.5 * self.D + eps
        for st in self.studs:
            f = self.frame(st, z)
            pts = [f.PointAt(x, y) for x, y in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd), (-hw, -hd))]
            cutters.append(G.PolylineCurve(pts))
        res = G.Curve.CreateBooleanDifference(outer, cutters, tol)
        min_area = self.D * ctx.u(0.25)
        self._pieces = [c for c in (res or []) if c.IsClosed and _area(c) > min_area]
        return self._pieces


def layout(ctx, band):
    cache = ctx.__dict__.setdefault("_mc_framing", {})
    if band.index not in cache:
        cache[band.index] = Layout(ctx, band)
    return cache[band.index]


def stud_stations(ctx, band):
    """Sorted distances (model units, along ctx.curve from its start) of every stud."""
    crv = ctx.curve
    t0 = crv.Domain.T0
    out = []
    for p in layout(ctx, band).points():
        ok, t = crv.ClosestPoint(p)
        out.append(crv.GetLength(G.Interval(t0, t)) if t - t0 > 1e-12 else 0.0)
    return sorted(out)


# -- geometry helpers ---------------------------------------------------
def _dims(defn):
    vals = []
    for k in ("width", "depth", "flange", "lip", "t"):
        if k in defn:
            vals.append("{:g}".format(round(units.parse_length(defn[k]), 4)))
    return "x".join(vals)


def _channel(ctx, d_hi, d_lo, z_lo, z_hi, t, opening):
    """U-channel following the curve. Outer section [d_lo, d_hi] x [z_lo, z_hi];
    opening: up | down | ext | int. Boolean of two band solids, else 3 pieces."""
    tol = ctx.tol
    e = max(d_hi - d_lo, z_hi - z_lo)
    ci = [d_lo + t, d_hi - t, z_lo + t, z_hi - t]
    ci[{"up": 3, "down": 2, "ext": 1, "int": 0}[opening]] += e if opening in ("up", "ext") else -e
    outer = geo.band_solids(ctx.curve, d_hi, d_lo, z_lo, z_hi - z_lo, tol)
    try:
        crv = ctx.curve
        if not crv.IsClosed:
            crv = crv.Extend(G.CurveEnd.Both, 2 * e, G.CurveExtensionStyle.Line) or crv
        cut = geo.band_solids(crv, ci[1], ci[0], ci[2], ci[3] - ci[2], tol)
        res = G.Brep.CreateBooleanDifference(outer, cut, tol)
        if res and len(res) == len(outer):
            return list(res)
    except Exception:
        pass
    ctx.warn("Channel built from separate web and legs (Boolean failed).")
    if opening == "up":
        rects = [(d_hi, d_lo, z_lo, z_lo + t), (d_hi, d_hi - t, z_lo + t, z_hi), (d_lo + t, d_lo, z_lo + t, z_hi)]
    elif opening == "down":
        rects = [(d_hi, d_lo, z_hi - t, z_hi), (d_hi, d_hi - t, z_lo, z_hi - t), (d_lo + t, d_lo, z_lo, z_hi - t)]
    elif opening == "int":
        rects = [(d_hi, d_hi - t, z_lo, z_hi), (d_hi - t, d_lo, z_lo, z_lo + t), (d_hi - t, d_lo, z_hi - t, z_hi)]
    else:
        rects = [(d_lo + t, d_lo, z_lo, z_hi), (d_hi, d_lo + t, z_lo, z_lo + t), (d_hi, d_lo + t, z_hi - t, z_hi)]
    out = []
    for a, b, za, zb in rects:
        out += ctx.solids(a, b, za, zb)
    return out


def _studs(ctx, lay, zb, zt):
    L = zt - zb
    L_in = round(L / ctx.s, 4)
    bname = "MC Stud {} [{}] L{:.4f}".format(lay.stud_name.replace('"', "in"), _dims(lay.stud), L_in)
    loops = profiles.build(lay.stud, ctx.s)
    idx = ctx.block(bname, [geo.extrude_profile(loops[0], G.Plane.WorldXY, L)], lay.material)
    member = lay.name("stud", lay.stud_name)
    out = []
    for st in lay.studs:
        xf = G.Transform.PlaneToPlane(G.Plane.WorldXY, lay.frame(st, zb))
        out.append(Part(material=lay.material, role="stud", block=idx, xform=xf,
                        extra={"length": L_in, "member": member, "position": st.kind}))
    return out


def _run(ctx, lay, solids, material, role, member):
    extra = {"length": round(lay.length_in, 4), "member": member}
    return [Part(s, material, role=role, extra=extra) for s in solids]


def _cavity(ctx, lay, zb, zt, cuts=(), cut_material=None, cut_member=None):
    """Fill between the members from zb to zt; `cuts` are z-intervals filled
    with blocking instead. Falls back to one continuous fill band."""
    fill = lay.opts.get("cavity_fill")
    if not fill and not cuts:
        return []
    out = []
    try:
        pieces = lay.cavity_pieces()
        if not pieces:
            raise geo.GeometryError("no cavity pieces")
    except Exception as ex:
        if fill:
            ctx.warn("Cavity fill between studs failed ({}); filled as one band.".format(ex))
            band = lay.band
            out += [Part(s, fill, role="insulation")
                    for s in ctx.solids(band.d_mid + 0.5 * lay.D, band.d_mid - 0.5 * lay.D, zb, zt)]
        return out
    cuts = sorted(c for c in cuts if zb < c[0] < c[1] < zt)
    spans, z = [], zb
    for c0, c1 in cuts:
        spans.append((z, c0))
        z = c1
    spans.append((z, zt))
    for crv in pieces:
        regions = G.Brep.CreatePlanarBreps(crv, ctx.tol)
        if not regions:
            continue
        reg = regions[0]
        run_in = round(_area(crv) / lay.D / ctx.s, 4)
        for c0, c1 in cuts:
            out.append(Part(geo.extrude_region(reg, c0, c1 - c0, ctx.tol), cut_material, role="blocking",
                            extra={"length": run_in, "member": cut_member}))
        if fill:
            for z0, z1 in spans:
                if z1 - z0 > ctx.tol:
                    out.append(Part(geo.extrude_region(reg, z0, z1 - z0, ctx.tol), fill, role="insulation",
                                    extra={"area": round(run_in * (z1 - z0) / ctx.s, 2)}))
    return out


# -- systems ----------------------------------------------------------------
def _wood(ctx, band, lay, z0, z1):
    pt = lay.w
    nb = int(lay.opt("bottom_plates", 1))
    nt = int(lay.opt("top_plates", 2))
    d_hi, d_lo = band.d_mid + 0.5 * lay.D, band.d_mid - 0.5 * lay.D
    member = lay.name("plate", lay.stud_name)
    parts = []
    for j in range(nb):
        parts += _run(ctx, lay, ctx.solids(d_hi, d_lo, z0 + j * pt, z0 + (j + 1) * pt), lay.material, "plate", member)
    for j in range(nt):
        parts += _run(ctx, lay, ctx.solids(d_hi, d_lo, z1 - (j + 1) * pt, z1 - j * pt), lay.material, "plate", member)
    zb, zt = z0 + nb * pt, z1 - nt * pt
    if zt - zb < 4 * pt:
        raise geo.GeometryError("Wall too short for wood framing.")
    parts += _studs(ctx, lay, zb, zt)
    if ctx.lod == "detail":
        cuts = []
        if lay.opt("blocking", False):
            zc = 0.5 * (zb + zt)
            cuts.append((zc - 0.5 * pt, zc + 0.5 * pt))
        parts += _cavity(ctx, lay, zb, zt, cuts, lay.material, lay.name("blocking", lay.stud_name))
    return parts


def _metal(ctx, band, lay, z0, z1):
    lib = ctx.lib
    t = ctx.u(lay.stud.get("t", 0.0346))
    d_hi, d_lo = band.d_mid + 0.5 * lay.D + t, band.d_mid - 0.5 * lay.D - t
    tname, track = _companion(lib, lay.stud, lay.sys.get("track_family"))
    leg = ctx.u(track["flange"]) if track else ctx.u(1.25)
    tname = tname or "Track"
    parts = _run(ctx, lay, _channel(ctx, d_hi, d_lo, z0, z0 + leg, t, "up"), lay.material, "track",
                 lay.name("track", tname))
    zt = z1 - t
    if lay.opt("deflection_track", False):
        dname, dtrack = _companion(lib, lay.stud, lay.sys.get("deflection_family"))
        dleg = ctx.u(dtrack["flange"]) if dtrack else ctx.u(2.0)
        gap = min(ctx.u(lay.opt("deflection_gap", 0.75)), dleg - ctx.u(0.5))
        parts += _run(ctx, lay, _channel(ctx, d_hi, d_lo, z1 - dleg, z1, t, "down"), lay.material,
                      "track", lay.name("track", dname or "Deflection Track"))
        zt = z1 - t - gap
    else:
        parts += _run(ctx, lay, _channel(ctx, d_hi, d_lo, z1 - leg, z1, t, "down"), lay.material, "track",
                      lay.name("track", tname))
    zb = z0 + t
    if zt - zb < ctx.u(12):
        raise geo.GeometryError("Wall too short for metal framing.")
    parts += _studs(ctx, lay, zb, zt)
    if ctx.lod == "detail":
        parts += _cavity(ctx, lay, zb, z1 - t)
        sp = ctx.u(lay.opt("bridging_spacing", 0) or 0)
        crc_name = lay.sys.get("bridging")
        if sp > 0 and crc_name:
            crc = lib.profile(crc_name)
            h, c, tc = ctx.u(crc["depth"]), ctx.u(crc["flange"]), ctx.u(crc["t"])
            zr = zb + sp
            while zr + h < zt - ctx.u(6):
                parts += _run(ctx, lay, _channel(ctx, band.d_mid + 0.5 * c, band.d_mid - 0.5 * c,
                                                 zr - 0.5 * h, zr + 0.5 * h, tc, "int"),
                              lay.material, "bridging", lay.name("bridging", crc_name))
                zr += sp
    return parts


@register
class Framing(Component):
    name = "framing"

    def layer_thickness(self, lib, spec, opts):
        """Inches the layer should be (the chosen stud's depth), or None to keep it."""
        if opts.get("fit", "stud") != "stud":
            return None
        system = lib.framing_system(opts.get("system") or DEFAULT_SYSTEM)
        T = units.parse_length(spec.get("thickness", 0))
        _, stud, _ = select_stud(lib, system, opts, T)
        d = profiles.size(stud)[1]
        return d if abs(d - T) > 1e-6 else None

    def build(self, ctx, band):
        lay = layout(ctx, band)
        z0, z1 = ctx.z_range(band)
        if ctx.lod == "schematic":
            return [Part(s, lay.material, role="framing") for s in ctx.solids(band.d_ext, band.d_int, z0, z1)]
        return (_metal if lay.metal else _wood)(ctx, band, lay, z0, z1)
