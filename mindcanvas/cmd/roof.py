"""MCRoof: turn closed curves into roofs (or draw a closed polyline).

Pick a roof assembly, then select closed boundaries (the plate line: outside face of the wall
framing). Options: Assembly, PlateHeight (base offset: the top of the wall plates), Shape (Flat /
Shed / Gable), Pitch (rise in 12), Overhang (eave), Rake, Ridge (Long / Short / Edge: click the
boundary edge the ridge or the eaves run parallel to), Flip (shed: high side), System, Detail, Draw."""

import scriptcontext
import Rhino

from .. import engine, library, meta, units
from ..kinds import roof as roofkind
from . import ui
from .floor import SYSTEM_OPTIONS, pick_edge_angle, system_override
from .wall import LOD_OPTIONS, _draw_polyline

RI = Rhino.Input
SHAPE_OPTIONS = ["Flat", "Shed", "Gable"]
RIDGE_OPTIONS = ["Long", "Short", "Edge"]
STICKY = "mindcanvas.roof.settings"


def roof_settings(lib, name):
    return roofkind.settings(lib.assembly(name), {})


def run():
    doc = ui.doc()
    lib = library.get()
    if not engine.tolerance_ok(doc):
        ui.say("Mind Canvas: model tolerance is too coarse for assembly detail. Run MCSetup first.")
    names = lib.assemblies(roofkind.KIND)
    if not names:
        ui.say("No roof assemblies in library/assemblies.")
        return ui.Result.Cancel
    name = scriptcontext.sticky.get(ui.LAST_ASSEMBLY + roofkind.KIND)
    if name not in names:
        name = ui.pick_assembly(lib, roofkind.KIND, "Mind Canvas - Roof")
        if not name:
            return ui.Result.Cancel
    sticky = scriptcontext.sticky.get(STICKY, {})

    def _defaults(asm_name):
        s = roof_settings(lib, asm_name)
        return (SHAPE_OPTIONS.index(s["shape"].capitalize()), RI.Custom.OptionDouble(float(s["pitch"]), 0.0, 48.0),
                ui.length_option(units.parse_length(s["overhang"]), doc), ui.length_option(units.parse_length(s["rake"]), doc))

    shape_i, opt_pitch, opt_ov, opt_rake = _defaults(name)
    opt_plate = ui.length_option(float(sticky.get("base_offset", 0.0)), doc)
    ridge_i = 0
    opt_flip = RI.Custom.OptionToggle(False, "No", "Yes")
    sys_i = 0
    lod_i = LOD_OPTIONS.index(sticky.get("lod", "Detail")) if sticky.get("lod") in LOD_OPTIONS else 2

    go = RI.Custom.GetObject()
    go.GeometryFilter = Rhino.DocObjects.ObjectType.Curve
    go.GeometryAttributeFilter = RI.Custom.GeometryAttributeFilter.ClosedCurve
    go.EnablePreSelect(True, True)
    curves = []
    while True:
        go.SetCommandPrompt("Select closed roof boundaries (plate line) [{}]".format(name))
        go.ClearCommandOptions()
        i_asm = go.AddOption("Assembly")
        ui.add_option_double(go, "PlateHeight", opt_plate)
        i_shape = ui.add_option_list(go, "Shape", SHAPE_OPTIONS, shape_i)
        ui.add_option_double(go, "Pitch", opt_pitch)
        ui.add_option_double(go, "Overhang", opt_ov)
        ui.add_option_double(go, "Rake", opt_rake)
        i_ridge = ui.add_option_list(go, "Ridge", RIDGE_OPTIONS, ridge_i)
        ui.add_option_toggle(go, "Flip", opt_flip)
        i_sys = ui.add_option_list(go, "System", SYSTEM_OPTIONS, sys_i)
        i_lod = ui.add_option_list(go, "Detail", LOD_OPTIONS, lod_i)
        i_draw = go.AddOption("Draw")
        res = go.GetMultiple(1, 0)
        if res == RI.GetResult.Option:
            oi = go.OptionIndex()
            if oi == i_asm:
                picked = ui.pick_assembly(lib, roofkind.KIND, "Mind Canvas - Roof")
                if picked:
                    name = picked
                    shape_i, opt_pitch, opt_ov, opt_rake = _defaults(name)
            elif oi == i_shape:
                shape_i = go.Option().CurrentListOptionIndex
            elif oi == i_ridge:
                ridge_i = go.Option().CurrentListOptionIndex
            elif oi == i_sys:
                sys_i = go.Option().CurrentListOptionIndex
            elif oi == i_lod:
                lod_i = go.Option().CurrentListOptionIndex
            elif oi == i_draw:
                curves = [c for c in _draw_polyline(doc) if c.Geometry.IsClosed]
                break
            continue
        if res == RI.GetResult.Object:
            curves = [go.Object(i).Object() for i in range(go.ObjectCount)]
            break
        return ui.Result.Cancel
    if not curves:
        ui.say("Roofs need closed boundary curves.")
        return ui.Result.Cancel
    base = round(units.to_inches(doc, opt_plate.CurrentValue), 4)
    scriptcontext.sticky[STICKY] = {"base_offset": base, "lod": LOD_OPTIONS[lod_i]}
    doc.Objects.UnselectAll()
    s = roof_settings(lib, name)
    for c in curves:
        if meta.is_driver(c) and meta.get(c, meta.TYPE) != roofkind.KIND:
            ui.say("Skipped a curve that already drives a {}.".format(meta.get(c, meta.TYPE)))
            continue
        params = {"base_offset": base, "lod": roofkind.LODS[lod_i]}
        shape = SHAPE_OPTIONS[shape_i].lower()
        if shape != s["shape"]:
            params["shape"] = shape
        for key, opt in (("pitch", opt_pitch), ("overhang", opt_ov), ("rake", opt_rake)):
            v = opt.CurrentValue if key == "pitch" else units.to_inches(doc, opt.CurrentValue)
            if abs(v - units.parse_length(s[key])) > 1e-4:
                params[key] = round(v, 4)
        ridge = RIDGE_OPTIONS[ridge_i].lower()
        if ridge == "edge":
            ang = pick_edge_angle(doc, c.Geometry, "Click the boundary edge the ridge / eaves run along")
            if ang is None:
                return ui.Result.Cancel
            params["ridge"] = ang
        elif ridge != s["ridge"]:
            params["ridge"] = ridge
        if opt_flip.CurrentValue:
            params["flip"] = True
        params = system_override(lib, name, SYSTEM_OPTIONS[sys_i], params)
        if meta.is_driver(c):
            r = engine.set_assembly(doc, c, name)
        else:
            r = engine.create(doc, c, name, params)
        ui.report(r, "Roof:")
    doc.Views.Redraw()
    return ui.Result.Success
