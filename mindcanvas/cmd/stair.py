"""MCStair: turn a curve into a stair (or draw a polyline).

The curve is the LEFT or RIGHT side of the stair in plan; corners become landings, curved parts
curved flights. A CLOSED curve (a circle or rounded rectangle around an elevator) makes a stair
that winds around it: you click where it starts and which way it goes up; Laps = times around.
Options: Assembly, FloorHeight (floor to floor), Floors (floors climbed: a landing at each floor),
Laps (closed curves), Width, Elevation (lower floor above the curve), Side (Left / Right: which side
of the stair the curve is, looking up), MaxRiserInches, LandingsPerFloor (evenly spaced), Draw.
With one curve you then click the bottom, the side the stair goes and any landing centers (Enter
skips each step). Risers come from the floor height, treads are fitted to the curve's length."""

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


def _get_point(prompt, curve=None):
    gp = RI.Custom.GetPoint()
    gp.SetCommandPrompt(prompt)
    gp.AcceptNothing(True)
    if curve is not None:
        gp.Constrain(curve, False)
    if gp.Get() != RI.GetResult.Point:
        return None
    return gp.Point()


def along(curve, p, doc):
    """Inches along the curve (as drawn) to the point nearest p."""
    ok, t = curve.ClosestPoint(p)
    return round(units.to_inches(doc, curve.GetLength(G.Interval(curve.Domain.T0, t))), 4)


def pick_bottom(doc, curve):
    """Open curve: click near the bottom end -> flip (True = up from the curve's end); None = Enter."""
    p = _get_point("Click near the BOTTOM end of the stair (Enter = the curve's start)")
    if p is None:
        return None
    return p.DistanceTo(curve.PointAtEnd) < p.DistanceTo(curve.PointAtStart)


def pick_start(doc, curve):
    """Closed curve: (start inches, flip) from a click where the stair starts and a click a little
    way along in the direction it goes up; None for a skipped step."""
    p = _get_point("Click on the curve where the stair STARTS (bottom) (Enter = the curve's seam)", curve)
    start = along(curve, p, doc) if p is not None else None
    q = _get_point("Click a little further along the curve, the way the stair goes UP (Enter = as drawn)", curve)
    flip = None
    if q is not None:
        L = units.to_inches(doc, curve.GetLength())
        d = (along(curve, q, doc) - (start or 0.0)) % L
        flip = d > L / 2.0
    return start, flip


def pick_side(doc, curve, flip):
    """Click on the side the stair goes -> "left" / "right" (which side of the stair the curve is
    when walking up); None = Enter."""
    p = _get_point("Click on the side of the curve the stair goes (Enter = the Side option)")
    if p is None:
        return None
    ok, t = curve.ClosestPoint(p)
    q, tan = curve.PointAt(t), curve.TangentAt(t)
    if flip:
        tan = -tan
    cross = tan.X * (p.Y - q.Y) - tan.Y * (p.X - q.X)
    return "right" if cross > 0 else "left"     # stair left of travel = the curve is its right side


def pick_landings(doc, curve, current=None):
    """Click landing centers on the curve (Enter when done) -> inches along the curve as drawn."""
    out = list(current or [])
    while True:
        p = _get_point("Click the center of a landing on the curve ({} so far, Enter when done)".format(len(out)),
                       curve)
        if p is None:
            return out
        out.append(along(curve, p, doc))


def run():
    doc = ui.doc()
    lib = library.get()
    if not engine.tolerance_ok(doc):
        ui.say("Mind Canvas: model tolerance is too coarse for assembly detail. Run MCSetup first.")
    names = lib.assemblies(stairkind.KIND)
    if not names:
        ui.say("No stair assemblies in library/assemblies.")
        return ui.Result.Cancel
    name = ui.current_assembly(lib, stairkind.KIND, doc)   # Assembly option changes it; no dialog
    st =scriptcontext.sticky.get(STICKY, {})
    opt_h = ui.length_option(float(st.get("height", stairkind.DEFAULTS["height"])), doc)
    opt_floors = RI.Custom.OptionInteger(int(st.get("floors", 1)), 1, 100)
    opt_laps = RI.Custom.OptionDouble(float(st.get("laps", 1.0)), 0.05, 50.0)
    opt_w = ui.length_option(float(st.get("width", stairkind.DEFAULTS["width"])), doc)
    opt_el = ui.length_option(float(st.get("base_offset", 0.0)), doc)
    opt_r = RI.Custom.OptionDouble(float(st.get("max_riser") or lib.assembly(name).get("max_riser", 7)), 4.0, 12.0)
    opt_lc = RI.Custom.OptionInteger(int(st.get("landing_count", 0)), 0, 50)
    side_i = SIDE_OPTIONS.index(st.get("side", "Left")) if st.get("side") in SIDE_OPTIONS else 0

    go = RI.Custom.GetObject()
    go.GeometryFilter = Rhino.DocObjects.ObjectType.Curve
    go.EnablePreSelect(True, True)
    curves = []
    while True:
        go.SetCommandPrompt("Select the curve along one side of the stair (closed = winds around) [{}]".format(name))
        go.ClearCommandOptions()
        i_asm = go.AddOption("Assembly")
        ui.add_option_double(go, "FloorHeight", opt_h)
        ui._idx(go.AddOptionInteger("Floors", opt_floors))
        ui.add_option_double(go, "Laps", opt_laps)
        ui.add_option_double(go, "Width", opt_w)
        ui.add_option_double(go, "Elevation", opt_el)
        i_side = ui.add_option_list(go, "Side", SIDE_OPTIONS, side_i)
        ui.add_option_double(go, "MaxRiserInches", opt_r)
        ui._idx(go.AddOptionInteger("LandingsPerFloor", opt_lc))
        i_draw = go.AddOption("Draw")
        res = go.GetMultiple(1, 0)
        if res == RI.GetResult.Option:
            oi = go.OptionIndex()
            if oi == i_asm:
                name = ui.pick_assembly(lib, stairkind.KIND, "Mind Canvas - Stair") or name
            elif oi == i_side:
                side_i = go.Option().CurrentListOptionIndex
            elif oi == i_draw:
                curves = _draw_polyline(doc)
                break
            continue
        if res == RI.GetResult.Object:
            curves = [go.Object(i).Object() for i in range(go.ObjectCount)]
            break
        return ui.Result.Cancel
    if not curves:
        ui.say("Stairs need a curve along one side.")
        return ui.Result.Cancel
    params = {"height": round(units.to_inches(doc, opt_h.CurrentValue), 4),
              "width": round(units.to_inches(doc, opt_w.CurrentValue), 4),
              "base_offset": round(units.to_inches(doc, opt_el.CurrentValue), 4),
              "side": SIDE_OPTIONS[side_i].lower()}
    if opt_floors.CurrentValue > 1:
        params["floors"] = opt_floors.CurrentValue
    if opt_lc.CurrentValue > 0:
        params["landing_count"] = opt_lc.CurrentValue
    asm_riser = float(lib.assembly(name).get("max_riser", stairkind.SETTINGS["max_riser"]))
    if abs(opt_r.CurrentValue - asm_riser) > 1e-6:
        params["max_riser"] = round(opt_r.CurrentValue, 4)
    sticky = dict(params)
    sticky.update(side=SIDE_OPTIONS[side_i], max_riser=opt_r.CurrentValue, floors=opt_floors.CurrentValue,
                  laps=opt_laps.CurrentValue, landing_count=opt_lc.CurrentValue)
    scriptcontext.sticky[STICKY] = sticky
    doc.Objects.UnselectAll()
    for c in curves:
        if meta.is_driver(c) and meta.get(c, meta.TYPE) != stairkind.KIND:
            ui.say("Skipped a curve that already drives a {}.".format(meta.get(c, meta.TYPE)))
            continue
        prm = dict(params)
        crv = c.Geometry
        if crv.IsClosed:
            prm["laps"] = round(opt_laps.CurrentValue, 4)
        if len(curves) == 1 and not meta.is_driver(c):
            doc.Views.Redraw()
            if crv.IsClosed:
                start, flip = pick_start(doc, crv)
                if start is not None:
                    prm["start"] = start
            else:
                flip = pick_bottom(doc, crv)
            if flip is not None:
                prm["flip"] = flip
            side = pick_side(doc, crv, prm.get("flip", False))
            if side is not None:
                prm["side"] = side
            landings = pick_landings(doc, crv)
            if landings:
                prm["landings"] = landings
        if meta.is_driver(c):
            r = engine.set_assembly(doc, c, name)
        else:
            r = engine.create(doc, c, name, prm)
        ui.report(r, "Stair:")
        ui.say("  " + describe(doc, lib, doc.Objects.FindId(c.Id)))
    doc.Views.Redraw()
    return ui.Result.Success
