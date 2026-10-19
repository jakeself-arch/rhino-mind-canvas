"""MCStair: turn an open curve into a stair (or draw a polyline).

The curve is the LEFT or RIGHT side of the stair in plan; corners become landings, curved parts
curved flights. Pick a stair assembly, then select the curve(s). Options: Assembly, FloorHeight
(floor to floor), Width, Elevation (lower floor above the curve), Side (Left / Right: which side of
the stair the curve is, looking up), MaxRiserInches, Draw. With one curve you then click near the
bottom end and on the side the stair goes (Enter keeps the curve start / the Side option).
Risers come from the floor height, treads are fitted to the curve's length."""

import scriptcontext
import Rhino

from .. import engine, library, meta, units
from ..kinds import stair as stairkind
from . import ui
from .wall import _draw_polyline

RI = Rhino.Input
G = Rhino.Geometry
SIDE_OPTIONS = ["Left", "Right"]
STICKY = "mindcanvas.stair.settings"


def describe(doc, lib, obj):
    try:
        ctx = stairkind.make_context(doc, lib, obj, meta.get(obj, meta.ASSEMBLY), meta.params(obj))
        return stairkind.describe(ctx)
    except Exception as ex:
        return "({})".format(ex)


def pick_bottom(doc, curve):
    """Click near the bottom end -> flip (True = the stair goes up from the curve's end); None = Enter."""
    gp = RI.Custom.GetPoint()
    gp.SetCommandPrompt("Click near the BOTTOM end of the stair (Enter = the curve's start)")
    gp.AcceptNothing(True)
    if gp.Get() != RI.GetResult.Point:
        return None
    p = gp.Point()
    return p.DistanceTo(curve.PointAtEnd) < p.DistanceTo(curve.PointAtStart)


def pick_side(doc, curve, flip):
    """Click on the side the stair goes -> "left" / "right" (which side of the stair the curve is
    when walking up); None = Enter."""
    gp = RI.Custom.GetPoint()
    gp.SetCommandPrompt("Click on the side of the curve the stair goes (Enter = the Side option)")
    gp.AcceptNothing(True)
    if gp.Get() != RI.GetResult.Point:
        return None
    p = gp.Point()
    ok, t = curve.ClosestPoint(p)
    q, tan = curve.PointAt(t), curve.TangentAt(t)
    if flip:
        tan = -tan
    cross = tan.X * (p.Y - q.Y) - tan.Y * (p.X - q.X)
    return "right" if cross > 0 else "left"     # stair left of travel = the curve is its right side


def run():
    doc = ui.doc()
    lib = library.get()
    if not engine.tolerance_ok(doc):
        ui.say("Mind Canvas: model tolerance is too coarse for assembly detail. Run MCSetup first.")
    names = lib.assemblies(stairkind.KIND)
    if not names:
        ui.say("No stair assemblies in library/assemblies.")
        return ui.Result.Cancel
    name = scriptcontext.sticky.get(ui.LAST_ASSEMBLY + stairkind.KIND)
    if name not in names:
        name = ui.pick_assembly(lib, stairkind.KIND, "Mind Canvas - Stair")
        if not name:
            return ui.Result.Cancel
    st = scriptcontext.sticky.get(STICKY, {})
    opt_h = ui.length_option(float(st.get("height", stairkind.DEFAULTS["height"])), doc)
    opt_w = ui.length_option(float(st.get("width", stairkind.DEFAULTS["width"])), doc)
    opt_el = ui.length_option(float(st.get("base_offset", 0.0)), doc)
    opt_r = RI.Custom.OptionDouble(float(st.get("max_riser") or lib.assembly(name).get("max_riser", 7)), 4.0, 12.0)
    side_i = SIDE_OPTIONS.index(st.get("side", "Left")) if st.get("side") in SIDE_OPTIONS else 0

    go = RI.Custom.GetObject()
    go.GeometryFilter = Rhino.DocObjects.ObjectType.Curve
    go.GeometryAttributeFilter = RI.Custom.GeometryAttributeFilter.OpenCurve
    go.EnablePreSelect(True, True)
    curves = []
    while True:
        go.SetCommandPrompt("Select the curve along one side of the stair [{}]".format(name))
        go.ClearCommandOptions()
        i_asm = go.AddOption("Assembly")
        ui.add_option_double(go, "FloorHeight", opt_h)
        ui.add_option_double(go, "Width", opt_w)
        ui.add_option_double(go, "Elevation", opt_el)
        i_side = ui.add_option_list(go, "Side", SIDE_OPTIONS, side_i)
        ui.add_option_double(go, "MaxRiserInches", opt_r)
        i_draw = go.AddOption("Draw")
        res = go.GetMultiple(1, 0)
        if res == RI.GetResult.Option:
            oi = go.OptionIndex()
            if oi == i_asm:
                name = ui.pick_assembly(lib, stairkind.KIND, "Mind Canvas - Stair") or name
            elif oi == i_side:
                side_i = go.Option().CurrentListOptionIndex
            elif oi == i_draw:
                curves = [c for c in _draw_polyline(doc) if not c.Geometry.IsClosed]
                break
            continue
        if res == RI.GetResult.Object:
            curves = [go.Object(i).Object() for i in range(go.ObjectCount)]
            break
        return ui.Result.Cancel
    if not curves:
        ui.say("Stairs need an open curve along one side.")
        return ui.Result.Cancel
    params = {"height": round(units.to_inches(doc, opt_h.CurrentValue), 4),
              "width": round(units.to_inches(doc, opt_w.CurrentValue), 4),
              "base_offset": round(units.to_inches(doc, opt_el.CurrentValue), 4),
              "side": SIDE_OPTIONS[side_i].lower()}
    asm_riser = float(lib.assembly(name).get("max_riser", stairkind.SETTINGS["max_riser"]))
    if abs(opt_r.CurrentValue - asm_riser) > 1e-6:
        params["max_riser"] = round(opt_r.CurrentValue, 4)
    sticky = dict(params)
    sticky["side"] = SIDE_OPTIONS[side_i]
    sticky["max_riser"] = opt_r.CurrentValue
    scriptcontext.sticky[STICKY] = sticky
    doc.Objects.UnselectAll()
    for c in curves:
        if meta.is_driver(c) and meta.get(c, meta.TYPE) != stairkind.KIND:
            ui.say("Skipped a curve that already drives a {}.".format(meta.get(c, meta.TYPE)))
            continue
        prm = dict(params)
        if len(curves) == 1 and not meta.is_driver(c):
            doc.Views.Redraw()
            flip = pick_bottom(doc, c.Geometry)
            if flip is not None:
                prm["flip"] = flip
            side = pick_side(doc, c.Geometry, prm.get("flip", False))
            if side is not None:
                prm["side"] = side
        if meta.is_driver(c):
            r = engine.set_assembly(doc, c, name)
        else:
            r = engine.create(doc, c, name, prm)
        ui.report(r, "Stair:")
        ui.say("  " + describe(doc, lib, doc.Objects.FindId(c.Id)))
    doc.Views.Redraw()
    return ui.Result.Success
