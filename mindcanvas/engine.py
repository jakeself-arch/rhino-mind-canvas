"""Build, rebuild and delete assemblies.

    create(doc, curve_obj, assembly_name, params)  turn a curve into a driver + build
    build(doc, driver_id)                          (re)generate a driver's parts
    delete_parts(doc, driver_id)
    rebuild_all(doc)
    update_params(doc, driver_obj, changes)        merge param changes + rebuild
    set_assembly(doc, driver_obj, assembly_name)
    add_opening(doc, host_obj, type_name, params, point)   window / door in a wall + rebuild
    update_opening(doc, opening_obj, changes, type_name)
    delete_openings(doc, host_id)

Openings are drivers of a HOSTED kind: build(opening) re-reads its line and builds the host.
Opening masses (mindcanvas/masses.py) write opening params; after every host build the masses
with one opening follow it (masses.follow). Wall masses (mindcanvas/wallmasses.py) write wall
drivers; a mass-driven wall's mass follows its base / height / moved line (wallmasses.follow), and
flip / reference / layer edits re-derive it from its mass (wallmasses.after_params).

Joins (mindcanvas/joins): an assembly's geometry depends on the drivers joined to it (walls at an
L / T, the floors and roofs over walls). build() rebuilds those partners afterwards - the ones
joined now and the ones joined at the last build (user text mc.joined) - so a move that breaks a
join cleans up the other side too. Partners are rebuilt without cascading further.
"""

import json
import time

import System
import Rhino

from . import docutil, kinds, library, meta, units

UNASSIGNED = "Unassigned"

# Detailed assemblies contain 1/32" membranes and 0.03" steel; anything
# coarser than this tolerance silently drops or distorts parts.
MAX_TOLERANCE_IN = 1.0 / 256.0
SETUP_TOLERANCE_IN = 0.001


def tolerance_ok(doc):
    return doc.ModelAbsoluteTolerance <= units.to_model(doc, MAX_TOLERANCE_IN) * 1.0001


def setup_document(doc):
    """Tighten tolerances for assembly-level detail. Units are left alone."""
    doc.ModelAbsoluteTolerance = units.to_model(doc, SETUP_TOLERANCE_IN)
    doc.ModelAngleToleranceDegrees = 0.1
    docutil.ensure_driver_layer(doc)


class BuildResult(object):
    def __init__(self, driver_id, part_ids, warnings, seconds, partners=None):
        self.driver_id = driver_id
        self.part_ids = part_ids
        self.warnings = warnings
        self.seconds = seconds
        self.partners = set(partners or ())   # ids joined now or at the previous build
        self.joined = []                      # BuildResults of the partners rebuilt with it

    def __repr__(self):
        return "<BuildResult {} parts in {:.2f}s, {} warnings>".format(
            len(self.part_ids), self.seconds, len(self.warnings))


def _guid(x):
    return x if isinstance(x, System.Guid) else System.Guid(str(x))


def _group_name(kind, driver_id):
    return "MC {} {}".format(kind, str(driver_id)[:8])


def create(doc, curve_obj, assembly_name, params=None, lib=None):
    lib = lib or library.get()
    assembly = lib.assembly(assembly_name)
    kind = assembly.get("kind", "wall")
    prm = dict(kinds.get(kind).DEFAULTS)
    prm.update(params or {})
    meta.write_driver(doc, curve_obj, kind, assembly_name, prm)
    obj = doc.Objects.FindId(curve_obj.Id)
    attrs = obj.Attributes.Duplicate()
    attrs.LayerIndex = docutil.ensure_driver_layer(doc)
    doc.Objects.ModifyAttributes(obj, attrs, True)
    return build(doc, curve_obj.Id, lib)


def delete_parts(doc, driver_id):
    n = 0
    for obj in meta.parts_of(doc, driver_id):
        if doc.Objects.Delete(obj, True):
            n += 1
    return n


def _bake(doc, ctx, part, driver_id, group_index):
    attrs = Rhino.DocObjects.ObjectAttributes()
    attrs.LayerIndex = ctx.material_layer(part.material or UNASSIGNED)
    attrs.SetUserString(meta.KIND, meta.PART_KIND)
    attrs.SetUserString(meta.DRIVER, str(driver_id))
    attrs.SetUserString(meta.LAYER, part.layer_name or "")
    attrs.SetUserString(meta.ROLE, part.role or "")
    attrs.SetUserString(meta.MATERIAL, part.material or UNASSIGNED)
    for k, v in part.extra.items():
        attrs.SetUserString(meta.EXTRA_PREFIX + k, v if isinstance(v, str) else json.dumps(v))
    attrs.AddToGroup(group_index)
    if part.block is not None:
        return doc.Objects.AddInstanceObject(part.block, part.xform, attrs)
    return doc.Objects.Add(part.geometry, attrs)


def build(doc, driver_id, lib=None, sync=True, joined=True):
    """Regenerate a driver's parts. Parts are computed first, so a failure
    leaves the previous parts untouched. For an opening: re-read its line (sync)
    and build its host. joined: also rebuild the assemblies joined to it."""
    t0 = time.time()
    lib = lib or library.get()
    driver_id = _guid(driver_id)
    obj = doc.Objects.FindId(driver_id)
    if not meta.is_driver(obj):
        raise ValueError("Object {} is not a Mind Canvas driver".format(driver_id))
    kind = meta.get(obj, meta.TYPE, "wall")
    kmod = kinds.get(kind)
    if getattr(kmod, "HOSTED", False):
        host = kmod.host_of(doc, obj)
        if host is None:
            return BuildResult(driver_id, [], ["Opening has no host; delete it or run MCPurge."],
                               time.time() - t0)
        if sync:
            kmod.sync(doc, obj, host)
        return build(doc, host.Id, lib, joined=joined)
    ctx = kmod.make_context(doc, lib, obj, meta.get(obj, meta.ASSEMBLY), meta.params(obj))
    parts = kmod.build(ctx)

    delete_parts(doc, driver_id)
    gidx = docutil.ensure_group(doc, _group_name(kind, driver_id))
    ids = []
    for p in parts:
        pid = _bake(doc, ctx, p, driver_id, gidx)
        if pid != System.Guid.Empty:
            ids.append(pid)
        else:
            ctx.warn("A '{}' part on layer '{}' could not be added.".format(p.role, p.layer_name))
    _place_opening_lines(doc, ctx)
    _follow_masses(doc, ctx)
    if kind == "wall":
        _follow_wall_mass(doc, ctx, driver_id)
    now = set(getattr(ctx, "join_partners", None) or ())
    now.discard(str(driver_id))
    partners = now | meta.joined_ids(obj)
    with _quiet():
        meta.write_joined(doc, doc.Objects.FindId(driver_id), now)
    warnings = list(ctx.warnings) + list(lib.warnings)
    if not tolerance_ok(doc):
        warnings.insert(0, "Model tolerance is coarser than 1/256\"; thin layers may be "
                           "missing. Run MCSetup.")
    result = BuildResult(driver_id, ids, warnings, time.time() - t0, partners)
    if joined:
        rebuild_partners(doc, [result], lib, skip={str(driver_id)})
    return result


def rebuild_partners(doc, results, lib=None, skip=()):
    """Rebuild (without cascading) the joined partners of the given build results that are not
    in `skip`; their results are appended to the first result's `joined`."""
    lib = lib or library.get()
    seen = set(skip) | set(str(r.driver_id) for r in results)
    todo = sorted(set(p for r in results for p in r.partners) - seen)
    out = []
    for pid in todo:
        try:
            o = doc.Objects.FindId(System.Guid(pid))
        except Exception:
            o = None
        if o is None or o.IsDeleted or not meta.is_driver(o) or hosted_kind(o):
            continue
        try:
            out.append(build(doc, o.Id, lib, joined=False))
        except Exception as ex:
            if results:
                results[0].warnings.append("A joined assembly could not be rebuilt: {}".format(ex))
    if results:
        results[0].joined.extend(out)
    return out


def _place_opening_lines(doc, ctx):
    """Move each opening's line to where its host put it (follows host curve edits)."""
    from . import live
    tol = doc.ModelAbsoluteTolerance
    with live.quiet():
        for op in getattr(ctx, "openings", None) or []:
            line = op.driver_line()
            cur = op.obj.Geometry
            if (isinstance(cur, Rhino.Geometry.Curve) and cur.PointAtStart.DistanceTo(line.PointAtStart) < tol
                    and cur.PointAtEnd.DistanceTo(line.PointAtEnd) < tol):
                continue
            doc.Objects.Replace(op.id, line)


def _follow_masses(doc, ctx):
    if not getattr(ctx, "openings", None):
        return
    from . import masses
    try:
        masses.follow(doc, ctx)
    except Exception as ex:
        ctx.warn("Opening masses could not follow their openings: {}".format(ex))


def _follow_wall_mass(doc, ctx, driver_id):
    from . import wallmasses
    try:
        wallmasses.follow(doc, ctx, doc.Objects.FindId(driver_id))
    except Exception as ex:
        ctx.warn("The wall mass could not follow its wall: {}".format(ex))


def hosted_kind(obj):
    return getattr(kinds.KINDS.get(meta.get(obj, meta.TYPE, "wall")), "HOSTED", False)


def rebuild_all(doc, kind=None, lib=None):
    lib = lib or library.get()
    out = [build(doc, d.Id, lib, joined=False) for d in meta.all_drivers(doc, kind) if not hosted_kind(d)]
    if kind is not None:
        out += rebuild_partners(doc, out, lib)
    return out


def build_many(doc, drivers, lib=None):
    """Build drivers (hosted ones through their host), each host once."""
    lib = lib or library.get()
    out, seen = [], set()
    for d in drivers:
        if hosted_kind(d):
            kmod = kinds.get(meta.get(d, meta.TYPE))
            host = kmod.host_of(doc, d)
            if host is None or str(host.Id) in seen:
                continue
            kmod.sync(doc, d, host)
            d = host
        if str(d.Id) in seen:
            continue
        seen.add(str(d.Id))
        out.append(build(doc, d.Id, lib, joined=False))
    return out + rebuild_partners(doc, out, lib)


# -- openings -----------------------------------------------------------------
def add_opening(doc, host_obj, type_name, params=None, point=None, lib=None):
    """Add a window / door to a host (point: where along it) and rebuild the host.
    Returns (opening object, BuildResult)."""
    from .openings import core
    lib = lib or library.get()
    with _quiet():
        op = core.create(doc, host_obj, type_name, params, point, lib)
    r = build(doc, host_obj.Id, lib)
    return doc.Objects.FindId(op.Id), r


def snap_to_coursing(doc, host_obj, type_name, params, lib=None):
    """Move a window (its sill; a door: its height) so its head + sealant joint lands on the
    nearest bed joint of the host's brick (exterior brick first, else any masonry layer).
    Returns (params, delta inches); delta 0.0 when the host has no brick or it already fits."""
    from .components import masonry
    from .openings import core
    lib = lib or library.get()
    if meta.get(host_obj, meta.TYPE) != "wall":
        return dict(params), 0.0
    kmod = kinds.get("wall")
    ctx = kmod.make_context(doc, lib, host_obj, meta.get(host_obj, meta.ASSEMBLY), meta.params(host_obj))
    bands = [b for b in ctx.bands if b.component == "masonry"]
    if not bands:
        return dict(params), 0.0
    ext = [b for b in bands if masonry.exposed_side(ctx, b) > 0]
    v = masonry.layout(ctx, max(ext or bands, key=lambda b: b.d_ext))
    if len(v.courses) < 2:
        return dict(params), 0.0
    t = core.merged_type(lib, type_name, params)
    sill = units.parse_length(params.get("sill", t["sill"]))
    height = units.parse_length(params.get("height", t["height"]))
    gap = units.parse_length(t["joint"] if ext else t["shim"])
    target = ctx.base_z + (sill + height + gap) * ctx.s
    best = min((c.z for c in v.courses[1:]), key=lambda z: abs(z - target))
    delta = (best - target) / ctx.s
    if abs(delta) < 1.0 / 64:
        return dict(params), 0.0
    out = dict(params)
    if t.get("category") == "door" or sill + delta < 0:
        out["height"] = round(height + delta, 4)
    else:
        out["sill"] = round(sill + delta, 4)
    return out, delta


def update_opening(doc, op_obj, changes=None, type_name=None, lib=None):
    from .openings import core
    with _quiet():
        if type_name:
            from . import masses
            core.set_type(doc, op_obj, type_name)
            op_obj = doc.Objects.FindId(op_obj.Id)
            masses.set_type(doc, op_obj, type_name)
        if changes:
            core.update(doc, op_obj, changes)
    return build(doc, op_obj.Id, lib, sync=False)


def delete_openings(doc, host_id):
    """Delete a host's openings, and their masses when no other wall uses them."""
    from . import masses
    from .openings import core
    n = 0
    mass_ids = []
    with _quiet():
        for o in core.hosted(doc, host_id):
            mid = meta.get(o, masses.MASS)
            if doc.Objects.Delete(o, True):
                n += 1
                if mid:
                    mass_ids.append(mid)
    if mass_ids:
        masses.delete_unused(doc, mass_ids)
    return n


def orphan_openings(doc):
    from .openings import core
    return [o for o in meta.all_drivers(doc, core.KIND) if core.host_of(doc, o) is None]


def _quiet():
    from . import live
    return live.quiet()


def update_params(doc, driver_obj, changes, lib=None):
    prm = meta.params(driver_obj)
    old = dict(prm)
    for k, v in changes.items():
        if v is None:
            prm.pop(k, None)
        else:
            prm[k] = v
    meta.write_driver(doc, driver_obj, meta.get(driver_obj, meta.TYPE), meta.get(driver_obj, meta.ASSEMBLY), prm)
    r = build(doc, driver_obj.Id, lib)
    return _after_wall_params(doc, driver_obj, old, prm, lib) or r


def _after_wall_params(doc, driver_obj, old, new, lib, force=False):
    """A mass-driven wall: flip / reference / thickness changes re-derive it from its mass."""
    if meta.get(driver_obj, meta.TYPE) != "wall":
        return None
    from . import wallmasses
    return wallmasses.after_params(doc, driver_obj.Id, old, new, lib, force)


def set_override(doc, driver_obj, layer_name, key, value, lib=None):
    prm = meta.params(driver_obj)
    ov = prm.setdefault("overrides", {}).setdefault(layer_name, {})
    if value is None:
        ov.pop(key, None)
    else:
        ov[key] = value
    return update_params(doc, driver_obj, {"overrides": prm["overrides"]}, lib)


def set_layers(doc, driver_obj, layers, lib=None):
    """Give one wall its own layer stack (None = back to the assembly's)."""
    return update_params(doc, driver_obj, {"layers": layers or None}, lib)


def set_assembly(doc, driver_obj, assembly_name, lib=None):
    lib = lib or library.get()
    kind = lib.assembly(assembly_name).get("kind", "wall")
    prm = meta.params(driver_obj)
    old = dict(prm)
    prm.pop("layers", None)  # a per-wall stack belonged to the old assembly
    meta.write_driver(doc, driver_obj, kind, assembly_name, prm)
    r = build(doc, driver_obj.Id, lib)
    return _after_wall_params(doc, driver_obj, old, prm, lib, force=True) or r


def orphan_parts(doc):
    found = doc.Objects.FindByUserString(meta.KIND, meta.PART_KIND, True) or []
    out = []
    for o in found:
        did = meta.get(o, meta.DRIVER)
        d = doc.Objects.FindId(System.Guid(did)) if did else None
        if d is None or d.IsDeleted:
            out.append(o)
    return out


def rebuild_as(doc, driver_obj, assembly_name, params, lib=None):
    """Give a driver an assembly and a whole set of params in one rebuild (MCMatch)."""
    lib = lib or library.get()
    kind = lib.assembly(assembly_name).get("kind", "wall")
    old = meta.params(driver_obj)
    meta.write_driver(doc, driver_obj, kind, assembly_name, params)
    r = build(doc, driver_obj.Id, lib)
    return _after_wall_params(doc, driver_obj, old, params, lib, force=True) or r
