"""Spike Q1: export the active (live, clipped, section-styled) perspective view to vector PDF + SVG.

Defines export_view_pdf(doc, view, path, ...) and export_view_svg(...). When run as __main__
exports the active view to docs/spike-output/03_live_export.{pdf,svg} and reports what the
vector output contains (counts of paths / fills) so we can tell whether section fills survive.
"""
import os
import re
import time
import Rhino
import System

doc = __rhino_doc__
VCS = Rhino.Display.ViewCaptureSettings


def _settings(doc, view, width_in=17.0, height_in=11.0, dpi=300, raster=False):
    size = System.Drawing.Size(int(width_in * dpi), int(height_in * dpi))
    s = VCS(view, size, dpi)
    s.RasterMode = raster              # False = vector output
    s.OutputColor = VCS.ColorMode.PrintColor
    s.UsePrintWidths = True            # object/layer PlotWeight drives line width
    s.DrawBackground = False
    s.DrawGrid = s.DrawAxis = False
    s.DrawClippingPlanes = False
    s.DrawMargins = False
    s.MatchViewportAspectRatio()
    return s


def export_view_pdf(doc, view, path, **kw):
    pdf = Rhino.FileIO.FilePdf.Create()
    pdf.AddPage(_settings(doc, view, **kw))
    pdf.Write(path)
    return path


def export_view_svg(doc, view, path, **kw):
    xml = Rhino.Display.ViewCapture.CaptureToSvg(_settings(doc, view, **kw))
    xml.Save(path)
    return path


if __name__ == "__main__":
    out = os.path.join(r"C:\Users\jakob\Desktop\BAC\Rhino Mind Canvas", "docs", "spike-output")
    v = doc.Views.ActiveView
    t = time.time()
    p_pdf = export_view_pdf(doc, v, os.path.join(out, "03_live_export.pdf"))
    t_pdf = time.time() - t
    t = time.time()
    p_svg = export_view_svg(doc, v, os.path.join(out, "03_live_export.svg"))
    t_svg = time.time() - t
    svg = open(p_svg, encoding="utf-8", errors="ignore").read()
    EXPORT_RESULT = {
        "pdf_bytes": os.path.getsize(p_pdf), "pdf_s": round(t_pdf, 2),
        "svg_bytes": len(svg), "svg_s": round(t_svg, 2),
        "svg_paths": svg.count("<path"), "svg_polylines": svg.count("<polyline"),
        "svg_lines": svg.count("<line"), "svg_images": svg.count("<image"),
        "svg_fills": len(re.findall(r'fill="(?!none)[^"]+"', svg)),
        "svg_fill_colors": sorted(set(re.findall(r'fill="([^"]+)"', svg)))[:10],
        "svg_stroke_widths": sorted(set(re.findall(r'stroke-width="([^"]+)"', svg)))[:20],
    }
    print(EXPORT_RESULT)
