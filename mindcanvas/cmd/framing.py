"""MCFraming: swap the framing system (wood / metal), stud spacing and gauge of walls."""

import scriptcontext
import Rhino

from .. import engine, library, meta
from ..kinds import wall as wallkind
from . import ui

RI = Rhino.Input
STICKY = "mindcanvas.framing.settings"
GAUGES = ["Keep", "20", "18", "16"]


def framing_layers(lib, driver):
    """Names of the framing layers in a wall's (possibly per-wall) layer stack."""
    return [wallkind.layer_name(spec, i) for i, spec in enumerate(wallkind.effective_layers(lib, driver))
            if spec.get("component") == "framing"]


def run():
    doc = ui.doc()
    lib = library.get()
    drivers = ui.select_drivers("Select framed walls", kind="wall")
    drivers = [d for d in drivers if framing_layers(lib, d)]
    if not drivers:
        ui.say("No walls with a framing layer selected.")
        return ui.Result.Cancel
    systems = sorted(lib.data["framing"])
    st = scriptcontext.sticky.get(STICKY, {})
    system = ui.pick_from_list("Mind Canvas - Framing", "Framing system", systems, st.get("system"))
    if not system:
        return ui.Result.Cancel

    opt_sp = RI.Custom.OptionDouble(float(st.get("spacing", 16)), 4.0, 96.0)
    gauge_i = GAUGES.index(st.get("gauge", "Keep")) if st.get("gauge", "Keep") in GAUGES else 0
    gg = RI.Custom.GetOption()
    gg.SetCommandPrompt("{} framing (Enter to apply)".format(system))
    gg.AcceptNothing(True)
    while True:
        gg.ClearCommandOptions()
        ui.add_option_double(gg, "SpacingInches", opt_sp)
        i_g = ui.add_option_list(gg, "Gauge", GAUGES, gauge_i) if lib.framing_system(system).get("type") == "metal" else -1
        res = gg.Get()
        if res == RI.GetResult.Option:
            if gg.OptionIndex() == i_g:
                gauge_i = gg.Option().CurrentListOptionIndex
            continue
        if res == RI.GetResult.Nothing:
            break
        return ui.Result.Cancel

    spacing = round(opt_sp.CurrentValue, 4)
    gauge = GAUGES[gauge_i]
    scriptcontext.sticky[STICKY] = {"system": system, "spacing": spacing, "gauge": gauge}
    for d in drivers:
        prm = meta.params(d)
        overrides = prm.get("overrides", {})
        for name in framing_layers(lib, d):
            ov = overrides.setdefault(name, {})
            if ov.get("system") != system:
                ov.pop("stud", None)  # a 2x6 is not a metal stud
            ov["system"] = system
            ov["spacing"] = spacing
            if gauge != "Keep" and i_g >= 0:
                ov["gauge"] = int(gauge)
        ui.report(engine.update_params(doc, d, {"overrides": overrides}), "Framing ({}):".format(system))
    doc.Views.Redraw()
    return ui.Result.Success
