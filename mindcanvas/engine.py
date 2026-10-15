"""Build, rebuild and delete assemblies.

    create(doc, curve_obj, assembly_name, params)  turn a curve into a driver + build
    build(doc, driver_id)                          (re)generate a driver's parts
    delete_parts(doc, driver_id)
    rebuild_all(doc)
    update_params(doc, driver_obj, changes)        merge param changes + rebuild
    set_assembly(doc, driver_obj, assembly_name)
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
    def __init__(self, driver_id, part_ids, warnings, seconds):
        self.driver_id = driver_id
        self.part_ids = part_ids
        self.warnings = warnings
        self.seconds = seconds

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


def build(doc, driver_id, lib=None):
    """Regenerate a driver's parts. Parts are computed first, so a failure
    leaves the previous parts untouched."""
    t0 = time.time()
    lib = lib or library.get()
    driver_id = _guid(driver_id)
    obj = doc.Objects.FindId(driver_id)
    if not meta.is_driver(obj):
        raise ValueError("Object {} is not a Mind Canvas driver".format(driver_id))
    kind = meta.get(obj, meta.TYPE, "wall")
    kmod = kinds.get(kind)
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
    warnings = list(ctx.warnings) + list(lib.warnings)
    if not tolerance_ok(doc):
        warnings.insert(0, "Model tolerance is coarser than 1/256\"; thin layers may be "
                           "missing. Run MCSetup.")
    return BuildResult(driver_id, ids, warnings, time.time() - t0)


def rebuild_all(doc, kind=None, lib=None):
    lib = lib or library.get()
    return [build(doc, d.Id, lib) for d in meta.all_drivers(doc, kind)]


def update_params(doc, driver_obj, changes, lib=None):
    prm = meta.params(driver_obj)
    for k, v in changes.items():
        if v is None:
            prm.pop(k, None)
        else:
            prm[k] = v
    meta.write_driver(doc, driver_obj, meta.get(driver_obj, meta.TYPE), meta.get(driver_obj, meta.ASSEMBLY), prm)
    return build(doc, driver_obj.Id, lib)


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
    prm.pop("layers", None)  # a per-wall stack belonged to the old assembly
    meta.write_driver(doc, driver_obj, kind, assembly_name, prm)
    return build(doc, driver_obj.Id, lib)


def orphan_parts(doc):
    found = doc.Objects.FindByUserString(meta.KIND, meta.PART_KIND, True) or []
    out = []
    for o in found:
        did = meta.get(o, meta.DRIVER)
        d = doc.Objects.FindId(System.Guid(did)) if did else None
        if d is None or d.IsDeleted:
            out.append(o)
    return out
