"""The visual curtain-grid editor (MCCurtainGrid) as plain Python: the grid model, layout, hit
testing, tools, snapping and undo. The Eto window (eto/cwgrid.py) only paints what is here and
forwards mouse / key events (eto/cwgridview.py), so tests drive everything without clicks.
Reading a curtain wall into a model and writing it back is curtainwall/gridio.py.

GridModel: one curtain wall unfolded into an elevation, in INCHES. u = length along the wall's
grid curve (0 at its start, L at its end; a closed wall repeats its first grid line at L),
z = height above the base (0 = sill line, H = head line).

    verts    grid lines (mullion centre lines), sorted by u. `locked` ones (wall ends, corners,
             kinks) cannot move or go; the others are the custom `verticals`.
    hlines   horizontal lines: HLine(z, bays, kind) -- a transom crossing the bays in `bays`
             (a set of bay indices; every bay = a full-width transom), or a unitized stack joint
             (kind "stack", always full width).
    cells    {(bay, row): infill}; rows count per bay, bottom -> top, between its lines. Kept for
             every cell; edits that change the topology re-map the cells by their centres.
    doors    {bay: Door}: a door from the base up to its head line (the centre of the head
             transom) filling the bay's clear width; the bay's lines below the head are hidden
             (the builder drops them), the cells above keep their rows.

GridController: the screen side. Pixels, y down. The elevation is seen from the EXTERIOR by
default (u runs right -> left: the exterior is on the left of the drawing direction) or from the
interior. Tools:

    select      click a line / cell / door to select it; drag a grid line or a transom to move it
                (Ctrl-drag a transom: only its segment in that bay); drag a door's head
    vertical    click to add a grid line (then drag it while the button is down)
    horizontal  click in a bay to add a transom there (Shift or "whole width": across every bay);
                clicking at the height of a transom next door extends it
    delete      click a grid line, a transom segment (Shift: the whole transom) or a door
    paint       click / drag over cells: vision, spandrel or shadow box
    door        click a cell: a door in that bay up to the top of that cell (the bottom row:
                the door type's height)

Snapping: positions round to `snap` inches; a transom also snaps to the height of other lines and
door heads within MAGNET_PX; Alt = no snapping.
"""

import copy

from .. import units

VISION, SPANDREL, SHADOW = "vision", "spandrel", "shadow_box"
INFILLS = (VISION, SPANDREL, SHADOW)
TOOLS = ("select", "vertical", "horizontal", "delete", "paint", "door")
MIN_GAP = 2.0           # grid lines: closest spacing in mullion widths (= grid.MIN_GAP)
MIN_DOOR_HEAD = 60.0    # lowest door head above the base, inches
GRAB_PX = 5.0
DRAG_PX = 3.0
MAGNET_PX = 6.0
EPS = 1.0 / 64
MARGINS = (58.0, 92.0, 30.0, 70.0)      # left, right, top, bottom (px)


def fmt(inches):
    return units.format_inches(inches, 16)


class Vert(object):
    def __init__(self, u, locked=False, kind="inline"):
        self.u = float(u)
        self.locked = bool(locked)
        self.kind = kind

    def __repr__(self):
        return "<V {:.3f}{}>".format(self.u, " locked" if self.locked else "")


class HLine(object):
    def __init__(self, z, bays, kind="transom"):
        self.z = float(z)
        self.bays = set(bays)
        self.kind = kind

    def __repr__(self):
        return "<H {} {:.3f} {}>".format(self.kind, self.z, sorted(self.bays))


class Door(object):
    def __init__(self, type_name, head, swing="in", hinge="left", leaves=1, shim=0.5, oid=None):
        self.type = type_name
        self.head = float(head)
        self.swing = swing
        self.hinge = hinge
        self.leaves = int(leaves or 1)
        self.shim = float(shim)
        self.id = oid

    def __repr__(self):
        return "<Door {} head {:.3f}>".format(self.type, self.head)


class EditRefused(Exception):
    pass


class GridModel(object):
    def __init__(self, length, height, mullion_w, transom_w, closed=False, row_types=None):
        self.L = float(length)
        self.H = float(height)
        self.wv = float(mullion_w)
        self.wh = float(transom_w)
        self.closed = bool(closed)
        self.verts = [Vert(0.0, True, "start"), Vert(self.L, True, "end")]
        self.hlines = []
        self.cells = {}
        self.doors = {}
        self.row_types = list(row_types or [VISION])
        self.has_stack = False
        self.message = ""

    # -- geometry ------------------------------------------------------------------------------
    @property
    def gap_v(self):
        return MIN_GAP * self.wv

    @property
    def gap_h(self):
        return 2.0 * self.wh

    @property
    def margin_h(self):
        return 1.5 * self.wh

    @property
    def nbays(self):
        return len(self.verts) - 1

    def span(self, bay):
        return self.verts[bay].u, self.verts[bay + 1].u

    def mid(self, bay):
        a, b = self.span(bay)
        return 0.5 * (a + b)

    def bay_of_u(self, u):
        for i in range(self.nbays):
            if u <= self.verts[i + 1].u + 1e-9:
                return i
        return self.nbays - 1

    def lines_in(self, bay):
        """Indices of the lines crossing a bay, bottom -> top."""
        return sorted((i for i, h in enumerate(self.hlines) if bay in h.bays), key=lambda i: self.hlines[i].z)

    def rows(self, bay):
        zs = [0.0] + [self.hlines[i].z for i in self.lines_in(bay)] + [self.H]
        return list(zip(zs, zs[1:]))

    def row_of(self, bay, z):
        rows = self.rows(bay)
        for r, (z0, z1) in enumerate(rows):
            if z <= z1 + 1e-9:
                return r
        return len(rows) - 1

    def default(self, row):
        return self.row_types[min(row, len(self.row_types) - 1)]

    def cell_type(self, bay, row):
        return self.cells.get((bay, row)) or self.default(row)

    def hidden(self, bay, li):
        """True if line li is under the door of the bay (the builder drops it)."""
        d = self.doors.get(bay)
        return d is not None and self.hlines[li].z < d.head + self.margin_h - 1e-9

    def visible_cells(self, bay):
        """[(z0, z1, row)] of the panels the builder makes in a bay (above its door, if any)."""
        d = self.doors.get(bay)
        if d is None:
            return [(z0, z1, r) for r, (z0, z1) in enumerate(self.rows(bay))]
        zs = [d.head] + [self.hlines[i].z for i in self.lines_in(bay) if not self.hidden(bay, i)] + [self.H]
        out = []
        for z0, z1 in zip(zs, zs[1:]):
            out.append((z0, z1, self.row_of(bay, 0.5 * (z0 + z1))))
        return out

    def clear_width(self, bay):
        a, b = self.span(bay)
        return (b - a) - self.wv

    # -- state ----------------------------------------------------------------------------------
    def state(self):
        return copy.deepcopy((self.verts, self.hlines, self.cells, self.doors, self.row_types))

    def restore(self, st):
        self.verts, self.hlines, self.cells, self.doors, self.row_types = copy.deepcopy(st)

    def refuse(self, msg):
        self.message = msg
        raise EditRefused(msg)

    def materialize(self, infill):
        """cells for every cell from infill(bay, row)."""
        self.cells = {}
        for b in range(self.nbays):
            for r in range(len(self.rows(b))):
                self.cells[(b, r)] = infill(b, r)

    def _snapshot(self):
        out = []
        for b in range(self.nbays):
            u0, u1 = self.span(b)
            for r, (z0, z1) in enumerate(self.rows(b)):
                out.append((u0, u1, z0, z1, self.cell_type(b, r)))
        doors = [(self.mid(b), d) for b, d in self.doors.items()]
        return out, doors

    def _remap(self, snap):
        cells, doors = snap
        new = {}
        for b in range(self.nbays):
            uc = self.mid(b)
            for r, (z0, z1) in enumerate(self.rows(b)):
                zc = 0.5 * (z0 + z1)
                t = None
                for u0, u1, a, c, typ in cells:
                    if u0 - 1e-9 <= uc <= u1 + 1e-9 and a - 1e-9 <= zc <= c + 1e-9:
                        t = typ
                        break
                new[(b, r)] = t or self.default(r)
        self.cells = new
        self.doors = {}
        dropped = 0
        for u, d in sorted(doors, key=lambda x: x[0]):
            b = self.bay_of_u(u)
            if b in self.doors:
                dropped += 1
                continue
            self.doors[b] = d
        if dropped:
            self.message = "{} door(s) removed: one door per bay.".format(dropped)

    def _clean_bay(self, bay):
        """Drop lines from a bay where two come too close (after a merge)."""
        last = None
        for i in self.lines_in(bay):
            h = self.hlines[i]
            if last is not None and h.z - last < self.gap_h - 1e-9:
                h.bays.discard(bay)
                continue
            last = h.z
        self.hlines = [h for h in self.hlines if h.bays]

    # -- grid lines -----------------------------------------------------------------------------
    def add_vertical(self, u):
        i = self.bay_of_u(u)
        u0, u1 = self.span(i)
        if u - u0 < self.gap_v - 1e-9 or u1 - u < self.gap_v - 1e-9:
            self.refuse("Too close to a grid line (closest: {}).".format(fmt(self.gap_v)))
        snap = self._snapshot()
        self.verts.insert(i + 1, Vert(u))
        for h in self.hlines:
            nb = set()
            for b in h.bays:
                nb |= {b, b + 1} if b == i else {b + 1 if b > i else b}
            h.bays = nb
        self._remap(snap)
        return i + 1

    def remove_vertical(self, k):
        v = self.verts[k]
        if v.locked:
            self.refuse("Wall ends and corners stay.")
        snap = self._snapshot()
        keep = None
        if k - 1 in self.doors:
            keep = self.doors[k - 1]
        elif k in self.doors:
            keep = self.doors[k]
        del self.verts[k]
        for h in self.hlines:
            nb = set()
            for b in h.bays:
                nb.add(b if b < k else (k - 1 if b == k else b - 1))
            h.bays = nb
        self._clean_bay(k - 1)
        cells, doors = snap
        doors = [(u, d) for u, d in doors if d is not keep]
        if keep is not None:
            doors.insert(0, (self.mid(k - 1), keep))
        self._remap((cells, doors))
        return k - 1

    def move_vertical(self, k, u):
        v = self.verts[k]
        if v.locked:
            self.refuse("Wall ends and corners stay.")
        lo = self.verts[k - 1].u + self.gap_v
        hi = self.verts[k + 1].u - self.gap_v
        v.u = min(max(u, lo), hi)
        return v.u

    def run_of(self, bay):
        """(first, last) vertex indices of the locked run around a bay."""
        a = bay
        while not self.verts[a].locked:
            a -= 1
        b = bay + 1
        while not self.verts[b].locked:
            b += 1
        return a, b

    def equalize(self, bay):
        """Spread the movable grid lines of the run around a bay evenly."""
        a, b = self.run_of(bay)
        n = b - a
        if n < 2:
            self.refuse("No grid lines to spread in this run.")
        ua, ub = self.verts[a].u, self.verts[b].u
        w = (ub - ua) / n
        if w < self.gap_v:
            self.refuse("The run is too short for its grid lines.")
        for j in range(1, n):
            self.verts[a + j].u = ua + j * w
        return n

    def divide_bay(self, bay, n):
        n = int(n)
        if n < 2:
            self.refuse("Divide into 2 or more.")
        u0, u1 = self.span(bay)
        if (u1 - u0) / n < self.gap_v:
            self.refuse("The bay is too narrow for {} parts.".format(n))
        for j in range(1, n):
            self.add_vertical(u0 + j * (u1 - u0) / n)
        return n

    # -- horizontal lines ---------------------------------------------------------------------------
    def add_hline(self, z, bays):
        if z < self.margin_h - 1e-9 or z > self.H - self.margin_h + 1e-9:
            self.refuse("Too close to the sill or head.")
        target = None
        for i, h in enumerate(self.hlines):
            if h.kind == "transom" and abs(h.z - z) < EPS:
                target = i
        ok = []
        for b in sorted(bays):
            near = [i for i in self.lines_in(b) if i != target and abs(self.hlines[i].z - z) < self.gap_h - 1e-9]
            if b in (self.hlines[target].bays if target is not None else ()):
                continue
            if not near:
                ok.append(b)
        if not ok:
            self.refuse("Too close to another transom (closest: {}).".format(fmt(self.gap_h)))
        snap = self._snapshot()
        if target is None:
            self.hlines.append(HLine(z, ok))
            target = len(self.hlines) - 1
        else:
            self.hlines[target].bays |= set(ok)
        self._remap(snap)
        return target

    def remove_hline(self, li, bay=None):
        h = self.hlines[li]
        snap = self._snapshot()
        if bay is None or h.kind == "stack":
            del self.hlines[li]
        else:
            h.bays.discard(bay)
            if not h.bays:
                del self.hlines[li]
        self._remap(snap)

    def z_limits(self, li):
        h = self.hlines[li]
        lo, hi = self.margin_h, self.H - self.margin_h
        for b in h.bays:
            for j in self.lines_in(b):
                if j == li:
                    continue
                zj = self.hlines[j].z
                if zj < h.z:
                    lo = max(lo, zj + self.gap_h)
                else:
                    hi = min(hi, zj - self.gap_h)
        return lo, hi

    def move_hline(self, li, z):
        lo, hi = self.z_limits(li)
        h = self.hlines[li]
        h.z = min(max(z, lo), hi) if lo <= hi else h.z
        return h.z

    def split_hline(self, li, bay):
        """Take a bay's segment out of a line (to move it alone). Returns its line index."""
        h = self.hlines[li]
        if h.kind == "stack":
            self.refuse("Stack joints cross the whole wall.")
        if len(h.bays) <= 1:
            return li
        h.bays.discard(bay)
        self.hlines.append(HLine(h.z, [bay]))
        return len(self.hlines) - 1

    def merge_equal(self):
        """Join transoms at the same height into one line."""
        out = []
        for h in sorted(self.hlines, key=lambda h: h.z):
            if out and out[-1].kind == h.kind == "transom" and abs(out[-1].z - h.z) < EPS:
                out[-1].bays |= h.bays
            else:
                out.append(h)
        self.hlines = out

    def line_at(self, z, bay):
        for i in self.lines_in(bay):
            if abs(self.hlines[i].z - z) < EPS:
                return i
        return None

    # -- cells + doors ------------------------------------------------------------------------------
    def set_cell(self, bay, row, kind):
        if kind not in INFILLS:
            self.refuse("Unknown infill '{}'.".format(kind))
        self.cells[(bay, row)] = kind

    def head_limits(self):
        return MIN_DOOR_HEAD, self.H - 2.0 * self.wh

    def add_door(self, bay, row, type_name, default_head, swing="in", hinge="left", leaves=1, shim=0.5):
        rows = self.rows(bay)
        row = min(max(row, 0), len(rows) - 1)
        top = rows[row][1]
        if MIN_DOOR_HEAD - 1e-9 <= top < self.H - 1e-9:
            head = top                  # up to the top of the clicked panel
        else:                           # the type's height, or a transom within 12" of it
            near = [self.hlines[i].z for i in self.lines_in(bay)
                    if abs(self.hlines[i].z - default_head) <= 12.0 and self.hlines[i].z >= MIN_DOOR_HEAD]
            head = min(near, key=lambda z: abs(z - default_head)) if near else default_head
        lo, hi = self.head_limits()
        if hi < lo:
            self.refuse("The curtain wall is too low for a door.")
        head = min(max(head, lo), hi)
        old = self.doors.get(bay)
        self.doors[bay] = Door(type_name, head, swing, hinge, leaves, shim, old.id if old else None)
        return self.doors[bay]

    def remove_door(self, bay):
        self.doors.pop(bay, None)

    def move_door_head(self, bay, z):
        lo, hi = self.head_limits()
        d = self.doors[bay]
        d.head = min(max(z, lo), hi)
        return d.head

    # -- export -----------------------------------------------------------------------------------------
    def export(self, station_of_u):
        """Driver params (inches) for the model; station_of_u(u) = station along the driver as
        drawn for a length along the grid curve."""
        allb = set(range(self.nbays))
        transoms, stack = [], []
        for h in sorted(self.hlines, key=lambda h: h.z):
            z = round(h.z, 4)
            if h.kind == "stack":
                stack.append(z)
            elif h.bays >= allb:
                transoms.append(z)
            else:
                transoms.append({"z": z, "at": [round(station_of_u(self.mid(b)), 4) for b in sorted(h.bays)]})
        cells = {}
        for (b, r), t in sorted(self.cells.items()):
            if b < self.nbays and r < len(self.rows(b)) and t != self.default(r):
                cells["{},{}".format(b, r)] = t
        out = {
            "grid": "custom",
            "verticals": [round(station_of_u(v.u), 4) for v in self.verts if not v.locked],
            "transoms": transoms,
            "infill": {"rows": list(self.row_types), "cells": cells},
        }
        if self.has_stack:
            out["stack"] = stack
        return out

    def door_params(self, bay, station_of_u):
        """Opening params (inches) for the door of a bay."""
        d = self.doors[bay]
        width = max(12.0, self.clear_width(bay) - 2 * d.shim - 4.0)     # the builder fits the bay
        return {"station": round(station_of_u(self.mid(bay)), 4), "sill": 0.0,
                "height": round(d.head - 0.5 * self.wh - d.shim, 4), "width": round(width, 4),
                "swing": d.swing, "hinge": d.hinge}


# -- the screen side ---------------------------------------------------------------------------------
class GridController(object):
    def __init__(self, model, width=900, height=520, door_info=None):
        self.m = model
        self.W, self.Hpx = float(width), float(height)
        self.view = "exterior"
        self.tool = "select"
        self.paint = VISION
        self.snap = 1.0
        self.whole = False
        self.door_type = None
        self.door_swing = "in"
        self.door_hinge = "left"
        self.door_info = door_info or (lambda name: {"leaves": 1, "shim": 0.5, "head": 84.0 + 0.5 + 0.5 * model.wh})
        self.sel = None
        self.hover = None
        self.ghost = None
        self.drag = None
        self.undo_stack, self.redo_stack = [], []
        self.version = 0
        self.status = ""
        self.layout()

    # -- layout ---------------------------------------------------------------------------------
    def resize(self, width, height):
        self.W, self.Hpx = float(width), float(height)
        self.layout()

    def layout(self):
        ml, mr, mt, mb = MARGINS
        m = self.m
        aw, ah = max(10.0, self.W - ml - mr), max(10.0, self.Hpx - mt - mb)
        self.sc = min(aw / m.L, ah / m.H)
        self.x0 = ml + 0.5 * (aw - m.L * self.sc)
        self.y0 = mt + 0.5 * (ah - m.H * self.sc)

    def x(self, u):
        m = self.m
        return self.x0 + ((m.L - u) if self.view == "exterior" else u) * self.sc

    def y(self, z):
        return self.y0 + (self.m.H - z) * self.sc

    def u_at(self, px):
        d = (px - self.x0) / self.sc
        return self.m.L - d if self.view == "exterior" else d

    def z_at(self, py):
        return self.m.H - (py - self.y0) / self.sc

    def bay_rect(self, bay):
        a, b = self.m.span(bay)
        xa, xb = sorted((self.x(a), self.x(b)))
        return xa, xb

    def rect(self, bay, z0, z1):
        """(x, y, w, h) of a bay between two heights."""
        xa, xb = self.bay_rect(bay)
        return xa, self.y(z1), xb - xa, self.y(z0) - self.y(z1)

    def inside(self, px, py, pad=GRAB_PX):
        xa, xb = sorted((self.x(0.0), self.x(self.m.L)))
        return xa - pad <= px <= xb + pad and self.y(self.m.H) - pad <= py <= self.y(0.0) + pad

    # -- snapping -----------------------------------------------------------------------------------
    def snap_len(self, v, alt=False):
        if alt or self.snap <= 0:
            return v
        return round(v / self.snap) * self.snap

    def snap_z(self, z, alt=False, skip=None):
        z1 = self.snap_len(z, alt)
        if alt:
            return z1
        best = None
        for i, h in enumerate(self.m.hlines):
            if i == skip:
                continue
            d = abs(self.y(h.z) - self.y(z))
            if d <= MAGNET_PX and (best is None or d < best[0]):
                best = (d, h.z)
        for d_ in self.m.doors.values():
            d = abs(self.y(d_.head) - self.y(z))
            if d <= MAGNET_PX and (best is None or d < best[0]):
                best = (d, d_.head)
        return best[1] if best else z1

    # -- hit testing ----------------------------------------------------------------------------------
    def hit(self, px, py):
        """("vertical", k) | ("hline", li, bay) | ("door_head", bay) | ("door", bay) |
        ("cell", bay, row) | None."""
        m = self.m
        if not self.inside(px, py):
            return None
        cands = []
        for k, v in enumerate(m.verts):
            d = abs(self.x(v.u) - px)
            if d <= GRAB_PX + 0.5 * m.wv * self.sc:
                cands.append((d, ("vertical", k)))
        u = min(max(self.u_at(px), 0.0), m.L)
        bay = m.bay_of_u(u)
        z = self.z_at(py)
        door = m.doors.get(bay)
        if door is not None:
            d = abs(self.y(door.head) - py)
            if d <= GRAB_PX + 0.5 * m.wh * self.sc:
                cands.append((d, ("door_head", bay)))
        for li in m.lines_in(bay):
            if m.hidden(bay, li):
                continue
            d = abs(self.y(m.hlines[li].z) - py)
            if d <= GRAB_PX + 0.5 * m.wh * self.sc:
                cands.append((d, ("hline", li, bay)))
        if cands:
            return min(cands, key=lambda c: c[0])[1]
        if door is not None and z < door.head:
            return ("door", bay)
        z = min(max(z, 0.0), m.H)
        return ("cell", bay, m.row_of(bay, z))

    # -- edits ----------------------------------------------------------------------------------------
    def _push(self):
        self.undo_stack.append(self.m.state())
        del self.undo_stack[:-100]
        self.redo_stack = []

    def _edited(self, msg=""):
        self.version += 1
        self.status = msg or self.m.message
        self.m.message = ""

    def edit(self, fn, msg=""):
        """Run a model edit with an undo step; a refused edit changes nothing."""
        st = self.m.state()
        try:
            out = fn()
        except EditRefused as ex:
            self.m.restore(st)
            self.status = str(ex)
            return None
        self.undo_stack.append(st)
        del self.undo_stack[:-100]
        self.redo_stack = []
        self._edited(msg)
        return out

    def undo(self):
        if not self.undo_stack:
            self.status = "Nothing to undo."
            return False
        self.redo_stack.append(self.m.state())
        self.m.restore(self.undo_stack.pop())
        self.sel = None
        self._edited("Undone.")
        return True

    def redo(self):
        if not self.redo_stack:
            self.status = "Nothing to redo."
            return False
        self.undo_stack.append(self.m.state())
        self.m.restore(self.redo_stack.pop())
        self.sel = None
        self._edited("Redone.")
        return True

    def set_tool(self, tool):
        if tool in TOOLS:
            self.tool = tool
            self.ghost = None
            self.drag = None

    # -- mouse ---------------------------------------------------------------------------------------
    def mouse_down(self, px, py, ctrl=False, shift=False, alt=False):
        m = self.m
        h = self.hit(px, py)
        self.drag = None
        if h is None:
            self.sel = None
            return
        t = self.tool
        if t == "select":
            self.sel = h
            if h[0] == "vertical" and not m.verts[h[1]].locked:
                self.drag = {"what": "vertical", "k": h[1], "p": (px, py), "moved": False}
            elif h[0] == "hline":
                self.drag = {"what": "hline", "li": h[1], "bay": h[2], "split": ctrl, "p": (px, py),
                             "moved": False}
            elif h[0] == "door_head":
                self.drag = {"what": "door_head", "bay": h[1], "p": (px, py), "moved": False}
            elif h[0] == "vertical":
                self.status = "Wall ends and corners stay where the curve puts them."
        elif t == "vertical":
            u = self.snap_len(self.u_at(px), alt)
            k = self.edit(lambda: m.add_vertical(u), "Grid line at {}.".format(fmt(u)))
            if k is not None:
                self.sel = ("vertical", k)
                self.drag = {"what": "vertical", "k": k, "p": (px, py), "moved": True, "fresh": True}
        elif t == "horizontal":
            if h[0] == "vertical":
                return
            bay = h[1] if h[0] != "hline" else h[2]
            z = self.snap_z(self.z_at(py), alt)
            bays = range(m.nbays) if (self.whole != shift) else [bay]
            li = self.edit(lambda: m.add_hline(z, bays), "Transom at {}.".format(fmt(z)))
            if li is not None:
                self.sel = ("hline", li, bay)
                self.drag = {"what": "hline", "li": li, "bay": bay, "split": False, "p": (px, py),
                             "moved": True, "fresh": True}
        elif t == "delete":
            self.delete(h, shift)
        elif t == "paint":
            self._push()
            self._paint_at(h)
            self.drag = {"what": "paint", "p": (px, py), "moved": False}
        elif t == "door":
            self.place_door(h)

    def place_door(self, h):
        m = self.m
        if h[0] == "door":
            self.sel = h
            return
        if h[0] not in ("cell", "hline", "door_head"):
            return
        bay = h[1] if h[0] != "hline" else h[2]
        row = h[2] if h[0] == "cell" else 0
        if self.door_type is None:
            self.status = "Pick a door type first."
            return
        info = self.door_info(self.door_type)
        d = self.edit(lambda: m.add_door(bay, row, self.door_type, info["head"], self.door_swing,
                                         self.door_hinge, info["leaves"], info["shim"]))
        if d is not None:
            self.sel = ("door", bay)
            self.status = "{} in bay {} ({} wide).".format(d.type, bay + 1, fmt(m.clear_width(bay)))

    def _paint_at(self, h):
        m = self.m
        if h is None or h[0] != "cell":
            return
        self.sel = h
        if m.cell_type(h[1], h[2]) == self.paint:
            return
        m.set_cell(h[1], h[2], self.paint)
        self._edited()

    def delete(self, h=None, whole=False):
        m = self.m
        h = h or self.sel
        if h is None:
            return
        if h[0] == "vertical":
            k = self.edit(lambda: m.remove_vertical(h[1]), "Grid line removed.")
        elif h[0] == "hline":
            self.edit(lambda: m.remove_hline(h[1], None if whole else h[2]), "Transom removed.")
        elif h[0] in ("door", "door_head"):
            self.edit(lambda: m.remove_door(h[1]), "Door removed.")
        else:
            self.status = "Paint a panel instead of deleting it."
            return
        self.sel = None

    def mouse_move(self, px, py, down=False, ctrl=False, shift=False, alt=False):
        m = self.m
        dr = self.drag
        if dr is None or not down:
            self.hover = self.hit(px, py)
            self.ghost = self._ghost(px, py, shift, alt)
            return
        if not dr["moved"]:
            if abs(px - dr["p"][0]) + abs(py - dr["p"][1]) < DRAG_PX:
                return
            if dr["what"] != "paint":
                self._push()
            dr["moved"] = True
        w = dr["what"]
        if w == "vertical":
            u = m.move_vertical(dr["k"], self.snap_len(self.u_at(px), alt))
            self.status = "Grid line at {} ({} | {})".format(fmt(u), fmt(u - m.verts[dr["k"] - 1].u),
                                                             fmt(m.verts[dr["k"] + 1].u - u))
            self.version += 1
        elif w == "hline":
            if dr["split"]:
                try:
                    dr["li"] = m.split_hline(dr["li"], dr["bay"])
                except EditRefused as ex:
                    self.status = str(ex)
                dr["split"] = False
                self.sel = ("hline", dr["li"], dr["bay"])
            z = m.move_hline(dr["li"], self.snap_z(self.z_at(py), alt, skip=dr["li"]))
            self.status = "Transom at {}".format(fmt(z))
            self.version += 1
        elif w == "door_head":
            z = m.move_door_head(dr["bay"], self.snap_z(self.z_at(py), alt))
            d = m.doors[dr["bay"]]
            self.status = "Door head at {} (door {} high)".format(fmt(z), fmt(z - 0.5 * m.wh - d.shim))
            self.version += 1
        elif w == "paint":
            self._paint_at(self.hit(px, py))

    def mouse_up(self, px, py, **mods):
        dr = self.drag
        self.drag = None
        if dr is None:
            return False
        if dr["what"] == "hline" and dr["moved"]:
            z = self.m.hlines[dr["li"]].z
            self.m.merge_equal()
            li = self.m.line_at(z, dr["bay"])
            self.sel = ("hline", li, dr["bay"]) if li is not None else None
        if dr["moved"] or dr.get("fresh"):
            self._edited(self.status)
            return True
        return False

    def _ghost(self, px, py, shift=False, alt=False):
        """Preview of what a click would add: ("vertical", u) / ("hline", z, bays)."""
        m = self.m
        if not self.inside(px, py, 0):
            return None
        if self.tool == "vertical":
            return ("vertical", self.snap_len(self.u_at(px), alt))
        if self.tool == "horizontal":
            bay = m.bay_of_u(min(max(self.u_at(px), 0.0), m.L))
            bays = list(range(m.nbays)) if (self.whole != shift) else [bay]
            return ("hline", self.snap_z(self.z_at(py), alt), bays)
        return None

    def key(self, name, ctrl=False, shift=False):
        name = name.lower()
        if ctrl and (name == "y" or (shift and name == "z")):
            return self.redo()
        if ctrl and name == "z":
            return self.undo()
        if name in ("delete", "backspace"):
            self.delete()
            return True
        if name == "escape":
            self.set_tool("select")
            self.sel = None
            return True
        letters = {"s": "select", "v": "vertical", "h": "horizontal", "x": "delete", "p": "paint", "d": "door"}
        if not ctrl and name in letters:
            self.set_tool(letters[name])
            return True
        return False

    # -- selection info + numeric edits -------------------------------------------------------------------
    def info(self):
        """(title, [(field, label, inches or text, editable)]) of the selection."""
        m, s = self.m, self.sel
        if s is None:
            return "Curtain wall", [("length", "Length", m.L, False), ("height", "Height", m.H, False),
                                    ("bays", "Bays", str(m.nbays), False)]
        if s[0] == "vertical":
            k = s[1]
            v = m.verts[k]
            if v.locked:
                return "Fixed grid line ({})".format(v.kind), [("u", "Position", v.u, False)]
            return "Grid line", [("u", "Position", v.u, True),
                                 ("prev", "From previous", v.u - m.verts[k - 1].u, True),
                                 ("next", "To next", m.verts[k + 1].u - v.u, True)]
        if s[0] == "hline":
            li, bay = s[1], s[2]
            if li is None or li >= len(m.hlines):
                return "Curtain wall", []
            h = m.hlines[li]
            lines = m.lines_in(bay)
            j = lines.index(li) if li in lines else 0
            below = m.hlines[lines[j - 1]].z if j > 0 else 0.0
            return ("Stack joint" if h.kind == "stack" else "Transom"), [
                ("z", "Height", h.z, True), ("below", "Above the line below", h.z - below, True),
                ("span", "Bays", "all" if len(h.bays) == m.nbays else ", ".join(str(b + 1) for b in sorted(h.bays)), False)]
        if s[0] in ("door", "door_head"):
            d = m.doors.get(s[1])
            if d is None:
                return "Curtain wall", []
            return "Door ({} leaf{})".format(d.leaves, "" if d.leaves == 1 else "s"), [
                ("type", "Type", d.type, False), ("head", "Head line", d.head, True),
                ("door_h", "Door height", d.head - 0.5 * m.wh - d.shim, True),
                ("width", "Clear width", m.clear_width(s[1]), False),
                ("swing", "Swing", d.swing, False), ("hinge", "Hinge", d.hinge if d.leaves == 1 else "both", False)]
        if s[0] == "cell":
            bay, row = s[1], s[2]
            rows = m.rows(bay)
            if row >= len(rows):
                return "Curtain wall", []
            z0, z1 = rows[row]
            return "Panel (bay {}, row {})".format(bay + 1, row + 1), [
                ("infill", "Infill", m.cell_type(bay, row), False),
                ("width", "Width (c/c)", m.span(bay)[1] - m.span(bay)[0], False),
                ("cell_h", "Height (c/c)", z1 - z0, False)]
        return "Curtain wall", []

    def set_value(self, field, inches):
        """Numeric edit of the selection (a value typed in the info panel)."""
        m, s = self.m, self.sel
        if s is None:
            return False
        if s[0] == "vertical":
            k = s[1]
            if field == "prev":
                u = m.verts[k - 1].u + inches
            elif field == "next":
                u = m.verts[k + 1].u - inches
            else:
                u = inches
            return self.edit(lambda: m.move_vertical(k, u)) is not None
        if s[0] == "hline":
            li, bay = s[1], s[2]
            if field == "below":
                lines = m.lines_in(bay)
                j = lines.index(li)
                z = (m.hlines[lines[j - 1]].z if j > 0 else 0.0) + inches
            else:
                z = inches
            ok = self.edit(lambda: m.move_hline(li, z)) is not None
            m.merge_equal()
            return ok
        if s[0] in ("door", "door_head"):
            d = m.doors[s[1]]
            z = inches if field == "head" else inches + 0.5 * m.wh + d.shim
            return self.edit(lambda: m.move_door_head(s[1], z)) is not None
        return False

    def set_door_props(self, swing=None, hinge=None, type_name=None, info=None):
        s = self.sel
        if s is None or s[0] not in ("door", "door_head"):
            return False
        d = self.m.doors[s[1]]

        def go():
            if swing:
                d.swing = swing
            if hinge:
                d.hinge = hinge
            if type_name:
                d.type = type_name
                if info:
                    d.leaves, d.shim = info["leaves"], info["shim"]
        self.edit(go)
        return True

    def selected_bay(self):
        s = self.sel
        if s is None:
            return None
        if s[0] == "vertical":
            return min(s[1], self.m.nbays - 1)
        return s[2] if s[0] == "hline" else s[1]

    # -- dimensions (painted by the view) ----------------------------------------------------------------
    def bay_dims(self):
        """[(x_mid, text)] of the bay widths, centre to centre."""
        m = self.m
        out = []
        for b in range(m.nbays):
            a, c = m.span(b)
            out.append((0.5 * (self.x(a) + self.x(c)), fmt(c - a)))
        return out

    def row_dims(self, bay):
        m = self.m
        return [(0.5 * (self.y(z0) + self.y(z1)), fmt(z1 - z0)) for z0, z1 in m.rows(bay)]
