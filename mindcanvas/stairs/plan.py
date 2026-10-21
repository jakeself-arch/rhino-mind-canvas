"""Stair layout in plan (pure Python, no Rhino: testable anywhere).

The stair is driven by ONE side of its plan boundary: a path sampled into segments split at its
corners. Each segment is a list of samples (x, y, dx, dy): a point on the side line and the unit
tangent there, in the direction of travel UP the stair. `sigma` is the side the stair lies on:
+1 = left of the path (the path is the stair's RIGHT side), -1 = right of it (the path is the
LEFT side). Units: inches. A closed curve walked several times (a stair wrapping an elevator) is
just a longer path that overlaps itself in plan (mindcanvas/stairs/build.path_segments).

    lay = layout(segments, width=42, height=120, sigma=-1, max_riser=7)

- Every corner between two segments becomes a landing (a kite in the corner: square for a 90 degree
  turn). Landings can also sit ANYWHERE along a flight, straight or curved: `floors` > 1 puts one at
  each intermediate floor level (exactly at k x height, at equal walking distances), `landing_count`
  adds that many evenly spaced landings per floor, `landing_at` = centers at distances along the
  path's side line. Landings are `landing_depth` long on the walkline (default: the width).
- Risers per floor = ceil(height / max_riser) (or `risers`); the tread depth is FITTED: each
  flight's walkline length (the middle of the stair) / its number of treads. The first riser is at
  the start of the path, the last one (up to the top floor) at its end.

Result (`Layout`): `cuts` = lines across the stair (`Cut.c` on the side line, `Cut.o` on the other
side, `Cut.s` walkline station, `Cut.q` distance along the side line, `Cut.hard` = a tread / landing
/ element boundary), `levels[i]` = the step number of the cell between cut i and i + 1 (top =
level x R above the base), `pieces(style)` = (first cut, last cut, bottoms per cut) for the solids,
`flights` (treads, depth, narrow), `risers`, `R`, `warnings`.
"""

import math

MAX_TURN_DEG = 150.0        # sharper corners cannot get a landing
FLAT_FRACTION = 0.5         # a flight shorter than this x the tread depth gets no treads (a landing)
MIN_THICK = 0.5             # thinnest a slab stair gets under a tread root (inches)
TREAD_MIN, TREAD_MAX = 9.0, 14.0
NARROW_MIN = 6.0            # curved flights: tread depth at the narrow end
RISER_MAX = 7.75
HEADROOM = 80.0             # 6'-8"


class PlanError(Exception):
    pass


def _add(a, b, f=1.0):
    return (a[0] + b[0] * f, a[1] + b[1] * f)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _lerp(a, b, f):
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def _same(a, b, eps=1e-6):
    return _dist(a, b) <= eps


class Cut(object):
    """A line across the stair: c on the side line, o on the other side, s = walkline station,
    q = distance along the side line, hard = a boundary that must stay (not just a sample)."""
    __slots__ = ("c", "o", "s", "q", "hard")

    def __init__(self, c, o, s=0.0, q=0.0, hard=False):
        self.c, self.o, self.s, self.q, self.hard = c, o, s, q, hard

    @property
    def mid(self):
        return _lerp(self.c, self.o, 0.5)

    def copy(self, **kw):
        out = Cut(self.c, self.o, self.s, self.q, self.hard)
        for k, v in kw.items():
            setattr(out, k, v)
        return out

    def __repr__(self):
        return "<Cut s={:.3f} q={:.3f} c=({:.3f}, {:.3f}) o=({:.3f}, {:.3f})>".format(
            self.s, self.q, self.c[0], self.c[1], self.o[0], self.o[1])


def _lerp_cut(a, b, f):
    return Cut(_lerp(a.c, b.c, f), _lerp(a.o, b.o, f), a.s + (b.s - a.s) * f, a.q + (b.q - a.q) * f)


def _strip(samples, width, sigma):
    out = []
    for x, y, dx, dy in samples:
        n = (-dy * sigma, dx * sigma)
        out.append(Cut((x, y), (x + n[0] * width, y + n[1] * width)))
    return out


def _check_strip(strip, width, index):
    """Consecutive cuts must not cross: the path bends too tightly for the width otherwise."""
    along = 0.0
    for a, b in zip(strip, strip[1:]):
        dc = _sub(b.c, a.c)
        along += math.hypot(*dc)
        if math.hypot(*dc) < 1e-9:
            continue
        # o must advance with c, and b's cut line must not cross a's inside the stair
        if _dot(_sub(b.o, a.o), dc) <= 1e-9:
            raise PlanError("The stair line bends too tightly for a {:.0f}\" wide stair near {:.0f}\" along "
                            "segment {}: its inside radius must be larger than the width (draw the curve on the "
                            "inside, or make the stair narrower).".format(width, along, index + 1))
        d1, d2 = _sub(a.o, a.c), _sub(b.o, b.c)
        den = _cross(d1, d2)
        if abs(den) > 1e-12:
            t = _cross(_sub(b.c, a.c), d2) / den
            u = _cross(_sub(b.c, a.c), d1) / den
            if 1e-6 < t < 1 - 1e-6 and 1e-6 < u < 1 - 1e-6:
                raise PlanError("The stair line bends too tightly for a {:.0f}\" wide stair near {:.0f}\" along "
                                "segment {}.".format(width, along, index + 1))


def _walk(cuts):
    """Walkline length (through the middle of the cuts)."""
    return sum(_dist(a.mid, b.mid) for a, b in zip(cuts, cuts[1:]))


def _trim(strip, dist, at_end):
    """Strip shortened by `dist` measured along the side line from its end (or start)."""
    if dist <= 1e-9:
        return list(strip)
    seq = list(reversed(strip)) if at_end else list(strip)
    left = dist
    for i in range(len(seq) - 1):
        a, b = seq[i], seq[i + 1]
        L = _dist(a.c, b.c)
        if L >= left - 1e-9:
            f = left / L if L > 1e-12 else 0.0
            cut = Cut(_lerp(a.c, b.c, f), _lerp(a.o, b.o, f))
            rest = [cut] + seq[i + 1:] if f < 1.0 - 1e-9 else seq[i + 1:]
            return list(reversed(rest)) if at_end else rest
        left -= L
    return None


def _landing(seg_a, seg_b, width, sigma):
    """(trim at the end of a, trim at the start of b, [cut_a, mid, cut_b]) for the corner between
    two segments. The cuts are square to each segment through the corner's inner point."""
    dA, dB = (seg_a[-1][2], seg_a[-1][3]), (seg_b[0][2], seg_b[0][3])
    P = (seg_a[-1][0], seg_a[-1][1])
    nA = (-dA[1] * sigma, dA[0] * sigma)
    nB = (-dB[1] * sigma, dB[0] * sigma)
    turn = math.degrees(math.acos(max(-1.0, min(1.0, _dot(dA, dB)))))
    if turn > MAX_TURN_DEG:
        raise PlanError("A corner of the stair line turns {:.0f} degrees; at most {:.0f} can get a landing."
                        .format(turn, MAX_TURN_DEG))
    K = _add(P, (nA[0] + nB[0], nA[1] + nB[1]), width / (1.0 + _dot(nA, nB)))   # the other side's corner
    if _dot(nA, dB) > 1e-9:
        # turning toward the stair: the side line is the outer edge, K the inner corner
        ta, tb = _dot(_sub(P, K), dA), _dot(_sub(K, P), dB)
        cuts = [Cut(_add(P, dA, -ta), K), Cut(P, K), Cut(_add(P, dB, tb), K)]
        return ta, tb, cuts
    # turning away (or straight on): the side line is the inner edge
    return 0.0, 0.0, [Cut(P, _add(P, nA, width)), Cut(P, K), Cut(P, _add(P, nB, width))]


class Element(object):
    """A flight or a landing (kind "landing" = a corner, "flat" = along a flight)."""
    __slots__ = ("kind", "cuts", "length", "treads", "depth", "narrow", "flat", "floor", "level0", "s0")

    def __init__(self, kind, cuts):
        self.kind = kind
        self.cuts = cuts
        self.length = _walk(cuts)
        self.treads = 0
        self.depth = 0.0
        self.narrow = 0.0       # tread depth at the narrower edge (curved flights)
        self.flat = kind != "flight"
        self.floor = 0          # > 0: the landing at that floor level
        self.level0 = 0
        self.s0 = 0.0

    @property
    def s1(self):
        return self.s0 + self.length

    def __repr__(self):
        return "<{} {}{} s={:.1f}..{:.1f} treads={}>".format(self.kind, "flat " if self.flat else "",
                                                            "floor {} ".format(self.floor) if self.floor else "",
                                                            self.s0, self.s1, self.treads)


def _stations(elements):
    """Walkline station s and side-line distance q on every cut (shared boundary cuts once)."""
    prev = None
    for e in elements:
        for c in e.cuts:
            if prev is None:
                c.s = c.q = 0.0
            elif c is not prev:
                c.s = prev.s + _dist(prev.mid, c.mid)
                c.q = prev.q + _dist(prev.c, c.c)
            prev = c
    for e in elements:
        e.s0 = e.cuts[0].s
        e.length = e.cuts[-1].s - e.cuts[0].s


def _cut_at(cuts, s):
    for a, b in zip(cuts, cuts[1:]):
        if a.s - 1e-9 <= s <= b.s + 1e-9:
            f = 0.0 if b.s - a.s < 1e-12 else (s - a.s) / (b.s - a.s)
            if f <= 1e-9:
                return a, cuts.index(a), True
            if f >= 1 - 1e-9:
                return b, cuts.index(b), True
            return _lerp_cut(a, b, f), cuts.index(a), False
    raise ValueError("station outside")


def _split(e, a, b):
    """[flight before, landing a..b, flight after] (empty flights dropped)."""
    ca, ia, on_a = _cut_at(e.cuts, a)
    cb, ib, on_b = _cut_at(e.cuts, b)
    ca.hard = cb.hard = True
    before = e.cuts[:ia + 1] + ([] if on_a else [ca])
    inner = [c for c in e.cuts if a + 1e-9 < c.s < b - 1e-9]
    land = [ca] + inner + [cb]
    after = [cb] + [c for c in e.cuts if c.s > b + 1e-9]
    out = []
    if len(before) >= 2 and before[-1].s - before[0].s > 1e-6:
        out.append(Element("flight", before))
    out.append(Element("flat", land))
    if len(after) >= 2 and after[-1].s - after[0].s > 1e-6:
        out.append(Element("flight", after))
    for x in out:
        x.s0 = x.cuts[0].s
        x.length = x.cuts[-1].s - x.cuts[0].s
    return out


def _insert_landing(elements, center, depth, floor=0):
    """Put a landing `depth` long centered at walkline station `center` (shifted to fit its flight)."""
    for i, e in enumerate(elements):
        if not (e.s0 - 1e-6 <= center <= e.s1 + 1e-6):
            continue
        if e.flat:
            if floor and not e.floor:
                e.floor = floor
                return True
            if e.s1 - center > 1e-6:      # inside (not at the end of) a landing: nothing to add
                return False
            continue
        a, b = center - depth / 2.0, center + depth / 2.0
        if b - a >= e.length - 1e-6:
            a, b = e.s0, e.s1
        elif a < e.s0:
            a, b = e.s0, e.s0 + depth
        elif b > e.s1:
            a, b = e.s1 - depth, e.s1
        parts = _split(e, a, b)
        for p in parts:
            if p.flat:
                p.floor = floor
        elements[i:i + 1] = parts
        return True
    return False


def _runs(elements):
    """Maximal runs of flat elements: [(first index, last index)]."""
    out, i = [], 0
    while i < len(elements):
        if elements[i].flat:
            j = i
            while j + 1 < len(elements) and elements[j + 1].flat:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def _flat_runs(elements):
    return len(_runs(elements))


def _allocate(flights, total):
    """Treads per flight, proportional to the walkline lengths (largest remainder, >= 1 each)."""
    F = sum(f.length for f in flights)
    ideal = [f.length / F * total for f in flights]
    n = [max(1, int(math.floor(x))) for x in ideal]
    order = sorted(range(len(flights)), key=lambda i: -(ideal[i] - math.floor(ideal[i])))
    k = 0
    while sum(n) < total:
        n[order[k % len(order)]] += 1
        k += 1
    while sum(n) > total:
        cand = [i for i in reversed(order) if n[i] > 1]
        if not cand:
            break
        n[cand[0]] -= 1
    return n


def _sections(elements, floors):
    """Split the elements at the floor landings: [(elements of the section, floor run after it)]."""
    runs = _runs(elements)
    floor_runs = [(i, j) for i, j in runs if any(elements[k].floor for k in range(i, j + 1))]
    out, start = [], 0
    for k, (i, j) in enumerate(floor_runs):
        fl = sorted(set(elements[x].floor for x in range(i, j + 1) if elements[x].floor))
        if len(fl) > 1:
            raise PlanError("Floor landings {} overlap: the stair line is too short for {} floors."
                            .format(" and ".join(str(f) for f in fl), floors))
        out.append((elements[start:i], (i, j, fl[0])))
        start = j + 1
    out.append((elements[start:], None))
    return out


class Layout(object):
    def __init__(self):
        self.cuts = []
        self.levels = []
        self.risers = 0           # all floors
        self.per_floor = 0
        self.floors = 1
        self.R = 0.0
        self.height = 0.0         # floor to floor
        self.width = 0.0
        self.laps = 0.0
        self.elements = []
        self.warnings = []

    @property
    def rise(self):
        return self.height * self.floors

    @property
    def flights(self):
        return [e for e in self.elements if not e.flat]

    @property
    def landings(self):
        return [e for e in self.elements if e.flat]

    @property
    def landing_runs(self):
        return _flat_runs(self.elements)

    @property
    def run(self):
        return self.cuts[-1].s if self.cuts else 0.0

    def top(self, cell):
        return self.levels[cell] * self.R

    def ranges(self):
        """(first cut, last cut) of each flight and each run of landings, in order."""
        out = []
        for e in self.elements:
            a = min(range(len(self.cuts)), key=lambda j: abs(self.cuts[j].s - e.s0))
            b = min(range(len(self.cuts)), key=lambda j: abs(self.cuts[j].s - e.s1))
            if b <= a:
                continue
            if out and e.flat and out[-1][2]:
                out[-1] = (out[-1][0], b, True)
            else:
                out.append((a, b, e.flat))
        return [(a, b) for a, b, _ in out]

    # -- solids --------------------------------------------------------------------------------
    def _soffit(self, waist, landing):
        """Underside z per cut of a slab stair (above the base): parallel to the nosings of each
        flight, `waist` square to it under the tread roots; landings `landing` thick."""
        out = []
        for j, cut in enumerate(self.cuts):
            cand = []
            for e in self.elements:
                if not (e.s0 - 1e-6 <= cut.s <= e.s1 + 1e-6):
                    continue
                if e.flat:
                    cand.append(e.level0 * self.R - landing)
                else:
                    m = self.R / e.depth
                    cand.append(e.level0 * self.R + (cut.s - e.s0) * m - waist * math.sqrt(1.0 + m * m))
            b = min(cand) if cand else 0.0
            tops = [self.top(c) for c in (j - 1, j) if 0 <= c < len(self.levels)]
            out.append(max(0.0, min(b, min(tops) - MIN_THICK)))
        return out

    def _even_out(self, b):
        """Cuts that share a point (the corner of a landing) share one underside height."""
        out = list(b)
        j = 0
        while j < len(self.cuts):
            k = j
            while k + 1 < len(self.cuts) and (_same(self.cuts[k].c, self.cuts[k + 1].c)
                                              or _same(self.cuts[k].o, self.cuts[k + 1].o)):
                k += 1
            if k > j:
                lo = min(out[j:k + 1])
                for i in range(j, k + 1):
                    out[i] = lo
            j = k + 1
        return out

    def pieces(self, style="slab", waist=6.0, landing=None, tread=2.0):
        """[(first cut, last cut, bottoms per cut of that range)] (z above the base):
        slab = one solid with a sloped soffit, solid = one solid down to the base,
        open = one plate `tread` thick per tread and landing."""
        n = len(self.cuts)
        if style == "solid":
            return [(0, n - 1, [0.0] * n)]
        if style == "open":
            out, a = [], 0
            for c in range(1, len(self.levels) + 1):
                if c == len(self.levels) or self.levels[c] != self.levels[a]:
                    z = self.top(a) - min(tread, self.R)
                    out.append((a, c, [max(0.0, z)] * (c - a + 1)))
                    a = c
            return out
        b = self._even_out(self._soffit(waist, waist if landing is None else landing))
        return [(0, n - 1, b)]

    def coarse(self, a, b, max_turn_deg=20.0):
        """Cut indices a..b without the sample cuts that are not needed for a solid that is trimmed
        to the true curves afterwards: hard cuts, ends, and a sample wherever the cut direction has
        turned more than max_turn_deg since the last kept cut."""
        keep = [a]
        for j in range(a + 1, b):
            c, k = self.cuts[j], self.cuts[keep[-1]]
            u0, u1 = _sub(k.o, k.c), _sub(c.o, c.c)
            nxt = self.cuts[j + 1]
            u2 = _sub(nxt.o, nxt.c)
            ang = math.degrees(math.atan2(abs(_cross(u0, u2)), _dot(u0, u2)))
            if c.hard or self.levels[j - 1] != self.levels[j] or ang > max_turn_deg:
                keep.append(j)
        keep.append(b)
        return keep

    def extended(self, js, margin=1.0, clear=0.5):
        """{cut index: (c', o')}: the cuts js pushed out past both sides so that straight lines between
        consecutive ones stay outside the true side lines (sampled by every cut in between) by at
        least `clear`, without crossing where the cuts converge."""
        ext = dict((j, [margin, margin]) for j in js)
        for j0, j1 in zip(js, js[1:]):
            A, B = self.cuts[j0], self.cuts[j1]
            for side, sgn in ((0, -1.0), (1, 1.0)):     # c pushed against the across vector, o along it
                for _ in range(40):
                    pa = self._pushed(A, side, sgn * ext[j0][side])
                    pb = self._pushed(B, side, sgn * ext[j1][side])
                    worst = 0.0
                    for c in self.cuts[j0 + 1:j1]:
                        p = c.c if side == 0 else c.o
                        u = _sub(c.o, c.c)
                        L = math.hypot(*u)
                        u = (u[0] / L, u[1] / L)
                        # how far the chord is inside the stair from p, measured along the cut
                        d = _sub(pb, pa)
                        den = _cross(d, u)
                        if abs(den) < 1e-12:
                            continue
                        t = _cross(_sub(p, pa), d) / den     # p + u t lies on the chord
                        need = clear - sgn * t
                        worst = max(worst, need)
                    if worst <= 1e-6:
                        break
                    ext[j0][side] += worst + 0.25
                    ext[j1][side] += worst + 0.25
        for j0, j1 in zip(js, js[1:]):                     # converging cut lines: stop before they meet
            A, B = self.cuts[j0], self.cuts[j1]
            ua, ub = _sub(A.o, A.c), _sub(B.o, B.c)
            den = _cross(ua, ub)
            if abs(den) < 1e-12:
                continue
            t = _cross(_sub(B.c, A.c), ub) / den           # A.c + ua t = the meeting point (t in widths)
            w = math.hypot(*ua)
            if t > 1.0:
                lim = (t - 1.0) * w * 0.5
                ext[j0][1] = min(ext[j0][1], lim)
                ext[j1][1] = min(ext[j1][1], lim)
            elif t < 0.0:
                lim = -t * w * 0.5
                ext[j0][0] = min(ext[j0][0], lim)
                ext[j1][0] = min(ext[j1][0], lim)
        return dict((j, (self._pushed(self.cuts[j], 0, -ext[j][0]), self._pushed(self.cuts[j], 1, ext[j][1])))
                    for j in js)

    @staticmethod
    def _pushed(cut, side, d):
        u = _sub(cut.o, cut.c)
        L = math.hypot(*u)
        p = cut.c if side == 0 else cut.o
        return (p[0] + u[0] / L * d, p[1] + u[1] / L * d)


def layout(segments, width, height, sigma, max_riser=7.0, risers=0, floors=1, landing_count=0,
           landing_depth=None, landing_at=(), laps=0.0):
    """Plan the stair. segments: [[(x, y, dx, dy), ...], ...] split at the corners of the side
    line (inches, direction of travel up). height = floor to floor; floors = floors climbed (a
    landing at each intermediate floor); landing_count = extra landings per floor; landing_at =
    landing centers as distances along the side line; laps = times around a closed curve (for the
    headroom check). Raises PlanError when nothing sensible fits."""
    if width <= 0 or height <= 0:
        raise PlanError("A stair needs a positive width and floor height.")
    floors = max(1, int(floors or 1))
    depth = float(landing_depth) if landing_depth else float(width)
    segs = [s for s in segments if len(s) >= 2]
    if not segs:
        raise PlanError("The stair line is too short.")
    lay = Layout()
    lay.width, lay.height, lay.floors, lay.laps = width, height, floors, laps or 0.0
    strips = [_strip(s, width, sigma) for s in segs]
    for i, st in enumerate(strips):
        _check_strip(st, width, i)
    trims = [[0.0, 0.0] for _ in segs]
    corners = []
    for i in range(len(segs) - 1):
        ta, tb, cuts = _landing(segs[i], segs[i + 1], width, sigma)
        trims[i][1] += ta
        trims[i + 1][0] += tb
        corners.append(cuts)
    elements = []
    last = len(segs) - 1
    for i, st in enumerate(strips):
        L = sum(_dist(a.c, b.c) for a, b in zip(st, st[1:]))
        need = trims[i][0] + trims[i][1]
        if need > L + 1e-6:
            raise PlanError("Segment {} of the stair line is {:.1f}\" long; its landings need {:.1f}\"."
                            .format(i + 1, L, need))
        if need >= L - 1e-6:
            fl = [st[0], st[-1]]                                # landings back to back
        else:
            fl = _trim(_trim(st, trims[i][0], False), trims[i][1], True)
        if i > 0:
            fl[0] = corners[i - 1][-1]
        if i < last:
            fl[-1] = corners[i][0]
        fl[0].hard = fl[-1].hard = True
        elements.append(Element("flight", fl))
        if i < last:
            for c in corners[i]:
                c.hard = True
            elements.append(Element("landing", corners[i]))
    _stations(elements)
    total_s = elements[-1].s1

    # landings along the flights: floor levels first, then evenly spaced, then the clicked ones
    floor_s = [total_s * k / floors for k in range(1, floors)]
    for k, c in enumerate(floor_s):
        _insert_landing(elements, c, depth, floor=k + 1)
    if landing_count and int(landing_count) > 0:
        bounds = [0.0] + floor_s + [total_s]
        for f0, f1 in zip(bounds, bounds[1:]):
            n = int(landing_count)
            for i in range(1, n + 1):
                _insert_landing(elements, f0 + (f1 - f0) * i / (n + 1.0), depth)
    if landing_at:
        allc = []
        for e in elements:
            for c in e.cuts:
                if not allc or c is not allc[-1]:
                    allc.append(c)
        for q in sorted(landing_at):
            for a, b in zip(allc, allc[1:]):
                if a.q - 1e-6 <= q <= b.q + 1e-6:
                    f = 0.0 if b.q - a.q < 1e-12 else (q - a.q) / (b.q - a.q)
                    _insert_landing(elements, a.s + (b.s - a.s) * f, depth)
                    break
    if floors > 1 and sum(1 for e in elements if e.floor) < floors - 1:
        raise PlanError("No room for a landing at every floor: the stair line is too short for {} floors."
                        .format(floors))

    N = int(risers) if risers and int(risers) > 0 else int(math.ceil(height / max_riser - 1e-6))
    N = max(N, 1)
    lay.per_floor, lay.risers, lay.R = N, N * floors, height / N

    # treads per floor section (between floor landings): N - 1 levels each
    for sec, _ in _sections(elements, floors):
        flights = [e for e in sec if not e.flat]
        for _ in range(len(flights) + 1):
            live = [e for e in flights if not e.flat]
            total = N - 1 - _flat_runs(sec)
            if not live:
                break
            if total < len(live):
                raise PlanError("{} risers per floor are too few for {} flights and {} landings: raise the floor "
                                "height, lower the max riser or use fewer landings."
                                .format(N, len(live), _flat_runs(sec)))
            T = sum(e.length for e in live) / total
            short = [e for e in live if e.length < FLAT_FRACTION * T]
            if not short:
                break
            for e in short:
                e.flat = True
        live = [e for e in flights if not e.flat]
        total = N - 1 - _flat_runs(sec)
        if live:
            for e, n in zip(live, _allocate(live, total)):
                e.treads, e.depth = n, e.length / n
        elif total != 0:
            raise PlanError("A floor of the stair has no room for treads: draw a longer line or use fewer landings.")

    # cuts, cells and levels
    floor_at = {}
    for _, run in _sections(elements, floors):
        if run is not None:
            for k in range(run[0], run[1] + 1):
                floor_at[id(elements[k])] = run[2]
    level, prev = 0, None
    for e in elements:
        cuts = list(e.cuts)
        if not e.flat:
            e.level0 = level
            marks = [cuts[0].s + e.depth * k for k in range(1, e.treads)]
            out = [cuts[0]]
            mi = 0
            for a, b in zip(cuts, cuts[1:]):
                while mi < len(marks) and marks[mi] < b.s - 1e-6:
                    if marks[mi] > a.s + 1e-6:
                        out.append(_lerp_cut(a, b, (marks[mi] - a.s) / (b.s - a.s)).copy(hard=True))
                    else:
                        a.hard = True
                    mi += 1
                out.append(b)
            cuts = out
            cell_lv = [level + 1 + min(e.treads - 1, int((0.5 * (a.s + b.s) - e.s0) / e.depth + 1e-9))
                       for a, b in zip(cuts, cuts[1:])]
            level += e.treads
        else:
            if id(e) in floor_at:
                level = floor_at[id(e)] * N
            elif prev is None or not prev.flat or id(prev) in floor_at:
                level += 1          # a new run of landings (one right after a floor landing too)
            e.level0 = level
            cell_lv = [level] * (len(cuts) - 1)
        prev = e
        if not lay.cuts:
            lay.cuts.append(cuts[0])
        for b, lv in zip(cuts[1:], cell_lv):     # elements share their end cuts; skip empty cells
            a = lay.cuts[-1]
            if _same(a.c, b.c) and _same(a.o, b.o):
                continue
            lay.cuts.append(b)
            lay.levels.append(lv)
    lay.elements = elements
    if len(lay.cuts) < 2:
        raise PlanError("The stair line is too short.")
    if lay.levels[-1] != lay.risers - 1 or any(b - a > 1 or b < a for a, b in zip(lay.levels, lay.levels[1:])):
        raise PlanError("Internal error: the steps do not add up ({} levels for {} risers).".format(
            lay.levels[-1], lay.risers))
    for e in lay.flights:
        qc = sum(_dist(a.c, b.c) for a, b in zip(e.cuts, e.cuts[1:]))
        qo = sum(_dist(a.o, b.o) for a, b in zip(e.cuts, e.cuts[1:]))
        e.narrow = min(qc, qo) / e.treads
    _check(lay)
    return lay


def _check(lay):
    w = lay.warnings
    if lay.R > RISER_MAX + 1e-6:
        w.append("Risers are {:.2f}\" (more than {}\").".format(lay.R, RISER_MAX))
    fl = lay.flights
    ideal = lay.run + sum((11.0 - f.depth) * f.treads for f in fl)      # the same stair with 11" treads
    if lay.laps > 0 and fl and any(f.depth < TREAD_MIN - 1e-6 or f.depth > TREAD_MAX + 1e-6 for f in fl):
        depths = sorted(set(round(f.depth, 2) for f in fl))
        w.append("Treads are {}\" deep: about {:.2f} laps would give 11\" treads.".format(
            " / ".join("{:g}".format(x) for x in depths), lay.laps * ideal / lay.run))
        fl = []
    for i, f in enumerate(fl):
        tag = "" if len(fl) == 1 else " in flight {}".format(i + 1)
        if f.depth < TREAD_MIN - 1e-6:
            w.append("Treads{} are only {:.2f}\": draw a longer line (about {:.0f}' for 11\" treads) "
                     "or lower the floor height.".format(tag, f.depth, ideal / 12.0))
        elif f.depth > TREAD_MAX + 1e-6:
            w.append("Treads{} are {:.2f}\" deep: the stair line may be longer than the stair.".format(tag, f.depth))
    for i, f in enumerate(lay.flights):
        tag = "" if len(lay.flights) == 1 else " in flight {}".format(i + 1)
        if f.narrow < NARROW_MIN - 1e-6 and f.depth - f.narrow > 0.5:
            w.append("Treads{} are only {:.2f}\" deep at the inside of the curve (at least {}\"): use a larger "
                     "radius or a narrower stair.".format(tag, f.narrow, NARROW_MIN))
    if lay.laps > 1.0 + 1e-6:
        clear = lay.rise / lay.laps
        if clear < HEADROOM + 12.0:
            w.append("Each lap rises only {:.0f}\": the headroom under the lap above is less than 6'-8\" plus the "
                     "stair's thickness: draw a larger curve and use fewer laps.".format(clear))
