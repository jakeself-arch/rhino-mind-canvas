"""MCDrawing: crisp 2D drawing of the active view and its clipping planes - SVG
(true line widths) + PNG preview, and/or baked curves with plot weights."""

import os
import re
import time

import scriptcontext
import System
import Rhino

from .. import library
from ..drawing import pipeline, styles
from . import ui

RI = Rhino.Input
STICKY = "mindcanvas.drawing.settings"
OUTPUTS = ["SVG", "Bake", "Both"]


def default_folder(doc):
    if doc.Path:
        return os.path.join(os.path.dirname(doc.Path), "drawings")
    return os.path.join(os.path.expanduser("~"), "Documents", "MindCanvas Drawings")


def _slug(s):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_") or "drawing"


def _pick_window():
    """Drag a screen rectangle; returns two world points on its corner rays."""
    try:
        rc, rect, rview = RI.RhinoGet.Get2dRectangle(True, System.Drawing.Rectangle(), None)
    except TypeError:
        rc, rect, rview = RI.RhinoGet.Get2dRectangle(True)
    if rc != Rhino.Commands.Result.Success or rview is None:
        return None
    vp = rview.ActiveViewport
    pts = []
    for x, y in ((rect.Left, rect.Top), (rect.Right, rect.Bottom)):
        ok, ln = vp.GetFrustumLine(x, y)
        if not ok:
            return None
        pts.append(ln.PointAt(0.5))
    return pts


def run():
    doc = ui.doc()
    lib = library.get()
    view = doc.Views.ActiveView
    names = styles.names(lib)
    if not names:
        ui.say("No drawing styles in library/styles.")
        return ui.Result.Failure
    options = [styles.get(n, lib).option for n in names]
    s = scriptcontext.sticky.get(STICKY, {})
    scale_i = options.index(s["scale"]) if s.get("scale") in options else (options.index("Eighth") if "Eighth" in options else 0)
    out_i = OUTPUTS.index(s.get("output", "SVG"))
    o_tone = RI.Custom.OptionToggle(s.get("tone", True), "Off", "On")
    o_stip = RI.Custom.OptionToggle(s.get("stipple", True), "Off", "On")
    o_lod = RI.Custom.OptionToggle(s.get("lod", False), "No", "Yes")
    folder = s.get("folder") or default_folder(doc)

    window = None
    go = RI.Custom.GetOption()
    go.AcceptNothing(True)
    while True:
        go.SetCommandPrompt("Drawing of '{}'{} (Enter to draw)".format(
            view.ActiveViewport.Name, ", cropped to window" if window else ""))
        go.ClearCommandOptions()
        i_scale = ui.add_option_list(go, "Scale", options, scale_i)
        i_out = ui.add_option_list(go, "Output", OUTPUTS, out_i)
        ui.add_option_toggle(go, "Tone", o_tone)
        ui.add_option_toggle(go, "Stipple", o_stip)
        ui.add_option_toggle(go, "SetLOD", o_lod)
        i_folder = ui._idx(go.AddOption("Folder"))
        i_win = ui._idx(go.AddOption("Window"))
        res = go.Get()
        if res == RI.GetResult.Option:
            idx = go.OptionIndex()
            if idx == i_scale:
                scale_i = go.Option().CurrentListOptionIndex
            elif idx == i_out:
                out_i = go.Option().CurrentListOptionIndex
            elif idx == i_win:
                window = _pick_window()
                if window:
                    view = doc.Views.ActiveView
            elif idx == i_folder:
                rc, txt = RI.RhinoGet.GetString("Output folder", True, folder)
                if rc == Rhino.Commands.Result.Success and txt:
                    folder = txt.strip().strip('"')
            continue
        if res == RI.GetResult.Nothing:
            break
        return ui.Result.Cancel

    style = styles.get(names[scale_i], lib)
    output = OUTPUTS[out_i]
    scriptcontext.sticky[STICKY] = {"scale": options[scale_i], "output": output, "tone": o_tone.CurrentValue,
                                    "stipple": o_stip.CurrentValue, "lod": o_lod.CurrentValue, "folder": folder}
    t0 = time.time()
    if o_lod.CurrentValue:
        pipeline.set_lod(doc, style, ui.say)
    try:
        dwg = pipeline.make(doc, view, style, o_tone.CurrentValue, o_stip.CurrentValue, ui.say, interactive=True,
                            window=window)
    except pipeline.Cancelled as ex:
        ui.say(str(ex))
        return ui.Result.Cancel
    paths = []
    if output in ("SVG", "Both"):
        name = "{}_{}_{}".format(_slug(os.path.splitext(doc.Name or "untitled")[0]),
                                 _slug(view.ActiveViewport.Name), style.option)
        paths = pipeline.write(dwg, os.path.join(folder, name))
    if output in ("Bake", "Both"):
        from ..drawing.writers import bake
        n, origin, _ = bake.bake(doc, dwg)
        ui.say("Baked {} objects at ({:.1f}, {:.1f}) on 'MindCanvas Drawing' layers.".format(n, origin.X, origin.Y))
    st = dwg.stats
    ui.say("MCDrawing {}: {:.1f}s, {} lines, {} cut regions, {} dots, page {:.0f} x {:.0f} mm.".format(
        style.name, time.time() - t0, st["lines"], st["regions"], st["dots"] + st["cut_dots"], *dwg.size))
    for p in paths:
        ui.say("  " + p)
    for w in dwg.warnings:
        ui.say("  warning: " + w)
    if st.get("small", 0) > 0.3 * max(st.get("items", 1), 1) and not o_lod.CurrentValue:
        ui.say("  {} parts were too small to draw at {}; SetLOD=Yes rebuilds walls at '{}' LOD.".format(
            st["small"], style.name, style.lod))
    return ui.Result.Success
