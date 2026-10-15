"""Material quantity takeoff.

Rows are grouped by (material, role). Each row reports count, volume (ft^3)
and, when parts carry it, total length (`mc.x.length`, inches -> linear ft)
and area (`mc.x.area`, in^2 -> ft^2).
"""

import csv
import json

import Rhino

from . import meta, units

G = Rhino.Geometry


def _volume(geom):
    if geom is None:
        return 0.0
    mp = G.VolumeMassProperties.Compute(geom, True, False, False, False)
    return abs(mp.Volume) if mp else 0.0


def _num(obj, key):
    v = meta.get(obj, meta.EXTRA_PREFIX + key)
    try:
        return float(json.loads(v)) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def takeoff(doc, driver_ids=None):
    s = units.inch_scale(doc)
    cubic_ft = (1.0 / s) ** 3 / 1728.0
    if driver_ids is None:
        parts = doc.Objects.FindByUserString(meta.KIND, meta.PART_KIND, True) or []
    else:
        parts = []
        for d in driver_ids:
            parts.extend(meta.parts_of(doc, d))

    block_volume = {}
    rows = {}
    for o in parts:
        key = (meta.get(o, meta.MATERIAL, "?"), meta.get(o, meta.ROLE, "?"))
        row = rows.setdefault(key, {"material": key[0], "role": key[1], "count": 0,
                                    "volume_ft3": 0.0, "length_ft": 0.0, "area_ft2": 0.0})
        row["count"] += 1
        if isinstance(o, Rhino.DocObjects.InstanceObject):
            idx = o.InstanceDefinition.Index
            if idx not in block_volume:
                block_volume[idx] = sum(_volume(x.Geometry) for x in o.InstanceDefinition.GetObjects())
            vol = block_volume[idx]  # members are placed unscaled
        else:
            vol = _volume(o.Geometry)
        row["volume_ft3"] += vol * cubic_ft
        row["length_ft"] += _num(o, "length") / 12.0
        row["area_ft2"] += _num(o, "area") / 144.0
    return sorted(rows.values(), key=lambda r: (r["material"], r["role"]))


def format_table(rows):
    lines = ["{:<32} {:<14} {:>7} {:>10} {:>10} {:>10}".format(
        "Material", "Role", "Count", "Vol ft3", "Len ft", "Area ft2")]
    for r in rows:
        lines.append("{:<32} {:<14} {:>7} {:>10.2f} {:>10.1f} {:>10.1f}".format(
            r["material"][:32], r["role"][:14], r["count"], r["volume_ft3"], r["length_ft"], r["area_ft2"]))
    return "\n".join(lines)


def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["material", "role", "count", "volume_ft3", "length_ft", "area_ft2"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
