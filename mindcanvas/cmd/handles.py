"""MCHandles: turn the viewport drag handles and hover labels on or off (viewport/overlay.py).

Handles: select an assembly and drag its arrows (wall height / base, window edges, floor elevation,
roof plate / overhang / pitch); click the arrow out of a wall's face to flip it. Labels: rest the
mouse on an assembly to see what it is. SnapHead: a window / door drag lands its head on the brick
coursing (like MCOpening's SnapHead)."""

import Rhino

from ..viewport import overlay
from . import ui

RI = Rhino.Input


def run():
    st = overlay.state()
    on = overlay.is_on()
    opt_h = RI.Custom.OptionToggle(st["handles"] if on else True, "Off", "On")
    opt_l = RI.Custom.OptionToggle(st["labels"] if on else True, "Off", "On")
    opt_s = RI.Custom.OptionToggle(bool(st["snap"]), "No", "Yes")
    go = RI.Custom.GetOption()
    go.SetCommandPrompt("Viewport handles and hover labels (Enter to apply)")
    go.AcceptNothing(True)
    while True:
        go.ClearCommandOptions()
        ui.add_option_toggle(go, "Handles", opt_h)
        ui.add_option_toggle(go, "Labels", opt_l)
        ui.add_option_toggle(go, "SnapHead", opt_s)
        res = go.Get()
        if res == RI.GetResult.Option:
            continue
        if res != RI.GetResult.Nothing:
            return ui.Result.Cancel
        break
    h, l = bool(opt_h.CurrentValue), bool(opt_l.CurrentValue)
    if h or l:
        overlay.enable(h, l, bool(opt_s.CurrentValue))
    else:
        overlay.disable()
    ui.say("Handles {}, hover labels {}.".format("on" if h else "off", "on" if l else "off"))
    return ui.Result.Success
