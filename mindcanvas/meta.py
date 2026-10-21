"""User-text metadata linking driver curves to their generated parts."""

import json

import System

KIND = "mc.kind"            # "driver" | "part"
ASSEMBLY = "mc.assembly"    # assembly name (driver)
PARAMS = "mc.params"        # JSON params (driver)
TYPE = "mc.type"            # assembly kind: "wall", ... (driver)
DRIVER = "mc.driver"        # driver id (part)
LAYER = "mc.layer"          # assembly layer name, e.g. "Framing" (part)
ROLE = "mc.role"            # "stud", "plate", "brick", "solid", ... (part)
MATERIAL = "mc.material"    # material name (part)
EXTRA_PREFIX = "mc.x."      # free-form per-part data, e.g. mc.x.length
JOINED = "mc.joined"        # ids of the assemblies joined to this one at its last build (driver)
HOME = "mc.home"            # id of the layer a curve / solid was on before Mind Canvas moved it

DRIVER_KIND = "driver"
PART_KIND = "part"
MASS_KIND = "mass"          # a solid that controls drivers (mindcanvas/masses.py)


def get(obj, key, default=None):
    v = obj.Attributes.GetUserString(key)
    return default if v is None or v == "" else v


def is_driver(obj):
    return obj is not None and get(obj, KIND) == DRIVER_KIND


def is_part(obj):
    return obj is not None and get(obj, KIND) == PART_KIND


def is_mass(obj):
    return obj is not None and get(obj, KIND) == MASS_KIND


def params(obj):
    raw = get(obj, PARAMS)
    return json.loads(raw) if raw else {}


def write_driver(doc, obj, kind, assembly, prm):
    attrs = obj.Attributes.Duplicate()
    attrs.SetUserString(KIND, DRIVER_KIND)
    attrs.SetUserString(TYPE, kind)
    attrs.SetUserString(ASSEMBLY, assembly)
    attrs.SetUserString(PARAMS, json.dumps(prm, sort_keys=True))
    doc.Objects.ModifyAttributes(obj, attrs, True)


def remember_home(doc, attrs):
    """Before Mind Canvas moves a curve / solid to its own layer: keep the layer it is on, so a
    released object (strip) goes back there. The first home is kept."""
    if not attrs.GetUserString(HOME) and 0 <= attrs.LayerIndex < doc.Layers.Count:
        attrs.SetUserString(HOME, str(doc.Layers[attrs.LayerIndex].Id))


def strip(doc, obj, layer_index=None):
    """Make a driver / mass a plain object again: every mc.* user text removed, on layer_index
    (when given). Returns the object."""
    attrs = obj.Attributes.Duplicate()
    keys = attrs.GetUserStrings()
    for k in list(keys.AllKeys) if keys is not None else []:
        if k and k.startswith("mc."):
            attrs.DeleteUserString(k)
    if layer_index is not None and layer_index >= 0:
        attrs.LayerIndex = layer_index
    doc.Objects.ModifyAttributes(obj, attrs, True)
    return doc.Objects.FindId(obj.Id)


def driver_of(doc, obj):
    """The driver object for a driver or a part, else None."""
    if is_driver(obj):
        return obj
    if is_part(obj):
        did = get(obj, DRIVER)
        if did:
            return doc.Objects.FindId(System.Guid(did))
    return None


def parts_of(doc, driver_id):
    found = doc.Objects.FindByUserString(DRIVER, str(driver_id), True)
    return list(found) if found else []


def all_drivers(doc, kind=None):
    found = doc.Objects.FindByUserString(KIND, DRIVER_KIND, True)
    out = list(found) if found else []
    if kind:
        out = [o for o in out if get(o, TYPE) == kind]
    return out


def joined_ids(obj):
    raw = get(obj, JOINED)
    return set(x for x in raw.split(",") if x) if raw else set()


def write_joined(doc, obj, ids):
    """Remember the joined assemblies (rebuilt when this one changes or is deleted)."""
    raw = ",".join(sorted(ids))
    if (get(obj, JOINED) or "") == raw:
        return
    attrs = obj.Attributes.Duplicate()
    attrs.SetUserString(JOINED, raw)
    doc.Objects.ModifyAttributes(obj, attrs, True)
