"""Plan (2D) geometry of wall joins. Pure Python (no Rhino), so it can be tested anywhere.

Points and vectors are (x, y) tuples in model units. A wall end is described by a `Side`: the
driver end point P, the unit tangent t of the oriented driver there, n = Z x t (the exterior side,
the direction of positive signed offsets d) and the offsets of the wall's four characteristic faces
(ext >= cext >= cint >= int: exterior face, core faces, interior face).

An `EndCut` says where the layers of a wall end: a list of zones (d_hi, d_lo, line) from the
exterior to the interior. The face of a layer at offset d (the line P + n d + s t) ends where it
crosses the line of the zone it belongs to. Layers straddling a zone boundary get a stepped end
(`cap`).

Rules (see DEVELOPING.md, "Joins"):

L join (two wall ends meet at a corner), style
    wrap   (default) layers outside the core on the outer side of the corner miter with the other
           wall's layers on that side; likewise the layers on the inner side; the primary wall's
           core runs through to the far (outer) core face of the other wall, the secondary core
           stops at the primary's inner core face.
    miter  every layer on one line through the outer and the inner face corners.
    butt   the primary wall runs through to the other's outer face; the secondary stops at the
           primary's inner face.
T join (a wall end meets another wall's side), style
    core   (default) the joining wall's core runs to the host's near core face (the host's
           layers on that side are notched around it); its other layers stop at the host's face.
    butt   the joining wall stops at the host's face.
"""

import math

EPS = 1e-7
STYLES_L = ("wrap", "miter", "butt")
STYLES_T = ("core", "butt")
STYLES = ("auto", "wrap", "miter", "butt", "none")


# -- vectors ------------------------------------------------------------------------------
def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def mul(a, k):
    return (a[0] * k, a[1] * k)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def length(a):
    return math.hypot(a[0], a[1])


def unit(a):
    L = length(a)
    return (a[0] / L, a[1] / L) if L > 0 else (0.0, 0.0)


def left(v):
    """Z x v (90 degrees counter-clockwise)."""
    return (-v[1], v[0])


def neg(a):
    return (-a[0], -a[1])


def sign(x, eps=1e-9):
    return 1 if x > eps else (-1 if x < -eps else 0)


def dist(a, b):
    return length(sub(a, b))


def intersect(p, u, q, v):
    """Parameter s of the point p + s u where the line p + s u meets the line q + r v (None when
    they are parallel)."""
    c = cross(u, v)
    if abs(c) < 1e-12:
        return None
    return cross(sub(q, p), v) / c


class Line(object):
    __slots__ = ("p", "v")

    def __init__(self, p, v):
        self.p = (float(p[0]), float(p[1]))
        self.v = unit(v)

    def at(self, s):
        return add(self.p, mul(self.v, s))

    def meet(self, other):
        s = intersect(self.p, self.v, other.p, other.v)
        return None if s is None else self.at(s)

    def offset_of(self, pt):
        """Signed distance of a point to the left of the line."""
        return cross(self.v, sub(pt, self.p))

    def __repr__(self):
        return "<Line ({:.4f}, {:.4f}) dir ({:.4f}, {:.4f})>".format(self.p[0], self.p[1], self.v[0], self.v[1])


def through(p, q, fallback_dir):
    """Line through two points (along fallback_dir when they coincide)."""
    d = sub(q, p)
    return Line(p, d if length(d) > 1e-9 else fallback_dir)


# -- wall ends ------------------------------------------------------------------------------
class Side(object):
    """A wall in plan near one point: P on the oriented driver, unit tangent t, n = left of t.
    out: +1 at the driver's end, -1 at its start, 0 for a point along the wall (T host).
    ext >= cext >= cint >= int: offsets of the exterior face, the core faces, the interior face."""

    def __init__(self, P, t, out, ext, cext, cint, int_):
        self.P = (float(P[0]), float(P[1]))
        self.t = unit(t)
        self.n = left(self.t)
        self.out = out
        self.ext, self.cext, self.cint, self.int = float(ext), float(cext), float(cint), float(int_)

    @property
    def u(self):
        """Outward direction at an end (away from the wall body)."""
        return mul(self.t, self.out)

    @property
    def thickness(self):
        return self.ext - self.int

    def line(self, d):
        return Line(add(self.P, mul(self.n, d)), self.t)

    def point(self, d, s=0.0):
        return add(add(self.P, mul(self.n, d)), mul(self.t, s))

    def offset_of(self, pt):
        return dot(sub(pt, self.P), self.n)

    def ordered(self, sigma):
        """(outer, core outer, core inner, inner) face offsets for a corner whose inner side is
        this wall's exterior side (sigma > 0) or its interior side (sigma < 0)."""
        if sigma > 0:
            return self.int, self.cint, self.cext, self.ext
        return self.ext, self.cext, self.cint, self.int

    def __repr__(self):
        return "<Side P=({:.3f}, {:.3f}) t=({:.3f}, {:.3f}) out={} [{:.4f} {:.4f} {:.4f} {:.4f}]>".format(
            self.P[0], self.P[1], self.t[0], self.t[1], self.out, self.ext, self.cext, self.cint, self.int)


class Zone(object):
    __slots__ = ("hi", "lo", "line", "name")

    def __init__(self, a, b, line, name=""):
        self.hi, self.lo = max(a, b), min(a, b)
        self.line = line
        self.name = name

    @property
    def width(self):
        return self.hi - self.lo

    def __repr__(self):
        return "<Zone {} [{:.4f}, {:.4f}] {}>".format(self.name, self.lo, self.hi, self.line)


class EndCut(object):
    """Where every layer of one end of a wall stops (see module doc)."""

    def __init__(self, side, zones, kind, style, partner=None, role=""):
        self.side = side
        self.zones = sorted([z for z in zones if z.width > EPS], key=lambda z: -z.hi)
        if not self.zones and zones:
            self.zones = [zones[0]]
        self.kind = kind            # "L" | "T"
        self.style = style
        self.partner = partner      # id of the other wall
        self.role = role            # L: "primary" | "secondary"; T: "joining"

    def zone(self, d, below=True):
        x = d - EPS if below else d + EPS
        for z in self.zones:
            if z.lo <= x <= z.hi:
                return z
        return self.zones[0] if x > self.zones[0].hi else self.zones[-1]

    def s(self, d, below=True):
        """Distance along t from the driver end's perpendicular to where the face at d stops."""
        side = self.side
        z = self.zone(d, below)
        s = intersect(side.point(d), side.t, z.line.p, z.line.v)
        return 0.0 if s is None else s

    def ext(self, d, below=True):
        """How far the face at d runs past the driver end (negative: stops short of it)."""
        return self.side.out * self.s(d, below)

    def point(self, d, below=True):
        return self.side.point(d, self.s(d, below))

    def line_at(self, d):
        """The cut line of the zone containing d (layers wholly inside one zone)."""
        return self.zone(d, True).line

    def reach(self):
        """Largest extension past the driver end over all zone boundaries."""
        ds = set()
        for z in self.zones:
            ds.update((z.hi, z.lo))
        return max([max(self.ext(d, True), self.ext(d, False)) for d in ds] + [0.0])

    def cap(self, d_from, d_to):
        """End points from the face at d_from to the face at d_to, with the steps at zone
        boundaries in between."""
        if d_from < d_to:
            return list(reversed(self.cap(d_to, d_from)))
        pts = [self.point(d_from, True)]
        bounds = set()
        for z in self.zones:
            bounds.update((z.hi, z.lo))
        for b in sorted(bounds, reverse=True):
            if d_to + EPS < b < d_from - EPS:
                pts.append(self.point(b, False))
                pts.append(self.point(b, True))
        pts.append(self.point(d_to, False))
        out = []
        for p in pts:
            if not out or dist(p, out[-1]) > 1e-9:
                out.append(p)
        return out

    def __repr__(self):
        return "<EndCut {} {} {} zones={}>".format(self.kind, self.style, self.role, self.zones)


# -- rules ------------------------------------------------------------------------------------
def corner_sides(a, b):
    """sigma for each wall of an L: +1 when the other wall's body lies on its exterior side."""
    return sign(dot(neg(b.u), a.n)), sign(dot(neg(a.u), b.n))


def l_cut(a, b, style="wrap", primary=True, partner=None):
    """EndCut of wall end `a` meeting wall end `b` at an L."""
    sa, sb = corner_sides(a, b)
    if sa == 0 or sb == 0:
        return None
    ao, aco, aci, ai = a.ordered(sa)
    bo, bco, bci, bi = b.ordered(sb)
    X = lambda da, db: a.line(da).meet(b.line(db))
    role = "primary" if primary else "secondary"
    if style == "miter":
        zones = [Zone(a.ext, a.int, through(X(ao, bo), X(ai, bi), b.t), "all")]
    elif style == "butt":
        zones = [Zone(a.ext, a.int, b.line(bo if primary else bi), "all")]
    else:
        style = "wrap"
        zones = [Zone(ao, aco, through(X(ao, bo), X(aco, bco), b.t), "outer"),
                 Zone(aco, aci, b.line(bco if primary else bci), "core"),
                 Zone(aci, ai, through(X(aci, bci), X(ai, bi), b.t), "inner")]
    return EndCut(a, zones, "L", style, partner, role)


def host_side(host, sigma):
    """(near finish face, near core face) offsets of a T host on side sigma."""
    return (host.ext, host.cext) if sigma > 0 else (host.int, host.cint)


def t_sigma(b, host):
    """Side of the host where the joining wall's body lies (+1 = the host's exterior side)."""
    return sign(dot(neg(b.u), host.n))


def t_cut(b, host, style="core", partner=None):
    """EndCut of wall end `b` meeting the side of `host` (a Side at the closest point, out = 0)."""
    sigma = t_sigma(b, host)
    if sigma == 0:
        return None
    df, dc = host_side(host, sigma)
    hf, hc = host.line(df), host.line(dc)
    if style == "butt":
        zones = [Zone(b.ext, b.int, hf, "all")]
    else:
        style = "core"
        zones = [Zone(b.ext, b.cext, hf, "outer"), Zone(b.cext, b.cint, hc, "core"), Zone(b.cint, b.int, hf, "inner")]
    return EndCut(b, zones, "T", style, partner, "joining")


def t_notch(b, host, eps):
    """Plan polygon of the joining wall's core through the host's layers on its side, and the
    host offset range (lo, hi) those layers occupy. None when there is nothing to notch."""
    sigma = t_sigma(b, host)
    if sigma == 0:
        return None
    df, dc = host_side(host, sigma)
    if abs(df - dc) <= EPS or abs(b.cext - b.cint) <= EPS:
        return None
    hc = host.line(dc - sigma * eps)
    hf = host.line(df + sigma * eps)
    e, i = b.line(b.cext), b.line(b.cint)
    pts = [e.meet(hc), e.meet(hf), i.meet(hf), i.meet(hc)]
    if any(p is None for p in pts):
        return None
    return pts, (min(df, dc), max(df, dc))


class Backer(object):
    """An extra stud in a host wall's framing where another wall's core face meets it.
    line: the other wall's core face line; side: the host wall near the crossing (its t / n);
    shift: plan direction and amount (in stud widths) to move the stud off the line."""
    __slots__ = ("line", "side", "shift_dir", "shift")

    def __init__(self, line, side, shift_dir=(0.0, 0.0), shift=0.0):
        self.line, self.side, self.shift_dir, self.shift = line, side, unit(shift_dir) if shift else (0.0, 0.0), shift

    def point(self, d, w):
        """Plan point of the backer stud on the host face line at offset d (stud width w)."""
        p = self.side.line(d).meet(self.line)
        if p is None:
            return None
        return add(p, mul(self.shift_dir, self.shift * w))


def l_backer(a, b, primary, style):
    """Backer stud in wall a's framing at an L (primary, wrap / butt): flush with the inner core
    face of b, on a's body side, so a's inner finish has nailing at the corner."""
    if not primary or style == "miter":
        return None
    sa, sb = corner_sides(a, b)
    if sb == 0:
        return None
    bci = b.ordered(sb)[2]
    return Backer(b.line(bci), a, neg(a.u), 0.5)


def t_backers(b, host):
    """Two studs in the host's framing, centered on the joining wall's core faces."""
    return [Backer(b.line(b.cext), host), Backer(b.line(b.cint), host)]


# -- detection helpers ---------------------------------------------------------------------------
def l_meeting(a, b, snap):
    """(score, X) when wall ends a and b meet at an L, else None: their end lines cross at X near
    both ends (within the other wall's thickness + snap) at an angle of 15..165 degrees."""
    if abs(cross(a.u, b.u)) < math.sin(math.radians(15.0)):
        return None
    sa = intersect(a.P, a.u, b.P, b.u)
    sb = intersect(b.P, b.u, a.P, a.u)
    if sa is None or sb is None:
        return None
    ra, rb = b.thickness + snap, a.thickness + snap
    if not (-ra <= sa <= ra and -rb <= sb <= rb):
        return None
    return abs(sa) + abs(sb), a.P if sa == 0 else add(a.P, mul(a.u, sa))


def t_meeting(b, host, snap):
    """Score (distance of b's end to the host's near face) when the end of b lies within the host
    wall (its faces +- snap) and b meets it at 15..165 degrees, else None."""
    if abs(cross(b.u, host.t)) < math.sin(math.radians(15.0)):
        return None
    sigma = t_sigma(b, host)
    if sigma == 0:
        return None
    d = host.offset_of(b.P)
    if not (host.int - snap <= d <= host.ext + snap):
        return None
    df, dc = host_side(host, sigma)
    return abs(d - df)


def resolve_style(mine, theirs, primary):
    """Join style of an L from both ends' settings: 'none' anywhere wins, then the primary's
    explicit style, then the other's, then 'wrap'."""
    if mine == "none" or theirs == "none":
        return "none"
    first, second = (mine, theirs) if primary else (theirs, mine)
    for s in (first, second):
        if s in STYLES_L:
            return s
    return "wrap"


def primary_of(a_key, b_key):
    """True when the wall with sort key a_key runs through (keys: (priority, core thickness, id))."""
    return a_key > b_key
