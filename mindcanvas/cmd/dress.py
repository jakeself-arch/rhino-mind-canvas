"""MCDress: dress massing solids with walls and floors (mindcanvas/dress.py). Each closed solid is
one story: a closed wall runs around it (finished exterior face on the solid, growing inward) and
where one solid sits on another, the upper story gets a floor whose top is the shared face (the
walls below stop under its framing). Stack solids for more stories; push / pull them with the
gumball and everything follows (live mode). Options: Wall / Floor (assemblies; Floor None = no
floors), GroundFloor (a floor at the bottom of the lowest stories too). No roofs yet: put an MCRoof
on top. Select dressed solids again to change their options."""

import Rhino

from .. import dress, library, masses, wallmasses
from . import ui

RI = Rhino.Input


def _solid_filter(doc):
    def _ok(rh_obj, geom, ci):
        return masses.is_solid_candidate(rh_obj) or wallmasses.is_wall_mass(rh_obj)
    return RI.Custom.GetObjectGeometryFilter(_ok)


def run():
    doc = ui.doc()
    lib = library.get()
    wall = ui.current_assembly(lib, "wall", doc)
    floor = ui.current_assembly(lib, "floor", doc)
    ground = RI.Custom.OptionToggle(False, "No", "Yes")
    go = RI.Custom.GetObject()
    go.GeometryFilter = Rhino.DocObjects.ObjectType.Brep | Rhino.DocObjects.ObjectType.Extrusion
    go.SetCustomGeometryFilter(_solid_filter(doc))
    go.EnablePreSelect(True, True)
    go.SubObjectSelect = False
    while True:
        go.SetCommandPrompt("Select massing solids to dress (one story each) [walls: {}; floors: {}]".format(
            wall, floor or "none"))
        go.ClearCommandOptions()
        i_wall = go.AddOption("Wall")
        i_floor = go.AddOption("Floor")
        ui.add_option_toggle(go, "GroundFloor", ground)
        res = go.GetMultiple(1, 0)
        if res == RI.GetResult.Option:
            oi = go.OptionIndex()
            if oi == i_wall:
                wall = ui.pick_assembly(lib, "wall", "Mind Canvas - Dress: walls") or wall
            elif oi == i_floor:
                names = ["None"] + lib.assemblies("floor")
                pick = ui.pick_from_list("Mind Canvas - Dress: floors", "Floor between stories", names, floor or "None")
                if pick:
                    floor = None if pick == "None" else pick
            continue
        if res != RI.GetResult.Object:
            return ui.Result.Cancel
        break
    solids = [go.Object(i).Object() for i in range(go.ObjectCount)]
    doc.Objects.UnselectAll()
    objs, sr, notes = dress.make(doc, solids, wall, floor, bool(ground.CurrentValue), lib)
    for n in sorted(set(notes)):
        ui.say("  note: " + n)
    for w in sr.warnings:
        ui.say("  warning: " + w)
    secs = sum(r.seconds for r in sr.results)
    ui.say("Dressed {} solid(s): {} new floor(s), {} moved, {} removed ({:.2f}s of builds).".format(
        len(objs), sr.created, sr.moved, sr.removed, secs))
    doc.Views.Redraw()
    return ui.Result.Success
