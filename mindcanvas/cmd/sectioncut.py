"""MCSectionCut: pick a wall or curtain wall where to cut -> clipping plane perpendicular to it
there + a named view looking at the cut (parallel wall section, or perspective). Floors are cut
along their joists, roofs along the slope of the face you click (eave to ridge). Plan=Yes cuts a
horizontal plane at the picked height instead (a plan detail; CutHeight overrides the height)."""

import scriptcontext
import Rhino

from .. import library, meta, units
from ..drawing import sectioncut, styles
from . import ui

RI = Rhino.Input
STICKY = "mindcanvas.sectioncut.settings"
CUTTABLE = ("wall", "curtain_wall", "floor", "roof", "stair")


def run():
    doc = ui.doc()
    lib = library.get()
    names = styles.names(lib)
    options = [styles.get(n, lib).option for n in names]
    s = scriptcontext.sticky.get(STICKY, {})
    scale_i = options.index(s["scale"]) if s.get("scale") in options else max(0, len(options) - 2)
    o_persp = RI.Custom.OptionToggle(s.get("perspective", False), "No", "Yes")
    o_plan = RI.Custom.OptionToggle(s.get("plan", False), "No", "Yes")
    o_depth = RI.Custom.OptionDouble(float(s.get("depth", 24.0)), 0.0, 10000.0)
    o_cut = RI.Custom.OptionDouble(float(s.get("cut", 0.0)), 0.0, 100000.0)

    go = RI.Custom.GetObject()
    go.SubObjectSelect = False
    go.GroupSelect = False
    go.EnablePreSelect(False, True)

    def _ok(rh_obj, geom, ci):
        drv = meta.driver_of(doc, rh_obj)
        return drv is not None and meta.get(drv, meta.TYPE) in CUTTABLE

    go.SetCustomGeometryFilter(RI.Custom.GetObjectGeometryFilter(_ok))
    while True:
        go.SetCommandPrompt("Pick a wall, curtain wall, floor, roof or stair where to cut")
        go.ClearCommandOptions()
        i_scale = ui.add_option_list(go, "Scale", options, scale_i)
        ui.add_option_toggle(go, "Perspective", o_persp)
        ui.add_option_toggle(go, "Plan", o_plan)
        ui.add_option_double(go, "DepthInches", o_depth)
        ui.add_option_double(go, "CutHeightInches", o_cut)
        res = go.Get()
        if res == RI.GetResult.Option:
            if go.OptionIndex() == i_scale:
                scale_i = go.Option().CurrentListOptionIndex
            continue
        if res != RI.GetResult.Object:
            return ui.Result.Cancel
        break
    ref = go.Object(0)
    obj = ref.Object()
    pt = ref.SelectionPoint()
    if not pt.IsValid:
        pt = obj.Geometry.GetBoundingBox(True).Center
    drv = meta.driver_of(doc, obj)
    doc.Objects.UnselectAll()
    scriptcontext.sticky[STICKY] = {"scale": options[scale_i], "perspective": o_persp.CurrentValue,
                                    "plan": o_plan.CurrentValue, "depth": o_depth.CurrentValue,
                                    "cut": o_cut.CurrentValue}
    if o_plan.CurrentValue:
        cut_z = None
        if o_cut.CurrentValue > 0:
            base = drv.Geometry.PointAtStart.Z + units.to_model(doc, meta.params(drv).get("base_offset", 0))
            cut_z = base + units.to_model(doc, o_cut.CurrentValue)
        r = sectioncut.make_plan(doc, drv, pt, doc.Views.ActiveView, cut_z=cut_z, depth_in=o_depth.CurrentValue,
                                 style=names[scale_i])
        ui.say("Plan '{}': {} clipping plane(s), named view saved. MCDrawing draws it.".format(
            r["name"], len(r["clip_ids"])))
        return ui.Result.Success
    r = sectioncut.make(doc, drv, pt, doc.Views.ActiveView, depth_in=o_depth.CurrentValue,
                        perspective=o_persp.CurrentValue, style=names[scale_i])
    ui.say("Section '{}': {} clipping plane(s), named view saved. MCDrawing draws it.".format(
        r["name"], len(r["clip_ids"])))
    return ui.Result.Success
