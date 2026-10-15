"""MCEdit: change height, base offset, location line, flip and detail level of walls."""

import Rhino

from .. import engine, meta, units
from ..kinds import wall as wallkind
from . import ui
from .wall import LOD_OPTIONS, REF_OPTIONS

RI = Rhino.Input


def run():
    doc = ui.doc()
    drivers = ui.select_drivers("Select walls to edit", kind="wall")
    if not drivers:
        return ui.Result.Cancel
    p = meta.params(drivers[0])
    opt_h = ui.length_option(units.parse_length(p.get("height", 120)), doc)
    opt_base = ui.length_option(units.parse_length(p.get("base_offset", 0)), doc)
    opt_flip = RI.Custom.OptionToggle(bool(p.get("flip", False)), "No", "Yes")
    ref_i = wallkind.REFERENCES.index(p.get("reference", "center"))
    lod_i = wallkind.LODS.index(p.get("lod", "detail"))

    gg = RI.Custom.GetOption()
    gg.SetCommandPrompt("Wall settings (Enter to apply)")
    gg.AcceptNothing(True)
    while True:
        gg.ClearCommandOptions()
        ui.add_option_double(gg, "Height", opt_h)
        ui.add_option_double(gg, "BaseOffset", opt_base)
        i_ref = ui.add_option_list(gg, "Location", REF_OPTIONS, ref_i)
        ui.add_option_toggle(gg, "Flip", opt_flip)
        i_lod = ui.add_option_list(gg, "Detail", LOD_OPTIONS, lod_i)
        res = gg.Get()
        if res == RI.GetResult.Option:
            if gg.OptionIndex() == i_ref:
                ref_i = gg.Option().CurrentListOptionIndex
            elif gg.OptionIndex() == i_lod:
                lod_i = gg.Option().CurrentListOptionIndex
            continue
        if res == RI.GetResult.Nothing:
            break
        return ui.Result.Cancel

    changes = {
        "height": round(units.to_inches(doc, opt_h.CurrentValue), 4),
        "base_offset": round(units.to_inches(doc, opt_base.CurrentValue), 4),
        "reference": wallkind.REFERENCES[ref_i],
        "flip": bool(opt_flip.CurrentValue),
        "lod": wallkind.LODS[lod_i],
    }
    for d in drivers:
        ui.report(engine.update_params(doc, d, changes), "Updated:")
    doc.Views.Redraw()
    return ui.Result.Success
