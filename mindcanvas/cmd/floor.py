"""MCFloor: turn closed curves into floors (or draw a closed polyline).

Pick a floor assembly, then select closed boundary curves (the outside face of the rim = the outside
face of the wall framing below). Options: Assembly, Elevation (base offset of the framing bottom,
e.g. the wall height), Span (Short / Long / Edge: click the boundary edge the joists bear on),
System (Keep / Wood / Metal), Detail, Draw."""

import math

import scriptcontext
import Rhino

from .. import engine, library, meta, units
from ..kinds import floor as floorkind
from . import ui
from .wall import LOD_OPTIONS, _draw_polyline

RI = Rhino.Input
SPAN_OPTIONS = ["Short", "Long", "Edge"]
SYSTEM_OPTIONS = ["Keep", "Wood", "Metal"]
STICKY = "mindcanvas.floor.settings"


def pick_edge_angle(doc, curve, prompt):
    """Click a point on a boundary: the plan angle (degrees) of the boundary's tangent there."""
    gp = RI.Custom.GetPoint()
    gp.SetCommandPrompt(prompt)
    gp.Constrain(curve, False)
    if gp.Get() != RI.GetResult.Point:
        return None
    ok, t = curve.ClosestPoint(gp.Point())
    tan = curve.TangentAt(t)
    return round(math.degrees(math.atan2(tan.Y, tan.X)) % 180.0, 4)


def framing_layer(lib, driver_or_assembly, params=None):
    """Name of the joist / rafter layer of an assembly (or a driver's)."""
    if isinstance(driver_or_assembly, str):
        asm, prm = lib.assembly(driver_or_assembly), params or {}
    else:
        asm, prm = lib.assembly(meta.get(driver_or_assembly, meta.ASSEMBLY)), meta.params(driver_or_assembly)
    from ..kinds import wall as wallkind
    for i, spec in enumerate(prm.get("layers") or asm.get("layers") or []):
        spec = lib.resolve_layer(spec)
        if spec.get("component") in ("joists", "framing", "rafters"):
            return wallkind.layer_name(spec, i)
    return None


def system_override(lib, driver_or_assembly, system, params):
    """params with overrides[<framing layer>]["system"] set (system "Wood" / "Metal"; "Keep" = no change)."""
    if system == "Keep":
        return params
    name = framing_layer(lib, driver_or_assembly, params)
    if not name:
        return params
    ov = dict(params.get("overrides", {}))
    lay = dict(ov.get(name, {}))
    if lay.get("system") != system.lower():
        for k in ("joist", "rafter", "rim", "gauge"):
            lay.pop(k, None)    # a 2x10 is not a metal joist
    lay["system"] = system.lower()
    ov[name] = lay
    out = dict(params)
    out["overrides"] = ov
    return out


def run():
    doc = ui.doc()
    lib = library.get()
    if not engine.tolerance_ok(doc):
        ui.say("Mind Canvas: model tolerance is too coarse for assembly detail. Run MCSetup first.")
    names = lib.assemblies(floorkind.KIND)
    if not names:
        ui.say("No floor assemblies in library/assemblies.")
        return ui.Result.Cancel
    name = scriptcontext.sticky.get(ui.LAST_ASSEMBLY + floorkind.KIND)
    if name not in names:
        name = ui.pick_assembly(lib, floorkind.KIND, "Mind Canvas - Floor")
        if not name:
            return ui.Result.Cancel
    st = scriptcontext.sticky.get(STICKY, {})
    opt_el = ui.length_option(float(st.get("base_offset", 0.0)), doc)
    span_i = SPAN_OPTIONS.index(st.get("span", "Short")) if st.get("span") in SPAN_OPTIONS else 0
    sys_i = 0
    lod_i = LOD_OPTIONS.index(st.get("lod", "Detail")) if st.get("lod") in LOD_OPTIONS else 2

    go = RI.Custom.GetObject()
    go.GeometryFilter = Rhino.DocObjects.ObjectType.Curve
    go.GeometryAttributeFilter = RI.Custom.GeometryAttributeFilter.ClosedCurve
    go.EnablePreSelect(True, True)
    curves = []
    while True:
        go.SetCommandPrompt("Select closed floor boundaries [{}]".format(name))
        go.ClearCommandOptions()
        i_asm = go.AddOption("Assembly")
        ui.add_option_double(go, "Elevation", opt_el)
        i_span = ui.add_option_list(go, "Span", SPAN_OPTIONS, span_i)
        i_sys = ui.add_option_list(go, "System", SYSTEM_OPTIONS, sys_i)
        i_lod = ui.add_option_list(go, "Detail", LOD_OPTIONS, lod_i)
        i_draw = go.AddOption("Draw")
        res = go.GetMultiple(1, 0)
        if res == RI.GetResult.Option:
            oi = go.OptionIndex()
            if oi == i_asm:
                picked = ui.pick_assembly(lib, floorkind.KIND, "Mind Canvas - Floor")
                name = picked or name
            elif oi == i_span:
                span_i = go.Option().CurrentListOptionIndex
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
        ui.say("Floors need closed boundary curves.")
        return ui.Result.Cancel
    base = round(units.to_inches(doc, opt_el.CurrentValue), 4)
    scriptcontext.sticky[STICKY] = {"base_offset": base, "span": SPAN_OPTIONS[span_i], "lod": LOD_OPTIONS[lod_i]}
    doc.Objects.UnselectAll()
    for c in curves:
        if meta.is_driver(c) and meta.get(c, meta.TYPE) != floorkind.KIND:
            ui.say("Skipped a curve that already drives a {}.".format(meta.get(c, meta.TYPE)))
            continue
        span = SPAN_OPTIONS[span_i].lower()
        if span == "edge":
            ang = pick_edge_angle(doc, c.Geometry, "Click the boundary edge the joists bear on")
            if ang is None:
                return ui.Result.Cancel
            span = round((ang + 90.0) % 180.0, 4)
        params = {"base_offset": base, "span": span, "lod": floorkind.LODS[lod_i]}
        params = system_override(lib, name, SYSTEM_OPTIONS[sys_i], params)
        if meta.is_driver(c):
            r = engine.set_assembly(doc, c, name)
        else:
            r = engine.create(doc, c, name, params)
        ui.report(r, "Floor:")
    doc.Views.Redraw()
    return ui.Result.Success
