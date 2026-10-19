"""MCEditStair: floor height, width, elevation, side, direction, max riser / riser count and style of
selected stairs (click the curve or the stair)."""

import Rhino

from .. import engine, library, meta, units
from ..kinds import stair as stairkind
from . import ui
from .stair import SIDE_OPTIONS, describe

RI = Rhino.Input
STYLE_OPTIONS = ["Assembly", "Slab", "Solid", "Open"]


def run():
    doc = ui.doc()
    lib = library.get()
    drivers = ui.select_drivers("Select stairs to edit", kind=stairkind.KIND)
    if not drivers:
        return ui.Result.Cancel
    p = meta.params(drivers[0])
    st = stairkind.settings(lib.assembly(meta.get(drivers[0], meta.ASSEMBLY)), p)
    opt_h = ui.length_option(units.parse_length(p.get("height", stairkind.DEFAULTS["height"])), doc)
    opt_w = ui.length_option(units.parse_length(p.get("width", stairkind.DEFAULTS["width"])), doc)
    opt_el = ui.length_option(units.parse_length(p.get("base_offset", 0)), doc)
    opt_flip = RI.Custom.OptionToggle(bool(p.get("flip", False)), "No", "Yes")
    opt_r = RI.Custom.OptionDouble(float(units.parse_length(st["max_riser"])), 4.0, 12.0)
    opt_n = RI.Custom.OptionInteger(int(st["risers"] or 0), 0, 200)
    opt_waist = RI.Custom.OptionDouble(float(units.parse_length(st["waist"])), 1.0, 48.0)
    side_i = SIDE_OPTIONS.index(p.get("side", "left").capitalize())
    style_i = STYLE_OPTIONS.index(p["style"].capitalize()) if p.get("style") in stairkind.STYLES else 0
    gg = RI.Custom.GetOption()
    gg.SetCommandPrompt("Stair settings (Enter to apply; Risers 0 = from the max riser)")
    gg.AcceptNothing(True)
    while True:
        gg.ClearCommandOptions()
        ui.add_option_double(gg, "FloorHeight", opt_h)
        ui.add_option_double(gg, "Width", opt_w)
        ui.add_option_double(gg, "Elevation", opt_el)
        i_side = ui.add_option_list(gg, "Side", SIDE_OPTIONS, side_i)
        ui.add_option_toggle(gg, "Flip", opt_flip)
        ui.add_option_double(gg, "MaxRiserInches", opt_r)
        ui._idx(gg.AddOptionInteger("Risers", opt_n))
        i_style = ui.add_option_list(gg, "Style", STYLE_OPTIONS, style_i)
        ui.add_option_double(gg, "WaistInches", opt_waist)
        res = gg.Get()
        if res == RI.GetResult.Option:
            oi = gg.OptionIndex()
            if oi == i_side:
                side_i = gg.Option().CurrentListOptionIndex
            elif oi == i_style:
                style_i = gg.Option().CurrentListOptionIndex
            continue
        if res == RI.GetResult.Nothing:
            break
        return ui.Result.Cancel
    for d in drivers:
        asm = lib.assembly(meta.get(d, meta.ASSEMBLY))
        changes = {"height": round(units.to_inches(doc, opt_h.CurrentValue), 4),
                   "width": round(units.to_inches(doc, opt_w.CurrentValue), 4),
                   "base_offset": round(units.to_inches(doc, opt_el.CurrentValue), 4),
                   "side": SIDE_OPTIONS[side_i].lower(), "flip": bool(opt_flip.CurrentValue),
                   "risers": opt_n.CurrentValue or None,
                   "style": None if style_i == 0 else STYLE_OPTIONS[style_i].lower()}
        for key, opt in (("max_riser", opt_r), ("waist", opt_waist)):
            base = units.parse_length(asm.get(key, stairkind.SETTINGS[key]))
            changes[key] = None if abs(opt.CurrentValue - base) < 1e-6 else round(opt.CurrentValue, 4)
        r = engine.update_params(doc, d, changes, lib)
        ui.report(r, "Stair:")
        ui.say("  " + describe(doc, lib, doc.Objects.FindId(d.Id)))
    doc.Views.Redraw()
    return ui.Result.Success
