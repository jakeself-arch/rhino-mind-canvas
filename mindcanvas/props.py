"""Properties: what the inspector (MCInspector, eto/inspector.py) shows and changes for each kind
of assembly.

FIELDS[kind] lists the settings a kind shows: key, label, type (assembly | length | number |
choice | bool) and the choices of a choice. Kinds without an entry show the assembly and detail
level only; ACTIONS[kind] are the buttons that run the full edit commands.

    selected(doc)                     the selected assemblies: drivers, and windows / doors for
                                      their parts (a wall mass selects its wall)
    value(lib, driver, field)         the current value (lengths in inches)
    apply(doc, lib, drivers, field, value, snap)   change it on every driver, rebuild them
"""

from . import engine, masses, meta, units
from .curtainwall import settings as cwsettings
from .kinds import floor as floorkind
from .kinds import stair as stairkind
from .kinds import wall as wallkind
from .openings import core as opcore
from .roofs import shape as rshape

LODS = ("schematic", "design", "detail")
KIND_NAMES = {"wall": ("wall", "walls"), "curtain_wall": ("curtain wall", "curtain walls"),
              "floor": ("floor", "floors"), "roof": ("roof", "roofs"),
              "opening": ("window / door", "windows / doors"), "stair": ("stair", "stairs")}
DEFAULT_REFERENCE = {"wall": "center", "curtain_wall": "glass", "floor": "framing_bottom"}
SNAP_KEYS = ("assembly", "width", "height", "sill", "head")   # opening changes that move the head


class Field(object):
    def __init__(self, key, label, type_, choices=None, doors_only=False):
        self.key, self.label, self.type = key, label, type_
        self.choices = tuple(choices or ())
        self.doors_only = doors_only

    def __repr__(self):
        return "Field({})".format(self.key)


def _assembly(label="Assembly"):
    return Field("assembly", label, "assembly")


def _lod():
    return Field("lod", "Detail level", "choice", LODS)


FIELDS = {
    "wall": [_assembly(), Field("height", "Height", "length"), Field("base_offset", "Base offset", "length"),
             Field("reference", "Location line", "choice", wallkind.REFERENCES),
             Field("flip", "Flip side", "bool"), _lod()],
    "curtain_wall": [_assembly(), Field("height", "Height", "length"),
                     Field("base_offset", "Base offset", "length"),
                     Field("reference", "Location line", "choice", cwsettings.REFERENCES),
                     Field("style", "Style", "choice", cwsettings.STYLES),
                     Field("spacing", "Grid spacing", "length"),
                     Field("flip", "Flip side", "bool"), _lod()],
    "floor": [_assembly(), Field("base_offset", "Elevation", "length"),
              Field("reference", "Elevation is at", "choice", floorkind.REFERENCES), _lod()],
    "roof": [_assembly(), Field("base_offset", "Plate height", "length"),
             Field("shape", "Shape", "choice", rshape.SHAPES), Field("pitch", "Pitch (x in 12)", "number"),
             Field("overhang", "Overhang", "length"), Field("rake", "Rake", "length"),
             Field("flip", "Flip (shed)", "bool"), _lod()],
    "opening": [_assembly("Type"), Field("width", "Width", "length"), Field("height", "Height", "length"),
                Field("sill", "Sill", "length"),
                Field("swing", "Swing", "choice", ("in", "out"), doors_only=True),
                Field("hinge", "Hinge", "choice", ("left", "right"), doors_only=True),
                Field("head", "Head course", "choice", ("none", "soldier", "sailor"))],
    "stair": [_assembly(), Field("height", "Floor to floor", "length"),
              Field("floors", "Floors climbed", "number"), Field("width", "Width", "length"),
              Field("base_offset", "Elevation", "length"),
              Field("side", "Curve on the stair's", "choice", stairkind.SIDES),
              Field("flip", "Up the other way", "bool"),
              Field("laps", "Laps (closed curve)", "number"),
              Field("style", "Style", "choice", stairkind.STYLES),
              Field("max_riser", "Max riser", "length")],
}
GENERIC = [_assembly(), _lod()]

ACTIONS = {
    "wall": [("Layers...", "MCLayers"), ("Framing...", "MCFraming"), ("Joins...", "MCJoin"),
             ("Trim...", "MCTrim"), ("Add window / door", "MCOpening"), ("Section cut", "MCSectionCut")],
    "curtain_wall": [("Grid editor...", "MCCurtainGrid"), ("All settings...", "MCEditCurtainWall"),
                     ("Add door", "MCOpening"), ("Section cut", "MCSectionCut")],
    "floor": [("Span, spacing, framing...", "MCEditFloor"), ("Section cut", "MCSectionCut")],
    "roof": [("Ridge, framing...", "MCEditRoof"), ("Section cut", "MCSectionCut")],
    "opening": [("Snap / remove...", "MCEditOpening")],
    "stair": [("Stair settings...", "MCEditStair"), ("Section cut", "MCSectionCut")],
}


def fields(kind):
    return FIELDS.get(kind, GENERIC)


def kind_name(kind, n=1):
    one, many = KIND_NAMES.get(kind, (kind, kind + "s"))
    return one if n == 1 else many


def kind_label(kind, n):
    return "{} {}".format(n, kind_name(kind, n))


def label(value):
    """'exterior_face' -> 'Exterior face'."""
    s = str(value).replace("_", " ")
    return s[:1].upper() + s[1:]


def assembly_of(doc, obj):
    """The assembly an object stands for: a window / door for its line and parts, else the driver
    (a part selects its assembly, a wall mass its wall); None for anything else."""
    from . import wallmasses
    d = opcore.opening_of(doc, obj) or meta.driver_of(doc, obj)
    if d is None and wallmasses.is_wall_mass(obj):
        d = wallmasses.wall_of(doc, obj)
    return d


def selected(doc):
    """Assemblies of the selected objects (assembly_of), in selection order."""
    out, seen = [], set()
    for o in doc.Objects.GetSelectedObjects(False, False) or []:
        d = assembly_of(doc, o)
        if d is not None and not d.IsDeleted and d.Id not in seen:
            seen.add(d.Id)
            out.append(d)
    return out


def by_kind(drivers):
    """[(kind, [drivers])] in the order the kinds were first selected."""
    groups = []
    for d in drivers:
        k = meta.get(d, meta.TYPE)
        for kk, ds in groups:
            if kk == k:
                ds.append(d)
                break
        else:
            groups.append((k, [d]))
    return groups


def is_door(lib, driver):
    try:
        return opcore.merged_type(lib, meta.get(driver, meta.ASSEMBLY)).get("category") == "door"
    except Exception:
        return False


def settings(lib, driver):
    """Every setting of a driver, merged over its assembly / type defaults."""
    kind = meta.get(driver, meta.TYPE)
    prm = meta.params(driver)
    name = meta.get(driver, meta.ASSEMBLY)
    if kind == "opening":
        t = opcore.merged_type(lib, name, prm)
        s = dict(t)
        s.update(prm)
        s.setdefault("head", t.get("masonry", {}).get("head", "none"))
        return s
    asm = lib.assembly(name)
    if kind == "curtain_wall":
        s = dict(cwsettings.merged(asm, prm))
    elif kind == "roof":
        s = dict(rshape.merged(asm, prm))
    elif kind == "stair":
        s = dict(stairkind.DEFAULTS, floors=1, laps=1)
        s.update(stairkind.settings(asm, prm))
        s.update(prm)
    else:
        s = dict(prm)
    for k, v in prm.items():
        s.setdefault(k, v)
    s.setdefault("height", asm.get("default_height", 120))
    s.setdefault("base_offset", 0)
    s.setdefault("reference", asm.get("default_reference", DEFAULT_REFERENCE.get(kind, "center")))
    s.setdefault("flip", False)
    s.setdefault("lod", "detail")
    return s


def coerce(field, raw):
    """A stored setting as the field's type (None when it cannot be read)."""
    try:
        if field.type == "length":
            return round(units.parse_length(raw), 4)
        if field.type == "number":
            return round(float(raw), 4)
        if field.type == "bool":
            return bool(raw)
        return None if raw is None else str(raw)
    except (TypeError, ValueError):
        return None


def value(lib, driver, field):
    if field.type == "assembly":
        return meta.get(driver, meta.ASSEMBLY)
    try:
        s = settings(lib, driver)
    except Exception:
        return None
    return coerce(field, s.get(field.key))


def common(lib, drivers, field):
    """(value, mixed): the value shared by every driver, or (first value, True)."""
    vals = [value(lib, d, field) for d in drivers]
    first = vals[0] if vals else None
    return first, any(v != first for v in vals[1:])


def apply(doc, lib, drivers, field, new, snap=True):
    """Set one field on every driver (skipping those that already have it); returns BuildResults."""
    todo = [d for d in drivers if value(lib, d, field) != new]
    if not todo:
        return []
    undo = doc.BeginUndoRecord("Mind Canvas: " + field.label)
    try:
        if meta.get(todo[0], meta.TYPE) == "opening":
            return _apply_openings(doc, lib, todo, field, new, snap)
        out = []
        for d in todo:
            d = doc.Objects.FindId(d.Id)
            if d is None or d.IsDeleted:
                continue
            name, prm = meta.get(d, meta.ASSEMBLY), meta.params(d)
            try:
                if field.type == "assembly":
                    out.append(engine.set_assembly(doc, d, new, lib))
                else:
                    out.append(engine.update_params(doc, d, companions(lib, d, field.key, new), lib))
            except Exception:
                meta.write_driver(doc, doc.Objects.FindId(d.Id), meta.get(d, meta.TYPE), name, prm)
                engine.build(doc, d.Id, lib)    # back to how it was
                raise
        return out
    finally:
        doc.EndUndoRecord(undo)


def companions(lib, driver, key, new):
    """The change plus what it needs to build: a flat roof turned into a shed / gable gets a
    6 in 12 pitch when it has none; a stair going up the other way swaps its side too, so it stays
    where it is (as MCEditStair's Flip)."""
    changes = {key: new}
    if meta.get(driver, meta.TYPE) == "stair" and key == "flip":
        side = settings(lib, driver).get("side", "left")
        changes["side"] = "right" if side == "left" else "left"
    if meta.get(driver, meta.TYPE) == "roof" and key == "shape" and new != "flat":
        try:
            pitch = float(settings(lib, driver).get("pitch") or 0)
        except (TypeError, ValueError):
            pitch = 0.0
        if pitch <= 0:
            changes["pitch"] = 6.0
    return changes


def _apply_openings(doc, lib, ops, field, new, snap):
    hosts = {}
    with engine._quiet():
        for o in ops:
            o = doc.Objects.FindId(o.Id)
            if o is None or o.IsDeleted:
                continue
            changes = {}
            if field.type == "assembly":
                opcore.set_type(doc, o, new)
                o = doc.Objects.FindId(o.Id)
                masses.set_type(doc, o, new)
            else:
                changes[field.key] = new
            h = opcore.host_of(doc, o)
            if snap and h is not None and field.key in SNAP_KEYS:
                s = settings(lib, o)
                full = dict((k, units.parse_length(s[k])) for k in ("width", "height", "sill"))
                full.update(changes)
                out, delta = engine.snap_to_coursing(doc, h, meta.get(o, meta.ASSEMBLY), full, lib)
                if delta:
                    for k in ("height", "sill"):
                        if out.get(k) != full.get(k):
                            changes[k] = out[k]
            if changes:
                opcore.update(doc, o, changes)
            if h is not None:
                hosts[str(h.Id)] = h
    return [engine.build(doc, h.Id, lib) for h in hosts.values()]
