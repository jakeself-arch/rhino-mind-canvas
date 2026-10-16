"""Brick veneer: individual bricks (block instances), mortar joints, bonds, special courses.

Layer options (lengths in inches):
    brick        modular | norman | engineer | king | utility | roman
                 or {"length", "height", "depth", "coursing": [courses, height], "name"}
    bond         running | third | quarter | stack | flemish | english | common
    header_every common bond: a header course every Nth course (default 6)
    joint        head joint (default 3/8); bed joints follow the coursing (modular: 3 courses = 8")
    tooling      flush | concave | vee | struck | weathered | raked | <recess>
    courses      special courses: [{"type": "soldier" | "rowlock" | "sailor" | "shiner" | "header",
                 "at": "bottom" | "top" | <course index> | "<elevation above the brick base>", "count": 1}]
    top_course   cut (default) | round | gap   - when the height is not a whole number of courses
    weeps        weep vent spacing in the first course (default 24; 0 = none)
    mortar       mortar material (default "Mortar"), weep_material (default "Weep Vent")
    jockey       max head-joint adjustment used to bond out a run (default 1/16)
    face         auto (default: the side with no solid layer beyond the brick) | exterior | interior
    ties, base   accessories built with the layer - see veneer.py (default: ties + ledge flashing;
                 base and weeps only for an exterior-exposed face)

Coursing starts at ctx.z_range(band)[0]; each course = bed joint + brick. Corners (90 deg) lap:
alternate courses run through, the other leg stops behind them. Other angles are mitered.
Joined wall ends (mindcanvas/joins) stop on the join's cut line (JoinEnd); a square L between two
brick walls laps like a corner (the primary wall runs through on even courses).
Arcs and free curves get straight bricks on chords laid tight on the inner side; head joints open
up toward the outer side.
LOD: schematic = solid band, design = bricks, detail = bricks + bed/head joints + weeps.

Openings (ctx.openings, see MOpening): courses inside a masonry opening are split around it
(the bond is unchanged outside; jamb-end pieces shorter than min_piece are merged with their
neighbor into two equal closures), a course crossing the sill line is cut down to it, bed joints
are cut out. Steel angle lintel in the first bed joint over the head (bearing each side),
optional soldier / sailor course on it, rowlock sill, flashing with end dams, weeps over the
lintel, sealant + backer rod at the frame. Opening options live in the opening type ("masonry").

`layout(ctx, band)` gives the cached Veneer (coursing + geometry), used by veneer.py
(ties, flashing, shelf angles) to land on the same bed joints.
"""

import hashlib
import math

import Rhino

from .. import geo, units
from ..openings import core as openings
from .base import Component, Part, register

G = Rhino.Geometry

# name, length, height, depth, (courses, height) - inches
BRICKS = {
    "modular":  ("Modular", 7.625, 2.25, 3.625, (3, 8)),
    "norman":   ("Norman", 11.625, 2.25, 3.625, (3, 8)),
    "engineer": ("Engineer Modular", 7.625, 2.8125, 3.625, (5, 16)),
    "king":     ("King", 9.625, 2.625, 3.0, (5, 16)),
    "utility":  ("Utility", 11.625, 3.625, 3.625, (1, 4)),
    "roman":    ("Roman", 11.625, 1.625, 3.625, (2, 4)),
}
TOOLING = {"flush": 0.0, "concave": 0.0625, "vee": 0.125, "struck": 0.125, "weathered": 0.125, "raked": 0.25}
BONDS = ("running", "third", "quarter", "stack", "flemish", "english", "common")
QDIV = {"running": 2, "common": 2, "stack": 1, "third": 3, "quarter": 4, "flemish": 4, "english": 4}
ROLES = {"stretcher": "brick", "header": "brick_header", "soldier": "brick_soldier",
         "rowlock": "brick_rowlock", "sailor": "brick_sailor", "shiner": "brick_shiner"}
Z = G.Vector3d.ZAxis


def _frac(v):
    return units.format_inches(v).replace('"', "")


def _htan(v):
    v = G.Vector3d(v.X, v.Y, 0)
    v.Unitize()
    return v


# -- 2D helpers (leg-local x along the wall, y = signed offset) -----------
def _rect(x0, x1, y0, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _clip(poly, a, b, sign, eps=1e-9):
    """Keep the part of a convex polygon where sign * (x - (a + b*y)) >= 0."""
    out = []
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        fp = sign * (p[0] - a - b * p[1])
        fq = sign * (q[0] - a - b * q[1])
        if fp >= -eps:
            out.append(p)
        if (fp > eps and fq < -eps) or (fp < -eps and fq > eps):
            t = fp / (fp - fq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    clean = []
    for p in out:
        if not clean or abs(p[0] - clean[-1][0]) > eps or abs(p[1] - clean[-1][1]) > eps:
            clean.append(p)
    if len(clean) > 1 and abs(clean[0][0] - clean[-1][0]) <= eps and abs(clean[0][1] - clean[-1][1]) <= eps:
        clean.pop()
    return clean if len(clean) >= 3 and _area(clean) > 1e-10 else []


def _area(poly):
    s = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        s += x0 * y1 - x1 * y0
    return abs(s) * 0.5


def _clip_all(poly, planes):
    for a, b, sign in planes:
        if not poly:
            break
        poly = _clip(poly, a, b, sign)
    return poly


def prism(local, h):
    """Extrusion of a closed polygon (list of (x, y)) from z = 0 up to h."""
    pts = [G.Point3d(x, y, 0) for x, y in local]
    pts.append(pts[0])
    pc = G.PolylineCurve(pts)
    ext = G.Extrusion.Create(pc, h, True)
    if ext is None:
        return None
    if ext.GetBoundingBox(True).Min.Z < -1e-9:
        ext = G.Extrusion.Create(pc, -h, True)
    return ext


def profile_solids(ctx, poly, curve=None):
    """Closed (y, z) profile swept along the whole driver: y = signed offset, z = elevation.
    Corners are mitered, closed drivers give rings."""
    cache = {}
    crvs = []
    for y, z in poly:
        key = round(y, 9)
        if key not in cache:
            cache[key] = geo.offset(curve or ctx.curve, y, ctx.tol)
        c = cache[key].DuplicateCurve()
        c.Translate(G.Vector3d(0, 0, z - c.PointAtStart.Z))
        crvs.append(c)
    crvs.append(crvs[0].DuplicateCurve())
    res = G.Brep.CreateFromLoft(crvs, G.Point3d.Unset, G.Point3d.Unset, G.LoftType.Straight, False)
    out = []
    for b in res or []:
        if not b.IsSolid:
            b = b.CapPlanarHoles(ctx.tol) or b
        b.Faces.SplitKinkyFaces(Rhino.RhinoMath.DefaultAngleTolerance, True)
        if b.SolidOrientation == G.BrepSolidOrientation.Inward:
            b.Flip()
        out.append(b)
    return out


# -- driver legs and corners ----------------------------------------------
class Leg(object):
    """A kink-free piece of the driver. Straight legs work in local (x, y);
    curved legs lay bricks on chords of their inner offset."""

    def __init__(self, crv, tol, closed=False):
        self.crv = crv
        self.closed = closed
        self.straight = (not closed) and crv.IsLinear(tol)
        self.start = self.end = None
        self.delta = 0.0         # bond shift, fraction of a stretcher module
        self.j = None
        self.t_start = _htan(crv.TangentAtStart)
        self.t_end = _htan(crv.TangentAtEnd)
        self.length = crv.GetLength()
        self._inner = {}
        self.tol = tol
        if self.straight:
            p0, p1 = crv.PointAtStart, crv.PointAtEnd
            self.p0 = G.Point3d(p0.X, p0.Y, 0)
            t = G.Vector3d(p1.X - p0.X, p1.Y - p0.Y, 0)
            self.length = t.Length
            t.Unitize()
            self.t = t
            self.n = G.Vector3d.CrossProduct(Z, t)
            self.concave = False
        else:
            tm = crv.Domain.Mid
            k = crv.CurvatureAt(tm)
            nm = G.Vector3d.CrossProduct(Z, _htan(crv.TangentAt(tm)))
            self.concave = (k.X * nm.X + k.Y * nm.Y) > 0   # center of curvature on the exterior side

    def inner(self, y):
        key = round(y, 9)
        if key not in self._inner:
            self._inner[key] = geo.offset(self.crv, y, self.tol)
        return self._inner[key]


class Corner(object):
    def __init__(self, a, b):
        self.a, self.b = a, b
        a.end = self
        b.start = self
        ta, tb = a.t_end, b.t_start
        na = G.Vector3d.CrossProduct(Z, ta)
        nb = G.Vector3d.CrossProduct(Z, tb)
        self.nn = na * nb
        self.ta_nb = ta * nb
        self.tb_na = tb * na
        self.lap = a.straight and b.straight and abs(self.nn) < 0.01
        self.straight = a.straight and b.straight
        self.p = 0

    def a_through(self, i):
        return (i + self.p) % 2 == 0

    def end_line(self, la, y_f, y_b, through):
        if self.lap:
            xs = [la + c / self.ta_nb for c in (y_f, y_b)]
            return (max(xs) if through else min(xs)), 0.0
        return la, (1.0 - self.nn) / self.ta_nb

    def start_line(self, y_f, y_b, through):
        if self.lap:
            xs = [c / self.tb_na for c in (y_f, y_b)]
            return (min(xs) if through else max(xs)), 0.0
        return 0.0, (1.0 - self.nn) / self.tb_na


class JoinEnd(object):
    """A wall end joined to another wall (mindcanvas/joins), seen from one straight leg: the
    leg's courses stop on the join's cut line x = a + b*y (leg coordinates). At a square corner
    with brick on both walls (cut.lap) alternate courses lap: the primary wall's bricks run
    through on even courses, the other wall's on odd ones, so the two walls bond."""

    straight = True
    fixed = True       # the parity is shared with the other wall: never re-optimized

    def __init__(self, leg, cut, d, at_start):
        self.at_start = at_start
        self.p = 0
        self.ab = self._local(leg, cut.line_at(d))
        lap = getattr(cut, "lap", None)
        self.lap = False
        if lap is not None:
            front, back = self._local(leg, lap[0]), self._local(leg, lap[1])
            if abs(front[1]) < 0.02 and abs(back[1]) < 0.02:
                self.lap = True
                self.x_front, self.x_back, self.primary = front[0], back[0], lap[2]

    @staticmethod
    def _local(leg, line):
        q = G.Vector3d(line.p[0] - leg.p0.X, line.p[1] - leg.p0.Y, 0)
        v = G.Vector3d(line.v[0], line.v[1], 0)
        xq, yq = q * leg.t, q * leg.n
        vt, vn = v * leg.t, v * leg.n
        if abs(vn) < 1e-9:      # a cut along the leg cannot happen at a join (>= 15 degrees)
            return xq, 0.0
        b = vt / vn
        return xq - b * yq, b

    def mine(self, i):
        return (i % 2 == 0) == bool(self.primary)

    def a_through(self, i):
        if not self.lap:
            return False
        return (not self.mine(i)) if self.at_start else self.mine(i)

    def end_line(self, la, y_f, y_b, through):
        if self.lap:
            return (self.x_front if through else self.x_back), 0.0
        return self.ab

    def start_line(self, y_f, y_b, through):
        if self.lap:
            return (self.x_front if through else self.x_back), 0.0
        return self.ab


class Course(object):
    def __init__(self, index, k, z, bed, h, special=None, cut=False):
        self.index = index      # position from the bottom
        self.k = k              # regular-course counter (drives the bond); None for specials
        self.z = z              # bottom of the bed joint
        self.bed = bed
        self.h = h              # unit height in this course
        self.special = special
        self.cut = cut
        self.d = 0.0

    @property
    def zb(self):
        return self.z + self.bed

    @property
    def top(self):
        return self.z + self.bed + self.h

    def __repr__(self):
        return "<Course {} {} z={:.4f}>".format(self.index, self.special or self.k, self.z)


class MOpening(object):
    """An opening as seen by one masonry layer (veneer coordinates: y toward the exposed face).

    Exterior brick (the outermost exterior-exposed masonry layer, which sets the unit's frame
    position): masonry opening = unit + sealant joint; steel angle lintel in the bed joint of
    the first course clear of the frame head (+ joint); optional soldier / sailor course on the
    lintel; rowlock sill sloped outward on a mortar wedge, the course under it cut to fit;
    head and sill flashing, end dams, weeps over the lintel, sealant + backer rod.
    Any other masonry layer (e.g. interior brick): opening = rough opening, lintel, the course
    at the sill cut to the rough opening.
    """

    def __init__(self, v, op):
        ctx = v.ctx
        u = ctx.u
        self.v, self.op = v, op
        self.m = m = op.t.get("masonry", {})
        self.ext = v.sign > 0 and op.masonry_ext is not None and op.masonry_ext.index == v.band.index
        self.hx = 0.5 * op.W + op.joint if self.ext else op.rx
        self.bearing = u(m.get("bearing", 6))
        need = (op.z1 + op.joint) if self.ext else op.rz1
        self.k_head = None
        for c in v.courses[1:]:
            if c.z >= need - u(1.0 / 32):
                self.k_head = c.index
                break
        if self.k_head is None:
            self.z_top = v.z1 + u(12)
            ctx.warn("Opening '{}' reaches the top of the brick; no lintel.".format(op.name))
        else:
            self.z_top = v.courses[self.k_head].z
            gap = self.z_top - need
            if gap > u(0.5):
                ctx.warn("Brick over '{}': the lintel sits {} above the frame head + joint (next bed joint). "
                         "Use SnapHead (MCOpening / MCEditOpening) to put the head on the coursing.".format(op.name, units.format_inches(gap / ctx.s)))
        # head course on the lintel
        self.head, self.n_head, self.head_top = None, 0, self.z_top
        if op.head in ("soldier", "sailor") and self.k_head is not None:
            n = max(1, int(round((v.L + v.bed0) / v.ch)))
            ks = range(self.k_head, self.k_head + n)
            if ks[-1] < len(v.courses):
                self.head, self.n_head = op.head, n
                self.head_top = v.courses[ks[-1]].top
            else:
                ctx.warn("No room for a {} course over '{}'.".format(op.head, op.name))
        # sill
        sill = "none" if op.door else str(m.get("sill", "rowlock")).lower()
        self.rowlock = None
        if op.door:
            z_bot = op.z0
        elif self.ext and sill == "rowlock":
            z_bot = self._rowlock(ctx, m)
        elif self.ext:
            z_bot = op.z0 - op.joint
        else:
            z_bot = op.rz0
        self.z_bot = z_bot
        self.z_support = v.support(z_bot)

    def _rowlock(self, ctx, m):
        """Rowlock sill section (veneer y, z): back-top corner just under the frame, sloped down
        and out, projecting past the face; the back end stays clear of the backup."""
        from .veneer import Stack
        v, op, u = self.v, self.op, ctx.u
        th = math.radians(float(m.get("sill_slope", 15)))
        ct, sn = math.cos(th), math.sin(th)
        L, D = v.L, v.D
        st = Stack(ctx, v.band)
        y_bk = st.y_bk if st.y_bk is not None else v.y_face - D - u(2)
        proj = u(m.get("sill_projection", "1-1/2"))
        tan = math.tan(th)
        # top surface runs through (y_a, z_a): clear of the backup, just under the sill pan
        # (frame at the insulation line) or under the frame (frame in the masonry opening)
        y_a = y_bk + u(0.25)
        z_a = (op.rz0 if op.behind_brick else op.z0) - u(0.25)
        yT = v.y_face + proj - L * ct
        T = (yT, z_a - (yT - y_a) * tan)
        Uv, Vv = (ct, -sn), (sn, ct)
        P = lambda p, a, b: (p[0] + a * Uv[0] + b * Vv[0], p[1] + a * Uv[1] + b * Vv[1])
        poly = [T, P(T, L, 0), P(T, L, -D), P(T, 0, -D)]
        cut = _clip(poly, y_a, 0.0, 1)   # rowlock cut square at the back where it is too long
        self.rowlock_cut = len(cut) != 4 or abs(_area(cut) - _area(poly)) > 1e-9
        poly = cut or poly
        B0 = P(T, 0, -D)
        zb_at = lambda y: B0[1] - (y - B0[0]) * tan
        self.rowlock = {"poly": poly, "zb_at": zb_at, "y0": max(B0[0], y_a), "proj": proj, "slope": th}
        return zb_at(v.y_face) - v.bed0

    def course_cut(self, c):
        """None | "remove" | ("cut", height) for a course inside this opening's span."""
        eps = self.v.eps
        if c.top <= self.z_support + eps:
            return None
        if c.zb >= self.z_top - eps:
            if self.head and self.k_head <= c.index < self.k_head + self.n_head:
                return "remove"
            return None
        if c.zb >= self.z_support - eps:
            return "remove"
        return ("cut", self.z_support - c.zb)

    def wy(self, y):
        """Veneer y -> wall y."""
        return y * self.v.sign

    def wpoly(self, poly):
        return [(self.wy(y), z) for y, z in poly]


class Veneer(object):
    def __init__(self, ctx, band):
        self.ctx, self.band = ctx, band
        o = self.opts = ctx.options(band)
        self.eps = ctx.u(1.0 / 256)
        self._brick(o)
        self.bond = str(o.get("bond", "running")).lower().replace(" ", "_").split("_")[0]
        if self.bond == "american":
            self.bond = "common"
        if self.bond not in BONDS:
            ctx.warn("Unknown bond '{}'; using running bond.".format(o.get("bond")))
            self.bond = "running"
        self.header_every = max(2, int(o.get("header_every", 6)))
        tool = o.get("tooling", "concave")
        self.recess = ctx.u(TOOLING[tool] if tool in TOOLING else tool)
        self.jockey = ctx.u(o.get("jockey", "1/16"))
        self.min_piece = ctx.u(o.get("min_piece", 2))
        self.sign = exposed_side(ctx, band)
        if self.sign > 0:
            self.curve = ctx.curve
            self.y_face = band.d_ext
        else:
            # interior-exposed brick: work on the reversed driver, where "left" is the interior
            self.curve = ctx.curve.DuplicateCurve()
            self.curve.Reverse()
            self.y_face = -band.d_int
        self.weeps = ctx.u(o.get("weeps", 24) or 0) if self.sign > 0 else 0.0   # exterior face only
        self.mortar = o.get("mortar", "Mortar")
        self.weep_material = o.get("weep_material", "Weep Vent")
        self.material = band.material or "Brick - Red"
        if abs(band.thickness - self.D) > ctx.u(1.0 / 16):
            ctx.warn("Layer '{}' is {} thick but the brick is {} deep; bricks sit at the face.".format(
                band.name, units.format_inches(band.thickness / ctx.s), units.format_inches(self.D / ctx.s)))
        self.z0, self.z1 = ctx.z_range(band)
        self.courses = self._coursing(o)
        self._legs = None
        self._blocks = {}
        self._mos = None
        self._span_cache = {}

    # -- brick + coursing ------------------------------------------------
    def _brick(self, o):
        ctx = self.ctx
        b = o.get("brick", "modular")
        if isinstance(b, dict):
            L, H, D = [units.parse_length(b[k]) for k in ("length", "height", "depth")]
            cour = b.get("coursing")
            label = b.get("name", "Custom")
        else:
            key = str(b).lower().split()[0]
            if key not in BRICKS:
                ctx.warn("Unknown brick '{}'; using modular.".format(b))
                key = "modular"
            label, L, H, D, cour = BRICKS[key]
        j = units.parse_length(o.get("joint", "3/8"))
        ch = units.parse_length(cour[1]) / float(cour[0]) if cour else H + j
        self.name = "{} Brick {} x {} x {}".format(label, _frac(D), _frac(H), _frac(L))
        s = ctx.s
        self.L, self.H, self.D, self.j0, self.ch = L * s, H * s, D * s, j * s, ch * s
        self.bed0 = self.ch - self.H
        if self.bed0 <= 0:
            raise ValueError("Coursing {} is smaller than the brick height.".format(cour))
        self.Lh = (self.L - self.j0) / 2.0

    def unit(self, kind, h=None):
        L, H, D = self.L, self.H, self.D
        w, d, hh = {"stretcher": (L, D, H), "header": (D, D, H), "soldier": (H, D, L),
                    "rowlock": (H, D, D), "sailor": (D, H, L), "shiner": (L, H, D)}[kind]
        return (kind, w, d, hh if h is None else h)

    def _special_height(self, kind):
        hu = self.unit(kind)[3]
        n = (hu + self.bed0) / self.ch
        snap = round(n * 2) / 2.0
        if snap > 0 and abs(n - snap) < 0.06 and snap * self.ch - hu > 0.5 * self.bed0:
            return hu, snap * self.ch - hu
        return hu, self.bed0

    def _coursing(self, o):
        ctx = self.ctx
        bottom, top, at_index, at_z = [], [], {}, []
        for sp in o.get("courses", []) or []:
            kind = str(sp.get("type", "soldier")).lower()
            if kind not in ROLES:
                ctx.warn("Unknown special course '{}'.".format(kind))
                continue
            n = int(sp.get("count", 1))
            at = sp.get("at", "bottom")
            if at == "bottom":
                bottom += [kind] * n
            elif at == "top":
                top += [kind] * n
            elif isinstance(at, int):
                at_index.setdefault(at, []).extend([kind] * n)
            else:
                at_z.append([self.z0 + ctx.u(at), [kind] * n])
        courses = []
        z = self.z0
        k = 0

        def special(kind, z):
            hu, bed = self._special_height(kind)
            c = Course(len(courses), None, z, bed, hu, special=kind)
            courses.append(c)
            return c.top

        for kind in bottom:
            z = special(kind, z)
        top_h = sum(sum(self._special_height(kd)) for kd in top)
        limit = self.z1 - top_h
        while True:
            if len(courses) in at_index:
                for kind in at_index.pop(len(courses)):
                    z = special(kind, z)
                continue
            due = [a for a in at_z if z >= a[0] - self.ch * 0.5]
            if due:
                for a in due:
                    at_z.remove(a)
                    for kind in a[1]:
                        z = special(kind, z)
                continue
            if z + self.ch > limit + self.eps:
                break
            courses.append(Course(len(courses), k, z, self.bed0, self.H))
            z += self.ch
            k += 1
        rem = limit - z
        mode = str(o.get("top_course", "cut")).lower()
        if rem > self.eps:
            if mode == "round" and rem > self.ch * 0.5:
                courses.append(Course(len(courses), k, z, self.bed0, self.H))
                z += self.ch
                ctx.warn("Brick coursing rounded up: the top course ends {} above the wall.".format(
                    units.format_inches((self.ch - rem) / ctx.s)))
            elif mode == "cut" and rem - self.bed0 >= ctx.u(0.5):
                courses.append(Course(len(courses), k, z, self.bed0, rem - self.bed0, cut=True))
                z += rem
                ctx.warn("Height is not a whole number of brick courses: top course cut to {}.".format(
                    units.format_inches((rem - self.bed0) / ctx.s)))
            else:
                ctx.warn("Brick coursing leaves a {} gap at the top.".format(units.format_inches(rem / ctx.s)))
        for kind in top:
            z = special(kind, z)
        for c in courses:
            c.d = self.unit(c.special or "stretcher")[2]
        return courses

    def bed_joints(self):
        """(z_bottom, z_top) of every bed joint between courses (not under course 0)."""
        return [(c.z, c.z + c.bed) for c in self.courses[1:]]

    def support(self, z):
        """Top of what is left under a horizontal cut at z: a course top, or z itself when the
        course it falls in is cut down (at least 1/2" of it remains)."""
        cs = self.courses
        for i, c in enumerate(cs):
            if c.zb - self.eps <= z <= c.top + self.eps:
                return z if z - c.zb >= self.ctx.u(0.5) else c.z
            if i + 1 < len(cs) and c.top < z < cs[i + 1].zb:
                return c.top
        return z

    # -- openings ----------------------------------------------------------------
    @property
    def mos(self):
        if self._mos is None:
            self._mos = []
            for op in getattr(self.ctx, "openings", None) or []:
                if op.rz1 <= self.z0 or op.rz0 >= self.z1:
                    continue
                self._mos.append(MOpening(self, op))
        return self._mos

    def spans(self, crv):
        """[(a, b, MOpening)] lengths along crv (any curve of this veneer: a leg, its inner
        offset or face) between each opening's jamb planes."""
        key = id(crv)
        if key in self._span_cache:
            return self._span_cache[key][1]
        out = []
        tol = self.ctx.tol
        z = crv.PointAtStart.Z
        t0 = crv.Domain.T0
        L = crv.GetLength()
        for mo in self.mos:
            op = mo.op
            ls = []
            for x in (-mo.hx, mo.hx):
                hits = G.Intersect.Intersection.CurvePlane(crv, op.jamb_plane(x), tol)
                p0 = op.pt(x, 0, z)
                best = None
                for ev in hits or []:
                    d = ev.PointA.DistanceTo(p0)
                    if best is None or d < best[0]:
                        best = (d, ev.ParameterA)
                if best is None or best[0] > abs(self.y_face) + self.D + op.sag + self.ctx.u(24):
                    break
                ls.append(crv.GetLength(G.Interval(t0, best[1])) if best[1] - t0 > 1e-12 else 0.0)
            if len(ls) < 2:
                continue
            a, b = sorted(ls)
            if b - a > 2 * mo.hx + op.sag + self.ctx.u(12) or (crv.IsClosed and b - a > 0.5 * L):
                continue   # opening straddles a closed curve's seam
            out.append((a, b, mo))
        self._span_cache[key] = (crv, out)   # keep crv alive so its id stays unique
        return out

    def _remove(self, run, a, b, j):
        """Split a run of pieces around [a, b]; jamb-end pieces shorter than min_piece are
        merged with their neighbor into two equal closures."""
        eps = self.eps
        left, right = [], []
        for p in run:
            if p[1] <= a + eps:
                left.append(p)
            elif p[0] >= b - eps:
                right.append(p)
            else:
                if p[0] < a - eps:
                    left.append([p[0], a, "cut", p[3]] + p[4:])
                if p[1] > b + eps:
                    right.append([b, p[1], "cut", p[3]] + p[4:])
        if left and left[-1][1] - left[-1][0] < self.min_piece:
            if len(left) >= 2:
                q0 = left[-2][0]
                w = (a - q0 - j) / 2.0
                left[-2:] = [[q0, q0 + w, "cut", 2 * w], [a - w, a, "cut", 2 * w]]
            else:
                left = []
        if right and right[0][1] - right[0][0] < self.min_piece:
            if len(right) >= 2:
                q1 = right[1][1]
                w = (q1 - b - j) / 2.0
                right[:2] = [[b, b + w, "cut", 2 * w], [q1 - w, q1, "cut", 2 * w]]
            else:
                right = []
        return [r for r in (left, right) if r]

    def _lower(self, run, a, b, h):
        """Pieces inside [a, b] cut down to height h (split at the jambs)."""
        eps = self.eps
        out = []
        for p in run:
            if p[1] <= a + eps or p[0] >= b - eps:
                out.append(p)
                continue
            if p[0] < a - eps:
                out.append([p[0], a, "cut", p[3]] + p[4:])
            out.append([max(p[0], a), min(p[1], b), "cut", p[3], h])
            if p[1] > b + eps:
                out.append([b, p[1], "cut", p[3]] + p[4:])
        return out

    def _apply_openings(self, crv, c, pcs, j):
        runs = [pcs]
        for a, b, mo in self.spans(crv):
            mode = mo.course_cut(c)
            if mode is None:
                continue
            if mode == "remove":
                runs = [r2 for r in runs for r2 in self._remove(r, a, b, j)]
            elif mode[1] < self.ctx.u(0.5):
                runs = [r2 for r in runs for r2 in self._remove(r, a, b, j)]
            else:
                runs = [self._lower(r, a, b, mode[1]) for r in runs]
        return [r for r in runs if r]

    def _weep_zones(self, crv, c, lo, hi):
        """[(start, end, spacing)] where weeps go in a course: the base course, and the first
        course over each exterior lintel (at least two per opening)."""
        out = []
        if c.index == 0 and self.weeps:
            out.append((lo, hi, self.weeps))
        for a, b, mo in self.spans(crv):
            sp = self.ctx.u(mo.m.get("weeps", 24) or 0)
            if mo.ext and sp and mo.k_head is not None and c.index == mo.k_head and mo.m.get("flashing", True):
                out.append((a, b, min(sp, 0.5 * (b - a))))
        return out

    def pattern(self, c, j):
        """(units, phase) of a course for head joint j."""
        if c.special:
            return [self.unit(c.special)], 0.0
        L, D, h = self.L, self.D, c.h
        S, H = self.unit("stretcher", h), self.unit("header", h)
        M, MH = L + j, D + j
        k, b = c.k, self.bond
        if b == "stack":
            return [S], 0.0
        if b == "third":
            return [S], (k % 3) * M / 3.0
        if b == "quarter":
            return [S], (k % 4) * M / 4.0
        if b == "flemish":
            return [S, H], (k % 2) * (M + MH) / 2.0
        if b == "english":
            return ([S], 0.0) if k % 2 == 0 else ([H], MH / 2.0)
        if b == "common" and k % self.header_every == self.header_every - 1:
            return [H], MH / 2.0
        return [S], (k % 2) * M / 2.0

    # -- legs ------------------------------------------------------------
    @property
    def legs(self):
        if self._legs is None:
            self._legs = self._make_legs()
        return self._legs

    def _make_legs(self):
        ctx = self.ctx
        c = self.curve
        tol = ctx.tol
        ks = geo.kink_parameters(c)
        seam = False
        if c.IsClosed:
            seam = G.Vector3d.VectorAngle(c.TangentAtStart, c.TangentAtEnd) > math.radians(1.0)
        params = [c.Domain.T0] + ks + [c.Domain.T1]
        pieces = [c.Trim(a, b) for a, b in zip(params, params[1:]) if b - a > 1e-12]
        if c.IsClosed and not seam:
            if not ks:
                legs = [Leg(c.DuplicateCurve(), tol, closed=True)]
                self._prepare(legs, [])
                return legs
            joined = G.Curve.JoinCurves([pieces[-1], pieces[0]], tol * 2)
            pieces = [joined[0]] + pieces[1:-1]
        legs = [Leg(p, tol) for p in pieces]
        corners = [Corner(a, b) for a, b in zip(legs, legs[1:])]
        if c.IsClosed:
            corners.append(Corner(legs[-1], legs[0]))
        if any(not k.straight for k in corners):
            ctx.warn("Brick corners next to curved segments are approximate.")
        if not c.IsClosed:
            self._join_ends(legs)
        self._prepare(legs, corners)
        return legs

    def _join_ends(self, legs):
        """Wall ends joined to other walls (ctx.joins): the first / last leg stops on the cut."""
        J = getattr(self.ctx, "joins", None)
        if J is None or not J.ends:
            return
        names = ("start", "end") if self.sign > 0 else ("end", "start")
        d = self.band.d_mid
        for leg, name, at_start in ((legs[0], names[0], True), (legs[-1], names[1], False)):
            cut = J.ends.get(name)
            if cut is None:
                continue
            if not leg.straight:
                self.ctx.warn("Brick at a joined end of a curved wall is not cut to the join.")
                continue
            je = JoinEnd(leg, cut, d, at_start)
            if at_start:
                leg.start = je
            else:
                leg.end = je

    def _prepare(self, legs, corners):
        """Joint width per leg (bond the run out) and per-leg bond phase / corner parity."""
        regular = [c for c in self.courses if not c.special][:6] or self.courses[:2]
        if not regular:
            return
        c0 = regular[0]
        for leg in legs:
            if leg.closed:
                continue
            if leg.straight:
                b = self._bounds(leg, c0, self.j0, through=True)
                R = b["hi"] - b["anchor"]
            else:
                R = leg.inner(self._inner_y(leg, c0.d)).GetLength()
            leg.j = self._fit_joint(R, self.j0)
        qd = QDIV[self.bond]
        steps = sorted(set([round(i / 4.0, 9) for i in range(6)] + [round(i / 3.0, 9) for i in range(3)]))
        if qd == 1:
            steps = [0.0]
        n = len(legs)
        closed_loop = self.curve.IsClosed and corners and len(corners) == n
        for idx, leg in enumerate(legs):
            if leg.closed or not leg.straight:
                continue
            end_free = leg.end is not None and leg.end.lap and not (closed_loop and idx == n - 1) \
                and not getattr(leg.end, "fixed", False)
            best = None
            for p in ([0, 1] if end_free else [leg.end.p if leg.end else 0]):
                if leg.end is not None:
                    leg.end.p = p
                for dlt in steps:
                    leg.delta = dlt
                    cost = sum(self._cost(leg, c, i) for i, c in enumerate(regular))
                    if best is None or cost < best[0] - 1e-9:
                        best = (cost, p, leg.delta)
            if leg.end is not None:
                leg.end.p = best[1]
            leg.delta = best[2]

    def _fit_joint(self, R, j0):
        q = float(QDIV[self.bond])
        L = self.L
        m = round(q * (R + j0) / (L + j0))
        if m <= q:
            return j0
        j = (R - m * L / q) / (m / q - 1.0)
        return j if abs(j - j0) <= self.jockey and j > 0 else j0

    def _inner_y(self, leg, d):
        return self.y_face if leg.concave else self.y_face - d

    # -- straight legs: bounds + 1D layout ---------------------------------
    def _bounds(self, leg, c, j, through=None):
        """Start / end lines (x = a + b*y) of a course on a straight leg."""
        y_f = self.y_face
        y_b = y_f - c.d
        i = c.index
        r = {}
        if leg.start is None:
            sa, sb, sg, anchor, scorner = 0.0, 0.0, 0.0, 0.0, False
        else:
            k = leg.start
            thr = (not k.a_through(i)) if through is None else through
            sa, sb = k.start_line(y_f, y_b, thr if k.lap else True)
            sg = 0.0 if (thr or not k.lap) else j
            if k.lap:
                anchor = k.start_line(y_f, y_b, True)[0]
            else:
                anchor = min(sa + sb * y_f, sa + sb * y_b)
            scorner = True
        if leg.end is None:
            ea, eb, eg, ecorner = leg.length, 0.0, 0.0, False
        else:
            k = leg.end
            thr = k.a_through(i) if through is None else through
            ea, eb = k.end_line(leg.length, y_f, y_b, thr if k.lap else False)
            eg = 0.0 if (k.lap and thr) else j
            ecorner = True
        ks, ke = math.sqrt(1 + sb * sb), math.sqrt(1 + eb * eb)
        r.update(sa=sa, sb=sb, sg=sg * ks, ea=ea, eb=eb, eg=eg * ke, anchor=anchor,
                 scorner=scorner, ecorner=ecorner, y_f=y_f, y_b=y_b,
                 lo=min(sa + sb * y_f, sa + sb * y_b) + sg * ks,
                 hi=max(ea + eb * y_f, ea + eb * y_b) - eg * ke)
        return r

    def _run(self, units_, phase, anchor, lo, hi, j, snap_lo, snap_hi):
        """1D layout: [a, b, kind, w] pieces covering [lo, hi]."""
        eps = self.eps
        period = sum(u[1] + j for u in units_)
        pos = anchor + phase
        pos -= math.ceil((pos - lo) / period + 1e-9) * period
        pcs = []
        i = 0
        while pos < hi - eps:
            kind, w = units_[i % len(units_)][:2]
            a, b = pos, pos + w
            if b > lo + eps:
                pcs.append([max(a, lo), min(b, hi), kind, w])
            pos = b + j
            i += 1
        pcs = [p for p in pcs if p[1] - p[0] > eps]
        if not pcs:
            return pcs
        tol = self.jockey + eps
        for idx, snap in ((0, snap_lo), (-1, snap_hi)):
            p = pcs[idx]
            if not snap:
                continue
            l = p[1] - p[0]
            noms = [p[3]] + ([self.Lh] if p[2] == "stretcher" else [])
            for nom in noms:
                if 1e-12 < abs(l - nom) <= tol:
                    if idx == 0 and p[0] <= lo + eps:
                        nb = p[0] + nom
                        if len(pcs) == 1 or nb < pcs[1][0] - 0.25 * j:
                            p[1] = nb
                    elif idx == -1 and p[1] >= hi - eps:
                        na = p[1] - nom
                        if len(pcs) == 1 or na > pcs[-2][1] + 0.25 * j:
                            p[0] = na
                    break
        if len(pcs) >= 2:
            for idx, nxt in ((0, 1), (-1, -2)):
                p, q = pcs[idx], pcs[nxt]
                if p[1] - p[0] < self.min_piece:
                    a, b = min(p[0], q[0]), max(p[1], q[1])
                    w = (b - a - j) / 2.0
                    if idx == 0:
                        pcs[0:2] = [[a, a + w, "cut", w * 2], [b - w, b, "cut", w * 2]]
                    else:
                        pcs[-2:] = [[a, a + w, "cut", w * 2], [b - w, b, "cut", w * 2]]
                    if len(pcs) < 2:
                        break
        return pcs

    def _straight_pieces(self, leg, c):
        j = leg.j or self.j0
        units_, phase = self.pattern(c, j)
        b = self._bounds(leg, c, j)
        pcs = self._run(units_, phase + leg.delta * (self.L + j), b["anchor"], b["lo"], b["hi"], j,
                        b["sb"] == 0, b["eb"] == 0)
        return pcs, b

    def _cost(self, leg, c, i):
        pcs, b = self._straight_pieces(leg, c)
        cost = 0.0
        tol = self.eps * 4
        for n, (a, bb, kind, w) in enumerate(pcs):
            l = bb - a
            if abs(l - w) < tol and kind != "cut":
                continue
            at_corner = (n == 0 and b["scorner"]) or (n == len(pcs) - 1 and b["ecorner"])
            if kind == "stretcher" and abs(l - self.Lh) < tol and not at_corner:
                cost += 0.25
                continue
            cost += 3.0 if at_corner else 1.0
            if l < self.min_piece:
                cost += 3.0
        return cost

    # -- blocks ----------------------------------------------------------
    def _block(self, material, local, h):
        s = self.ctx.s
        xs = [p[0] for p in local]
        ys = [p[1] for p in local]
        w, d = max(xs) - min(xs), max(ys) - min(ys)
        is_rect = len(local) == 4 and abs(_area(local) - w * d) < 1e-9 * max(1.0, w * d)
        if is_rect:
            name = "MC {} {:.4f}x{:.4f}x{:.4f}".format(material, w / s, d / s, h / s)
            local = _rect(min(xs), max(xs), min(ys), max(ys))
        else:
            key = ";".join("{:.4f},{:.4f}".format(x / s, y / s) for x, y in local) + "|{:.4f}".format(h / s)
            name = "MC {} P{}".format(material, hashlib.md5(key.encode("utf-8")).hexdigest()[:10])
        idx = self._blocks.get(name)
        if idx is None:
            idx = self.ctx.block(name, [prism(local, h)], material)
            self._blocks[name] = idx
        return idx

    def _part_local(self, origin, X, Y, local, h, material, role):
        idx = self._block(material, local, h)
        plane = G.Plane(origin, X, Y)
        return Part(material=material, role=role, block=idx,
                    xform=G.Transform.PlaneToPlane(G.Plane.WorldXY, plane))

    def _leg_part(self, leg, poly, z, h, material, role):
        x0 = min(p[0] for p in poly)
        local = [(x - x0, y - self.y_face) for x, y in poly]
        o = leg.p0 + leg.t * x0 + leg.n * self.y_face
        o = G.Point3d(o.X, o.Y, z)
        return self._part_local(o, leg.t, leg.n, local, h, material, role)

    def _role(self, kind, l, w, c):
        if c.cut or kind == "cut":
            return "brick_closure"
        if abs(l - w) < self.eps * 4:
            return ROLES[kind]
        if kind == "stretcher" and abs(l - self.Lh) < self.eps * 4:
            return "brick_half"
        return "brick_closure"

    # -- geometry ----------------------------------------------------------
    def parts(self):
        detail = self.ctx.lod == "detail"
        out = []
        for leg in self.legs:
            for c in self.courses:
                if leg.straight:
                    self._straight_course(leg, c, detail, out)
                else:
                    self._curved_course(leg, c, detail, out)
        if detail:
            out.extend(self._bed_joint_parts())
        out.extend(self._opening_parts(detail))
        return out

    def _weep_slots(self, centers, start, end, spacing=None):
        """Indices of joints (by center position) nearest to weep stations in [start, end]."""
        spacing = spacing or self.weeps
        if not spacing or not centers:
            return set()
        chosen = set()
        idx = [i for i in range(len(centers)) if start - 1e-9 <= centers[i] <= end + 1e-9]
        if not idx:
            return chosen
        x = start + spacing * 0.5
        while x < end:
            best = min(idx, key=lambda i: abs(centers[i] - x))
            if abs(centers[best] - x) < spacing * 0.5:
                chosen.add(best)
            x += spacing
        return chosen

    def _course_weeps(self, centers, zones):
        out = set()
        for lo, hi, sp in zones:
            out |= self._weep_slots(centers, lo, hi, sp)
        return out

    def _straight_course(self, leg, c, detail, out):
        pcs, b = self._straight_pieces(leg, c)
        if not pcs:
            return
        j = leg.j or self.j0
        first, last = pcs[0], pcs[-1]
        runs = self._apply_openings(leg.crv, c, pcs, j)
        y_f, y_b = b["y_f"], b["y_b"]
        slanted = b["sb"] != 0 or b["eb"] != 0
        bplanes = [(b["sa"] + b["sg"], b["sb"], 1), (b["ea"] - b["eg"], b["eb"], -1)]
        zb = c.zb
        mat = self.material
        for run in runs:
            for p in run:
                a, bb, kind, w = p[:4]
                h = p[4] if len(p) > 4 else c.h
                poly = _rect(a, bb, y_b, y_f)
                if slanted:
                    poly = _clip_all(poly, bplanes)
                if poly:
                    out.append(self._leg_part(leg, poly, zb, h, mat, self._role(kind, bb - a, w, c)))
        if not detail:
            return
        y_j = y_f - self.recess
        zones = self._weep_zones(leg.crv, c, b["lo"], b["hi"])
        for run in runs:
            gaps = [(p[1], q[0], min(p[4] if len(p) > 4 else c.h, q[4] if len(q) > 4 else c.h))
                    for p, q in zip(run, run[1:])]
            weeps = self._course_weeps([0.5 * (g[0] + g[1]) for g in gaps], zones)
            for gi, (a, bb, h) in enumerate(gaps):
                if bb - a <= self.eps:
                    continue
                weep = gi in weeps
                poly = _rect(a, bb, y_b, y_f if weep else y_j)
                if slanted:
                    poly = _clip_all(poly, bplanes)
                if poly:
                    if weep:
                        out.append(self._leg_part(leg, poly, zb, h, self.weep_material, "weep"))
                    else:
                        out.append(self._leg_part(leg, poly, zb, h, self.mortar, "mortar_head"))
        ends = []
        if runs and runs[0][0] is first and b["sb"] == 0 and first[0] - b["sa"] > self.eps:
            ends.append(_rect(b["sa"], first[0], y_b, y_j))
        if runs and runs[-1][-1] is last:
            if b["eb"] == 0 and b["ea"] - last[1] > self.eps:
                ends.append(_rect(last[1], b["ea"], y_b, y_j))
            elif b["eg"] > 0:
                lo = min(b["ea"] - b["eg"] + b["eb"] * y for y in (y_b, y_j))
                hi = max(b["ea"] + b["eb"] * y for y in (y_b, y_j))
                ends.append(_clip_all(_rect(lo, hi, y_b, y_j),
                                      [(b["ea"] - b["eg"], b["eb"], 1), (b["ea"], b["eb"], -1)]))
        for poly in ends:
            if poly:
                out.append(self._leg_part(leg, poly, zb, c.h, self.mortar, "mortar_head"))

    def _chord_frame(self, ci, Li, a, b, closed, d, concave, zb):
        """(origin, X, Y, length) of a straight unit laid on the chord of ci from a to b."""
        l = b - a
        p0 = ci.PointAtLength(a % Li if closed else max(a, 0.0))
        p1 = ci.PointAtLength(b % Li if closed else min(b, Li))
        X = G.Vector3d(p1.X - p0.X, p1.Y - p0.Y, 0)
        chord = X.Length
        if chord < self.eps:
            return None
        X.Unitize()
        Y = G.Vector3d.CrossProduct(Z, X)
        o = G.Point3d(p0.X, p0.Y, zb) + X * ((chord - l) * 0.5)
        if not concave:
            o = o + Y * d
        return o, X, Y, l

    def _curved_course(self, leg, c, detail, out):
        units_, phase = None, None
        d = c.d
        y_in = self._inner_y(leg, d)
        ci = leg.inner(y_in)
        Li = ci.GetLength()
        if leg.closed:
            units_, _ = self.pattern(c, self.j0)
            P = sum(u[1] for u in units_)
            n = max(1, int(round(Li / (P + len(units_) * self.j0))))
            j = (Li / n - P) / len(units_)
            units_, phase = self.pattern(c, j)
            pcs = []
            pos = phase
            for _ in range(n):
                for u in units_:
                    pcs.append([pos, pos + u[1], u[0], u[1]])
                    pos += u[1] + j
        else:
            j = leg.j or self.j0
            units_, phase = self.pattern(c, j)
            pcs = self._run(units_, phase + leg.delta * (self.L + j), 0.0, 0.0, Li - (j if leg.end else 0.0), j,
                            True, leg.end is None)
        if not pcs:
            return
        first, last = pcs[0], pcs[-1]
        runs = self._apply_openings(ci, c, pcs, j)
        wrap = leg.closed and len(runs) == 1 and runs[0] is pcs
        if leg.closed and len(runs) > 1 and runs[0][0] is first and runs[-1][-1] is last:
            runs = [runs[-1] + runs[0]] + runs[1:-1]
        zb = c.zb
        zones = self._weep_zones(ci, c, 0.0, Li)
        for run in runs:
            frames = []
            for p in run:
                a, b, kind, w = p[:4]
                h = p[4] if len(p) > 4 else c.h
                fr = self._chord_frame(ci, Li, a, b, leg.closed, d, leg.concave, zb)
                if fr is None:
                    continue
                o, X, Y, l = fr
                out.append(self._part_local(o, X, Y, _rect(0, l, -d, 0), h, self.material,
                                            self._role(kind, l, w, c)))
                frames.append(fr + (h,))
            if not detail or len(frames) < 2:
                continue
            pairs = list(zip(frames, frames[1:]))
            if wrap:
                pairs.append((frames[-1], frames[0]))
            centers = []
            for fa, fb in pairs:
                m = (fa[0] + fa[1] * fa[3] + fb[0]) * 0.5
                ok, t = ci.ClosestPoint(G.Point3d(m.X, m.Y, ci.PointAtStart.Z))
                centers.append(ci.GetLength(G.Interval(ci.Domain.T0, t)))
            weeps = self._course_weeps(centers, zones)
            f = (d - self.recess) / d
            for gi, ((oa, Xa, Ya, la, ha), (ob, Xb, Yb, lb, hb)) in enumerate(pairs):
                weep = gi in weeps
                fa = oa + Xa * la
                ba = fa - Ya * d
                bb_ = ob - Yb * d
                ra = fa if weep else ba + (fa - ba) * f
                rb = ob if weep else bb_ + (ob - bb_) * f
                X = G.Vector3d(bb_.X - ba.X, bb_.Y - ba.Y, 0)
                if X.Length < self.eps * 0.5:
                    continue
                X.Unitize()
                Y = G.Vector3d.CrossProduct(Z, X)
                loc = [((p - ba) * X, (p - ba) * Y) for p in (ba, bb_, rb, ra)]
                if _area(loc) < 1e-12:
                    continue
                h = min(ha, hb)
                if weep:
                    out.append(self._part_local(ba, X, Y, loc, h, self.weep_material, "weep"))
                else:
                    out.append(self._part_local(ba, X, Y, loc, h, self.mortar, "mortar_head"))

    def _bed_joint_parts(self):
        ctx = self.ctx
        out = []
        cache = {}
        face_len = geo.offset(self.curve, self.y_face, ctx.tol).GetLength() / ctx.s
        cutters = self._bed_cutters()
        from ..openings import core as _openings
        for c in self.courses:
            if c.bed <= self.eps:
                continue
            key = (round(c.d, 9), round(c.bed, 9))
            if key not in cache:
                cache[key] = self._strip(self.y_face - self.recess, self.y_face - c.d, c.bed)
            solids = []
            for s in cache[key]:
                b = s.DuplicateBrep()
                b.Translate(G.Vector3d(0, 0, c.z))
                solids.append(b)
            if cutters:
                solids = _openings.subtract(ctx, solids, cutters, "a bed joint")
            for b in solids:
                out.append(Part(b, self.mortar, role="mortar_bed",
                                extra={"area": round(face_len * (c.bed + c.h) / ctx.s, 3)}))
        return out

    def _strip(self, y_a, y_b, h):
        """Solids of the strip y_a..y_b (veneer offsets) from z = 0 to h, stopped at join cuts."""
        ctx = self.ctx
        J = getattr(ctx, "joins", None)
        if J is not None and J.ends and not ctx.curve.IsClosed:
            from ..joins import geom as jgeom
            return jgeom.band_solids(ctx, self.sign * y_a, self.sign * y_b, 0.0, h, notch=False)
        return geo.band_solids(self.curve, y_a, y_b, 0.0, h, ctx.tol)

    # -- openings: bed joint cutters, lintel, sill, head course, flashing -----------------
    def _bed_cutters(self):
        ctx = self.ctx
        e = ctx.u(1.0 / 64)
        out = []
        for mo in self.mos:
            op = mo.op
            y0, y1 = sorted((mo.wy(self.y_face + ctx.u(1)), mo.wy(self.y_face - self.D - ctx.u(1))))
            if mo.z_top - e > mo.z_support - e:
                out.append(op.cutter(ctx, -mo.hx, mo.hx, mo.z_support - e, mo.z_top - e, y0, y1))
            if mo.k_head is not None:
                c = self.courses[mo.k_head]
                out.append(op.cutter(ctx, -mo.hx - mo.bearing, mo.hx + mo.bearing, c.z - e, c.zb + e, y0, y1))
                if mo.head and mo.n_head > 1:
                    out.append(op.cutter(ctx, -mo.hx, mo.hx, c.zb + e, mo.head_top - e, y0, y1))
        return out

    def _units_on(self, mo, crv, depth_y, kind, zb, h):
        """Soldiers / sailors / rowlock-width units across an opening, laid on chords of crv
        (a curve at veneer offset depth_y). Returns [(origin, X, Y, length)] with joints."""
        spans = [s for s in self.spans(crv) if s[2] is mo]
        if not spans:
            return [], []
        a, b, _ = spans[0]
        w = self.unit(kind)[1] if kind != "rowlock" else self.H
        n = max(1, int(round((b - a + self.j0) / (w + self.j0))))
        j = (b - a - n * w) / (n - 1) if n > 1 else 0.0
        if n == 1:
            a = 0.5 * (a + b) - 0.5 * w
        L = crv.GetLength()
        units_, gaps = [], []
        for i in range(n):
            x0 = a + i * (w + j)
            fr = self._chord_frame(crv, L, x0, x0 + w, crv.IsClosed, 0.0, True, zb)
            if fr is not None:
                units_.append(fr)
            if i < n - 1:
                g = self._chord_frame(crv, L, x0 + w, x0 + w + j, crv.IsClosed, 0.0, True, zb)
                if g is not None:
                    gaps.append(g)
        return units_, gaps

    def _section_block(self, name, poly_yz, w, material):
        """Block: a (y, z) section extruded along X from 0 to w (local Y = veneer y - y_face)."""
        from ..openings import geom as og
        key = "MC {} {} {}".format(material, name, hashlib.md5(
            (";".join("{:.4f},{:.4f}".format(y / self.ctx.s, z / self.ctx.s) for y, z in poly_yz)
             + "|{:.4f}".format(w / self.ctx.s)).encode("utf-8")).hexdigest()[:10])
        idx = self._blocks.get(key)
        if idx is None:
            b = og.extrude([G.Point3d(0, y, z) for y, z in poly_yz], G.Vector3d(w, 0, 0), self.ctx.tol)
            idx = self.ctx.block(key, [b], material)
            self._blocks[key] = idx
        return idx

    def _place_section(self, fr, poly_rel, z_ref, name, material, role):
        o, X, Y, l = fr[:4]
        idx = self._section_block(name, poly_rel, l, material)
        plane = G.Plane(G.Point3d(o.X, o.Y, z_ref), X, Y)
        return Part(material=material, role=role, block=idx, xform=G.Transform.PlaneToPlane(G.Plane.WorldXY, plane))

    def _opening_parts(self, detail):
        ctx = self.ctx
        out = []
        for mo in self.mos:
            try:
                parts = self._mo_parts(mo, detail)
            except Exception as ex:
                ctx.warn("Brick around '{}' failed ({}).".format(mo.op.name, ex))
                continue
            for p in parts:
                p.extra.setdefault("opening", str(mo.op.id))
            out += parts
        return out

    def _mo_parts(self, mo, detail):
        from ..openings import geom as og
        ctx, op, u = self.ctx, mo.op, self.ctx.u
        out = []
        tag = {"opening": str(op.id)}
        yf, yb = self.y_face, self.y_face - self.D
        face = geo.offset(self.curve, yf, ctx.tol)
        # lintel
        if mo.k_head is not None:
            name, p = self._lintel(mo)
            a, bv, t = [u(p[k]) for k in ("a", "b", "t")]
            yh = yb - u(1.0 / 16)
            zt = mo.z_top
            poly = [(yh - t, zt), (yh - t + a, zt), (yh - t + a, zt + t), (yh, zt + t), (yh, zt + bv), (yh - t, zt + bv)]
            x0, x1 = -mo.hx - mo.bearing, mo.hx + mo.bearing
            for s in og.sweep(ctx, op, mo.wpoly(poly), x0, x1):
                out.append(Part(s, mo.m.get("lintel_material", "Steel Angle"), role="lintel",
                                extra=dict(tag, profile=name, length=round((x1 - x0) / ctx.s, 3))))
            # soldier / sailor course on the lintel
            if mo.head:
                c = self.courses[mo.k_head]
                h = mo.head_top - c.zb
                kind = mo.head
                d = self.D if kind == "soldier" else self.H
                units_, gaps = self._units_on(mo, face, yf, kind, c.zb, h)
                for fr in units_:
                    o, X, Y, l = fr
                    out.append(self._part_local(o, X, Y, _rect(0, l, -d, 0), h, self.material, ROLES[kind]))
                if detail:
                    for fr in gaps:
                        o, X, Y, l = fr
                        out.append(self._part_local(o, X, Y, _rect(0, l, -d, -self.recess), h, self.mortar,
                                                    "mortar_head"))
            if mo.ext and detail and mo.m.get("flashing", True):
                out += self._head_flashing(mo, yh, zt + t, bv, x0, x1, tag)
        # rowlock sill
        if mo.rowlock:
            rl = mo.rowlock
            rel = [(y - yf, z - op.z0) for y, z in rl["poly"]]
            units_, gaps = self._units_on(mo, face, yf, "rowlock", op.z0, 0.0)
            for fr in units_:
                out.append(self._place_section(fr, rel, op.z0, "Rowlock", self.material, "brick_rowlock"))
            if detail:
                for fr in gaps:
                    out.append(self._place_section(fr, rel, op.z0, "Rowlock Joint", self.mortar, "mortar_head"))
                y0 = max(yb, rl["y0"])
                wedge = [(y0, mo.z_support), (yf, mo.z_support), (yf, rl["zb_at"](yf)), (y0, rl["zb_at"](y0))]
                for s in og.sweep(ctx, op, mo.wpoly(wedge), -mo.hx, mo.hx):
                    out.append(Part(s, self.mortar, role="mortar_bed", extra=dict(tag)))
                if mo.m.get("flashing", True):
                    out += self._sill_flashing(mo, tag)
        if mo.ext and detail:
            out += self._sealant(mo, tag)
        return out

    def _lintel(self, mo):
        lib = self.ctx.lib
        choice = mo.m.get("lintel", "auto")
        if choice and choice != "auto":
            return choice, lib.profile(choice)
        span = 2 * mo.hx
        cands = sorted(((units.parse_length(p.get("max_span", 0)), n, p) for n, p in lib.data["profiles"].items()
                        if p.get("family") == "lintel"), key=lambda c: (c[0], c[1]))
        if not cands:
            raise ValueError("no 'lintel' profiles in the library")
        for ms, n, p in cands:
            if ms * self.ctx.s >= span - self.ctx.tol:
                return n, p
        self.ctx.warn("Opening '{}' is wider than the largest lintel's max_span.".format(mo.op.name))
        return cands[-1][1], cands[-1][2]

    def _head_flashing(self, mo, yh, zf, bv, x0, x1, tag):
        from ..openings import geom as og
        from .veneer import Stack, thicken
        ctx, op, u = self.ctx, mo.op, self.ctx.u
        st = Stack(ctx, self.band)
        if st.y_bk is None:
            return []
        m = mo.m
        tf = u("1/32")
        mat = m.get("flashing_material", "Flashing")
        zv = mo.z_top + bv + tf
        top = max(zf + u(m.get("upturn", 8)), zv + u(2))
        drip = u("3/8")
        path = [(st.y_bk, top), (st.y_bk, zv + u(0.5)), (yh - u(1.0 / 16), zv), (yh, zv), (yh, zf),
                (self.y_face + drip - u(0.25), zf), (self.y_face + drip, zf - u(0.25))]
        out = [Part(s, mat, role="flashing", extra=dict(tag, length=round((x1 - x0) / ctx.s, 3)))
               for s in og.sweep(ctx, op, mo.wpoly(thicken(path, tf)), x0, x1)]
        dam = u(m.get("end_dam", 1))
        if dam > 0:
            poly = mo.wpoly([(yh, zf), (self.y_face - u(0.5), zf), (self.y_face - u(0.5), zf + dam), (yh, zf + dam)])
            for xa, xb in ((x0, x0 + tf), (x1 - tf, x1)):
                b = og.prism_x(op, poly, xa, xb, ctx.tol)
                if b is not None:
                    out.append(Part(b, mat, role="end_dam", extra=dict(tag)))
        return out

    def _sill_flashing(self, mo, tag):
        from ..openings import geom as og
        from .veneer import Stack, thicken
        ctx, op, u = self.ctx, mo.op, self.ctx.u
        st = Stack(ctx, self.band)
        if st.y_bk is None:
            return []
        tf = u("1/32")
        zs = mo.z_support
        up = max(u(2), min(u(8), (op.rz0 if op.behind_brick else op.z0) - zs - u(0.25)))
        drip = u("3/8")
        path = [(st.y_bk, zs + up), (st.y_bk, zs + u(0.5)), (self.y_face - self.D, zs - tf),
                (self.y_face + drip - u(0.25), zs - tf), (self.y_face + drip, zs - tf - u(0.25))]
        return [Part(s, mo.m.get("flashing_material", "Flashing"), role="flashing", extra=dict(tag))
                for s in og.sweep(ctx, op, mo.wpoly(thicken(path, tf)), -mo.hx, mo.hx)]

    def _sealant(self, mo, tag):
        """Sealant + backer rod between the brick and the window / door, at the jambs and the
        head. Frame in the masonry opening: the joint is at the frame face. Frame behind the
        brick (insulation line): sheet-metal closures line the jambs and head from the frame to
        1/2" behind the brick face, and the joint is between the brick and the closure there."""
        from ..openings import geom as og
        ctx, op, u = self.ctx, mo.op, self.ctx.u
        out = []
        sealant, backer = op.t.get("sealant", "Sealant"), op.t.get("backer", "Backer Rod")
        ds = u("3/8")
        j = op.joint
        hw = 0.5 * op.W
        z_hi_j = mo.z_top if mo.k_head is not None else op.z1 + j
        if op.behind_brick:
            cl = op.t.get("closure") or {}
            tc = u(cl.get("thickness", "1/16"))
            cmat = cl.get("material", "Aluminum")
            y_seal = mo.wy(self.y_face) - u(cl.get("recess", "1/2"))   # wall coordinates from here on
            z_lo = op.z0 if op.door else op.rz0
            for s in (-1, 1):
                xa, xb = sorted((s * hw, s * (hw + tc)))
                out.append(Part(og.prism_z(op, [(xa, op.y_fe), (xb, op.y_fe), (xb, y_seal), (xa, y_seal)],
                                           z_lo, op.z1 + tc, ctx.tol), cmat, role="closure", extra=dict(tag)))
            out.append(Part(og.prism_x(op, [(op.y_fe, op.z1), (y_seal, op.z1), (y_seal, op.z1 + tc), (op.y_fe, op.z1 + tc)],
                                       -hw, hw, ctx.tol), cmat, role="closure", extra=dict(tag)))
            x_in, z_head = hw + tc, op.z1 + tc
        else:
            y_seal = op.y_fe
            z_lo = op.z0 if not mo.rowlock else op.z0 - u(0.25)
            x_in, z_head = hw, op.z1
        z_hi = min(z_hi_j, op.z1 + j)
        rr = 0.5 * min((hw + j - x_in) * 1.25, u("5/8"))
        for s in (-1, 1):
            xa, xb = sorted((s * x_in, s * (hw + j)))
            if xb - xa < u(1.0 / 16):
                continue
            seal = [(xa, y_seal - ds), (xb, y_seal - ds), (xb, y_seal), (xa, y_seal)]
            out.append(Part(og.prism_z(op, seal, z_lo, z_hi, ctx.tol), sealant, role="sealant", extra=dict(tag)))
            rod = [(0.5 * (xa + xb) + 0.49 * (xb - xa) * math.cos(a), y_seal - ds - rr + rr * math.sin(a))
                   for a in [i * math.pi / 8 for i in range(16)]]
            out.append(Part(og.prism_z(op, rod, z_lo, z_hi, ctx.tol), backer, role="backer_rod", extra=dict(tag)))
        if mo.k_head is not None and mo.z_top - z_head > u(0.125):
            gz = mo.z_top - z_head
            seal = [(y_seal - ds, z_head), (y_seal, z_head), (y_seal, mo.z_top), (y_seal - ds, mo.z_top)]
            out.append(Part(og.prism_x(op, seal, -hw - j, hw + j, ctx.tol), sealant, role="sealant", extra=dict(tag)))
            rz = 0.5 * min(gz * 0.98, u("5/8"))
            zc = z_head + 0.5 * gz
            rod = [(y_seal - ds - rr + rr * math.cos(a), zc + rz * math.sin(a)) for a in [i * math.pi / 8 for i in range(16)]]
            out.append(Part(og.prism_x(op, rod, -hw - j, hw + j, ctx.tol), backer, role="backer_rod", extra=dict(tag)))
        return [p for p in out if p.geometry is not None]

def layout(ctx, band):
    cache = ctx.__dict__.setdefault("_mc_masonry", {})
    if band.index not in cache:
        cache[band.index] = Veneer(ctx, band)
    return cache[band.index]


def masonry_bands(ctx, name=None):
    """Masonry bands of the stack (only the one named `name` when given)."""
    if name:
        b = ctx.band(name)
        return [b] if b is not None else []
    return [b for b in ctx.bands if b.component == "masonry"]


def exposed_side(ctx, band):
    """+1 when the brick face is the exterior side of the band, -1 when it is the interior side.
    Option face = exterior | interior | auto (the side with no solid layer beyond it)."""
    face = str(ctx.option(band, "face", "auto")).lower()
    if face.startswith("ext"):
        return 1
    if face.startswith("int"):
        return -1
    solid = lambda b: b.component != "void" and b.thickness > ctx.tol
    outer = any(solid(b) for b in ctx.bands if b.index < band.index)
    inner = any(solid(b) for b in ctx.bands if b.index > band.index)
    return -1 if (outer and not inner) else 1


@register
class Masonry(Component):
    name = "masonry"

    def build(self, ctx, band):
        if ctx.lod == "schematic":
            z0, z1 = ctx.z_range(band)
            solids = openings.cut(ctx, ctx.solids(band.d_ext, band.d_int, z0, z1), band, z0)
            return [Part(s, band.material, role="masonry") for s in solids]
        from . import veneer
        return layout(ctx, band).parts() + veneer.accessories(ctx, band)
