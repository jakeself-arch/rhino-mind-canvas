"""Brick veneer accessories: adjustable ties, through-wall flashing, shelf angles, soft joints.

Every masonry layer builds its own accessories from its options (so per-wall layer stacks work):
    ties   true (default) | false | {spacing_v 16, spacing_h 24, first 16 (first row above the brick
           base), cover 5/8 (wire end to brick face), wire 3/16, stagger false, material "Brick Tie"}
           Rows land on the nearest bed joint; columns follow the studs (framing.stud_stations) of the
           nearest framing layer behind the brick, else 16" o.c. from the start of the driver.
    base   "ledge" (default) | "shelf_angle" | false | {support: ledge | shelf_angle | none,
           angle: auto | "L4x4x3/8", material "Flashing", thickness 1/32, upturn 8,
           slope 1/2 (drop across the air space), drip 3/8 (past the brick face),
           top: {"soft_joint": "3/8", "angle": "auto"} - soft joint + shelf angle above the veneer}
           Only for brick whose exposed face is the exterior.

The brick's exposed face (exterior or interior, see masonry.exposed_side), the air space and the
backup (first solid layer behind the brick) are found from ctx.bands.
Assembly `extras` with component "brick_ties" / "veneer_base" do the same for every masonry layer
(or the one named by option "veneer") with the extra's options; the layers then skip their own.
LOD: ties and flashing at detail, shelf angles from design up.
"""

import math

import Rhino

from .. import geo, units
from . import masonry
from .base import Component, Part, register

G = Rhino.Geometry


class Stack(object):
    """Brick, air space and backup positions for one masonry band, in the veneer's own
    offsets (masonry.Veneer: positive = toward the exposed face)."""

    def __init__(self, ctx, vb):
        self.vb = vb
        v = self.v = masonry.layout(ctx, vb)
        sg = self.sign = v.sign
        behind = sorted([b for b in ctx.bands if (b.index - vb.index) * sg > 0], key=lambda b: b.index * sg)
        self.backup = None
        for b in behind:
            if b.component != "void" and b.thickness > ctx.tol:
                self.backup = b
                break
        self.framing = None
        for test in (lambda b: b.component == "framing", lambda b: b.spec.get("core")):
            for b in behind:
                if test(b):
                    self.framing = b
                    break
            if self.framing is not None:
                break
        self.y_face = v.y_face
        self.y_back = v.y_face - v.D
        self.y_bk = self.near(self.backup) if self.backup else None

    def near(self, b):
        """Offset of the face of band b that looks toward the brick."""
        return b.d_ext if self.sign > 0 else -b.d_int

    @property
    def gap(self):
        return None if self.y_bk is None else self.y_back - self.y_bk


def _cyl(p0, p1, r):
    axis = p1 - p0
    h = axis.Length
    if h < 1e-9:
        return None
    return G.Cylinder(G.Circle(G.Plane(p0, axis), r), h).ToBrep(True, True)


# -- ties ------------------------------------------------------------------
def tie_geometry(s, gap, emb, screw, wire):
    """Adjustable eye & pintle tie, inches -> model units by s. Origin on the backup face at
    the bed joint centerline; X along the wall, Y toward the brick, Z up."""
    P = lambda x, y, z: G.Point3d(x * s, y * s, z * s)
    r = wire * 0.5 * s
    out = []
    plate_t = 0.105
    out.append(G.Box(G.Plane.WorldXY, G.Interval(-0.625 * s, 0.625 * s), G.Interval(0, plate_t * s),
                     G.Interval(0.5 * s, 3.5 * s)).ToBrep())
    out.append(_cyl(P(0, plate_t + 0.12, 2.75), P(0, -screw, 2.75), 0.11 * s))
    out.append(_cyl(P(0, plate_t, 2.75), P(0, plate_t + 0.12, 2.75), 0.25 * s))
    eye_y = max(0.3, min(0.75, gap * 0.4))
    ring_r = 0.22
    yp = eye_y + ring_r
    for x in (-0.5, 0.5):
        out.append(_cyl(P(x, plate_t, 1.25), P(x, eye_y, 1.25), r))
        tor = G.Torus(G.Plane(P(x, yp, 1.25), G.Vector3d.ZAxis), ring_r * s, r * 0.9)
        out.append(G.Brep.CreateFromSurface(tor.ToNurbsSurface()))
        out.append(_cyl(P(x, yp, 0), P(x, yp, 1.85), r))
        out.append(_cyl(P(x, yp, 0), P(x, emb, 0), r))
        out.append(G.Brep.CreateFromSphere(G.Sphere(P(x, yp, 0), r)))
        out.append(G.Brep.CreateFromSphere(G.Sphere(P(x, emb, 0), r)))
    out.append(_cyl(P(-0.5, emb, 0), P(0.5, emb, 0), r))
    return [g for g in out if g is not None]


def _stations(ctx, st, spacing):
    """Distances along ctx.curve (from its start) for tie columns."""
    crv = ctx.curve
    L = crv.GetLength()
    cands = None
    if st.framing is not None and st.framing.component == "framing":
        try:
            from .framing import stud_stations
            cands = list(stud_stations(ctx, st.framing))
        except Exception as e:  # framing missing or failed: fall back to 16" o.c.
            ctx.warn("Brick ties: stud stations unavailable ({}); using 16\" o.c.".format(e))
    if not cands:
        step = ctx.u(16)
        cands = [i * step for i in range(int(L / step) + 1)]
    t0 = crv.Domain.T0
    kinks = [crv.GetLength(G.Interval(t0, t)) for t in geo.kink_parameters(crv)]
    if crv.IsClosed:
        kinks += [0.0, L]
    clear = ctx.u(3)
    ok = []
    for s in sorted(cands):
        if not crv.IsClosed and (s < clear or s > L - clear):
            continue
        if any(abs(s - k) < clear for k in kinks):
            continue
        if not ok or s - ok[-1] > ctx.u(1):
            ok.append(s)
    chosen = []
    i = 0
    eps = ctx.u(0.05)
    while i < len(ok):
        if not chosen:
            chosen.append(ok[i])
            i += 1
            continue
        best = None
        k = i
        while k < len(ok) and ok[k] - chosen[-1] <= spacing + eps:
            best = k
            k += 1
        best = i if best is None else best
        chosen.append(ok[best])
        i = best + 1
    return chosen


def build_ties(ctx, vb, o, material=None):
    if ctx.lod != "detail":
        return []
    st = Stack(ctx, vb)
    v = st.v
    s = ctx.s
    material = o.get("material", material or "Brick Tie")
    if st.backup is None:
        ctx.warn("{}: no backup layer behind the brick; no ties.".format(vb.name))
        return []
    if st.gap < ctx.u(0.5):
        ctx.warn("{}: less than 1/2\" air space behind the brick; no ties.".format(vb.name))
        return []
    sv, sh, first = ctx.u(o.get("spacing_v", 16)), ctx.u(o.get("spacing_h", 24)), ctx.u(o.get("first", 16))
    cover = ctx.u(o.get("cover", "5/8"))
    wire = units.parse_length(o.get("wire", "3/16"))
    beds = v.bed_joints()
    if not beds:
        return []
    top = v.courses[-1].top
    rows = []
    z = v.z0 + first
    while z < top - ctx.u(4):
        zb = min(beds, key=lambda b: abs(0.5 * (b[0] + b[1]) - z))
        zm = 0.5 * (zb[0] + zb[1])
        if not rows or zm - rows[-1] > ctx.tol:
            rows.append(zm)
        z += sv
    stations = _stations(ctx, st, sh)
    if not rows or not stations:
        return []
    if st.framing is not None:
        tip = st.near(st.framing) - ctx.u(0.75)
    else:
        tip = st.y_bk - ctx.u(1.5)
    gap_in = st.gap / s
    emb_in = (st.y_face - cover - st.y_bk) / s
    screw_in = (st.y_bk - tip) / s
    name = "MC {} g{:.4f} e{:.4f} s{:.4f} w{:.4f}".format(material, gap_in, emb_in, screw_in, wire)
    idx = ctx.block(name, tie_geometry(s, gap_in, emb_in, screw_in, wire), material)
    crv = ctx.curve
    sg = st.sign
    frames = []
    for sta in stations:
        ok, t = crv.LengthParameter(sta)
        if ok:
            frames.append(geo.frame_at(crv, t))
    stagger = bool(o.get("stagger", False))
    parts = []
    for ri, zr in enumerate(rows):
        use = frames[ri % 2::2] if (stagger and len(frames) > 2) else frames
        for f in use:
            p = f.Origin + f.YAxis * (sg * st.y_bk)
            plane = G.Plane(G.Point3d(p.X, p.Y, zr), f.XAxis * sg, f.YAxis * sg)
            parts.append(Part(material=material, role="brick_tie", block=idx,
                              xform=G.Transform.PlaneToPlane(G.Plane.WorldXY, plane),
                              extra={"embed": round(emb_in - gap_in, 3)}))
    return parts


# -- base: flashing, shelf angle, soft joint --------------------------------
def thicken(path, t):
    """Polygon of a sheet of thickness t lying on the LEFT of a (y, z) polyline."""
    segs = []
    for (y0, z0), (y1, z1) in zip(path, path[1:]):
        dy, dz = y1 - y0, z1 - z0
        l = math.hypot(dy, dz)
        segs.append((-dz / l, dy / l))
    offs = []
    for i, (y, z) in enumerate(path):
        if i == 0:
            n, k = segs[0], t
        elif i == len(path) - 1:
            n, k = segs[-1], t
        else:
            a, b = segs[i - 1], segs[i]
            n = (a[0] + b[0], a[1] + b[1])
            ln = math.hypot(*n)
            n = (n[0] / ln, n[1] / ln)
            k = t / max(0.2, n[0] * b[0] + n[1] * b[1])
        offs.append((y + n[0] * k, z + n[1] * k))
    return list(path) + offs[::-1]


def _angles(lib):
    out = []
    for name, p in lib.data["profiles"].items():
        if p.get("type") == "angle" and p.get("family") == "steel_angle":
            out.append((units.parse_length(p["a"]), name, p))
    return sorted(out, key=lambda c: (c[0], c[1]))


def _angle(ctx, st, choice):
    lib = ctx.lib
    if choice and choice != "auto":
        return choice, lib.profile(choice)
    cands = _angles(lib)
    if not cands:
        raise ValueError("no steel_angle profiles in the library")
    s = ctx.s
    need = (st.y_back - st.y_bk + st.v.D * 2.0 / 3.0) / s
    most = (st.y_face - st.y_bk) / s - 0.25
    fits = [c for c in cands if need - 1e-6 <= c[0] <= most + 1e-6]
    if fits:
        return fits[0][1], fits[0][2]
    bigger = [c for c in cands if c[0] >= need - 1e-6]
    pick = bigger[0] if bigger else cands[-1]
    ctx.warn("Shelf angle: no angle gives 2/3 bearing within the brick face; using {}.".format(pick[1]))
    return pick[1], pick[2]


def _support(ctx, st, o, zl, support, material, angle_choice=None):
    detail = ctx.lod == "detail"
    tf = ctx.u(o.get("thickness", "1/32"))
    crv = st.v.curve
    parts = []
    length_in = round(geo.offset(crv, st.y_face, ctx.tol).GetLength() / ctx.s, 3)
    if support == "shelf_angle":
        name, p = _angle(ctx, st, angle_choice or o.get("angle", "auto"))
        a, b, t = [ctx.u(p[k]) for k in ("a", "b", "t")]
        zt = zl - tf
        yh = st.y_bk
        poly = [(yh, zt), (yh + a, zt), (yh + a, zt - t), (yh + t, zt - t), (yh + t, zt - b), (yh, zt - b)]
        mat = o.get("angle_material", "Steel Angle")
        for s_ in masonry.profile_solids(ctx, poly, crv):
            parts.append(Part(s_, mat, role="shelf_angle", extra={"profile": name, "length": length_in}))
    elif support not in ("ledge", "none"):
        ctx.warn("Veneer base: unknown support '{}'.".format(support))
    if detail:
        up, rise = ctx.u(o.get("upturn", 8)), ctx.u(o.get("slope", "1/2"))
        drip = ctx.u(o.get("drip", "3/8"))
        zf = zl - tf
        path = [(st.y_bk, zl + up), (st.y_bk, zf + rise), (st.y_back, zf),
                (st.y_face + drip - ctx.u(0.25), zf), (st.y_face + drip, zf - ctx.u(0.25))]
        if st.gap < rise * 1.5:
            path = [path[0], (st.y_bk, zf)] + path[3:]
        for s_ in masonry.profile_solids(ctx, thicken(path, tf), crv):
            parts.append(Part(s_, material, role="flashing", extra={"length": length_in}))
    return parts


def _soft_joint(ctx, st, o, top, material):
    g = ctx.u(top.get("soft_joint", "3/8"))
    zt = st.v.courses[-1].top if st.v.courses else st.v.z1
    crv = st.v.curve
    parts = []
    if ctx.lod == "detail":
        yf = st.y_face
        seal = [(yf - ctx.u(0.375), zt), (yf - ctx.u(0.0625), zt), (yf - ctx.u(0.0625), zt + g),
                (yf - ctx.u(0.375), zt + g)]
        for s_ in masonry.profile_solids(ctx, seal, crv):
            parts.append(Part(s_, top.get("sealant", "Sealant"), role="sealant"))
        rw = ctx.u(top.get("rod", "1/2"))
        cy, cz = yf - ctx.u(0.375) - rw * 0.5, zt + g * 0.5
        rod = [(cy + 0.5 * rw * math.cos(a), cz + 0.5 * g * 0.98 * math.sin(a))
               for a in [i * math.pi / 8 for i in range(16)]]
        for s_ in masonry.profile_solids(ctx, rod, crv):
            parts.append(Part(s_, top.get("backer", "Backer Rod"), role="backer_rod"))
    name, p = _angle(ctx, st, top.get("angle", "auto"))
    zl = zt + g + ctx.u(p["t"]) + ctx.u(o.get("thickness", "1/32"))
    return parts + _support(ctx, st, o, zl, "shelf_angle", material, name)


def build_base(ctx, vb, o, material=None):
    if ctx.lod == "schematic":
        return []
    st = Stack(ctx, vb)
    if st.sign < 0:
        return []   # interior-exposed brick: no flashing / shelf angle
    if st.backup is None:
        ctx.warn("{}: no backup layer behind the brick; no flashing.".format(vb.name))
        return []
    material = o.get("material", material or "Flashing")
    parts = _support(ctx, st, o, st.v.z0, str(o.get("support", "ledge")).lower(), material)
    top = o.get("top")
    if top:
        parts += _soft_joint(ctx, st, o, top if isinstance(top, dict) else {"soft_joint": "3/8"}, material)
    return parts


def _opts(value, key=None):
    if isinstance(value, dict):
        return value
    if key and isinstance(value, str):
        return {key: value}
    return {}


def accessories(ctx, band):
    """Ties + base owned by a masonry layer (skipped when assembly extras provide them)."""
    extras = set(e.get("component") for e in ctx.assembly.get("extras", []))
    o = ctx.options(band)
    out = []
    ties = o.get("ties", True)
    if ties and "brick_ties" not in extras:
        out += build_ties(ctx, band, _opts(ties))
    base = o.get("base", "ledge")
    if base and "veneer_base" not in extras:
        out += build_base(ctx, band, _opts(base, "support"))
    return out


@register
class BrickTies(Component):
    """Assembly extra: ties for every masonry layer (or the one named by option `veneer`)."""
    name = "brick_ties"

    def build(self, ctx, band):
        o = ctx.options(band)
        out = []
        for vb in masonry.masonry_bands(ctx, o.get("veneer")):
            out += build_ties(ctx, vb, o, band.material)
        return out


@register
class VeneerBase(Component):
    """Assembly extra: flashing / shelf angle under every exterior-exposed masonry layer."""
    name = "veneer_base"

    def build(self, ctx, band):
        o = ctx.options(band)
        out = []
        for vb in masonry.masonry_bands(ctx, o.get("veneer")):
            out += build_base(ctx, vb, o, band.material)
        return out
