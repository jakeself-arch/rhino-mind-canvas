"""Match: give assemblies the assembly and settings of another one (MCMatch).

Settings that belong to each driver's own curve are never copied: a wall's end joins, a curtain
wall's custom grid lines (and transoms / cells placed on them), an opening's place along its
wall. A wall driven by a wall mass keeps the height and base its mass gives it. Kinds without a
rule here (e.g. stairs, whose landings sit on their own curve) get the assembly only.
"""

import copy

from . import engine, meta

OWN = {
    "wall": ("joins",),
    "curtain_wall": ("verticals",),
    "floor": (),
    "roof": (),
    "opening": ("station", "ro"),
}
MASS_OWN = ("height", "base_offset")


def matched_params(kind, src, dst, keep=()):
    """dst's params after matching src (both dicts; neither is changed)."""
    if kind not in OWN:
        return dict(dst)
    own = set(OWN[kind]) | set(keep)
    out = dict((k, copy.deepcopy(v)) for k, v in dst.items() if k in own)
    for k, v in src.items():
        if k not in own:
            out[k] = copy.deepcopy(v)
    if kind == "curtain_wall":
        _curtain_wall(src, dst, out)
    return out


def _curtain_wall(src, dst, out):
    if src.get("grid") == "custom":   # its grid lines are stations along the source's own curve
        for k in ("grid", "transoms"):
            if k in dst:
                out[k] = copy.deepcopy(dst[k])
            else:
                out.pop(k, None)
    elif "transoms" in out:           # transoms across only some bays sit at the source's stations
        out["transoms"] = [t for t in out["transoms"] if not (isinstance(t, dict) and t.get("at"))]
    if "infill" in src:               # rows match; painted cells stay the target's
        inf = copy.deepcopy(src["infill"])
        inf["cells"] = copy.deepcopy((dst.get("infill") or {}).get("cells", {}))
        out["infill"] = inf


def match(doc, lib, src, dst, assembly_only=False):
    """Give dst (a driver of src's kind) src's assembly and, unless assembly_only, its settings."""
    kind = meta.get(src, meta.TYPE)
    if meta.get(dst, meta.TYPE) != kind:
        raise ValueError("Can't match a {} to a {}.".format(meta.get(dst, meta.TYPE), kind))
    name = meta.get(src, meta.ASSEMBLY)
    sp, dp = meta.params(src), meta.params(dst)
    if kind == "opening":
        new = dp if assembly_only else matched_params(kind, sp, dp)
        changes = dict((k, new.get(k)) for k in set(new) | set(dp) if new.get(k) != dp.get(k))
        return engine.update_opening(doc, dst, changes, name if name != meta.get(dst, meta.ASSEMBLY) else None, lib)
    keep = ()
    if kind == "wall":
        from . import wallmasses
        if wallmasses.mass_of(doc, dst) is not None:
            keep = MASS_OWN
    new = dict(dp) if assembly_only else matched_params(kind, sp, dp, keep)
    if name != meta.get(dst, meta.ASSEMBLY) and assembly_only:
        new.pop("layers", None)       # a per-wall stack belonged to the old assembly
    return engine.rebuild_as(doc, dst, name, new, lib)
