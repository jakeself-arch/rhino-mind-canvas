"""Offline test of the visual curtain-grid editor model + controller (mindcanvas/curtainwall/
gridedit.py): grid line add / move / remove, partial transoms, cell re-mapping, doors, undo,
the mouse logic and the exported driver params. Plain Python 3:
python tests/offline/test_cw_gridedit.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "fake"), os.path.join(HERE, "..", "..")]
from mindcanvas.curtainwall import gridedit as ge


def close(a, b, e=1e-6):
    return abs(a - b) < e


def model():
    # 30' x 12' wall, 2-1/2" mullions, bays at 60" (6 bays), a full transom at 30"
    m = ge.GridModel(360, 144, 2.5, 2.5, row_types=["spandrel", "vision"])
    for u in (60, 120, 180, 240, 300):
        m.verts.insert(-1, ge.Vert(u))
    m.hlines.append(ge.HLine(30, range(6)))
    m.materialize(lambda b, r: m.default(r))
    return m


m = model()
assert m.nbays == 6 and m.rows(0) == [(0.0, 30.0), (30.0, 144.0)]
assert m.cell_type(2, 0) == "spandrel" and m.cell_type(2, 1) == "vision"

# a grid line splits bay 2: both halves keep the transom and the cell types
m.set_cell(2, 1, "shadow_box")
k = m.add_vertical(150)
assert k == 3 and m.nbays == 7 and m.hlines[0].bays == set(range(7))
assert m.cell_type(2, 1) == "shadow_box" and m.cell_type(3, 1) == "shadow_box" and m.cell_type(4, 1) == "vision"
# too close
try:
    m.add_vertical(152)
    assert False
except ge.EditRefused:
    pass
# move clamps at the neighbours (gap 5")
assert close(m.move_vertical(3, 10), 125.0) and close(m.move_vertical(3, 500), 175.0)
m.move_vertical(3, 150)
# a transom in bay 3 only, then extended into bay 4 by clicking at its height
li = m.add_hline(96, [3])
assert m.rows(3) == [(0, 30), (30, 96), (96, 144)] and m.rows(4) == [(0, 30), (30, 144)]
assert m.cell_type(3, 2) == "shadow_box"            # the split cell keeps its type
li2 = m.add_hline(96, [4])
assert li2 == li and m.hlines[li].bays == {3, 4}
# too close to another transom in that bay
try:
    m.add_hline(32, [3])
    assert False
except ge.EditRefused:
    pass
# moving a transom: limits from the lines in its bays
lo, hi = m.z_limits(li)
assert close(lo, 35.0) and close(hi, 144 - 3.75), (lo, hi)
# split a segment out and move it alone; merge back when it returns to the same height
lj = m.split_hline(li, 4)
m.move_hline(lj, 84)
assert m.rows(4)[2] == (84, 144) and m.rows(3)[2] == (96, 144)
m.move_hline(lj, 96)
m.merge_equal()
assert len([h for h in m.hlines if abs(h.z - 96) < 1e-9]) == 1
# removing grid line 3 merges bays 2 + 3; the merged bay keeps bay 3's transom (union)
m.remove_vertical(3)
assert m.nbays == 6 and any(2 in h.bays and h.z == 96 for h in m.hlines)

# doors: in the bottom row = the type's head; in row 1 = up to that row's top
m = model()
m.add_door(1, 0, "Door", 86.0, leaves=1, shim=0.5)
assert close(m.doors[1].head, 86.0)       # the bottom row tops out at 30": the type's height
m.add_hline(90, [1])
m.add_door(1, 1, "Door", 86.0)
assert close(m.doors[1].head, 90.0)
assert m.hidden(1, 0) and m.hidden(1, 1)        # the head line becomes the door's head transom
vc = m.visible_cells(1)
assert vc == [(90.0, 144.0, 2)], vc
# a door bay split by a grid line: the door goes with its centre
m.add_vertical(100)
assert list(m.doors) == [1] or list(m.doors) == [2]
# the door params
p = m.door_params(list(m.doors)[0], lambda u: u)
assert p["sill"] == 0.0 and close(p["height"], 90 - 1.25 - 0.5)

# export: custom verticals, a full + a partial transom, non-default cells only
m = model()
m.add_hline(96, [0, 1])
m.set_cell(0, 2, "spandrel")
ex = m.export(lambda u: 360 - u)      # a flipped driver: stations run the other way
assert ex["grid"] == "custom" and ex["verticals"] == [300, 240, 180, 120, 60], ex["verticals"]
assert ex["transoms"][0] == 30 and ex["transoms"][1] == {"z": 96, "at": [330, 270]}, ex["transoms"]
assert ex["infill"]["cells"] == {"0,2": "spandrel"}, ex["infill"]
assert "stack" not in ex

# controller: exterior view runs right -> left
m = model()
c = ge.GridController(m, 900, 520)
assert c.x(0) > c.x(360)
c.view = "interior"
c.layout()
assert c.x(0) < c.x(360)
c.view = "exterior"
# hit a grid line, drag it 10" (snap 1")
px, py = c.x(120), c.y(70)
assert c.hit(px, py) == ("vertical", 2), c.hit(px, py)
c.mouse_down(px, py)
c.mouse_move(c.x(130.2), py, down=True)
assert c.mouse_up(c.x(130.2), py)
assert close(m.verts[2].u, 130.0), m.verts[2].u
c.undo()
assert close(m.verts[2].u, 120.0)
c.redo()
assert close(m.verts[2].u, 130.0)
# add a grid line with the tool
c.set_tool("vertical")
c.mouse_down(c.x(90.4), py)
c.mouse_up(c.x(90.4), py)
assert any(close(v.u, 90.0) for v in m.verts) and m.nbays == 7
# add a transom in one bay, then shift-click = the whole width
c.set_tool("horizontal")
bx = 0.5 * (c.x(0) + c.x(60))
c.mouse_down(bx, c.y(100.3))
c.mouse_up(bx, c.y(100.3))
h = [x for x in m.hlines if close(x.z, 100.0)]
assert h and h[0].bays == {0}
c.mouse_down(bx, c.y(110), shift=True)
c.mouse_up(bx, c.y(110), shift=True)
assert any(close(x.z, 110) and x.bays == set(range(m.nbays)) for x in m.hlines)
# paint by dragging over row 0
c.set_tool("paint")
c.paint = "shadow_box"
y0 = c.y(15)
c.mouse_down(c.x(30), y0)
c.mouse_move(c.x(150), y0, down=True)
c.mouse_move(c.x(330), y0, down=True)
c.mouse_up(c.x(330), y0)
assert m.cell_type(0, 0) == "shadow_box" and m.cell_type(m.nbays - 1, 0) == "shadow_box"
# a door with the tool, its head dragged
c.set_tool("door")
c.door_type = "Door - Aluminum Entrance, Full Lite"
c.door_info = lambda n: {"leaves": 1, "shim": 0.5, "head": 85.75}
b = m.bay_of_u(160)
c.mouse_down(c.x(160), c.y(10))
assert b in m.doors and close(m.doors[b].head, 85.75)
c.set_tool("select")
c.mouse_down(c.x(160), c.y(85.75))
assert c.drag and c.drag["what"] == "door_head", c.drag
c.mouse_move(c.x(160), c.y(96), down=True)
c.mouse_up(c.x(160), c.y(96))
assert close(m.doors[b].head, 96.0), m.doors[b].head
title, fields = c.info()
assert title.startswith("Door") and dict((f[0], f[2]) for f in fields)["door_h"] == 96 - 1.25 - 0.5
assert c.set_value("door_h", 84.0) and close(m.doors[b].head, 84 + 1.75)
# delete with the key
c.key("delete")
assert b not in m.doors
# a locked end cannot be dragged or deleted
c.mouse_down(c.x(0), c.y(70))
assert c.drag is None
c.delete(("vertical", 0))
assert "stay" in c.status
# equalize the run
c.sel = ("vertical", 2)
m2 = c.m
c.edit(lambda: m2.equalize(0))
ws = [m2.span(i)[1] - m2.span(i)[0] for i in range(m2.nbays)]
assert max(ws) - min(ws) < 1e-6, ws
print("test_cw_gridedit: OK ({} bays, {} lines)".format(m2.nbays, len(m2.hlines)))
