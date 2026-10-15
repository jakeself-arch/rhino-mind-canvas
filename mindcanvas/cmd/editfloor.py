"""MCEditFloor: change elevation, reference, joist span direction, spacing, framing system and detail
level of selected floors (click the boundary or any part)."""

import Rhino

from .. import engine, library, meta, units
from ..kinds import floor as floorkind
from . import ui
from .floor import SYSTEM_OPTIONS, framing_layer, pick_edge_angle, system_override
from .wall import LOD_OPTIONS

RI = Rhino.Input
REF_OPTIONS = ["FramingBottom", "FramingTop", "Top", "Bottom"]
SPAN_OPTIONS = ["Keep", "Short", "Long", "Edge", "Rotate90"]


def run():
    doc = ui.doc()
    lib = library.get()
    drivers = ui.select_drivers("Select floors to edit", kind=floorkind.KIND)
    if not drivers:
        return ui.Result.Cancel
    p = meta.params(drivers[0])
    opt_el = ui.length_option(units.parse_length(p.get("base_offset", 0)), doc)
    ref_i = floorkind.REFERENCES.index(p.get("reference", "framing_bottom"))
    lay = framing_layer(lib, drivers[0])
    cur_sp = p.get("overrides", {}).get(lay, {}).get("spacing", 0) if lay else 0
    opt_sp = RI.Custom.OptionDouble(float(cur_sp or 0), 0.0, 96.0)
    span_i, sys_i = 0, 0
    lod_i = floorkind.LODS.index(p.get("lod", "detail"))
    gg = RI.Custom.GetOption()
    gg.SetCommandPrompt("Floor settings (Enter to apply; SpacingInches 0 = the assembly's)")
    gg.AcceptNothing(True)
    while True:
        gg.ClearCommandOptions()
        ui.add_option_double(gg, "Elevation", opt_el)
        i_ref = ui.add_option_list(gg, "Reference", REF_OPTIONS, ref_i)
        i_span = ui.add_option_list(gg, "Span", SPAN_OPTIONS, span_i)
        ui.add_option_double(gg, "SpacingInches", opt_sp)
        i_sys = ui.add_option_list(gg, "System", SYSTEM_OPTIONS, sys_i)
        i_lod = ui.add_option_list(gg, "Detail", LOD_OPTIONS, lod_i)
        res = gg.Get()
        if res == RI.GetResult.Option:
            oi = gg.OptionIndex()
            if oi == i_ref:
                ref_i = gg.Option().CurrentListOptionIndex
            elif oi == i_span:
                span_i = gg.Option().CurrentListOptionIndex
            elif oi == i_sys:
                sys_i = gg.Option().CurrentListOptionIndex
            elif oi == i_lod:
                lod_i = gg.Option().CurrentListOptionIndex
            continue
        if res == RI.GetResult.Nothing:
            break
        return ui.Result.Cancel
    for d in drivers:
        prm = meta.params(d)
        changes = {"base_offset": round(units.to_inches(doc, opt_el.CurrentValue), 4),
                   "reference": floorkind.REFERENCES[ref_i], "lod": floorkind.LODS[lod_i]}
        span = SPAN_OPTIONS[span_i]
        if span in ("Short", "Long"):
            changes["span"] = span.lower()
        elif span == "Edge":
            ang = pick_edge_angle(doc, d.Geometry, "Click the boundary edge the joists bear on")
            if ang is not None:
                changes["span"] = round((ang + 90.0) % 180.0, 4)
        elif span == "Rotate90":
            ctx = floorkind.make_context(doc, lib, d, meta.get(d, meta.ASSEMBLY), prm)
            changes["span"] = round((floorkind.angle_of(ctx.jdir) + 90.0) % 180.0, 4)
        sp = round(opt_sp.CurrentValue, 4)
        name = framing_layer(lib, d)
        ov = dict(prm.get("overrides", {}))
        if name:
            lo = dict(ov.get(name, {}))
            if sp > 0:
                lo["spacing"] = sp
            else:
                lo.pop("spacing", None)
            ov[name] = lo
        changes["overrides"] = ov
        changes = system_override(lib, d, SYSTEM_OPTIONS[sys_i], changes)
        ui.report(engine.update_params(doc, d, changes, lib), "Floor:")
    doc.Views.Redraw()
    return ui.Result.Success
