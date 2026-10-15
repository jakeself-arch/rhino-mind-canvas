"""MCSectionCut: pick a wall where to cut -> clipping plane perpendicular to the wall
there + a named view looking at the cut (parallel wall section, or perspective)."""

import scriptcontext
import Rhino

from .. import library, meta
from ..drawing import sectioncut, styles
from . import ui

RI = Rhino.Input
STICKY = "mindcanvas.sectioncut.settings"


def run():
    doc = ui.doc()
    lib = library.get()
    names = styles.names(lib)
    options = [styles.get(n, lib).option for n in names]
    s = scriptcontext.sticky.get(STICKY, {})
    scale_i = options.index(s["scale"]) if s.get("scale") in options else max(0, len(options) - 2)
    o_persp = RI.Custom.OptionToggle(s.get("perspective", False), "No", "Yes")
    o_depth = RI.Custom.OptionDouble(float(s.get("depth", 24.0)), 0.0, 10000.0)

    go = RI.Custom.GetObject()
    go.SubObjectSelect = False
    go.GroupSelect = False
    go.EnablePreSelect(False, True)

    def _ok(rh_obj, geom, ci):
        drv = meta.driver_of(doc, rh_obj)
        return drv is not None and meta.get(drv, meta.TYPE) == "wall"

    go.SetCustomGeometryFilter(RI.Custom.GetObjectGeometryFilter(_ok))
    while True:
        go.SetCommandPrompt("Pick a wall where to cut")
        go.ClearCommandOptions()
        i_scale = ui.add_option_list(go, "Scale", options, scale_i)
        ui.add_option_toggle(go, "Perspective", o_persp)
        ui.add_option_double(go, "DepthInches", o_depth)
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
                                    "depth": o_depth.CurrentValue}
    r = sectioncut.make(doc, drv, pt, doc.Views.ActiveView, depth_in=o_depth.CurrentValue,
                        perspective=o_persp.CurrentValue, style=names[scale_i])
    ui.say("Section '{}': {} clipping plane(s), named view saved. MCDrawing draws it.".format(
        r["name"], len(r["clip_ids"])))
    return ui.Result.Success
