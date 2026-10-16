"""Per-wall trims: `sweep` extras stored in a wall's params["extras"] (MCTrim, MCProfileCapture).

A trim is {"component": "sweep", "name": "Trim: <profile> (<face>, <z>)", "material": ...,
"options": {"profile", "face", "z", "offset"}}; see components/sweep.py.
"""

from . import engine, meta


def profiles(lib):
    """Profiles offered for trims: family 'trim' and captured ones."""
    return sorted(n for n, p in lib.data["profiles"].items() if p.get("family") == "trim" or p.get("captured"))


def trims(driver_obj):
    return [e for e in (meta.params(driver_obj).get("extras") or []) if e.get("component") == "sweep"]


def spec(lib, profile, face="interior", z="base", offset=0.0, material=None):
    lib.profile(profile)        # raises if unknown
    zs = z if isinstance(z, str) else '{:g}"'.format(float(z))
    s = {"component": "sweep", "name": "Trim: {} ({}, {})".format(profile, face, zs),
         "options": {"profile": profile, "face": face, "z": z}}
    if offset:
        s["options"]["offset"] = offset
    mat = material or lib.profile(profile).get("material")
    if mat:
        s["material"] = mat
    return s


def add(doc, driver_obj, lib, profile, face="interior", z="base", offset=0.0, material=None):
    """Add (or replace: same profile, face and height) a trim on a wall; rebuilds it."""
    new = spec(lib, profile, face, z, offset, material)
    extras = [e for e in (meta.params(driver_obj).get("extras") or []) if e.get("name") != new["name"]]
    extras.append(new)
    return engine.update_params(doc, driver_obj, {"extras": extras}, lib)


def remove(doc, driver_obj, lib, profile=None):
    """Remove every trim (or those of one profile). Returns the BuildResult, or None if unchanged."""
    extras = meta.params(driver_obj).get("extras") or []
    keep = [e for e in extras if not (e.get("component") == "sweep" and
                                      (profile is None or e.get("options", {}).get("profile") == profile))]
    if len(keep) == len(extras):
        return None
    return engine.update_params(doc, driver_obj, {"extras": keep or None}, lib)
