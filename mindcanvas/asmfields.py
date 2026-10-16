"""Typed fields for the assembly editor (Phase 12): the known option keys of each component and the
known settings of each assembly kind, so the editor shows dropdowns, length boxes and checkboxes
instead of raw JSON. No UI here (asmedit.AssemblyModel uses it; the Eto view draws the widgets).

A schema entry is (key, type, label, choices, default):
    type      choice | bool | length | number | int | text | material | profile
    choices   choice: a list, or fn(lib, kind, opts) -> list; profile: the profile family, or
              fn(lib, kind, opts) -> family name(s)
    default   shown when the key is unset: a value, ("sys", key) = the layer's framing / joist
              system's value, or None
An entry may also carry a 6th item when(lib, kind, opts) -> bool (shown only then).
Keys not in the schema with scalar values get a field typed from their value; dict / list values
stay in the "advanced JSON" box.
"""

import json

from . import units

DEFAULT = "(default)"
NONE = "(none)"
SCALARS = (bool, int, float, str, type(None))
HIDDEN_SETTINGS = ("kind", "layers", "ceiling", "based_on")
LODS = ["schematic", "design", "detail"]


# -- helpers for choices / defaults -----------------------------------------------------------------
def _wall_systems(lib, kind, opts):
    return sorted(n for n, s in lib.data["framing"].items() if s.get("use") != "joists")


def _joist_systems(lib, kind, opts):
    out = []
    for n, s in sorted(lib.data["framing"].items()):
        if s.get("use") == "joists":
            out.append(n[:-len("_joists")] if n.endswith("_joists") else n)
    return out


def wall_system(lib, opts):
    name = opts.get("system") or "wood"
    return lib.data["framing"].get(name) or {}


def joist_system(lib, opts):
    name = opts.get("system") or "wood"
    fr = lib.data["framing"]
    for cand in (name + "_joists", name):
        if cand in fr and fr[cand].get("use") == "joists":
            return fr[cand]
    return {}


def _is_metal_wall(lib, kind, opts):
    return wall_system(lib, opts).get("type") == "metal"


def _is_metal_joist(lib, kind, opts):
    return joist_system(lib, opts).get("type") == "metal"


def _stud_family(lib, kind, opts):
    return wall_system(lib, opts).get("stud_family") or "lumber"


def _joist_family(lib, kind, opts):
    sysd = joist_system(lib, opts)
    fams = [sysd.get("family") or "lumber"]
    if sysd.get("type") != "metal":
        fams += ["i_joist", "lumber_deep"]
    return fams


def _rim_family(lib, kind, opts):
    return ["rim_board", "lumber"]


def _bricks(lib, kind, opts):
    from .components import masonry
    return sorted(masonry.BRICKS)


def _bonds(lib, kind, opts):
    from .components import masonry
    return list(masonry.BONDS)


def _toolings(lib, kind, opts):
    from .components import masonry
    return sorted(masonry.TOOLING)


GAUGES = [20, 18, 16, 14]
JOIST_GAUGES = [16, 14]

# -- layer options per (kind, component); kind None = any kind --------------------------------------
_JOIST_COMMON = [
    ("gauge", "choice", "Gauge (metal)", JOIST_GAUGES, ("sys", "gauge"), _is_metal_joist),
    ("spacing", "length", "Spacing o.c.", None, ("sys", "spacing")),
    ("cavity_fill", "material", "Cavity fill", None, None),
    ("fill_depth", "length", "Fill depth", None, "full depth"),
    ("fit", "choice", "Thickness", ["joist", "layer"], "joist"),
]

LAYER_OPTIONS = {
    ("wall", "framing"): [
        ("system", "choice", "Framing system", _wall_systems, "wood"),
        ("stud", "profile", "Stud", _stud_family, "by thickness"),
        ("gauge", "choice", "Gauge (metal)", GAUGES, ("sys", "gauge"), _is_metal_wall),
        ("spacing", "length", "Spacing o.c.", None, ("sys", "spacing")),
        ("cavity_fill", "material", "Cavity fill", None, None),
        ("blocking", "bool", "Blocking", None, ("sys", "blocking")),
        ("deflection_track", "bool", "Deflection track", None, ("sys", "deflection_track"), _is_metal_wall),
        ("double_end_studs", "bool", "Double end studs", None, ("sys", "double_end_studs")),
        ("bottom_plates", "int", "Bottom plates", None, ("sys", "bottom_plates")),
        ("top_plates", "int", "Top plates", None, ("sys", "top_plates")),
        ("bridging_spacing", "length", "Bridging spacing", None, ("sys", "bridging_spacing"), _is_metal_wall),
        ("header_type", "choice", "Header", ["box", "L"], "box", _is_metal_wall),
        ("fit", "choice", "Thickness", ["stud", "layer"], "stud"),
    ],
    ("wall", "masonry"): [
        ("brick", "choice", "Brick", _bricks, "modular"),
        ("bond", "choice", "Bond", _bonds, "running"),
        ("header_every", "int", "Header course every", None, 6),
        ("joint", "length", "Head joint", None, "3/8"),
        ("tooling", "choice", "Joint tooling", _toolings, "concave"),
        ("weeps", "length", "Weep spacing", None, None),
        ("mortar", "material", "Mortar", None, "Mortar"),
        ("jockey", "length", "Max joint adjustment", None, "1/16"),
        ("min_piece", "length", "Min piece at jambs", None, None),
    ],
    ("floor", "joists"): [
        ("system", "choice", "Joist system", _joist_systems, "wood"),
        ("joist", "profile", "Joist", _joist_family, "by thickness"),
    ] + _JOIST_COMMON[:2] + [
        ("rim", "profile", "Rim", _rim_family, "the joist"),
        ("rim_plies", "int", "Rim plies", None, ("sys", "rim_plies")),
        ("rim_material", "material", "Rim material", None, None),
        ("blocking", "bool", "Blocking", None, ("sys", "blocking")),
        ("blocking_spacing", "length", "Blocking spacing", None, ("sys", "blocking_spacing")),
    ] + _JOIST_COMMON[2:],
    ("floor", "deck"): [
        ("profile", "profile", "Deck profile", "deck", "1-1/2\" Composite Deck, 20 ga"),
        ("fill", "material", "Flute fill", None, "Concrete"),
    ],
    ("roof", "rafters"): [
        ("system", "choice", "Rafter system", _joist_systems, "wood"),
        ("rafter", "profile", "Rafter", _joist_family, "by thickness"),
    ] + _JOIST_COMMON[:2] + [
        ("rafter_material", "material", "Rafter material", None, None),
    ] + _JOIST_COMMON[2:],
    ("roof", "joists"): [
        ("system", "choice", "Joist system", _joist_systems, "wood"),
        ("joist", "profile", "Ceiling joist", _joist_family, "by thickness"),
    ] + _JOIST_COMMON[:2] + [
        ("joist_material", "material", "Joist material", None, None),
    ] + _JOIST_COMMON[2:],
    ("roof", "shingles"): [
        ("exposure", "length", "Exposure", None, 5),
        ("tip", "length", "Butt thickness", None, "1/8"),
    ],
    ("floor", "solid"): [("inset", "length", "Inset from the edge", None, 0)],
    ("floor", "membrane"): [("inset", "length", "Inset from the edge", None, 0)],
    ("floor", "void"): [("inset", "length", "Inset from the edge", None, 0)],
    ("roof", "solid"): [("taper", "number", "Taper (in / ft)", None, None)],
}

# -- assembly settings per kind -----------------------------------------------------------------------
WALL_REFERENCES = ["exterior_face", "interior_face", "center", "core_exterior", "core_interior", "core_center"]

SETTINGS = {
    "wall": [
        ("default_height", "length", "Default height", None, "10'"),
        ("default_reference", "choice", "Location line", WALL_REFERENCES, "center"),
        ("lod", "choice", "Detail level", LODS, "detail"),
    ],
    "floor": [
        ("reference", "choice", "Datum", ["framing_bottom", "framing_top", "top", "bottom"], "framing_bottom"),
        ("span", "text", "Span (short | long | degrees)", None, "short"),
        ("lod", "choice", "Detail level", LODS, "detail"),
    ],
    "roof": [
        ("shape", "choice", "Shape", ["gable", "shed", "flat"], "gable"),
        ("pitch", "number", "Pitch (x in 12)", None, 6),
        ("overhang", "length", "Eave overhang", None, 18),
        ("rake", "length", "Rake overhang", None, 12),
        ("ridge", "text", "Ridge (long | short | degrees)", None, "long"),
        ("flip", "bool", "Flip (shed high side)", None, False),
        ("wall_depth", "length", "Bearing wall depth", None, "from the walls"),
        ("wall_ext", "length", "Wall layers outside", None, "from the walls"),
        ("wall_int", "length", "Wall layers inside", None, "from the walls"),
        ("lod", "choice", "Detail level", LODS, "detail"),
    ],
    "curtain_wall": [
        ("default_height", "length", "Default height", None, "10'"),
        ("style", "choice", "Joint style", ["captured", "ssg4", "ssg2", "butt", "unitized"], "captured"),
        ("grid", "choice", "Grid", ["equal", "fixed", "list"], "equal"),
        ("spacing", "length", "Mullion spacing", None, 60),
        ("mullion", "profile", "Mullion", "cw_mullion", "CW Aluminum 2-1/2 x 6"),
        ("transom", "profile", "Transom", "cw_mullion", "the mullion"),
        ("ssg_sides", "choice", "SSG sides (2-side)", ["vertical", "horizontal"], "vertical"),
        ("corner_angle", "number", "Corner angle (deg)", None, 25),
        ("lod", "choice", "Detail level", LODS, "detail"),
    ],
}


class Field(object):
    """One typed field as the view shows it."""

    def __init__(self, key, type_, label, value, choices=None, default=None, explicit=False):
        self.key = key
        self.type = type_
        self.label = label
        self.value = value          # display value: str for text-like, bool for bool, str choice
        self.choices = choices      # [display strings] for choice / material / profile
        self.default = default      # display string of the default ("" if none)
        self.explicit = explicit    # the key is set (not the default)

    def __repr__(self):
        return "<Field {} {}={!r}>".format(self.key, self.type, self.value)


# -- conversion ---------------------------------------------------------------------------------------
FEET_FROM = 60.0       # lengths from 5' up show in feet (heights), below in inches (spacing 16, 48)


def show_length(v):
    """Library length -> field text: '3-5/8', '16', '9'-6"'."""
    try:
        t = units.parse_length(v)
    except (ValueError, TypeError):
        return str(v)
    if abs(t) >= FEET_FROM:
        return units.format_inches(t, 64)
    return (_inches(t) if t >= 12 else units.format_inches(t, 64)).replace('"', "")


def _inches(t):
    whole = int(t)
    frac = units.format_inches(t - whole, 64).replace('"', "") if abs(t - whole) * 64 >= 0.5 else ""
    if frac in ("0", "1"):
        whole, frac = whole + int(frac), ""
    return "{}-{}".format(whole, frac) if frac else str(whole)


def store_length(text):
    """'3-5/8' / '1'-6"' / 16 -> a library value: int inches, a fraction string, or feet + inches
    from 5' up."""
    t = units.parse_length(text)
    if abs(t) >= FEET_FROM:
        return units.format_inches(t, 64)
    if abs(t - round(t)) < 1e-9:
        return int(round(t))
    return _inches(t) if t >= 12 else units.format_inches(t, 64).replace('"', "")


def _show(type_, v):
    if v is None:
        return ""
    if type_ == "length":
        return show_length(v)
    if type_ == "bool":
        return bool(v)
    if isinstance(v, float) and abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return str(v)


def _infer(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str) and any(c in v for c in "/'\"") and v[:1].isdigit():
        try:
            units.parse_length(v)
            return "length"
        except ValueError:
            pass
    return "text"


def _label(key):
    return key.replace("_", " ").capitalize()


def _profiles(lib, family):
    fams = family if isinstance(family, (list, tuple)) else [family]
    out = []
    for f in fams:
        cands = sorted(((units.parse_length(p.get("depth", 0)), n) for n, p in lib.data["profiles"].items()
                        if p.get("family") == f), key=lambda c: (c[0], c[1]))
        out += [n for _, n in cands if n not in out]
    return out


def _resolve_default(lib, kind, comp, opts, default):
    if isinstance(default, tuple) and default and default[0] == "sys":
        sysd = wall_system(lib, opts) if (kind == "wall" and comp == "framing") else joist_system(lib, opts)
        key = default[1]
        if key == "spacing" and comp == "rafters":
            v = sysd.get("rafter_spacing", sysd.get("spacing"))
        else:
            v = sysd.get(key)
        if key == "header_type":
            v = (sysd.get("header") or {}).get("type")
        return v
    return default


def _default_text(type_, v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if type_ == "length" and not (isinstance(v, str) and v[:1].isalpha()):
        try:
            s = show_length(v)
            return s if s.endswith('"') else s + '"'
        except ValueError:
            pass
    return str(v)


def build_fields(lib, kind, comp, values, schema):
    """[Field] for a dict of values (layer options or assembly settings) and its schema."""
    out, known = [], set()
    for entry in schema:
        key, type_, label, choices, default = entry[:5]
        when = entry[5] if len(entry) > 5 else None
        known.add(key)
        if when is not None and not when(lib, kind, values) and key not in values:
            continue
        v = values.get(key)
        dflt = _resolve_default(lib, kind, comp, values, default)
        explicit = key in values
        if type_ in ("choice", "material", "profile"):
            if type_ == "choice":
                items = choices(lib, kind, values) if callable(choices) else list(choices)
                items = [str(c) for c in items]
            elif type_ == "material":
                items = sorted(lib.data["materials"])
            else:
                fam = choices(lib, kind, values) if callable(choices) else choices
                items = _profiles(lib, fam)
            first = NONE if (type_ == "material" and dflt is None) else DEFAULT
            cur = str(v) if v is not None else first
            if v is not None and cur not in items:
                items.append(cur)
            out.append(Field(key, type_, label, cur, [first] + items, _default_text(type_, dflt), explicit))
        else:
            if type_ == "bool":
                val = bool(v) if explicit else bool(dflt)
            else:
                val = _show(type_, v)
            out.append(Field(key, type_, label, val, None, _default_text(type_, dflt), explicit))
    for key in sorted(values):
        if key in known or not isinstance(values[key], SCALARS) or key in HIDDEN_SETTINGS:
            continue
        type_ = _infer(values[key])
        out.append(Field(key, type_, _label(key), _show(type_, values[key]), None, "", True))
    return out


def parse_value(field_type, raw, current=None):
    """Widget value -> (value, unset). raw: str (text / choice) or bool. unset = remove the key."""
    if field_type == "bool":
        return bool(raw), False
    text = "" if raw is None else str(raw).strip()
    if text in ("", DEFAULT, NONE):
        return None, True
    if field_type == "length":
        return store_length(text), False
    if field_type == "number":
        f = float(text)
        return (int(f) if abs(f - round(f)) < 1e-9 else f), False
    if field_type == "int":
        return int(float(text)), False
    if field_type == "choice":
        for c in (GAUGES + JOIST_GAUGES):
            if text == str(c):
                return c, False
        return text, False
    if field_type == "text":
        try:
            f = float(text)
            return (int(f) if abs(f - round(f)) < 1e-9 else f), False
        except ValueError:
            return text, False
    return text, False


def layer_schema(kind, comp):
    return LAYER_OPTIONS.get((kind, comp)) or LAYER_OPTIONS.get((None, comp)) or []


def advanced(values, hidden=()):
    """JSON of the keys that have no field (dicts / lists)."""
    rest = dict((k, v) for k, v in values.items() if not isinstance(v, SCALARS) and k not in hidden)
    return json.dumps(rest, indent=1, sort_keys=True) if rest else ""


def merge_advanced(values, text, hidden=()):
    """New dict: the scalar keys of values + the parsed JSON (which replaces every dict / list key)."""
    try:
        extra = json.loads(text) if (text or "").strip() else {}
    except ValueError as ex:
        raise ValueError("Advanced options are not valid JSON: {}".format(ex))
    if not isinstance(extra, dict):
        raise ValueError("Advanced options must be a JSON object {...}.")
    out = dict((k, v) for k, v in values.items() if isinstance(v, SCALARS) or k in hidden)
    for k, v in extra.items():
        if k in hidden:
            continue
        out[k] = v
    return out
