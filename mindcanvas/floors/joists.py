"""Joist / rafter systems and the joist layout of a floor framing layer.

Layer options (overridable per floor with params["overrides"][<layer name>]; lengths in inches):
    system            "wood" | "metal" (library/framing/joists.json: '<system>_joists')
    joist             member profile (default: the system family's member matching the layer
                      thickness; swapping systems keeps the nominal depth, 2x10 <-> 10")
    gauge             metal: 16 | 14
    spacing           on center (default: the system's)
    rim, rim_plies    wood rim profile (default: the joist) and plies; rim_material
    blocking          rows of solid blocking (metal: C blocking + flat strap) at detail LOD
    blocking_spacing  max distance between rows (default 96)
    cavity_fill       insulation between the joists (detail LOD); fill_depth (default full depth)
    fit               "joist" (default): the layer thickness follows the member (metal: + 2 x
                      track thickness, the joists sit inside the rim track); "layer": keep it

Layout (JoistLayout): local frame x = joist direction, y = Z x x (spacing direction). The rim runs
around the boundary (its outside face on the boundary); joists sit every `spacing` from the
boundary's lowest y and run between the rim's inside faces (square cut; a joist whose sides
leave the boundary is dropped, so L-shapes and notches work).
"""

import math

from .. import hgeo, library, profiles, units

FIT_IN = 1.0 / 64
JOIST_FAMILIES = ("lumber", "i_joist", "metal_joist", "lumber_deep")


def system(lib, name):
    """(system name, definition) for "wood" / "metal" / an explicit system name."""
    name = name or "wood"
    fr = lib.data["framing"]
    for cand in (name + "_joists", name):
        if cand in fr and fr[cand].get("use") == "joists":
            return cand, fr[cand]
    raise library.LibraryError("Joist system '{}' not found in library/framing (expected '{}_joists').".format(
        name, name))


def _family(lib, family, gauge=None):
    out = []
    for name, p in lib.data["profiles"].items():
        if p.get("family") == family and (gauge is None or p.get("gauge") == gauge):
            out.append((units.parse_length(p.get("depth", 0)), name, p))
    return sorted(out, key=lambda c: (c[0], c[1]))


def member_depth(p, metal=False):
    """Depth (inches) a member occupies in its layer (metal: + the rim track's 2 x t)."""
    d = units.parse_length(p.get("depth", 0))
    return d + (2 * units.parse_length(p.get("t", 0)) if metal else 0.0)


def select_member(lib, sysd, name, thickness_in, family=None, gauge=None):
    """(profile name, definition, warning or None) for a joist / rafter layer."""
    if name:
        return name, lib.profile(name), None
    fam = family or sysd.get("family")
    metal = sysd.get("type") == "metal"
    if metal and gauge is None:
        gauge = sysd.get("gauge")
    cands = _family(lib, fam, gauge if metal else None)
    msg = None
    if not cands and metal:
        cands = _family(lib, fam)
        msg = "No {} ga members in the '{}' family; using another gauge.".format(gauge, fam)
    if not cands:
        raise library.LibraryError("No '{}' profiles in the library.".format(fam))
    T = thickness_in
    exact = [c for c in cands if abs(member_depth(c[2], metal) - T) < FIT_IN or abs(c[0] - T) < FIT_IN]
    if exact:
        return exact[0][1], exact[0][2], msg
    nominal = None
    for f in JOIST_FAMILIES:
        for d, _, p in _family(lib, f):
            m = f == "metal_joist"
            if (abs(d - T) < FIT_IN or abs(member_depth(p, m) - T) < FIT_IN) and p.get("nominal") is not None:
                nominal = p.get("nominal")
    same = [c for c in cands if nominal is not None and c[2].get("nominal") == nominal]
    if same:
        return same[0][1], same[0][2], msg
    below = [c for c in cands if c[0] <= T + FIT_IN]
    pick = below[-1] if below else cands[0]
    return pick[1], pick[2], "Framing layer is {} deep; using {}.".format(units.format_inches(T), pick[1])


def companion(lib, member, family):
    """Track matching a metal member (nominal + gauge)."""
    best = None
    for _, name, p in _family(lib, family):
        if p.get("nominal") == member.get("nominal"):
            if p.get("gauge") == member.get("gauge"):
                return name, p
            best = best or (name, p)
    return best or (None, None)


def deeper(lib, family, depth_in, metal=False):
    """Shallowest member of a family at least depth_in deep (ridge boards)."""
    cands = _family(lib, family)
    for d, n, p in cands:
        if d >= depth_in - FIT_IN:
            return n, p
    return (cands[-1][1], cands[-1][2]) if cands else (None, None)


def label(sysd, role, profile):
    return sysd.get("names", {}).get(role, "{profile}").format(profile=profile)


def layer_thickness(lib, spec, opts):
    """Inches a joist layer should be (member depth; metal + 2 track t), or None to keep it."""
    if opts.get("fit", "joist") != "joist":
        return None
    _, sysd = system(lib, opts.get("system"))
    T = units.parse_length(spec.get("thickness", 0))
    gauge = opts.get("gauge")
    _, p, _ = select_member(lib, sysd, opts.get("joist"), T, gauge=int(gauge) if gauge else None)
    d = member_depth(p, sysd.get("type") == "metal")
    return d if abs(d - T) > 1e-6 else None


class JoistLayout(object):
    """Members + positions of one floor framing band (model units)."""

    def __init__(self, ctx, band):
        self.ctx, self.band = ctx, band
        lib = ctx.lib
        o = self.opts = ctx.options(band)
        self.system_name, self.sys = system(lib, o.get("system"))
        self.metal = self.sys.get("type") == "metal"
        gauge = o.get("gauge")
        self.joist_name, self.joist, msg = select_member(lib, self.sys, o.get("joist"), band.thickness / ctx.s,
                                                         gauge=int(gauge) if gauge else None)
        if msg:
            ctx.warn(msg)
        self.material = o.get("joist_material") or self.joist.get("material") or self.sys.get("material") \
            or band.material
        w_in, d_in = profiles.size(self.joist)
        self.w, self.D = w_in * ctx.s, d_in * ctx.s
        self.t = ctx.u(self.joist.get("t", 0)) if self.metal else 0.0
        self.spacing = ctx.u(o.get("spacing", self.sys.get("spacing", 16)))
        if self.spacing < 2 * self.w:
            ctx.warn("Joist spacing too small; using {}.".format(units.format_inches(4 * w_in)))
            self.spacing = 4 * self.w
        # rim
        if self.metal:
            self.track_name, self.track = companion(lib, self.joist, self.sys.get("track_family"))
            self.leg = ctx.u(self.track["flange"]) if self.track else ctx.u(1.25)
            self.rim_t = self.t
            self.rim_material = self.material
            self.rim_name = self.track_name or "Joist Track"
        else:
            rim = o.get("rim")
            self.rim_profile = lib.profile(rim) if rim else self.joist
            self.rim_name = rim or self.joist_name
            if self.rim_profile.get("type") not in ("rect",):
                self.rim_profile = {"type": "rect", "width": 1.5, "depth": d_in}
                self.rim_name = "{} Rim".format(self.joist_name)
            self.plies = max(1, int(o.get("rim_plies", self.sys.get("rim_plies", 1))))
            self.ply_t = ctx.u(profiles.size(self.rim_profile)[0])
            self.rim_t = self.plies * self.ply_t
            self.rim_material = o.get("rim_material") or self.rim_profile.get("material") or self.material
        # layout in the joist frame
        self.frame = hgeo.Frame(ctx.jdir)
        self.poly = hgeo.ccw(ctx.local_poly(self.frame))
        self.inner = hgeo.offset_edges(self.poly, [-self.rim_t] * len(self.poly))
        self.z0 = band.d_int
        self.z1 = band.d_ext
        self._place()

    def opt(self, key, default=None):
        return self.opts.get(key, self.sys.get(key, default))

    def name(self, role, profile):
        return label(self.sys, role, profile)

    def _place(self):
        ctx = self.ctx
        x0, y0, x1, y1 = hgeo.bbox(self.poly)
        w, sp = self.w, self.spacing
        eps = ctx.tol * 4
        self.joists = []
        k = 1
        while True:
            y = y0 + k * sp
            k += 1
            if y - 0.5 * w > y1:
                break
            a = hgeo.chords(self.inner, y - 0.5 * w + eps)
            b = hgeo.chords(self.inner, y + 0.5 * w - eps)
            for (a0, a1) in a:
                for (b0, b1) in b:
                    s0, s1 = max(a0, b0), min(a1, b1)
                    if s1 - s0 > ctx.u(6):
                        self.joists.append((y, s0, s1))
        if not self.joists:
            ctx.warn("The floor is too narrow for joists at {} o.c.".format(units.format_inches(sp / ctx.s)))
        self.max_span = max([j[2] - j[1] for j in self.joists] or [0.0])
        limit = self.sys.get("max_span", {}).get(self.joist_name)
        if limit and self.max_span > units.parse_length(limit) * ctx.s + ctx.tol:
            ctx.warn("Joist span {} exceeds the typical {} for {} (library/framing/joists.json).".format(
                units.format_inches(self.max_span / ctx.s), units.format_inches(units.parse_length(limit)),
                self.joist_name))

    def rows(self):
        """x positions of blocking / bridging rows (evenly dividing the joist run)."""
        bs = self.ctx.u(self.opt("blocking_spacing", 96) or 0)
        if bs <= 0 or not self.joists:
            return []
        xa = min(j[1] for j in self.joists)
        xb = max(j[2] for j in self.joists)
        n = int(math.ceil((xb - xa) / bs - 1e-9)) - 1
        return [xa + (i + 1) * (xb - xa) / (n + 1) for i in range(max(0, n))]

    def neighbors(self, x, half):
        """Consecutive joist pairs (y_a, y_b) whose segments both cover [x - half, x + half]."""
        ys = sorted(set(j[0] for j in self.joists if j[1] <= x - half and j[2] >= x + half))
        sp = self.spacing
        return [(a, b) for a, b in zip(ys, ys[1:]) if b - a < 1.5 * sp]

    def plan_rects(self, eps):
        """World plan rectangles (closed polylines) of every joist, slightly longer than the joist."""
        G = hgeo.G
        out = []
        hw = 0.5 * self.w
        for y, x0, x1 in self.joists:
            pts = [self.frame.world(x, yy) for x, yy in ((x0 - eps, y - hw), (x1 + eps, y - hw), (x1 + eps, y + hw),
                                                           (x0 - eps, y + hw), (x0 - eps, y - hw))]
            out.append(G.PolylineCurve(pts))
        return out
