"""Layer = assembly (MCAssemblyLayers): a layer per library assembly; put geometry on it and it
becomes that assembly.

    MC Assemblies::Walls::<assembly>          (also Curtain walls, Floors, Roofs, Stairs)

Each layer carries user text mc.kind / mc.assembly (its name is only a label, so assembly names
with quotes or slashes still work) and the color of the assembly's main material.

Watched (enable(), turned on by MCSetup and MCAssemblyLayers): an object added to such a layer
(drawn, pasted, copied, imported) or moved onto it (Layer panel, ChangeLayer, Match Properties):

    a curve on a wall / curtain-wall layer          -> a wall / curtain wall (engine.create)
    a closed curve on a floor / roof layer          -> a floor / roof (its elevation as drawn)
    a curve on a stair layer                        -> a stair (default settings: the curve is
                                                       its left side, up from the curve's start)
    a closed solid on a wall layer                  -> a wall mass (wallmasses.make)
    a driver of that kind (or its wall mass)        -> takes the layer's assembly
                                                       (engine.set_assembly)

The driver then goes to its usual layer (MindCanvas::_Drivers / _Masses), so the assembly layers
stay empty: they are an inbox. Anything else on them is left alone (one note on the command line).
Nothing happens during Undo / Redo or while Mind Canvas itself builds (live.quiet).
"""

import sys

import System
import Rhino
import scriptcontext

from . import docutil, meta

ROOT = "MC Assemblies"
GROUPS = [("wall", "Walls"), ("curtain_wall", "Curtain walls"), ("floor", "Floors"), ("roof", "Roofs"),
          ("stair", "Stairs")]
KIND_KEY = "mc.kind"
ASM_KEY = "mc.assembly"
STATE_KEY = "mindcanvas.laylink"
MODULE = "mindcanvas.laylink"
BAD = '{}[]()<>:;*?|\\"'


def _mod():
    return sys.modules.get(MODULE) or __import__(MODULE, fromlist=["x"])


def layer_name(assembly):
    """A valid Rhino layer name for an assembly (the layer's user text keeps the real name)."""
    s = assembly.replace('"', "in")                 # 6" Metal Stud -> 6in Metal Stud
    s = "".join("-" if c in BAD else c for c in s).strip()
    s = s.replace("--", "-")
    while s and s[0] in "-. ":
        s = s[1:]
    return s or "Assembly"


def main_color(lib, kind, name):
    """The color of an assembly's main material: a wall's exterior layer (the first one not a
    void / membrane), a floor's / roof's top layer; curtain walls: glass; stairs: their material."""
    asm = lib.assembly(name)
    if kind == "curtain_wall":
        return (120, 165, 200)
    if kind == "stair":
        m = lib.data["materials"].get(asm.get("material") or "Concrete")
        return tuple(m["color"]) if m and m.get("color") else (160, 160, 160)
    for spec in asm.get("layers") or []:
        try:
            spec = lib.resolve_layer(spec)
        except Exception:
            continue
        if spec.get("component") in ("void", "membrane"):
            continue
        m = lib.data["materials"].get(spec.get("material")) if spec.get("material") else None
        if m and m.get("color"):
            return tuple(m["color"])
    return (160, 160, 160)


def ensure_layers(doc, lib):
    """Create / refresh the assembly layers. Returns {(kind, assembly): layer index}."""
    out = {}
    for kind, title in GROUPS:
        for name in lib.assemblies(kind):
            base = "{}::{}::{}".format(ROOT, title, layer_name(name))
            path, k = base, 1
            while True:            # two names that clean up alike get their own layers
                found = doc.Layers.FindByFullPath(path, -1)
                other = doc.Layers[found].GetUserString(ASM_KEY) if found >= 0 else None
                if found < 0 or not other or other == name:
                    break
                k += 1
                path = "{} ({})".format(base, k)
            idx = docutil.ensure_layer(doc, path, main_color(lib, kind, name))
            layer = doc.Layers[idx]
            if layer.GetUserString(KIND_KEY) != kind or layer.GetUserString(ASM_KEY) != name:
                layer.SetUserString(KIND_KEY, kind)
                layer.SetUserString(ASM_KEY, name)
                doc.Layers.Modify(layer, idx, True)
            out[(kind, name)] = idx
    return out


def assembly_of_layer(doc, index):
    """(kind, assembly) of an assembly layer, else None."""
    if index is None or index < 0 or index >= doc.Layers.Count:
        return None
    layer = doc.Layers[index]
    kind = layer.GetUserString(KIND_KEY)
    name = layer.GetUserString(ASM_KEY)
    return (kind, name) if kind and name else None


# -- watching ---------------------------------------------------------------------------------------
def _state():
    st = scriptcontext.sticky.get(STATE_KEY)
    if st is None:
        st = {"queue": [], "busy": False, "hooks": None}
        scriptcontext.sticky[STATE_KEY] = st
    return st


def is_on():
    st = scriptcontext.sticky.get(STATE_KEY)
    return bool(st and st["hooks"])


def _quiet_now(doc):
    live = sys.modules.get("mindcanvas.live")
    ls = live._state() if live is not None else None
    return doc is None or doc.UndoActive or getattr(doc, "RedoActive", False) or bool(ls and ls["busy"])


def enable():
    st = _state()
    if st["hooks"] is not None:
        return st

    def on_add(sender, e):
        try:
            _mod().queue_if_linked(e.TheObject.Document or Rhino.RhinoDoc.ActiveDoc, e.TheObject, e.ObjectId)
        except Exception as ex:
            print("Mind Canvas layers (add): {}".format(ex))

    def on_modify(sender, e):
        try:
            if e.OldAttributes.LayerIndex != e.NewAttributes.LayerIndex:
                o = e.RhinoObject
                _mod().queue_if_linked(o.Document or Rhino.RhinoDoc.ActiveDoc, o, o.Id, e.NewAttributes.LayerIndex)
        except Exception as ex:
            print("Mind Canvas layers (modify): {}".format(ex))

    def on_idle(sender, e):
        _mod().process()

    st["hooks"] = (on_add, on_modify, on_idle)
    Rhino.RhinoDoc.AddRhinoObject += on_add
    Rhino.RhinoDoc.ModifyObjectAttributes += on_modify
    Rhino.RhinoApp.Idle += on_idle
    return st


def disable():
    st = scriptcontext.sticky.get(STATE_KEY)
    if not st or st["hooks"] is None:
        return
    on_add, on_modify, on_idle = st["hooks"]
    Rhino.RhinoDoc.AddRhinoObject -= on_add
    Rhino.RhinoDoc.ModifyObjectAttributes -= on_modify
    Rhino.RhinoApp.Idle -= on_idle
    st["hooks"] = None


def queue_if_linked(doc, obj, oid, layer_index=None):
    st = _state()
    if st["busy"] or _quiet_now(doc):
        return
    if layer_index is None:
        layer_index = obj.Attributes.LayerIndex
    if assembly_of_layer(doc, layer_index) is not None:
        st["queue"].append((doc.RuntimeSerialNumber, oid))


def process():
    """Turn the queued objects into assemblies (Idle; tests call it directly). Returns the
    [(object id, what happened)] list."""
    st = _state()
    if not st["queue"] or st["busy"]:
        return []
    items, st["queue"] = st["queue"], []
    st["busy"] = True
    done = []
    try:
        seen = set()
        for sn, oid in items:
            if (sn, oid) in seen:
                continue
            seen.add((sn, oid))
            doc = Rhino.RhinoDoc.FromRuntimeSerialNumber(sn)
            if doc is None:
                continue
            obj = doc.Objects.FindId(oid)
            if obj is None or obj.IsDeleted:
                continue
            link = assembly_of_layer(doc, obj.Attributes.LayerIndex)
            if link is None:
                continue
            undo = doc.BeginUndoRecord("Mind Canvas: layer -> assembly")
            try:
                what = convert(doc, obj, link[0], link[1])
            except Exception as ex:
                what = "failed: {}".format(ex)
            finally:
                doc.EndUndoRecord(undo)
            done.append((oid, what))
            Rhino.RhinoApp.WriteLine("Mind Canvas: {} ({})".format(what, link[1]))
            doc.Views.Redraw()
    finally:
        st["busy"] = False
    return done


def _home(doc, obj):
    """Back to the layer Mind Canvas keeps it on."""
    from . import masses
    obj = doc.Objects.FindId(obj.Id)
    attrs = obj.Attributes.Duplicate()
    attrs.LayerIndex = masses.ensure_layer(doc) if meta.is_mass(obj) else docutil.ensure_driver_layer(doc)
    doc.Objects.ModifyAttributes(obj, attrs, True)


def convert(doc, obj, kind, name):
    """What the object on an assembly layer becomes (see the module doc). Returns a short note."""
    from . import engine, library, masses, wallmasses
    lib = library.get()
    if name not in lib.assemblies(kind):
        return "the layer's assembly '{}' is not in the library; left as is".format(name)
    G = Rhino.Geometry
    if wallmasses.is_wall_mass(obj):
        if kind != "wall":
            _home(doc, obj)
            return "a wall mass cannot be a {}; put back".format(kind)
        w = wallmasses.wall_of(doc, obj)
        _home(doc, obj)
        if w is not None:
            engine.set_assembly(doc, w, name, lib)
        return "wall mass -> {}".format(name)
    if meta.is_driver(obj):
        have = meta.get(obj, meta.TYPE)
        _home(doc, obj)
        if have != kind:
            return "a {} cannot take a {} assembly; put back".format(have, kind)
        if meta.get(obj, meta.ASSEMBLY) != name:
            engine.set_assembly(doc, doc.Objects.FindId(obj.Id), name, lib)
        return "{} -> {}".format(have, name)
    if meta.get(obj, meta.KIND):
        return "a Mind Canvas part / mass is left as is"
    geom = obj.Geometry
    if isinstance(geom, G.Curve):
        if kind in ("floor", "roof") and not geom.IsClosed:
            return "a {} needs a closed curve; left as is".format(kind)
        engine.create(doc, obj, name, {}, lib)
        return "curve -> {}".format(kind.replace("_", " "))
    if kind == "wall" and masses.is_solid_candidate(obj):
        wallmasses.make(doc, obj, name, {}, lib)
        return "solid -> wall mass"
    return "a {} on a {} layer is not a curve{}; left as is".format(
        obj.ObjectType, kind.replace("_", " "), " or a closed solid" if kind == "wall" else "")
