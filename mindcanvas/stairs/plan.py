"""Stair layout in plan (pure Python, no Rhino: testable anywhere).

The stair is driven by ONE side of its plan boundary: a curve sampled into segments split at its
corners. Each segment is a list of samples (x, y, dx, dy): a point on the side line and the unit
tangent there, in the direction of travel UP the stair. `sigma` is the side the stair lies on:
+1 = left of the curve (the curve is the stair's RIGHT side), -1 = right of it (the curve is the
LEFT side). Units: inches.

    lay = layout(segments, width=42, height=120, sigma=-1, max_riser=7)

Segments become flights; every corner between two segments becomes a landing (a kite in the
corner: square for a 90 degree turn). The riser count comes from the floor height
(ceil(height / max_riser), or `risers`), the tread depth is FITTED to the curve: each flight's
walkline length (the middle of the stair) / its number of treads. The first riser is at the start
of the curve, the last one (up to the upper floor) at its end.

Result (`Layout`): `cuts` = lines across the stair (`Cut.c` on the side curve, `Cut.o` on the
other side, `Cut.s` walkline station), `levels[i]` = the step number of the cell between cut i and
i + 1 (top = level * R above the base), `pieces(style, ...)` = (first cut, last cut, bottoms per
cut) for the solids, `flights` (n treads, depth), `risers`, `R`, `warnings`.
"""

import math

MAX_TURN_DEG = 150.0        # sharper corners cannot get a landing
FLAT_FRACTION = 0.5         # a flight shorter than this x the tread depth gets no treads (a landing)
MIN_THICK = 0.5             # thinnest a slab stair gets under a tread root (inches)
TREAD_MIN, TREAD_MAX = 9.0, 14.0
RISER_MAX = 7.75


class PlanError(Exception):
    pass


def _add(a, b, f=1.0):
    return (a[0] + b[0] * f, a[1] + b[1] * f)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _lerp(a, b, f):
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def _same(a, b, eps=1e-6):
    return _dist(a, b) <= eps


class Cut(object):
    """A line across the stair: c on the side curve, o on the other side, s = walkline station."""
    __slots__ = ("c", "o", "s")

    def __init__(self, c, o, s=0.0):
        self.c, self.o, self.s = c, o, s

    @property
    def mid(self):
        return _lerp(self.c, self.o, 0.5)

    def __repr__(self):
        return "<Cut s={:.3f} c=({:.3f}, {:.3f}) o=({:.3f}, {:.3f})>".format(self.s, self.c[0], self.c[1],
                                                                             self.o[0], self.o[1])


def _strip(samples, width, sigma):
    out = []
    for x, y, dx, dy in samples:
        n = (-dy * sigma, dx * sigma)
        out.append(Cut((x, y), (x + n[0] * width, y + n[1] * width)))
    return out


def _walk(strip):
    """Walkline length of a strip (through the middle of its cuts)."""
    return sum(_dist(a.mid, b.mid) for a, b in zip(strip, strip[1:]))


def _trim(strip, dist, at_end):
    """Strip shortened by `dist` measured along the side curve from its end (or start)."""
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


def _tangent(samples, end):
    s = samples[-1] if end else samples[0]
    return (s[2], s[3])


def _landing(seg_a, seg_b, width, sigma):
    """(trim at the end of a, trim at the start of b, [cut_a, mid, cut_b]) for the corner between
    two segments. The cuts are square to each segment through the corner's inner point."""
    dA, dB = _tangent(seg_a, True), _tangent(seg_b, False)
    P = (seg_a[-1][0], seg_a[-1][1])
    nA = (-dA[1] * sigma, dA[0] * sigma)
    nB = (-dB[1] * sigma, dB[0] * sigma)
    turn = math.degrees(math.acos(max(-1.0, min(1.0, _dot(dA, dB)))))
    if turn > MAX_TURN_DEG:
        raise PlanError("A corner of the stair line turns {:.0f} degrees; at most {:.0f} can get a landing."
                        .format(turn, MAX_TURN_DEG))
    K = _add(P, (nA[0] + nB[0], nA[1] + nB[1]), width / (1.0 + _dot(nA, nB)))   # the other side's corner
    if _dot(nA, dB) > 1e-9:
        # turning toward the stair: the side curve is the outer edge, K the inner corner
        ta, tb = _dot(_sub(P, K), dA), _dot(_sub(K, P), dB)
        cuts = [Cut(_add(P, dA, -ta), K), Cut(P, K), Cut(_add(P, dB, tb), K)]
        return ta, tb, cuts
    # turning away (or straight on): the side curve is the inner edge
    return 0.0, 0.0, [Cut(P, _add(P, nA, width)), Cut(P, K), Cut(P, _add(P, nB, width))]


class Element(object):
    """A flight (cuts of a strip) or a landing (3 cuts)."""
    __slots__ = ("kind", "cuts", "length", "treads", "depth", "flat", "level0", "s0")

    def __init__(self, kind, cuts):
        self.kind = kind
        self.cuts = cuts
        self.length = _walk(cuts)
        self.treads = 0
        self.depth = 0.0
        self.flat = kind == "landing"
        self.level0 = 0
        self.s0 = 0.0


def _flat_runs(elements):
    n, prev = 0, False
    for e in elements:
        if e.flat and not prev:
            n += 1
        prev = e.flat
    return n


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
    for i in reversed(order):
        if sum(n) <= total:
            break
        if n[i] > 1:
            n[i] -= 1
    return n


class Layout(object):
    def __init__(self):
        self.cuts = []
        self.levels = []
        self.risers = 0
        self.R = 0.0
        self.height = 0.0
        self.width = 0.0
        self.elements = []
        self.warnings = []

    @property
    def flights(self):
        return [e for e in self.elements if e.kind == "flight" and not e.flat]

    @property
    def landings(self):
        return [e for e in self.elements if e.flat]

    @property
    def run(self):
        return self.cuts[-1].s if self.cuts else 0.0

    def top(self, cell):
        return self.levels[cell] * self.R

    def riser_at(self, j):
        """Index of a cut with a riser (the level changes across it, or the stair starts there)."""
        return 0 < j < len(self.cuts) - 1 and self.levels[j - 1] != self.levels[j]

    # -- solids --------------------------------------------------------------------------------
    def _soffit(self, waist, landing):
        """Underside z per cut of a slab stair (above the base): parallel to the nosings of each
        flight, `waist` square to it under the tread roots; landings `landing` thick."""
        out = []
        for j, cut in enumerate(self.cuts):
            cand = []
            for e in self.elements:
                lo, hi = e.s0, e.s0 + e.length
                if not (lo - 1e-6 <= cut.s <= hi + 1e-6):
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


def layout(segments, width, height, sigma, max_riser=7.0, risers=0):
    """Plan the stair. segments: [[(x, y, dx, dy), ...], ...] split at the corners of the side
    curve (inches, direction of travel up). Raises PlanError when nothing sensible fits."""
    if width <= 0 or height <= 0:
        raise PlanError("A stair needs a positive width and floor height.")
    segs = [s for s in segments if len(s) >= 2]
    if not segs:
        raise PlanError("The stair line is too short.")
    lay = Layout()
    lay.width, lay.height = width, height
    strips = [_strip(s, width, sigma) for s in segs]
    trims = [[0.0, 0.0] for _ in segs]
    landings = []
    for i in range(len(segs) - 1):
        ta, tb, cuts = _landing(segs[i], segs[i + 1], width, sigma)
        trims[i][1] += ta
        trims[i + 1][0] += tb
        landings.append(cuts)
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
            fl[0] = landings[i - 1][-1]
        if i < last:
            fl[-1] = landings[i][0]
        elements.append(Element("flight", fl))
        if i < len(segs) - 1:
            elements.append(Element("landing", landings[i]))

    N = int(risers) if risers and int(risers) > 0 else int(math.ceil(height / max_riser - 1e-6))
    N = max(N, 1)
    lay.risers, lay.R = N, height / N
    flights = [e for e in elements if e.kind == "flight"]
    for e in flights:
        e.flat = e.length < 1e-6
    for _ in range(len(flights) + 1):
        live = [e for e in flights if not e.flat]
        total = N - 1 - _flat_runs(elements)
        if not live:
            break
        if total < len(live):
            raise PlanError("{} risers are too few for {} flights and {} landings: raise the floor height or "
                            "lower the max riser.".format(N, len(live), len(elements) - len(live)))
        T = sum(e.length for e in live) / total
        short = [e for e in live if e.length < FLAT_FRACTION * T]
        if not short:
            break
        for e in short:
            e.flat = True
    live = [e for e in flights if not e.flat]
    total = N - 1 - _flat_runs(elements)
    if live:
        for e, n in zip(live, _allocate(live, total)):
            e.treads, e.depth = n, e.length / n
    elif total != 0:
        raise PlanError("The stair line has no room for treads.")

    # cuts, cells and levels
    level, prev_flat, s = 0, False, 0.0
    for e in elements:
        e.s0 = s
        cuts = list(e.cuts)
        if not e.flat:
            e.level0 = level
            # tread boundaries at equal walkline steps
            stations = [0.0]
            for a, b in zip(cuts, cuts[1:]):
                stations.append(stations[-1] + _dist(a.mid, b.mid))
            marks = [e.depth * k for k in range(1, e.treads)]
            out, cell_lv = [cuts[0]], []
            mi = 0
            for i in range(len(cuts) - 1):
                a, b, s_a, s_b = cuts[i], cuts[i + 1], stations[i], stations[i + 1]
                while mi < len(marks) and marks[mi] < s_b - 1e-6:
                    if marks[mi] > s_a + 1e-6:
                        f = (marks[mi] - s_a) / (s_b - s_a)
                        out.append(Cut(_lerp(a.c, b.c, f), _lerp(a.o, b.o, f)))
                    mi += 1
                out.append(b)
            cuts = out
            st = [0.0]
            for a, b in zip(cuts, cuts[1:]):
                st.append(st[-1] + _dist(a.mid, b.mid))
            for a, b in zip(st, st[1:]):
                cell_lv.append(level + 1 + min(e.treads - 1, int((0.5 * (a + b)) / e.depth + 1e-9)))
            level += e.treads
        else:
            if not prev_flat:
                level += 1
            e.level0 = level
            cell_lv = [level] * (len(cuts) - 1)
        prev_flat = e.flat
        if not lay.cuts:
            cuts[0].s = 0.0
            lay.cuts.append(cuts[0])
        for b, lv in zip(cuts[1:], cell_lv):     # elements share their end cuts; skip empty cells
            a = lay.cuts[-1]
            if _same(a.c, b.c) and _same(a.o, b.o):
                continue
            s += _dist(a.mid, b.mid)
            b = Cut(b.c, b.o, s)
            lay.cuts.append(b)
            lay.levels.append(lv)
    lay.elements = elements
    if len(lay.cuts) < 2:
        raise PlanError("The stair line is too short.")
    _check(lay)
    return lay


def _check(lay):
    w = lay.warnings
    if lay.R > RISER_MAX + 1e-6:
        w.append("Risers are {:.2f}\" (more than {}\").".format(lay.R, RISER_MAX))
    for i, f in enumerate(lay.flights):
        tag = "" if len(lay.flights) == 1 else " in flight {}".format(i + 1)
        if f.depth < TREAD_MIN - 1e-6:
            w.append("Treads{} are only {:.2f}\": draw a longer line (about {:.0f}' for 11\" treads) "
                     "or lower the floor height.".format(tag, f.depth, (lay.run + (11.0 - f.depth) * f.treads) / 12.0))
        elif f.depth > TREAD_MAX + 1e-6:
            w.append("Treads{} are {:.2f}\" deep: the stair line may be longer than the stair.".format(tag, f.depth))
