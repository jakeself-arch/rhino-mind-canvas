"""MCAssemblyLayers: a layer per library assembly under "MC Assemblies" (Walls, Curtain walls,
Floors, Roofs). Draw a curve on a wall layer and it becomes that wall; a closed curve on a floor /
roof layer becomes a floor / roof; a closed solid on a wall layer becomes a wall mass; move an
existing wall / floor / ... onto another layer of its kind and it takes that assembly (see
mindcanvas/laylink.py). Option Watch: Off stops turning things on these layers into assemblies."""

import Rhino

from .. import laylink, library
from . import ui

RI = Rhino.Input


def run():
    doc = ui.doc()
    lib = library.get()
    opt = RI.Custom.OptionToggle(True, "Off", "On")
    go = RI.Custom.GetOption()
    go.SetCommandPrompt("Create / refresh the assembly layers (Enter)")
    go.AcceptNothing(True)
    while True:
        go.ClearCommandOptions()
        ui.add_option_toggle(go, "Watch", opt)
        res = go.Get()
        if res == RI.GetResult.Option:
            continue
        if res != RI.GetResult.Nothing:
            return ui.Result.Cancel
        break
    made = laylink.ensure_layers(doc, lib)
    if opt.CurrentValue:
        laylink.enable()
        ui.say("{} assembly layers under '{}': draw or move curves / solids onto them to make assemblies.".format(
            len(made), laylink.ROOT))
    else:
        laylink.disable()
        ui.say("{} assembly layers; watching is off.".format(len(made)))
    doc.Views.Redraw()
    return ui.Result.Success
