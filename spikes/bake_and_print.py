"""Spike Q6: bake the 2D drawing into the doc (layers per line class + per-object PlotWeight /
PlotColor for depth falloff, Rhino Hatch objects for white cut fills) and print it to vector PDF
+ SVG through ViewCaptureSettings (UsePrintWidths) from the Top view.

Expects DWG (from build_drawing) in globals, plus hld_drawing.py + export_vector.py helpers.
"""
import os
import Rhino
import System

doc = __rhino_doc__
O = r"C:\Users\jakob\Desktop\BAC\Rhino Mind Canvas\docs\spike-output\\"
ORIGIN = (5000.0, 0.0)

# clear previous bake
root = doc.Layers.FindByFullPath("MC Drawing", -1)
if root >= 0:
    for L in doc.Layers:
        if L.FullPath.startswith("MC Drawing"):
            for o in doc.Objects.FindByLayer(L) or []:
                doc.Objects.Delete(o, True)

n = bake(DWG, doc, ORIGIN, STYLE)
pw, ph = STYLE["page_mm"]

# hide everything that is not the drawing
hidden = []
for L in doc.Layers:
    if not L.FullPath.startswith("MC Drawing") and L.IsVisible and L.Index != doc.Layers.CurrentLayerIndex:
        L.IsVisible = False
        hidden.append(L.Index)
clips = [o for o in doc.Objects if isinstance(o, Rhino.DocObjects.ClippingPlaneObject)]
for o in clips:
    doc.Objects.Hide(o, True)

top = [v for v in doc.Views if v.ActiveViewport.Name == "Top"][0]
vp = top.ActiveViewport
vp.DisplayMode = Rhino.Display.DisplayModeDescription.GetDisplayMode(Rhino.Display.DisplayModeDescription.WireframeId)
bb = Rhino.Geometry.BoundingBox(Rhino.Geometry.Point3d(ORIGIN[0], ORIGIN[1], 0), Rhino.Geometry.Point3d(ORIGIN[0] + pw, ORIGIN[1] + ph, 0))
vp.ZoomBoundingBox(bb)
doc.Views.Redraw()

VCS = Rhino.Display.ViewCaptureSettings
dpi = 300
s = VCS(top, System.Drawing.Size(int(pw / 25.4 * dpi), int(ph / 25.4 * dpi)), dpi)
s.RasterMode = False
s.UsePrintWidths = True
s.OutputColor = VCS.ColorMode.PrintColor
s.DrawBackground = False
s.DrawGrid = s.DrawAxis = False
s.SetWindowRect(Rhino.Geometry.Point3d(ORIGIN[0], ORIGIN[1], 0), Rhino.Geometry.Point3d(ORIGIN[0] + pw, ORIGIN[1] + ph, 0))
pdf = Rhino.FileIO.FilePdf.Create()
pdf.AddPage(s)
pdf.Write(O + "11_baked_print.pdf")
xml = Rhino.Display.ViewCapture.CaptureToSvg(s)
xml.Save(O + "11_baked_print.svg")

# restore
for i in hidden:
    doc.Layers[i].IsVisible = True
for o in clips:
    doc.Objects.Show(o, True)
doc.Views.Redraw()

import re
svg = open(O + "11_baked_print.svg", encoding="utf-8", errors="ignore").read()
widths = re.findall(r'stroke-width="([^"]+)"', svg)
from collections import Counter
BAKE_RESULT = {"baked": n, "pdf_bytes": os.path.getsize(O + "11_baked_print.pdf"),
               "svg_paths": svg.count("<path"), "distinct_widths": len(set(widths)),
               "top_widths": Counter(widths).most_common(8)}
print(BAKE_RESULT)
