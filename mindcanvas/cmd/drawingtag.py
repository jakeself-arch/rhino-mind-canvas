"""MCDrawingTag: mark objects for drawings - Ground (stippled), NoTone, Exclude, NoCut,
or Clear. Stored as user text mc.draw (a layer may carry it too)."""

import scriptcontext
import Rhino

from ..drawing import tags
from . import ui

RI = Rhino.Input
ACTIONS = ["Ground", "NoTone", "Exclude", "NoCut", "Clear"]
STICKY = "mindcanvas.drawingtag.action"


def run():
    doc = ui.doc()
    act_i = ACTIONS.index(scriptcontext.sticky.get(STICKY, "Ground"))
    o_remove = RI.Custom.OptionToggle(False, "Add", "Remove")
    go = RI.Custom.GetObject()
    go.SubObjectSelect = False
    go.GroupSelect = True
    go.EnablePreSelect(True, True)
    while True:
        go.SetCommandPrompt("Select objects to tag")
        go.ClearCommandOptions()
        i_act = ui.add_option_list(go, "Tag", ACTIONS, act_i)
        ui.add_option_toggle(go, "Mode", o_remove)
        res = go.GetMultiple(1, 0)
        if res == RI.GetResult.Option:
            if go.OptionIndex() == i_act:
                act_i = go.Option().CurrentListOptionIndex
            go.EnablePreSelect(False, True)
            continue
        if res != RI.GetResult.Object:
            return ui.Result.Cancel
        break
    action = ACTIONS[act_i]
    scriptcontext.sticky[STICKY] = action
    flag = action.lower()
    n = 0
    for i in range(go.ObjectCount):
        obj = go.Object(i).Object()
        if action == "Clear":
            tags.set_flags(doc, obj, clear=True)
        elif o_remove.CurrentValue:
            tags.set_flags(doc, obj, remove=[flag])
        else:
            tags.set_flags(doc, obj, add=[flag])
        n += 1
    doc.Objects.UnselectAll()
    doc.Views.Redraw()
    ui.say("Mind Canvas: {} {} object(s).".format("cleared tags on" if action == "Clear" else
                                                   ("removed '{}' from".format(flag) if o_remove.CurrentValue
                                                    else "tagged '{}' on".format(flag)), n))
    return ui.Result.Success
