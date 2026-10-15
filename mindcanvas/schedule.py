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


# -- floors + roofs ------------------------------------------------------------
FRAMING_ROLES = ("joist", "rim_joist", "blocking", "bridging", "rafter", "roof_joist", "barge_rafter", "ridge",
                 "lookout", "bird_block", "ceiling_joist", "subfascia")
FR_KINDS = ("floor", "roof")


def _fr_drivers(doc, driver_ids):
    if driver_ids is None:
        return [d for d in meta.all_drivers(doc) if meta.get(d, meta.TYPE) in FR_KINDS]
    out = [doc.Objects.FindId(d) for d in driver_ids]
    return [d for d in out if d is not None and meta.get(d, meta.TYPE) in FR_KINDS]


def framing_members(doc, driver_ids=None):
    """Joist / rafter cut list of floors and roofs: one row per role, member and length (1/16")
    with the count and total linear feet."""
    rows = {}
    for d in _fr_drivers(doc, driver_ids):
        for o in meta.parts_of(doc, d.Id):
            role = meta.get(o, meta.ROLE)
            if role not in FRAMING_ROLES:
                continue
            L = _num(o, "length")
            Lr = round(L * 16) / 16.0
            member = meta.get(o, meta.EXTRA_PREFIX + "member") or ""
            try:
                member = json.loads(member) if member.startswith('"') else member
            except ValueError:
                pass
            key = (meta.get(d, meta.TYPE), role, member, Lr)
            r = rows.setdefault(key, {"kind": key[0], "role": role, "member": member, "length": units.format_inches(Lr),
                                      "length_in": Lr, "count": 0, "total_ft": 0.0})
            r["count"] += 1
            r["total_ft"] += L / 12.0
    return [rows[k] for k in sorted(rows, key=lambda k: (k[0], k[1], k[2], -k[3]))]


def format_framing_members(rows):
    lines = ["{:<6} {:<14} {:<34} {:>12} {:>6} {:>9}".format("Kind", "Role", "Member", "Length", "Count", "Total ft")]
    for r in rows:
        lines.append("{:<6} {:<14} {:<34} {:>12} {:>6} {:>9.1f}".format(
            r["kind"], r["role"][:14], r["member"][:34], r["length"], r["count"], r["total_ft"]))
    return "\n".join(lines)


def write_framing_members_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["kind", "role", "member", "length", "length_in", "count", "total_ft"])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def floors_roofs(doc, driver_ids=None):
    """One row per floor / roof: assembly, area, joist or rafter count, member, spacing, longest span,
    roof shape / pitch / ridge and plate heights (inches)."""
    from . import library
    from .kinds import floor as floorkind, roof as roofkind
    lib = library.get()
    out = []
    for d in _fr_drivers(doc, driver_ids):
        kind = meta.get(d, meta.TYPE)
        kmod = floorkind if kind == "floor" else roofkind
        row = {"id": str(d.Id)[:8], "kind": kind, "assembly": meta.get(d, meta.ASSEMBLY)}
        try:
            ctx = kmod.make_context(doc, lib, d, row["assembly"], meta.params(d))
            row.update(kmod.summary(ctx))
        except Exception as ex:
            row["error"] = str(ex)
        out.append(row)
    return out


def format_floors_roofs(rows):
    lines = ["{:<9} {:<6} {:<44} {:>9} {:>7} {:<22} {:>6}  {}".format(
        "Id", "Kind", "Assembly", "Area ft2", "Members", "Member", "o.c.", "Notes")]
    for r in rows:
        if "error" in r:
            lines.append("{:<9} {:<6} {:<44} error: {}".format(r["id"], r["kind"], r["assembly"][:44], r["error"]))
            continue
        n = r.get("joists", r.get("rafters", 0))
        if r["kind"] == "floor":
            note = "span {:.1f} ft, {} blocking rows, {}".format(r["max_span_ft"], r.get("rows", 0), r["system"])
        else:
            note = "{} {}:12, ridge {}, plate {}{}".format(
                r["shape"], r["pitch"], units.format_inches(r["ridge"]) if r.get("ridge") else "-",
                units.format_inches(r["plate"]),
                ", high plate {}".format(units.format_inches(r["high_plate"])) if r.get("high_plate") else "")
        lines.append("{:<9} {:<6} {:<44} {:>9.1f} {:>7} {:<22} {:>6}  {}".format(
            r["id"], r["kind"], r["assembly"][:44], r["area_ft2"], n, r["member"][:22],
            units.format_inches(r["spacing"]), note))
    return "\n".join(lines)
