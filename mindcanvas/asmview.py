"""The drawn layer section of the visual assembly editor (Phase 12), as plain Python: layout (band
positions at true relative thickness, labels + leaders), hit testing, and the mouse logic (click to
select, drag a layer to reorder it, drag a boundary to change a thickness with snapping). The Eto
view (eto/sectionview.py) only paints a SectionLayout and forwards mouse events to a
SectionController, so tests drive everything here without clicks.

Orientation: walls are drawn as a plan cut, exterior LEFT -> interior RIGHT (vertical bands);
floors and roofs top -> bottom (horizontal bands). Coordinates are pixels, y down.
A boundary drag resizes the layer on the exterior / top side of it (the first boundary: the first
layer, the last: the last layer); a membrane next to a thicker layer gives the drag to that layer.
Members: framing / joist / rafter layers snap to the library member depths of their system
(AssemblyModel.snap); other layers to 1/16" (1/64" below 1/16" or with `fine`).
"""

from . import asmfields

MIN_PX = 6.0          # thinnest drawn band (membranes)
EDGE_PX = 4.0         # boundary grab distance
DRAG_PX = 4.0         # movement before a press becomes a reorder drag
ROW = 15.0            # label row height
LABEL_W = 190.0       # room for the labels (right side)
FIXED = ("membrane",)  # thickness of these goes to the neighbor when their shared edge is dragged

END_LABELS = {"wall": ("EXTERIOR", "INTERIOR"), "floor": ("TOP", "BOTTOM"), "roof": ("OUTSIDE", "INSIDE")}


def spans(thicknesses, length, min_px=MIN_PX, scale=None):
    """[(lo, hi)] of the bands along the stack (from 0) and the px / inch scale. Thin layers get
    min_px, the rest share what is left in proportion; scale given = no fitting (a frozen drag)."""
    n = len(thicknesses)
    if not n:
        return [], 1.0
    t = [max(0.0, x) for x in thicknesses]
    if scale is None:
        fixed = set()
        while True:
            free = sum(t[i] for i in range(n) if i not in fixed)
            room = length - min_px * len(fixed)
            if free <= 1e-12 or room <= 0:
                scale = None
                break
            scale = room / free
            more = set(i for i in range(n) if i not in fixed and t[i] * scale < min_px)
            if not more:
                break
            fixed |= more
        if scale is None:
            w = length / float(n)
            out = [(i * w, (i + 1) * w) for i in range(n)]
            return out, (w / max(t) if max(t) > 0 else 1.0)
    out, x = [], 0.0
    for v in t:
        w = max(min_px, v * scale)
        out.append((x, x + w))
        x += w
    return out, scale


class Band(object):
    def __init__(self, index, spec, thickness, lib):
        self.index = index
        self.spec = spec
        self.name = spec.get("name") or spec.get("material") or "Layer {}".format(index + 1)
        self.thickness = thickness
        self.component = spec.get("component", "solid")
        self.material = spec.get("material")
        m = lib.data["materials"].get(self.material) if self.material else None
        self.color = tuple((m or {}).get("color") or ((255, 255, 255) if self.component == "void" else (180, 180, 180)))
        self.section = dict((m or {}).get("section") or {})
        self.core = bool(spec.get("core"))
        self.options = spec.get("options") or {}
        self.lifts = []               # strata: [(rgb, height)] bottom -> top
        if self.component == "strata":
            for lift in self.options.get("lifts") or []:
                lm = lib.data["materials"].get(lift.get("material")) or {}
                self.lifts.append((tuple(lm.get("color") or self.color), lift.get("height", 6)))
        self.lo = self.hi = 0.0
        self.rect = (0.0, 0.0, 0.0, 0.0)
        self.thin = False
        self.label = ""
        self.label_pos = (0.0, 0.0)
        self.leader = []

    @property
    def fixed(self):
        return self.component in FIXED

    @property
    def center(self):
        return 0.5 * (self.lo + self.hi)

    def __repr__(self):
        return "<Band {} {} {:.4f}in [{:.1f},{:.1f}]>".format(self.index, self.name, self.thickness, self.lo, self.hi)


class SectionLayout(object):
    """Bands of a model's current stack fitted into width x height pixels.
    override: {index: inches} (a thickness being dragged); scale: frozen px / inch.
    compact: the whole size for the bands, no labels (the assembly palette's tiles)."""

    def __init__(self, model, width, height, override=None, scale=None, compact=False):
        self.compact = compact
        self.kind = model.kind if model.kind in END_LABELS else "wall"
        self.orient = "h" if self.kind == "wall" else "v"
        self.width, self.height = float(width), float(height)
        lib = model.lib
        n = len(model.layers)
        self.bands = []
        for i in range(n):
            t = (override or {}).get(i)
            if t is None:
                t = model.thickness_in(i)
            spec = model.fitted(i)
            b = Band(i, spec, t, lib)
            b.member_name, b.member, b.metal = model.member(i)
            fill = b.options.get("cavity_fill")
            fm = lib.data["materials"].get(fill) if fill else None
            b.fill = (fill, tuple(fm.get("color") or (220, 220, 220)), dict(fm.get("section") or {})) if fm else None
            self.bands.append(b)
        self.total = sum(b.thickness for b in self.bands)
        self.ends = END_LABELS[self.kind]
        if compact:
            m = 4.0
            self.x0, self.x1, self.y0, self.y1 = m, self.width - m, m, self.height - m
            length = (self.x1 - self.x0) if self.orient == "h" else (self.y1 - self.y0)
        elif self.orient == "h":
            self.x0, self.x1 = 30.0, max(90.0, self.width - LABEL_W)
            self.y0 = 40.0
            self.y1 = max(self.y0 + 60.0, self.height - 20.0 - n * ROW)
            length = self.x1 - self.x0
        else:
            self.x0, self.x1 = 40.0, max(100.0, self.width - LABEL_W - 40.0)
            self.y0, self.y1 = 30.0, max(90.0, self.height - 30.0)
            length = self.y1 - self.y0
        sp, self.scale = spans([b.thickness for b in self.bands], length, 2.0 if compact else MIN_PX, scale)
        start = self.x0 if self.orient == "h" else self.y0
        for b, (lo, hi) in zip(self.bands, sp):
            b.lo, b.hi = start + lo, start + hi
            b.thin = (hi - lo) <= MIN_PX + 1e-6 and b.thickness * self.scale < MIN_PX
            if self.orient == "h":
                b.rect = (b.lo, self.y0, b.hi - b.lo, self.y1 - self.y0)
            else:
                b.rect = (self.x0, b.lo, self.x1 - self.x0, b.hi - b.lo)
            b.label = "{}  {}\"".format(b.name, asmfields.show_length(b.thickness))
        self.end = self.bands[-1].hi if self.bands else start
        self.reference = None, None
        if self.kind == "wall" and self.bands:
            ref = model.data.get("default_reference") or "center"
            self.reference = ref, self._reference(ref)
        if not compact:
            self._labels()

    def _reference(self, ref):
        """Pixel position of a wall's location line (kinds.wall.reference_distance)."""
        bs = self.bands
        core = [b for b in bs if b.core]
        c0, c1 = (core[0].lo, core[-1].hi) if core else (bs[0].lo, bs[-1].hi)
        return {"exterior_face": bs[0].lo, "interior_face": bs[-1].hi, "center": 0.5 * (bs[0].lo + bs[-1].hi),
                "core_exterior": c0, "core_interior": c1, "core_center": 0.5 * (c0 + c1)}.get(ref)

    # -- labels ---------------------------------------------------------------------------------
    def _labels(self):
        n = len(self.bands)
        if self.orient == "h":
            # a staircase: the exterior layer's label lowest, so leaders never cross a label
            for b in self.bands:
                r = n - 1 - b.index
                y = self.y1 + 12.0 + r * ROW
                x = b.center
                b.leader = [(x, self.y1), (x, y), (x + 6.0, y)]
                b.label_pos = (x + 9.0, y - 7.0)
        else:
            want = [b.center for b in self.bands]
            ys = spread(want, ROW, self.y0 - 10.0, self.height - 8.0)
            for b, y in zip(self.bands, ys):
                b.leader = [(self.x1, b.center), (self.x1 + 14.0, b.center), (self.x1 + 30.0, y), (self.x1 + 36.0, y)]
                b.label_pos = (self.x1 + 40.0, y - 7.0)

    def label_rect(self, b):
        x, y = b.label_pos
        return (x, y, 6.6 * len(b.label) + 4.0, ROW)

    # -- geometry queries -----------------------------------------------------------------------
    def along(self, x, y):
        return x if self.orient == "h" else y

    def across(self, x, y):
        return y if self.orient == "h" else x

    def in_span(self, x, y):
        c = self.across(x, y)
        lo, hi = (self.y0, self.y1) if self.orient == "h" else (self.x0, self.x1)
        return lo - 2 <= c <= hi + 2

    def edges(self):
        """Boundary positions: edge k is before band k (edge n = the last face)."""
        if not self.bands:
            return []
        return [self.bands[0].lo] + [b.hi for b in self.bands]

    def edge_target(self, k):
        """(band index, sign) a drag of edge k resizes; sign +1 = moving the edge toward the
        interior / bottom makes it thicker."""
        n = len(self.bands)
        if k <= 0:
            return 0, -1
        if k >= n:
            return n - 1, 1
        a, b = self.bands[k - 1], self.bands[k]
        if a.fixed and not b.fixed:
            return k, -1
        return k - 1, 1

    def hit(self, x, y):
        """("edge", k) | ("band", i) | ("label", i) | None."""
        for b in self.bands:
            rx, ry, rw, rh = self.label_rect(b)
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                return ("label", b.index)
        if not self.bands or not self.in_span(x, y):
            return None
        p = self.along(x, y)
        es = self.edges()
        best = None
        for k, e in enumerate(es):
            # grab distance never more than a third of a neighbor, so a thin band stays clickable
            nb = [self.bands[j] for j in (k - 1, k) if 0 <= j < len(self.bands)]
            tol = min([EDGE_PX] + [(q.hi - q.lo) / 3.0 for q in nb])
            d = abs(p - e)
            if d <= tol and (best is None or d < best[0]):
                best = (d, k)
        if best is not None:
            return ("edge", best[1])
        for b in self.bands:
            if b.lo <= p <= b.hi:
                return ("band", b.index)
        return None

    def slot(self, p):
        """Insertion slot 0..n for a dragged layer at position p (number of band centers before p)."""
        return sum(1 for b in self.bands if b.center < p)

    def slot_pos(self, s):
        es = self.edges()
        return es[max(0, min(s, len(es) - 1))] if es else 0.0


def spread(want, gap, lo, hi):
    """Label positions near `want` (sorted as given), at least `gap` apart, kept in [lo, hi]."""
    n = len(want)
    if not n:
        return []
    ys = list(want)
    for i in range(n):
        if i and ys[i] < ys[i - 1] + gap:
            ys[i] = ys[i - 1] + gap
    over = ys[-1] - hi
    if over > 0:
        ys[-1] -= over
        for i in range(n - 2, -1, -1):
            if ys[i] > ys[i + 1] - gap:
                ys[i] = ys[i + 1] - gap
    if ys[0] < lo:
        d = lo - ys[0]
        ys = [y + d for y in ys]
    return ys


def drop_index(i, slot):
    """Final index of layer i dropped at insertion slot `slot`."""
    return slot if slot <= i else slot - 1


class SectionController(object):
    """Selection + drag state of the drawn section. down / move / up take pixel coordinates and
    return what happened ("select", "thickness", "reorder", True = redraw, None)."""

    def __init__(self, model, width=640, height=380):
        self.model = model
        self.width, self.height = width, height
        self.selected = 0 if model.layers else -1
        self.drag = None
        self.hover = None
        self.layout = None
        self.relayout()

    def resize(self, width, height):
        self.width, self.height = max(200, int(width)), max(160, int(height))
        self.relayout()

    def relayout(self):
        d = self.drag
        if d and d["mode"] == "edge":
            self.layout = SectionLayout(self.model, self.width, self.height, {d["index"]: d["value"]}, d["scale"])
        else:
            self.layout = SectionLayout(self.model, self.width, self.height)
        n = len(self.model.layers)
        if self.selected >= n:
            self.selected = n - 1
        return self.layout

    def select(self, i):
        self.selected = i if 0 <= i < len(self.model.layers) else -1

    # -- mouse ----------------------------------------------------------------------------------
    def down(self, x, y):
        h = self.layout.hit(x, y)
        if h is None:
            return None
        lay = self.layout
        if h[0] == "edge":
            i, sign = lay.edge_target(h[1])
            t0 = lay.bands[i].thickness
            self.drag = {"mode": "edge", "edge": h[1], "index": i, "sign": sign, "start": lay.along(x, y),
                         "t0": t0, "value": t0, "member": None, "scale": lay.scale, "moved": False}
        else:
            i = h[1]
            self.drag = {"mode": "press", "index": i, "start": lay.along(x, y), "slot": None,
                         "label": h[0] == "label"}
        self.select(self.drag["index"])
        return "select"

    def move(self, x, y, fine=False):
        d = self.drag
        if d is None:
            h = self.layout.hit(x, y)
            if h != self.hover:
                self.hover = h
                return True
            return None
        p = self.layout.along(x, y)
        if d["mode"] == "edge":
            raw = d["t0"] + d["sign"] * (p - d["start"]) / max(d["scale"], 1e-9)
            raw = max(raw, 1.0 / 64)
            value, member = self.model.snap(d["index"], raw, fine)
            changed = abs(value - d["value"]) > 1e-9
            d["value"], d["member"] = value, member
            d["moved"] = d["moved"] or abs(p - d["start"]) > 1
            if changed:
                self.relayout()
            return True
        if d["label"]:
            return None
        if d["mode"] == "press" and abs(p - d["start"]) > DRAG_PX:
            d["mode"] = "reorder"
        if d["mode"] == "reorder":
            d["slot"] = self.layout.slot(p)
            return True
        return None

    def up(self, x=None, y=None):
        d, self.drag = self.drag, None
        if d is None:
            return None
        out = "select"
        if d["mode"] == "edge":
            if abs(d["value"] - d["t0"]) > 1e-9:
                self.model.set_thickness_in(d["index"], d["value"], d["member"])
                out = "thickness"
        elif d["mode"] == "reorder" and d["slot"] is not None:
            j = drop_index(d["index"], d["slot"])
            if j != d["index"]:
                self.selected = self.model.move_to(d["index"], j)
                out = "reorder"
        self.relayout()
        return out

    def cancel(self):
        self.drag = None
        self.relayout()

    # -- helpers for tests / the view ------------------------------------------------------------
    def band_point(self, i, frac=0.5):
        """A pixel inside band i (frac along it), on the section's middle line."""
        b = self.layout.bands[i]
        p = b.lo + frac * (b.hi - b.lo)
        lay = self.layout
        if lay.orient == "h":
            return p, 0.5 * (lay.y0 + lay.y1)
        return 0.5 * (lay.x0 + lay.x1), p

    def edge_point(self, k):
        e = self.layout.edges()[k]
        lay = self.layout
        if lay.orient == "h":
            return e, 0.5 * (lay.y0 + lay.y1)
        return 0.5 * (lay.x0 + lay.x1), e

    def drag_edge(self, k, inches_delta, fine=False):
        """Press edge k, move it by inches_delta (at the frozen scale), release. Returns up()."""
        x, y = self.edge_point(k)
        if self.down(x, y) is None or self.drag["mode"] != "edge":
            raise ValueError("edge {} not grabbed (hit {})".format(k, self.layout.hit(x, y)))
        dp = self.drag["sign"] * inches_delta * self.drag["scale"]
        if self.layout.orient == "h":
            self.move(x + dp, y, fine)
        else:
            self.move(x, y + dp, fine)
        return self.up()

    def drag_band(self, i, slot):
        """Press band i, drag it to insertion slot `slot`, release. Returns up()."""
        x, y = self.band_point(i)
        self.down(x, y)
        target = self.layout.slot_pos(slot)
        lay = self.layout
        # just past the slot's boundary, on the side away from the band
        p = target + (-2.0 if target > lay.bands[i].center else 2.0)
        steps = [lay.along(x, y) + (p - lay.along(x, y)) * f for f in (0.25, 0.6, 1.0)]
        for q in steps:
            if lay.orient == "h":
                self.move(q, y)
            else:
                self.move(x, q)
        return self.up()
