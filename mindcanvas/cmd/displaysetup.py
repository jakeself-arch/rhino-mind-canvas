"""MCDisplaySetup: hatch patterns, the "MC Section" display mode and section styles
for a drawing scale on the active view (the live counterpart of MCDrawing)."""

import scriptcontext
import Rhino

from .. import library
from ..drawing import displaymode, patterns, sectionstyle, styles
from . import ui

RI = Rhino.Input
STICKY = "mindcanvas.displaysetup.scale"


def run():
    doc = ui.doc()
    lib = library.get()
    names = styles.names(lib)
    options = [styles.get(n, lib).option for n in names]
    cur = scriptcontext.sticky.get(STICKY)
    scale_i = options.index(cur) if cur in options else 0
    o_rebuild = RI.Custom.OptionToggle(False, "No", "Yes")
    go = RI.Custom.GetOption()
    go.AcceptNothing(True)
    while True:
        go.SetCommandPrompt("Section display for scale (Enter to apply)")
        go.ClearCommandOptions()
        i_scale = ui.add_option_list(go, "Scale", options, scale_i)
        ui.add_option_toggle(go, "RebuildMode", o_rebuild)
        res = go.Get()
        if res == RI.GetResult.Option:
            if go.OptionIndex() == i_scale:
                scale_i = go.Option().CurrentListOptionIndex
            continue
        if res == RI.GetResult.Nothing:
            break
        return ui.Result.Cancel
    scriptcontext.sticky[STICKY] = options[scale_i]
    pats = patterns.ensure(doc)
    dm = displaymode.ensure(force=o_rebuild.CurrentValue)
    n = sectionstyle.apply(doc, names[scale_i])
    displaymode.assign(doc.Views.ActiveView, dm)
    ui.say("Mind Canvas: {} hatch patterns, display mode '{}', section styles on {} material layers ({}).".format(
        len(pats), displaymode.NAME, n, names[scale_i]))
    return ui.Result.Success
