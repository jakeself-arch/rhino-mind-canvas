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


# -- openings ------------------------------------------------------------------
def openings(doc, driver_ids=None):
    """Window / door schedule: one row per type and size, with the count and the walls.
    driver_ids: walls (their openings are counted) and/or openings; None = all."""
    from .openings import core
    if driver_ids is None:
        ops = meta.all_drivers(doc, core.KIND)
    else:
        ops, seen = [], set()
        for d in driver_ids:
            obj = doc.Objects.FindId(d)
            cands = [obj] if core.is_opening(obj) else core.hosted(doc, d)
            for o in cands:
                if str(o.Id) not in seen:
                    seen.add(str(o.Id))
                    ops.append(o)
    rows = {}
    for o in ops:
        p = meta.params(o)
        name = meta.get(o, meta.ASSEMBLY, "?")
        size = "{} x {}".format(units.format_inches(float(p.get("width", 0))),
                                units.format_inches(float(p.get("height", 0))))
        key = (name, size)
        row = rows.setdefault(key, {"type": name, "size": size, "count": 0, "walls": set(),
                                    "sill": units.format_inches(float(p.get("sill", 0)))})
        row["count"] += 1
        h = meta.get(o, core.HOST)
        if h:
            row["walls"].add(h[:8])
    out = []
    for key in sorted(rows):
        r = rows[key]
        r["walls"] = len(r["walls"])
        out.append(r)
    return out


def format_openings(rows):
    lines = ["{:<36} {:<20} {:>10} {:>6} {:>6}".format("Opening type", "Size (W x H)", "Sill", "Count", "Walls")]
    for r in rows:
        lines.append("{:<36} {:<20} {:>10} {:>6} {:>6}".format(r["type"][:36], r["size"], r["sill"], r["count"], r["walls"]))
    lines.append("{:<36} {:<20} {:>10} {:>6}".format("Total", "", "", sum(r["count"] for r in rows)))
    return "\n".join(lines)


def write_openings_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["type", "size", "sill", "count", "walls"])
        w.writeheader()
        for r in rows:
            w.writerow(r)


# -- curtain walls -------------------------------------------------------------
def curtain_walls(doc, driver_ids=None):
    """Curtain-wall panel schedule: one row per curtain wall and infill type with the panel
    count and the nominal glass / panel area (ft2, visible glass + bite). driver_ids: None = all."""
    from . import library
    from .kinds import curtainwall as cwkind
    lib = library.get()
    if driver_ids is None:
        drivers = meta.all_drivers(doc, cwkind.KIND)
    else:
        drivers = [doc.Objects.FindId(d) for d in driver_ids]
        drivers = [d for d in drivers if d is not None and meta.get(d, meta.TYPE) == cwkind.KIND]
    out = []
    for d in drivers:
        try:
            ctx = cwkind.make_context(doc, lib, d, meta.get(d, meta.ASSEMBLY), meta.params(d))
            s = cwkind.summary(ctx)
        except Exception as ex:
            out.append({"wall": str(d.Id)[:8], "assembly": meta.get(d, meta.ASSEMBLY), "panel": "error: {}".format(ex),
                        "count": 0, "area_ft2": 0.0, "bays": 0, "rows": 0})
            continue
        for p in s["panels"]:
            out.append({"wall": str(d.Id)[:8], "assembly": meta.get(d, meta.ASSEMBLY), "panel": p["panel"],
                        "count": p["count"], "area_ft2": round(p["area_ft2"], 2), "bays": s["bays"],
                        "rows": s["rows"]})
    return out


def format_curtain_walls(rows):
    lines = ["{:<10} {:<40} {:<12} {:>6} {:>10} {:>9}".format(
        "Wall", "Curtain wall", "Panel", "Count", "Area ft2", "Bays x rows")]
    for r in rows:
        lines.append("{:<10} {:<40} {:<12} {:>6} {:>10.1f} {:>9}".format(
            r["wall"], r["assembly"][:40], r["panel"][:12], r["count"], r["area_ft2"],
            "{} x {}".format(r["bays"], r["rows"])))
    lines.append("{:<10} {:<40} {:<12} {:>6} {:>10.1f}".format(
        "Total", "", "", sum(r["count"] for r in rows), sum(r["area_ft2"] for r in rows)))
    return "\n".join(lines)


def write_curtain_walls_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["wall", "assembly", "panel", "count", "area_ft2", "bays", "rows"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
