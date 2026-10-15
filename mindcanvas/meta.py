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

DRIVER_KIND = "driver"
PART_KIND = "part"


def get(obj, key, default=None):
    v = obj.Attributes.GetUserString(key)
    return default if v is None or v == "" else v


def is_driver(obj):
    return obj is not None and get(obj, KIND) == DRIVER_KIND


def is_part(obj):
    return obj is not None and get(obj, KIND) == PART_KIND


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
