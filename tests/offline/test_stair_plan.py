"""Offline check of the stair layout (mindcanvas/stairs/plan.py) and of the watertightness of the
stair meshes (mindcanvas/stairs/build.piece_faces: every edge shared by exactly two faces), against
the fake Rhino in tests/offline/fake. Run with plain Python 3: python tests/offline/test_stair_plan.py"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "fake"), os.path.join(HERE, "..", "..")]
from mindcanvas.stairs import plan
from mindcanvas.stairs import build as sbuild

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def line(*pts):
    """Polyline -> segments (one per straight leg; every vertex is a corner)."""
    out = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        d = ((x1 - x0) / L, (y1 - y0) / L)
        out.append([(x0, y0, d[0], d[1]), (x1, y1, d[0], d[1])])
    return out


def arc(r, a0, a1, n=24, cx=0.0, cy=0.0):
    """Counter-clockwise arc as one curved segment."""
    out = []
    for i in range(n + 1):
        a = a0 + (a1 - a0) * i / n
        out.append((cx + r * math.cos(a), cy + r * math.sin(a), -math.sin(a), math.cos(a)))
    return [out]


def watertight(lay, style, **kw):
    bad = 0
    for a, b, bottoms in lay.pieces(style, **kw):
        M = sbuild.piece_faces(lay, a, b, bottoms)
        edges = {}
        for f in M.faces:
            for i in range(len(f)):
                e = tuple(sorted((f[i], f[(i + 1) % len(f)])))
                edges[e] = edges.get(e, 0) + 1
        bad += sum(1 for n in edges.values() if n != 2)
    return bad


def levels_ok(lay):
    lv = lay.levels
    return lv[0] == 1 and lv[-1] == lay.risers - 1 and all(0 <= b - a <= 1 for a, b in zip(lv, lv[1:]))


def all_styles(lay, name):
    for st in ("slab", "solid", "open"):
        check(watertight(lay, st) == 0, "{}: {} pieces are closed".format(name, st))


# 1. straight run: 120" floor to floor, 7" max -> 18 risers @ 6.667", 17 treads fitted to 17 x 11"
lay = plan.layout(line((0, 0), (187, 0)), 42, 120, -1, 7)
check(lay.risers == 18 and abs(lay.R - 120 / 18.0) < 1e-9, "straight: 18 risers")
check(len(lay.flights) == 1 and lay.flights[0].treads == 17 and abs(lay.flights[0].depth - 11) < 1e-9,
      "straight: 17 treads @ 11\"")
check(len(lay.cuts) == 18 and levels_ok(lay), "straight: 18 cuts, levels 1..17")
check(abs(lay.cuts[0].o[1] + 42) < 1e-9, "straight, side left: the stair lies right of the line (-y)")
check(not lay.warnings, "straight: no warnings")
all_styles(lay, "straight")
b = lay.pieces("slab", waist=6)[0][2]
check(b[0] == 0.0 and all(y <= lay.top(min(j, len(lay.levels) - 1)) - plan.MIN_THICK + 1e-9 for j, y in enumerate(b)),
      "straight: soffit starts on the floor, stays under the treads")
m = lay.R / 11.0
check(abs((b[10] - b[9]) / 11.0 - m) < 1e-9, "straight: soffit parallel to the nosings")
op = lay.pieces("open", tread=2)
check(len(op) == 17, "straight, open: 17 tread plates")

# right side: the stair lies left of the line
lay_r = plan.layout(line((0, 0), (187, 0)), 42, 120, +1, 7)
check(abs(lay_r.cuts[0].o[1] - 42) < 1e-9, "straight, side right: the stair lies left of the line (+y)")

# 2. too short a line -> a warning about steep treads
lay = plan.layout(line((0, 0), (100, 0)), 36, 120, -1, 7)
check(any("only" in w for w in lay.warnings), "short line warns: " + "; ".join(lay.warnings))

# 3. L stair turning toward the stair side (curve = outer edge): a 42" square landing
lay = plan.layout(line((0, 0), (120, 0), (120, -150)), 42, 120, -1, 7)
check(len(lay.landings) == 1 and len(lay.flights) == 2, "L outer: 2 flights + a landing")
fl = lay.flights
check(sum(f.treads for f in fl) == lay.risers - 2, "L outer: treads = risers - 2")
check(abs(fl[0].length - (120 - 42)) < 1e-6 and abs(fl[1].length - (150 - 42)) < 1e-6,
      "L outer: flights trimmed by the landing ({:.2f}, {:.2f})".format(fl[0].length, fl[1].length))
check(levels_ok(lay), "L outer: levels step by one")
all_styles(lay, "L outer")

# 4. L stair turning away from the stair side (curve = inner edge)
lay = plan.layout(line((0, 0), (120, 0), (120, 150)), 42, 120, -1, 7)
check(len(lay.landings) == 1, "L inner: a landing")
check(abs(lay.flights[0].length - 120) < 1e-6, "L inner: flights not trimmed")
check(levels_ok(lay), "L inner: levels step by one")
all_styles(lay, "L inner")

# 5. U stair with a half landing: the middle leg is exactly 2 x width -> two landings back to back
lay = plan.layout(line((0, 0), (110, 0), (110, -84), (0, -84)), 42, 120, -1, 7)
check(len(lay.flights) == 2, "U: 2 flights ({})".format(len(lay.flights)))
check(sum(f.treads for f in lay.flights) == lay.risers - 2, "U: one landing level")
check(levels_ok(lay), "U: levels step by one")
all_styles(lay, "U")

# 6. U stair with a short middle flight -> it becomes flat (a long landing)
lay = plan.layout(line((0, 0), (110, 0), (110, -88), (0, -88)), 42, 120, -1, 7)
check(sum(f.treads for f in lay.flights) == lay.risers - 2, "U + 4\" gap: still one landing level")
all_styles(lay, "U gap")

# 7. curved stair along an arc (curve = inner side, stair outside it)
lay = plan.layout(arc(48, 0, math.pi * 1.25), 40, 120, -1, 7)
check(not lay.landings and len(lay.flights) == 1, "arc: one curved flight")
check(levels_ok(lay), "arc: levels step by one")
check(abs(lay.flights[0].depth - (48 + 20) * math.pi * 1.25 / 17) < 0.05,
      "arc: treads fitted on the walkline ({:.3f})".format(lay.flights[0].depth))
all_styles(lay, "arc")

# 8. explicit risers + a corner too sharp for a landing
lay = plan.layout(line((0, 0), (200, 0)), 42, 120, -1, 7, risers=16)
check(lay.risers == 16 and lay.flights[0].treads == 15, "risers override: 16 / 15")
try:
    plan.layout(line((0, 0), (120, 0), (0, 10)), 42, 120, -1, 7)
    check(False, "a 175 degree corner is refused")
except plan.PlanError as ex:
    check(True, "a 175 degree corner is refused: {}".format(ex))

print("\n{} failure(s)".format(len(FAILS)))
sys.exit(1 if FAILS else 0)
