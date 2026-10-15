"""Drawing styles: library/styles/*.json presets, one per drawing scale.

A preset may say "extends": "<other preset>"; dicts are merged recursively,
lists and scalars replace. `get("Eighth")`, `get('1/8" = 1\'-0"')` and
`get("1/8")` all find the 1/8" preset.
"""

import copy
import fnmatch

from .. import library, units

WHITE_KEEP = ("ground", "stipple", "tone", "inner")


def _merge(a, b):
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _resolve(lib, name, seen=()):
    data = lib.style(name)
    if data is None:
        raise KeyError("Drawing style '{}' not found in library/styles".format(name))
    parent = data.get("extends")
    if parent and parent not in seen:
        merged = _merge(_resolve(lib, parent, seen + (name,)), data)
        merged["abstract"] = data.get("abstract", False)
        return merged
    return copy.deepcopy(data)


class Style(object):
    def __init__(self, name, data):
        self.name = name
        self.data = data
        self.scale = float(data.get("scale", 48))
        self.lod = data.get("lod", "design")
        self.option = data.get("option") or "".join(c for c in name if c.isalnum())
        self.classes = data.get("classes", {})
        self.depth = data.get("depth", {})
        self.tone = data.get("tone", {})
        self.stipple = data.get("stipple", {})
        self.page = data.get("page", {})
        self.white_cuts = data.get("cut_mode", "material") == "white"
        self._mat = {}
        mats = data.get("materials", {})
        self._exact = dict((k.lower(), v) for k, v in mats.items() if not any(c in k for c in "*?["))
        pats = [(k, v) for k, v in mats.items() if any(c in k for c in "*?[") and k != "*"]
        # most specific pattern first: more literal characters wins
        self._patterns = sorted(pats, key=lambda kv: -len(kv[0].replace("*", "").replace("?", "")))
        self._default = mats.get("*", {"fill": "white"})

    def __repr__(self):
        return "<Style {} 1:{:g} {}>".format(self.name, self.scale, self.lod)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def mm_per_unit(self, doc):
        """Paper mm per model unit at this scale."""
        return 25.4 / self.scale / units.inch_scale(doc)

    def cls(self, name):
        return self.classes.get(name) or self.classes.get("edge") or {"w": 0.18, "order": 20}

    def width(self, cls, dn=0.0):
        far = float(self.depth.get("width_far", 0.45))
        return float(self.cls(cls).get("w", 0.18)) * (1.0 - (1.0 - far) * max(0.0, min(1.0, dn)))

    def grey(self, dn):
        g = float(self.depth.get("grey_far", 0.55)) * (max(0.0, min(1.0, dn)) ** float(self.depth.get("gamma", 0.85)))
        return int(round(255 * g))

    def material(self, name):
        """Cut appearance for a material: fill (white|black|grey|none), hatch, batt,
        cross, stipple, ground, inner, tone."""
        key = (name or "").lower()
        hit = self._mat.get(key)
        if hit is not None:
            return hit
        spec = dict(self._default)
        match = self._exact.get(key)
        if match is None:
            for pat, v in self._patterns:
                if fnmatch.fnmatch(key, pat.lower()):
                    match = v
                    break
        spec.update(match or {})
        if self.white_cuts and not spec.get("ground"):
            spec = dict((k, spec[k]) for k in WHITE_KEEP if k in spec)
            spec["fill"] = "white"
        spec.setdefault("fill", "white")
        spec.setdefault("inner", True)
        spec.setdefault("tone", True)
        self._mat[key] = spec
        return spec


def names(lib=None):
    """Concrete presets, largest drawing (smallest scale ratio last)."""
    lib = lib or library.get()
    out = []
    for name in lib.data["styles"]:
        try:
            st = get(name, lib)
        except KeyError:
            continue
        if not st.get("abstract"):
            out.append(st)
    return [s.name for s in sorted(out, key=lambda s: -s.scale)]


def get(name=None, lib=None):
    """Style by preset key, option name or a scale string like '1/8' / '1-1/2'."""
    lib = lib or library.get()
    styles = lib.data["styles"]
    if name is None:
        name = '1/8" = 1\'-0"'
    if isinstance(name, Style):
        return name
    if name in styles:
        return Style(name, _resolve(lib, name))
    low = str(name).lower().replace('"', "").replace(" ", "")
    for key, data in styles.items():
        opt = str(data.get("option", "")).lower()
        k = key.lower().replace('"', "").replace(" ", "")
        if low == opt or k.startswith(low + "=") or k == low:
            return Style(key, _resolve(lib, key))
    raise KeyError("Drawing style '{}' not found in library/styles".format(name))
