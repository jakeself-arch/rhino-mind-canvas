"""Hatch patterns built in code (a template-less doc has none).

Every MC pattern has a unit repeat, so a hatch scale equals the repeat length:
paper mm in the 2D writer, model units in a live section style. A line is
(angle deg, base (x, y), offset (along, across), dashes); positive dashes
draw, negative are gaps, 0 is a dot. `offset` places each next parallel line
in the line's own frame (x along it, y to its left).
"""

import math

import System
import Rhino

D = Rhino.DocObjects
G = Rhino.Geometry


def _batt(a=0.5):
    # zigzag rows of height 1: up strokes (0,m)->(a,m+1)... as two dashed families
    L = math.hypot(a, 1.0)
    up = (math.degrees(math.atan2(1.0, a)), (0.0, 0.0), (1.0 / L, a / L), [L, -L])
    down = (math.degrees(math.atan2(1.0, -a)), (2 * a, 0.0), (1.0 / L, -a / L), [L, -L])
    return [up, down]


PATTERNS = {
    # brick / masonry in section: 45 degree lines
    "MC Brick": [(45, (0, 0), (0, 1), None)],
    # brick in elevation: bed joints every course, head joints every 3 courses-lengths, half bond
    "MC Brick Coursing": [(0, (0, 0), (0, 1), None),
                          (90, (0, 0), (1, -1.5), [1, -1])],
    # concrete: scattered aggregate ticks + dots
    "MC Concrete": [(0, (0, 0), (0.37, 0.61), [0.07, -0.93]),
                    (60, (0.2, 0.1), (0.55, 0.83), [0.09, -1.21]),
                    (120, (0.5, 0.3), (0.23, 0.71), [0.06, -0.74]),
                    (30, (0.1, 0.4), (0.21, 0.37), [0, -0.53])],
    # earth: AutoCAD EARTH, 3 strokes each way per unit
    "MC Earth": [(0, (0, 0), (1, 1), [1, -1]),
                 (0, (0, 0.375), (1, 1), [1, -1]),
                 (0, (0, 0.75), (1, 1), [1, -1]),
                 (90, (0.125, 0.875), (1, 1), [1, -1]),
                 (90, (0.5, 0.875), (1, 1), [1, -1]),
                 (90, (0.875, 0.875), (1, 1), [1, -1])],
    "MC Batt": _batt(),
    # rigid insulation: diagonal crosshatch
    "MC Rigid": [(45, (0, 0), (0, 1), None), (135, (0, 0), (0, 1), None)],
    # plywood: plies + veneer dashes
    "MC Plywood": [(0, (0, 0), (0, 1), None), (0, (0, 0.5), (0.35, 1), [0.55, -0.45])],
    # wood grain (live view only; the 2D writer draws an X in framing)
    "MC Wood": [(0, (0, 0), (0.6, 0.5), [2.2, -0.3]), (0, (0.3, 0.25), (0.6, 0.5), [1.2, -0.25, 0.4, -0.3])],
    # gypsum / cementitious board: fine dots
    "MC Gypsum": [(0, (0, 0), (0.5, 0.5), [0, -1]), (0, (0.25, 0.25), (0.5, 0.5), [0, -1])],
}


def _hatch_line(angle, base, offset, dashes):
    hl = D.HatchLine()
    hl.Angle = math.radians(angle)
    hl.BasePoint = G.Point2d(float(base[0]), float(base[1]))
    hl.Offset = G.Vector2d(float(offset[0]), float(offset[1]))
    if dashes:
        try:
            for d in dashes:
                hl.AppendDash(float(d))
        except AttributeError:
            hl.SetDashes(System.Array[System.Double]([float(d) for d in dashes]))
    return hl


def build(name):
    hp = D.HatchPattern()
    hp.Name = name
    hp.FillType = D.HatchPatternFillType.Lines
    for spec in PATTERNS[name]:
        hp.AddHatchLine(_hatch_line(*spec))
    return hp


def index(doc, name):
    """Pattern index by name; MC patterns and Rhino defaults are added on demand."""
    if not name:
        return -1
    hp = doc.HatchPatterns.FindName(name)
    if hp is not None and not hp.IsDeleted:
        return hp.Index
    if name in PATTERNS:
        return doc.HatchPatterns.Add(build(name))
    builtin = getattr(D.HatchPattern.Defaults, name, None)
    if builtin is not None:
        return doc.HatchPatterns.Add(builtin)
    return -1


def ensure(doc):
    """Add Rhino's Solid + every MC pattern. Returns {name: index}."""
    out = {"Solid": index(doc, "Solid")}
    for name in PATTERNS:
        out[name] = index(doc, name)
    return out
