"""MCCurtainWall: turn curves into curtain walls (or draw a new polyline).

Pick a curtain-wall assembly, then select curves. Options: Assembly, Height, Spacing (grid
module), Style (Captured / SSG4 / SSG2 / Butt / Unitized), Detail level, Draw."""

import scriptcontext
import Rhino

from .. import engine, library, meta, units
from ..kinds import curtainwall as cwkind
from . import ui
from .wall import LOD_OPTIONS, _draw_polyline

RI = Rhino.Input
STYLE_OPTIONS = ["Captured", "SSG4", "SSG2", "Butt", "Unitized"]
STICKY = "mindcanvas.curtainwall.settings"


def style_index(style):
    return list(cwkind.STYLES).index(style) if style in cwkind.STYLES else 0


def run():
    doc = ui.doc()
    lib = library.get()
    if not engine.tolerance_ok(doc):
        ui.say("Mind Canvas: model tolerance is too coarse for assembly detail. Run MCSetup first.")
    names = lib.assemblies(cwkind.KIND)
    if not names:
        ui.say("No curtain-wall assemblies in library/assemblies.")
        return ui.Result.Cancel
    name = ui.current_assembly(lib, cwkind.KIND, doc)   # Assembly option changes it; no dialog
    st = scriptcontext.sticky.get(STICKY, {})

    def _defaults(asm_name):
        asm = lib.assembly(asm_name)
        h = units.parse_length(asm.get("default_height", "13'-4\""))
        sp = units.parse_length(asm.get("spacing", 60))
        return ui.length_option(h, doc), ui.length_option(sp, doc), style_index(asm.get("style", "captured"))

    opt_h, opt_sp, style_i = _defaults(name)
    lod_i = LOD_OPTIONS.index(st.get("lod", "Detail")) if st.get("lod") in LOD_OPTIONS else 2

    go = RI.Custom.GetObject()
    go.GeometryFilter = Rhino.DocObjects.ObjectType.Curve
    go.EnablePreSelect(True, True)
    curves = []
    while True:
        go.SetCommandPrompt("Select curtain wall curves [{}]".format(name))
        go.ClearCommandOptions()
        i_asm = go.AddOption("Assembly")
        ui.add_option_double(go, "Height", opt_h)
        ui.add_option_double(go, "Spacing", opt_sp)
        i_style = ui.add_option_list(go, "Style", STYLE_OPTIONS, style_i)
        i_lod = ui.add_option_list(go, "Detail", LOD_OPTIONS, lod_i)
        i_draw = go.AddOption("Draw")
        res = go.GetMultiple(1, 0)
        if res == RI.GetResult.Option:
            oi = go.OptionIndex()
            if oi == i_asm:
                picked = ui.pick_assembly(lib, cwkind.KIND, "Mind Canvas - Curtain Wall")
                if picked:
                    name = picked
                    opt_h, opt_sp, style_i = _defaults(name)
            elif oi == i_style:
                style_i = go.Option().CurrentListOptionIndex
            elif oi == i_lod:
                lod_i = go.Option().CurrentListOptionIndex
            elif oi == i_draw:
                curves = _draw_polyline(doc)
                break
            continue
        if res == RI.GetResult.Object:
            curves = [go.Object(i).Object() for i in range(go.ObjectCount)]
            break
        return ui.Result.Cancel
    if not curves:
        return ui.Result.Cancel
    asm = lib.assembly(name)
    params = {
        "height": round(units.to_inches(doc, opt_h.CurrentValue), 4),
        "lod": ["schematic", "design", "detail"][lod_i],
    }
    sp = round(units.to_inches(doc, opt_sp.CurrentValue), 4)
    if abs(sp - units.parse_length(asm.get("spacing", 60))) > 1e-3:
        params["spacing"] = sp
    style = cwkind.STYLES[style_i]
    if style != asm.get("style", "captured"):
        params["style"] = style
    scriptcontext.sticky[STICKY] = {"lod": LOD_OPTIONS[lod_i]}
    for c in curves:
        if meta.is_driver(c) and meta.get(c, meta.TYPE) != cwkind.KIND:
            ui.say("Skipped a {} curve (it already drives a {}).".format(meta.get(c, meta.TYPE), meta.get(c, meta.TYPE)))
            continue
        if meta.is_driver(c):
            r = engine.set_assembly(doc, c, name)
        else:
            r = engine.create(doc, c, name, params)
        ui.report(r, "Curtain wall:")
    doc.Objects.UnselectAll()
    doc.Views.Redraw()
    return ui.Result.Success
