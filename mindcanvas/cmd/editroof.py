"""MCEditRoof: change plate height, shape, pitch, overhangs, ridge direction, flip, framing system and
detail level of selected roofs (click the boundary or any part)."""

import Rhino

from .. import engine, library, meta, units
from ..kinds import roof as roofkind
from . import ui
from .floor import SYSTEM_OPTIONS, pick_edge_angle, system_override
from .roof import SHAPE_OPTIONS
from .wall import LOD_OPTIONS

RI = Rhino.Input
RIDGE_OPTIONS = ["Keep", "Long", "Short", "Edge"]


def run():
    doc = ui.doc()
    lib = library.get()
    drivers = ui.select_drivers("Select roofs to edit", kind=roofkind.KIND)
    if not drivers:
        return ui.Result.Cancel
    d0 = drivers[0]
    p = meta.params(d0)
    s = roofkind.settings(lib.assembly(meta.get(d0, meta.ASSEMBLY)), p)
    opt_plate = ui.length_option(units.parse_length(p.get("base_offset", 0)), doc)
    shape_i = SHAPE_OPTIONS.index(s["shape"].capitalize())
    opt_pitch = RI.Custom.OptionDouble(float(s["pitch"]), 0.0, 48.0)
    opt_ov = ui.length_option(units.parse_length(s["overhang"]), doc)
    opt_rake = ui.length_option(units.parse_length(s["rake"]), doc)
    opt_flip = RI.Custom.OptionToggle(bool(s.get("flip")), "No", "Yes")
    ridge_i, sys_i = 0, 0
    lod_i = roofkind.LODS.index(p.get("lod", "detail"))
    gg = RI.Custom.GetOption()
    gg.SetCommandPrompt("Roof settings (Enter to apply)")
    gg.AcceptNothing(True)
    while True:
        gg.ClearCommandOptions()
        ui.add_option_double(gg, "PlateHeight", opt_plate)
        i_shape = ui.add_option_list(gg, "Shape", SHAPE_OPTIONS, shape_i)
        ui.add_option_double(gg, "Pitch", opt_pitch)
        ui.add_option_double(gg, "Overhang", opt_ov)
        ui.add_option_double(gg, "Rake", opt_rake)
        i_ridge = ui.add_option_list(gg, "Ridge", RIDGE_OPTIONS, ridge_i)
        ui.add_option_toggle(gg, "Flip", opt_flip)
        i_sys = ui.add_option_list(gg, "System", SYSTEM_OPTIONS, sys_i)
        i_lod = ui.add_option_list(gg, "Detail", LOD_OPTIONS, lod_i)
        res = gg.Get()
        if res == RI.GetResult.Option:
            oi = gg.OptionIndex()
            if oi == i_shape:
                shape_i = gg.Option().CurrentListOptionIndex
            elif oi == i_ridge:
                ridge_i = gg.Option().CurrentListOptionIndex
            elif oi == i_sys:
                sys_i = gg.Option().CurrentListOptionIndex
            elif oi == i_lod:
                lod_i = gg.Option().CurrentListOptionIndex
            continue
        if res == RI.GetResult.Nothing:
            break
        return ui.Result.Cancel
    for d in drivers:
        changes = {"base_offset": round(units.to_inches(doc, opt_plate.CurrentValue), 4),
                   "shape": SHAPE_OPTIONS[shape_i].lower(), "pitch": round(opt_pitch.CurrentValue, 4),
                   "overhang": round(units.to_inches(doc, opt_ov.CurrentValue), 4),
                   "rake": round(units.to_inches(doc, opt_rake.CurrentValue), 4),
                   "flip": bool(opt_flip.CurrentValue), "lod": roofkind.LODS[lod_i]}
        ridge = RIDGE_OPTIONS[ridge_i]
        if ridge in ("Long", "Short"):
            changes["ridge"] = ridge.lower()
        elif ridge == "Edge":
            ang = pick_edge_angle(doc, d.Geometry, "Click the boundary edge the ridge / eaves run along")
            if ang is not None:
                changes["ridge"] = ang
        changes["overrides"] = dict(meta.params(d).get("overrides", {}))
        changes = system_override(lib, d, SYSTEM_OPTIONS[sys_i], changes)
        ui.report(engine.update_params(doc, d, changes, lib), "Roof:")
    doc.Views.Redraw()
    return ui.Result.Success
