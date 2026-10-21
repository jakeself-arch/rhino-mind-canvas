"""Offline test of MCMatch's settings rules (mindcanvas/match.py) and the short aliases of
tools/install.py. Plain Python 3: python tests/offline/test_match_aliases.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
sys.path[:0] = [os.path.join(HERE, "fake"), ROOT, os.path.join(ROOT, "tools")]
from mindcanvas import match
import install

# walls: everything but the target's own end joins; a per-wall layer stack is copied (or dropped)
src = {"height": 108, "base_offset": 0, "reference": "exterior_face", "flip": True, "lod": "design",
       "layers": [{"name": "Brick"}], "joins": {"start": "miter"}, "join_priority": 2}
dst = {"height": 120, "base_offset": 12, "reference": "center", "flip": False, "lod": "detail",
       "joins": {"end": "butt"}, "overrides": {"Framing": {"spacing": 24}}}
out = match.matched_params("wall", src, dst)
assert out["height"] == 108 and out["reference"] == "exterior_face" and out["flip"] is True
assert out["joins"] == {"end": "butt"} and out["layers"] == [{"name": "Brick"}]
assert "overrides" not in out and out["join_priority"] == 2
assert dst["height"] == 120 and "layers" not in dst          # inputs untouched
out["layers"][0]["name"] = "x"
assert src["layers"][0]["name"] == "Brick"                   # deep copies

# a mass-driven wall keeps its height / base
out = match.matched_params("wall", src, dst, keep=match.MASS_OWN)
assert out["height"] == 120 and out["base_offset"] == 12 and out["lod"] == "design"

# curtain walls: a custom grid stays the target's; plain grids copy, minus partial transoms
cw_src = {"grid": "custom", "verticals": [30, 90], "transoms": [{"z": 40, "at": [10]}, 80],
          "style": "ssg4", "infill": {"rows": ["spandrel", "vision"], "cells": {"0,0": "vision"}}}
cw_dst = {"grid": "equal", "spacing": 48, "transoms": [60], "infill": {"rows": ["vision"], "cells": {"1,1": "spandrel"}}}
out = match.matched_params("curtain_wall", cw_src, cw_dst)
assert out["grid"] == "equal" and out["transoms"] == [60] and "verticals" not in out
assert out["style"] == "ssg4" and out["infill"] == {"rows": ["spandrel", "vision"], "cells": {"1,1": "spandrel"}}
cw_src2 = dict(cw_src, grid="fixed")
out = match.matched_params("curtain_wall", cw_src2, cw_dst)
assert out["grid"] == "fixed" and out["transoms"] == [80]

# openings keep their place; stairs keep what is measured on their own curve; unknown kinds are not changed
op = match.matched_params("opening", {"width": 36, "height": 84, "station": 10, "swing": "out"},
                          {"width": 30, "height": 60, "station": 99, "ro": {"width": 32}})
assert op == {"width": 36, "height": 84, "station": 99, "ro": {"width": 32}, "swing": "out"}
st = match.matched_params("stair", {"width": 60, "height": 144, "side": "right", "landings": [10], "start": 5},
                          {"width": 44, "side": "left", "flip": True, "landings": [99]})
assert st == {"width": 60, "height": 144, "side": "left", "flip": True, "landings": [99]}, st
assert match.matched_params("ramp", {"width": 60}, {"width": 44}) == {"width": 44}


# short aliases: added / updated when free or ours, never over someone else's
class Aliases(object):
    def __init__(self, d):
        self.d = dict(d)

    def IsAlias(self, a):
        return a in self.d

    def GetMacro(self, a):
        return self.d[a]

    def SetMacro(self, a, m):
        self.d[a] = m

    def Add(self, a, m):
        self.d[a] = m


ours = install._macro("MCOpening")
al = Aliases({"I": "'_Invert", "OP": ours.replace("MCOpening", "MCOldName"), "WA": "! _Polyline"})
cmds = ["MCInspector", "MCMatch", "MCWall", "MCOpening", "MCFloor", "MCRoof", "MCCurtainWall",
        "MCWallMass", "MCOpeningMass", "MCSectionCut", "MCDrawing", "MCUpdate"]
added, skipped = install.install_short(al, cmds)
assert al.d["I"] == "'_Invert" and al.d["WA"] == "! _Polyline"     # someone else's: kept
assert sorted(a for a, _ in skipped) == ["I", "WA"]
assert al.d["OP"] == ours and al.d["MT"] == install._macro("MCMatch")
assert "FL=MCFloor" in added and al.d["FL"].endswith('MCFloor.py"')
added, skipped = install.install_short(Aliases({}), ["MCWall"])     # missing commands are skipped
assert added == ["WA=MCWall"]
print("test_match_aliases: OK")
