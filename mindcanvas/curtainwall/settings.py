"""Curtain-wall settings: DEFAULTS <- assembly <- driver params (dicts merge, lists replace).

Every length is inches (numbers or imperial strings). Keys:

    style          captured | ssg4 | ssg2 | butt | unitized
    reference      where the driver sits: glass (exterior face of the glass, default) |
                   glass_center | exterior_face (face of caps / lips) | mullion_back
    grid           equal (each run divided into equal bays <= spacing) | fixed (spacing from
                   the start of each run, the remainder in the last bay) | list (bays widths,
                   repeated)
    spacing, bays  module and the list for grid = list
    transoms       heights of horizontal mullions above the base (the sill and head are always
                   there)
    stack          unitized: heights of stack joints (split horizontals) above the base
    slabs          heights of slab tops above the base: slab-edge anchors at every mullion,
                   fire safing + smoke seal (detail)
    infill         {"rows": [type per row, bottom -> top; the last repeats],
                    "cells": {"<bay>,<row>": type}}   type: vision | spandrel | shadow_box
    mullion        profile name (library/profiles/curtainwall.json): width, depth, t,
                   material, solid (wood)
    transom        profile for horizontals (default: the mullion's)
    ssg_sides      ssg2 only: "vertical" (SSG verticals, captured horizontals) | "horizontal"
    corner_angle   turns (degrees) at curve kinks above this get a corner mullion
    overrides      {"<key>": value} merged last (MCEditCurtainWall writes plain keys)
"""

import copy

from .. import units

STYLES = ("captured", "ssg4", "ssg2", "butt", "unitized")
REFERENCES = ("glass", "glass_center", "exterior_face", "mullion_back")
GRIDS = ("equal", "fixed", "list")
INFILLS = ("vision", "spandrel", "shadow_box")
LODS = ("schematic", "design", "detail")

DEFAULTS = {
    "style": "captured",
    "reference": "glass",
    "grid": "equal",
    "spacing": 60,
    "bays": [],
    "transoms": [],
    "stack": [],
    "slabs": [],
    "infill": {"rows": ["vision"], "cells": {}},
    "mullion": "CW Aluminum 2-1/2 x 6",
    "transom": None,
    "ssg_sides": "vertical",
    "corner_angle": 25,
    "glazing": {"lites": 2, "glass": "1/4", "space": "1/2", "material": "Glass", "spacer": "Aluminum"},
    "bite": "1/2",                 # glass edge cover on captured / pocket-glazed members
    "gasket": "1/4",               # glazing gasket thickness (each face of the glass)
    "spline": "1/2",               # width of the screw spline (captured)
    "pressure_plate": {"t": "1/8", "material": None},    # None = mullion material (aluminum)
    "isolator": "Thermal Break",
    "cap": {"depth": 1, "t": "1/16", "material": None},
    "gasket_material": "Gasket",
    "ssg": {"joint": "3/4", "bite": "1/2", "glueline": "1/4", "seal": "3/8",
            "silicone": "Structural Silicone", "sealant": "Sealant", "backer": "Backer Rod",
            "tape": "Gasket"},
    "butt": {"joint": "1/2", "backup": "none", "fin": {"depth": 12, "t": "3/4"}},
    "unitized": {"split": "1/2", "lip": "1/8"},
    "spandrel": {"panel": "glass", "material": "Spandrel Glass", "air": 1, "insulation": 3,
                 "insulation_material": "Mineral Wool Board", "back_pan": "Back Pan",
                 "back_pan_t": "1/32", "metal": "Metal Panel", "core": "Panel Core",
                 "skin": "1/16"},
    "shadow_box": {"back_pan": "Shadow Box Pan", "back_pan_t": "1/32", "insulation": 2,
                   "insulation_material": "Mineral Wool Board"},
    "setting_blocks": {"material": "Setting Block", "length": 4},
    "perimeter": {"joint": "1/2", "sealant": "Sealant", "backer": "Backer Rod"},
    "anchors": {"material": "Steel Angle", "leg": 4, "height": 5, "t": "3/8", "slab_gap": "1-1/2",
                "slab_thickness": 8, "safing": "Fire Safing", "smoke_seal": "Sealant"},
}

# vertical / horizontal joint style per system style
V_STYLE = {"captured": "captured", "ssg4": "ssg", "ssg2": "ssg", "butt": "butt", "unitized": "split"}
H_STYLE = {"captured": "captured", "ssg4": "ssg", "ssg2": "captured", "butt": "captured",
           "unitized": "unit"}

ASSEMBLY_ONLY = ("kind", "default_height", "lod", "layers", "description", "_comment")


def merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def merged(assembly, params):
    """DEFAULTS <- assembly <- params <- params['overrides']."""
    a = dict((k, v) for k, v in assembly.items() if k not in ASSEMBLY_ONLY)
    out = merge(DEFAULTS, a)
    p = dict((k, v) for k, v in (params or {}).items()
             if k not in ("height", "base_offset", "flip", "lod", "overrides"))
    out = merge(out, p)
    out = merge(out, (params or {}).get("overrides"))
    if out.get("style") not in STYLES:
        raise ValueError("Unknown curtain wall style '{}'".format(out.get("style")))
    return out


def L(v):
    return units.parse_length(v)


class Dims(object):
    """Every section dimension in inches, resolved from the settings + library profiles."""

    def __init__(self, lib, st):
        self.st = st
        self.style = st["style"]
        self.v_style = V_STYLE[self.style]
        self.h_style = H_STYLE[self.style]
        if self.style == "ssg2" and str(st.get("ssg_sides", "vertical")).lower().startswith("h"):
            self.v_style, self.h_style = "captured", "ssg"
        self.mp = self._profile(lib, st["mullion"])
        self.tp = self._profile(lib, st.get("transom") or st["mullion"])
        gz = st["glazing"]
        self.lites = max(1, int(gz.get("lites", 2)))
        self.glass = L(gz.get("glass", "1/4"))
        self.space = L(gz.get("space", "1/2"))
        self.T = self.lites * self.glass + (self.lites - 1) * self.space
        self.glass_mat = gz.get("material", "Glass")
        self.spacer_mat = gz.get("spacer", "Aluminum")
        self.bite = L(st["bite"])
        self.g = L(st["gasket"])
        self.l = L(st["spline"])
        self.ppt = L(st["pressure_plate"]["t"])
        cap = st["cap"]
        self.cap_P = L(cap["depth"])
        self.cap_t = L(cap["t"])
        self.iso_mat = st["isolator"]
        self.gasket_mat = st["gasket_material"]
        s = st["ssg"]
        self.j = L(s["joint"])
        self.sb = L(s["bite"])
        self.glue = L(s["glueline"])
        self.seal = L(s["seal"])
        self.silicone = s["silicone"]
        self.sealant = s["sealant"]
        self.backer = s["backer"]
        self.tape_mat = s["tape"]
        b = st["butt"]
        self.jb = L(b["joint"])
        self.backup = str(b.get("backup", "none")).lower()
        self.fin_d = L(b["fin"]["depth"])
        self.fin_t = L(b["fin"]["t"])
        u = st["unitized"]
        self.split = L(u["split"])
        self.lip = L(u["lip"])

    def _profile(self, lib, name):
        p = dict(lib.profile(name))
        out = {
            "name": name,
            "w": L(p.get("width", "2-1/2")),
            "D": L(p.get("depth", 6)),
            "t": L(p.get("t", "1/8")),
            "material": p.get("material", "Aluminum"),
            "solid": bool(p.get("solid", p.get("type") == "rect")),
            "adaptor": L(p.get("adaptor", "1/8")),
        }
        return out

    def material(self, key):
        """Pressure plate / cap material (None in the settings = the mullion's)."""
        m = self.st[key].get("material")
        return m or ("Aluminum" if self.mp["solid"] else self.mp["material"])

    def q_tube(self, style, prof):
        """Depth of the tube's front face (glazing pocket face) behind the glass face."""
        if style == "ssg":
            return self.T + self.glue
        if style == "butt":
            return self.T + self.g
        q = self.T + self.g
        if prof["solid"] and style == "captured":
            q += prof["adaptor"]
        return q

    def q_front(self):
        """Most exterior q of the system (negative = in front of the glass)."""
        vs = (self.v_style, self.h_style)
        if "captured" in vs:
            return -self.cap_P
        if "split" in vs or "unit" in vs:
            return -(self.g + self.lip)
        return 0.0

    def q_back(self):
        return max(self.q_tube(self.v_style if self.v_style != "butt" else "captured", self.mp) + self.mp["D"],
                   self.q_tube(self.h_style, self.tp) + self.tp["D"])
