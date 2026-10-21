"""MCEntourage: place 3D entourage from the model library (library/entourage): people, trees,
plants, vehicles, furniture, kitchen & bath, lighting, site. A ghost of the model follows the
cursor; click points to place (Enter to finish).

People turn to face the view; with Aim=Yes a second click sets where the front faces (vehicles:
where the nose points); otherwise Turn (degrees) or RandomTurn sets it.

Options: Category, Model (a list of the category), Library (the picture window,
MCEntourageLibrary), Height (0 = the library size), RandomModel (each click a different model of
the same group: a row of different trees), RandomTurn, Turn, Aim, Mirror, Color (Model = the
OBJ colours, Gray = the layer colour), and the actions FaceView (turn models to the current view),
Swap (selected models become the current one, same place) and Import (add your own OBJ file).
"""

import math
import os
import random

import Rhino
import scriptcontext
import System

from .. import library
from ..entourage import catalog, place
from . import ui

RI = Rhino.Input
G = Rhino.Geometry
STICKY = "mindcanvas.entourage.settings"
GHOST = System.Drawing.Color.FromArgb(90, 90, 90)
GHOST_MAX_TRIS = 8000


def settings():
    return dict(scriptcontext.sticky.get(STICKY) or {})


def save_settings(st):
    scriptcontext.sticky[STICKY] = st


def current(lib, st=None):
    st = st or settings()
    ns = catalog.names(lib)
    name = st.get("name")
    if name in ns:
        return name
    cat = st.get("category")
    in_cat = catalog.names(lib, cat) if cat else []
    return (in_cat or ns or [None])[0]


def set_current(name):
    st = settings()
    st["name"] = name
    lib = library.get()
    if name in catalog.names(lib):
        st["category"] = catalog.entry(lib, name).get("category")
    save_settings(st)


# -- selection helpers ----------------------------------------------------------------------
def _select_models(prompt, allow_all=True):
    doc = ui.doc()
    go = RI.Custom.GetObject()
    go.SetCommandPrompt(prompt + (" (Enter for all)" if allow_all else ""))
    go.SubObjectSelect = False
    go.EnablePreSelect(True, True)
    go.AcceptNothing(allow_all)
    go.SetCustomGeometryFilter(RI.Custom.GetObjectGeometryFilter(lambda o, g, ci: place.is_entourage(o)))
    res = go.GetMultiple(1, 0)
    if res == RI.GetResult.Nothing and allow_all:
        return place.all_figures(doc)
    if res != RI.GetResult.Object:
        return []
    out = [go.Object(i).Object() for i in range(go.ObjectCount)]
    doc.Objects.UnselectAll()
    return out


def face_view():
    doc = ui.doc()
    objs = _select_models("Models to turn toward the current view")
    n = place.face_view(doc, objs, doc.Views.ActiveView.ActiveViewport)
    ui.say("Turned {} model(s) to face '{}'.".format(n, doc.Views.ActiveView.ActiveViewport.Name))
    doc.Views.Redraw()


def swap(lib, name):
    doc = ui.doc()
    objs = _select_models("Models to replace with '{}'".format(name), allow_all=False)
    for o in objs:
        place.rebuild(doc, lib, o, name=name)
    ui.say("Replaced {} model(s) with '{}'.".format(len(objs), name))
    doc.Views.Redraw()


def import_model(lib):
    """Ask for an OBJ file, its units, up axis and height; add it to the library. Returns the name."""
    dlg = Rhino.UI.OpenFileDialog()
    dlg.Filter = "OBJ files (*.obj)|*.obj"
    dlg.Title = "Add an OBJ model to the entourage library"
    if not dlg.ShowOpenDialog():
        return None
    src = dlg.FileName
    base = os.path.splitext(os.path.basename(src))[0].replace("_", " ")
    gs = RI.Custom.GetString()
    gs.SetCommandPrompt("Name in the library")
    gs.SetDefaultString(base)
    gs.AcceptNothing(True)
    if gs.Get() not in (RI.GetResult.String, RI.GetResult.Nothing):
        return None
    name = (gs.StringResult() or base).strip() or base
    unit_names = list(catalog.UNITS)
    o_units = 0
    o_up = 1          # Y up: what most OBJ exporters (Blender, SketchUp, 3ds Max) write
    o_h = RI.Custom.OptionDouble(0.0, 0.0, 100000.0)
    o_turn = RI.Custom.OptionDouble(0.0, -360.0, 360.0)
    o_face = RI.Custom.OptionToggle(False, "No", "Yes")
    go = RI.Custom.GetOption()
    while True:
        go.ClearCommandOptions()
        go.SetCommandPrompt("'{}': file units and orientation (Enter to add)".format(name))
        go.AcceptNothing(True)
        i_u = ui.add_option_list(go, "Units", unit_names, o_units)
        i_up = ui.add_option_list(go, "Up", ["Z", "Y"], o_up)
        ui.add_option_double(go, "HeightInches", o_h)
        ui.add_option_double(go, "Turn", o_turn)
        ui.add_option_toggle(go, "FaceView", o_face)
        r = go.Get()
        if r == RI.GetResult.Option:
            if go.OptionIndex() == i_u:
                o_units = go.Option().CurrentListOptionIndex
            elif go.OptionIndex() == i_up:
                o_up = go.Option().CurrentListOptionIndex
            continue
        if r != RI.GetResult.Nothing:
            return None
        break
    try:
        catalog.add_model(lib, src, name, unit_names[o_units], "zy"[o_up], o_h.CurrentValue or None,
                          o_turn.CurrentValue, face_view=o_face.CurrentValue)
    except Exception as ex:
        ui.say("Could not add '{}': {}".format(src, ex))
        return None
    d = catalog.entry(lib, name)
    ui.say("Added '{}' to {} ({:.0f}\" x {:.0f}\" x {:.0f}\" high, {} triangles).".format(
        name, catalog.USER_CATEGORY, d["size"][0], d["size"][1], d["size"][2], d["triangles"]))
    return name


# -- placing --------------------------------------------------------------------------------
class Ghost(object):
    """DynamicDraw handler: the model at the cursor (wires; its box when it is heavy)."""

    def __init__(self, doc, lib):
        self.doc, self.lib = doc, lib
        self.name = None
        self.meshes = []
        self.box = None
        self.angle_fn = lambda pt, vp: 0.0
        self.k = 1.0
        self.mirror = False

    def set(self, name, k, mirror):
        if name != self.name:
            self.name = name
            ms = place.preview(self.doc, self.lib, name)
            tris = sum(m.Faces.Count for m in ms)
            self.meshes = ms if tris <= GHOST_MAX_TRIS else []
            bb = G.BoundingBox.Empty
            for m in ms:
                bb.Union(m.GetBoundingBox(False))
            self.box = bb
        self.k, self.mirror = k, mirror

    def draw(self, sender, e):
        try:
            vp = e.Viewport
            xf = place.xform(e.CurrentPoint, self.angle_fn(e.CurrentPoint, vp), self.mirror, self.k)
            e.Display.PushModelTransform(xf)
            if self.meshes:
                for m in self.meshes:
                    e.Display.DrawMeshWires(m, GHOST)
            elif self.box is not None and self.box.IsValid:
                e.Display.DrawBox(self.box, GHOST)
            e.Display.PopModelTransform()
        except Exception:
            pass


def _angle_for_view(pt, vp):
    if vp.IsParallelProjection:
        d = -G.Vector3d(vp.CameraDirection)
    else:
        d = vp.CameraLocation - pt
    d.Z = 0
    return math.atan2(d.X, -d.Y) if d.Length > 1e-9 else 0.0


def run():
    doc = ui.doc()
    lib = library.get()
    if not catalog.names(lib):
        ui.say("No models in library/entourage.")
        return ui.Result.Failure
    st = settings()
    name = current(lib, st)
    cats = catalog.categories(lib)
    o_h = RI.Custom.OptionDouble(float(st.get("height", 0.0)), 0.0, 100000.0)
    o_turn = RI.Custom.OptionDouble(float(st.get("turn", 0.0)), -360.0, 360.0)
    o_rmodel = RI.Custom.OptionToggle(st.get("random_model", False), "No", "Yes")
    o_rturn = RI.Custom.OptionToggle(st.get("random_turn", False), "No", "Yes")
    o_aim = RI.Custom.OptionToggle(st.get("aim", False), "No", "Yes")
    o_mirror = RI.Custom.OptionToggle(st.get("mirror", False), "No", "Yes")
    o_gray = RI.Custom.OptionToggle(st.get("gray", False), "Model", "Gray")
    ghost = Ghost(doc, lib)
    placed = 0
    next_name = name
    next_turn = random.uniform(0, 2 * math.pi)
    while True:
        d = catalog.entry(lib, next_name)
        cat = d.get("category", catalog.USER_CATEGORY)
        faces = bool(d.get("face_view"))
        h = o_h.CurrentValue or None
        ghost.set(next_name, place.size_factor(lib, next_name, h), o_mirror.CurrentValue)
        if faces:
            ghost.angle_fn = _angle_for_view
        elif o_rturn.CurrentValue:
            ghost.angle_fn = lambda pt, vp, a=next_turn: a
        else:
            ghost.angle_fn = lambda pt, vp, a=math.radians(o_turn.CurrentValue): a
        gp = RI.Custom.GetPoint()
        gp.AcceptNothing(True)
        gp.DynamicDraw += ghost.draw
        size = d.get("size") or [0, 0, 0]
        gp.SetCommandPrompt("Place '{}' ({}, {}\" high{}) - Enter to finish".format(
            next_name, cat, int(round(h or size[2])), ", ceiling: click its top" if d.get("mount") == "ceiling" else ""))
        i_cat = ui.add_option_list(gp, "Category", cats, cats.index(cat) if cat in cats else 0)
        i_model = ui._idx(gp.AddOption("Model"))
        i_lib = ui._idx(gp.AddOption("Library"))
        ui.add_option_double(gp, "Height", o_h)
        ui.add_option_toggle(gp, "RandomModel", o_rmodel)
        ui.add_option_toggle(gp, "RandomTurn", o_rturn)
        ui.add_option_double(gp, "Turn", o_turn)
        ui.add_option_toggle(gp, "Aim", o_aim)
        ui.add_option_toggle(gp, "Mirror", o_mirror)
        ui.add_option_toggle(gp, "Color", o_gray)
        i_face = ui._idx(gp.AddOption("FaceView"))
        i_swap = ui._idx(gp.AddOption("Swap"))
        i_imp = ui._idx(gp.AddOption("Import"))
        res = gp.Get()
        if res == RI.GetResult.Option:
            idx = gp.OptionIndex()
            if idx == i_cat:
                c = cats[gp.Option().CurrentListOptionIndex]
                ns = catalog.names(lib, c)
                if ns:
                    next_name = ns[0]
            elif idx == i_model:
                ns = catalog.names(lib, cat)
                pick = ui.pick_from_list("Mind Canvas - Entourage", cat, ns, next_name)
                next_name = pick or next_name
            elif idx == i_lib:
                from ..eto import entourage as ent_window
                ent_window.open_library()
            elif idx == i_face:
                face_view()
            elif idx == i_swap:
                swap(lib, next_name)
            elif idx == i_imp:
                new = import_model(lib)
                if new:
                    lib = library.get()
                    cats = catalog.categories(lib)
                    next_name = new
            name = next_name
            continue
        if res != RI.GetResult.Point:
            break
        pt = gp.Point()
        vp = gp.View().ActiveViewport if gp.View() else doc.Views.ActiveView.ActiveViewport
        if faces:
            angle = _angle_for_view(pt, vp)
        elif o_aim.CurrentValue:
            ga = RI.Custom.GetPoint()
            ga.SetCommandPrompt("Point the front of '{}' toward".format(next_name))
            ga.SetBasePoint(pt, True)
            ga.DrawLineFromPoint(pt, True)
            heading = bool(d.get("heading"))
            ga.DynamicDraw += lambda s, e, base=pt, hd=heading: _draw_at(ghost, base, e, hd)
            if ga.Get() != RI.GetResult.Point:
                break
            angle = place.aim_angle(ga.Point() - pt, heading)
        elif o_rturn.CurrentValue:
            angle = next_turn
        else:
            angle = math.radians(o_turn.CurrentValue)
        place.place(doc, lib, next_name, pt, angle, o_mirror.CurrentValue, h, o_gray.CurrentValue)
        placed += 1
        doc.Views.Redraw()
        name = next_name
        next_turn = random.uniform(0, 2 * math.pi)
        if o_rmodel.CurrentValue:
            pool = catalog.names(lib, cat, d.get("group", "")) or catalog.names(lib, cat)
            others = [n for n in pool if n != next_name]
            next_name = random.choice(others) if others else next_name
    st.update({"name": name, "category": catalog.entry(lib, name).get("category"), "height": o_h.CurrentValue,
               "turn": o_turn.CurrentValue, "random_model": o_rmodel.CurrentValue,
               "random_turn": o_rturn.CurrentValue, "aim": o_aim.CurrentValue, "mirror": o_mirror.CurrentValue,
               "gray": o_gray.CurrentValue})
    save_settings(st)
    if placed:
        ui.say("Placed {} model(s).".format(placed))
    return ui.Result.Success


def _draw_at(ghost, base, e, heading=False):
    """Aim step: the ghost stays at the base point and turns toward the cursor."""
    try:
        a = place.aim_angle(e.CurrentPoint - base, heading)
        xf = place.xform(base, a, ghost.mirror, ghost.k)
        e.Display.PushModelTransform(xf)
        if ghost.meshes:
            for m in ghost.meshes:
                e.Display.DrawMeshWires(m, GHOST)
        elif ghost.box is not None and ghost.box.IsValid:
            e.Display.DrawBox(ghost.box, GHOST)
        e.Display.PopModelTransform()
    except Exception:
        pass

