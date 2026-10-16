"""MCTrim: add a swept profile (base, chair rail, crown, water table, captured profiles) to the
interior or exterior face of selected walls, or remove them."""

import scriptcontext
import Rhino

from .. import library, trims
from . import ui

RI = Rhino.Input
STICKY = "mindcanvas.trim.settings"
FACES = ["Interior", "Exterior"]
HEIGHTS = ["Base", "Top", "Custom"]
ACTIONS = ["Add", "Remove"]


def run():
    doc = ui.doc()
    lib = library.get()
    names = trims.profiles(lib)
    if not names:
        ui.say("No trim profiles (family 'trim') in library/profiles.")
        return ui.Result.Failure
    st = scriptcontext.sticky.get(STICKY, {})
    walls = ui.select_drivers("Select walls for trim", kind="wall")
    if not walls:
        return ui.Result.Cancel
    prof_i = names.index(st["profile"]) if st.get("profile") in names else 0
    face_i = FACES.index(st.get("face", "Interior"))
    z_i = HEIGHTS.index(st.get("height", "Base"))
    act_i = 0
    o_z = RI.Custom.OptionDouble(float(st.get("z", 36.0)), 0.0, 1200.0)
    o_off = RI.Custom.OptionDouble(float(st.get("offset", 0.0)), -12.0, 12.0)
    go = RI.Custom.GetOption()
    go.AcceptNothing(True)
    while True:
        go.SetCommandPrompt("{} trim '{}' on {} wall(s) (Enter to apply)".format(
            ACTIONS[act_i], names[prof_i], len(walls)))
        go.ClearCommandOptions()
        i_act = ui.add_option_list(go, "Action", ACTIONS, act_i)
        i_prof = ui._idx(go.AddOption("Profile"))
        i_face = ui.add_option_list(go, "Face", FACES, face_i)
        i_z = ui.add_option_list(go, "Height", HEIGHTS, z_i)
        if HEIGHTS[z_i] == "Custom":
            ui.add_option_double(go, "HeightInches", o_z)
        ui.add_option_double(go, "OffsetInches", o_off)
        res = go.Get()
        if res == RI.GetResult.Option:
            idx = go.OptionIndex()
            if idx == i_act:
                act_i = go.Option().CurrentListOptionIndex
            elif idx == i_face:
                face_i = go.Option().CurrentListOptionIndex
            elif idx == i_z:
                z_i = go.Option().CurrentListOptionIndex
            elif idx == i_prof:
                pick = ui.pick_from_list("Mind Canvas - Trim", "Profile", names, names[prof_i])
                if pick:
                    prof_i = names.index(pick)
            continue
        if res == RI.GetResult.Nothing:
            break
        return ui.Result.Cancel
    profile = names[prof_i]
    z = {"Base": "base", "Top": "top"}.get(HEIGHTS[z_i], round(o_z.CurrentValue, 4))
    scriptcontext.sticky[STICKY] = {"profile": profile, "face": FACES[face_i], "height": HEIGHTS[z_i],
                                    "z": o_z.CurrentValue, "offset": o_off.CurrentValue}
    for w in walls:
        if ACTIONS[act_i] == "Remove":
            r = trims.remove(doc, w, lib, profile)
            if r is not None:
                ui.report(r, "Removed trim:")
        else:
            ui.report(trims.add(doc, w, lib, profile, FACES[face_i].lower(), z, round(o_off.CurrentValue, 4)),
                      "Trim:")
    doc.Views.Redraw()
    return ui.Result.Success
