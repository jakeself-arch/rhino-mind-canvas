"""Editing a wall's layer stack (used by MCLayers).

A stack is a list of layer specs, exterior -> interior. Edits return new
lists; nothing here touches the document. The catalog of layers to choose
from is every library preset (library/layers) plus every distinct layer used
in any wall assembly, so e.g. the brick layer of a brick assembly can be
reused with all its options.
"""

import copy
import json

from . import units
from .kinds import wall as wallkind


def describe(spec, index=None):
    t = units.format_inches(units.parse_length(spec.get("thickness", 0)), 64)
    head = "{:>2}. ".format(index + 1) if index is not None else ""
    core = "  [core]" if spec.get("core") else ""
    mat = spec.get("material") or "-"
    return "{}{}  |  {}  |  {}  |  {}{}".format(
        head, wallkind.layer_name(spec, index or 0), mat, t, spec.get("component", "solid"), core)


def _signature(spec):
    s = dict(spec)
    s.pop("core", None)
    s.pop("name", None)
    return json.dumps(s, sort_keys=True)


def catalog(lib):
    """[(label, spec)] — presets first, then layers harvested from assemblies."""
    out, seen = [], set()
    for name in sorted(lib.data["layers"]):
        spec = lib.resolve_layer({"preset": name})
        out.append(("Preset: " + describe(spec), copy.deepcopy(spec)))
        seen.add(_signature(spec))
    for asm_name in lib.assemblies("wall"):
        for spec in lib.assembly(asm_name)["layers"]:
            full = lib.resolve_layer(spec)
            sig = _signature(full)
            if sig in seen:
                continue
            seen.add(sig)
            clean = copy.deepcopy(spec)
            clean.pop("core", None)
            out.append(("{}   (from {})".format(describe(full), asm_name), clean))
    return out


def current(lib, driver_obj):
    """The wall's stack as stored (presets unexpanded), deep-copied."""
    from . import meta
    prm = meta.params(driver_obj)
    raw = prm.get("layers") or lib.assembly(meta.get(driver_obj, meta.ASSEMBLY))["layers"]
    return copy.deepcopy(raw)


def _unique(layers, spec, skip=None):
    """Give spec a name not used by any other layer ("Brick Veneer (2)")."""
    base = wallkind.layer_name(spec, 0)
    taken = set(wallkind.layer_name(l, i) for i, l in enumerate(layers) if i != skip)
    name, n = base, 2
    while name in taken:
        name = "{} ({})".format(base, n)
        n += 1
    out = copy.deepcopy(spec)
    if name != base:
        out["name"] = name
    return out


def replace(layers, index, spec):
    """Swap one layer; the replacement inherits the old layer's core flag so
    the wall's location line stays put."""
    out = copy.deepcopy(layers)
    new = _unique(out, spec, skip=index)
    if out[index].get("core"):
        new["core"] = True
    else:
        new.pop("core", None)
    out[index] = new
    return out


def insert(layers, index, spec):
    """Insert before position `index` (0 = new exterior-most layer)."""
    out = copy.deepcopy(layers)
    new = _unique(out, spec)
    new.pop("core", None)
    out.insert(index, new)
    return out


def remove(layers, index):
    out = copy.deepcopy(layers)
    del out[index]
    if not out:
        raise ValueError("A wall needs at least one layer.")
    return out


def set_thickness(layers, index, value):
    inches = units.parse_length(value)
    if inches <= 0:
        raise ValueError("Thickness must be positive.")
    out = copy.deepcopy(layers)
    out[index]["thickness"] = units.format_inches(inches, 64)
    # framing picks the stud matching its thickness; a pinned stud would win
    out[index].get("options", {}).pop("stud", None)
    return out


def move(layers, index, step):
    out = copy.deepcopy(layers)
    j = index + step
    if not 0 <= j < len(out):
        return out
    out[index], out[j] = out[j], out[index]
    return out


def mirror(layers):
    """Reverse the stack (the old interior becomes the exterior)."""
    return list(reversed(copy.deepcopy(layers)))


def as_assembly(lib, base_name, layers):
    base = copy.deepcopy(lib.assembly(base_name))
    base["layers"] = copy.deepcopy(layers)
    base["based_on"] = base_name
    return base
