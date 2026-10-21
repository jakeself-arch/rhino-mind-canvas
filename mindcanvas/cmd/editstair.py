"""MCEditStair: floor height, floors, laps, width, elevation, side, direction, start point, landings,
max riser / riser count and style of selected stairs (click the curve or the stair). Flip (or a new
StartPoint direction) reverses the way up and keeps the stair where it is; Side moves it across."""

import Rhino

from .. import engine, library, meta, units
from ..kinds import stair as stairkind
from . import ui
from .stair import SIDE_OPTIONS, describe, pick_landings, pick_start

RI = Rhino.Input
STYLE_OPTIONS = ["Assembly", "Slab", "Solid", "Open"]


def run():
    doc = ui.doc()
    lib = library.get()
    drivers = ui.select_drivers("Select stairs to edit", kind=stairkind.KIND)
    if not drivers:
        return ui.Result.Cancel
    d0 = drivers[0]
    p = meta.params(d0)
    st = stairkind.settings(lib.assembly(meta.get(d0, meta.ASSEMBLY)), p)
    width = units.parse_length(p.get("width", stairkind.DEFAULTS["width"]))
    opt_h = ui.length_option(units.parse_length(p.get("height", stairkind.DEFAULTS["height"])), doc)
    opt_floors = RI.Custom.OptionInteger(int(p.get("floors") or 1), 1, 100)
    opt_laps = RI.Custom.OptionDouble(float(p.get("laps") or 1.0), 0.05, 50.0)
    opt_w = ui.length_option(width, doc)
    opt_el = ui.length_option(units.parse_length(p.get("base_offset", 0)), doc)
    opt_flip = RI.Custom.OptionToggle(bool(p.get("flip", False)), "No", "Yes")
    opt_r = RI.Custom.OptionDouble(float(units.parse_length(st["max_riser"])), 4.0, 12.0)
    opt_n = RI.Custom.OptionInteger(int(st["risers"] or 0), 0, 200)
    opt_waist = RI.Custom.OptionDouble(float(units.parse_length(st["waist"])), 1.0, 48.0)
    opt_lc = RI.Custom.OptionInteger(int(p.get("landing_count") or 0), 0, 50)
    opt_ld = ui.length_option(units.parse_length(p.get("landing_depth") or width), doc)
    side_i = side_i0 = SIDE_OPTIONS.index(p.get("side", "left").capitalize())
    style_i = STYLE_OPTIONS.index(p["style"].capitalize()) if p.get("style") in stairkind.STYLES else 0
    landings = list(p.get("landings") or [])
    start, start_flip, landings_changed = None, None, False
    closed = d0.Geometry.IsClosed
    gg = RI.Custom.GetOption()
    gg.SetCommandPrompt("Stair settings (Enter to apply; Risers 0 = from the max riser)")
    gg.AcceptNothing(True)
    while True:
        gg.ClearCommandOptions()
        ui.add_option_double(gg, "FloorHeight", opt_h)
        ui._idx(gg.AddOptionInteger("Floors", opt_floors))
        if closed:
            ui.add_option_double(gg, "Laps", opt_laps)
        ui.add_option_double(gg, "Width", opt_w)
        ui.add_option_double(gg, "Elevation", opt_el)
        i_side = ui.add_option_list(gg, "Side", SIDE_OPTIONS, side_i)
        ui.add_option_toggle(gg, "Flip", opt_flip)
        i_start = gg.AddOption("StartPoint") if closed else -1
        ui._idx(gg.AddOptionInteger("LandingsPerFloor", opt_lc))
        ui.add_option_double(gg, "LandingDepth", opt_ld)
        i_add = gg.AddOption("AddLandings")
        i_clear = gg.AddOption("ClearLandings")
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
            elif oi == i_start:
                start, start_flip = pick_start(doc, d0.Geometry)
                if start_flip is not None:
                    opt_flip.CurrentValue = start_flip
            elif oi == i_add:
                landings = pick_landings(doc, d0.Geometry, landings)
                landings_changed = True
            elif oi == i_clear:
                landings, landings_changed = [], True
                ui.say("Clicked landings cleared (corner, floor and evenly spaced landings stay).")
            continue
        if res == RI.GetResult.Nothing:
            break
        return ui.Result.Cancel
    for d in drivers:
        asm = lib.assembly(meta.get(d, meta.ASSEMBLY))
        w = round(units.to_inches(doc, opt_w.CurrentValue), 4)
        ld = round(units.to_inches(doc, opt_ld.CurrentValue), 4)
        pd = meta.params(d)
        side = SIDE_OPTIONS[side_i].lower()
        flip = bool(opt_flip.CurrentValue)
        if side_i == side_i0 and flip != bool(pd.get("flip", False)):
            # going up the other way round: keep the footprint (the curve's side of the stair swaps)
            side = "right" if pd.get("side", "left") == "left" else "left"
        changes = {"height": round(units.to_inches(doc, opt_h.CurrentValue), 4), "width": w,
                   "base_offset": round(units.to_inches(doc, opt_el.CurrentValue), 4),
                   "side": side, "flip": flip,
                   "floors": opt_floors.CurrentValue if opt_floors.CurrentValue > 1 else None,
                   "landing_count": opt_lc.CurrentValue or None,
                   "landing_depth": None if abs(ld - w) < 1e-6 else ld,
                   "risers": opt_n.CurrentValue or None,
                   "style": None if style_i == 0 else STYLE_OPTIONS[style_i].lower()}
        if d.Geometry.IsClosed:
            changes["laps"] = round(opt_laps.CurrentValue, 4)
        if d.Id == d0.Id:
            if start is not None:
                changes["start"] = start
            if landings_changed:
                changes["landings"] = landings or None
        for key, opt in (("max_riser", opt_r), ("waist", opt_waist)):
            base = units.parse_length(asm.get(key, stairkind.SETTINGS[key]))
            changes[key] = None if abs(opt.CurrentValue - base) < 1e-6 else round(opt.CurrentValue, 4)
        r = engine.update_params(doc, d, changes, lib)
        ui.report(r, "Stair:")
        ui.say("  " + describe(doc, lib, doc.Objects.FindId(d.Id)))
    doc.Views.Redraw()
    return ui.Result.Success
