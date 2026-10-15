"""Spike Q1/Q2: live perspective view with clipping plane + per-layer section styles +
a programmatically created display mode "MC Section" (copied from Pen).

Requires scene_build.py to have run (layers MC::*). Run via exec with __rhino_doc__.
Outputs SECTION_RESULT dict.
"""
import os
import Rhino
import System
from System.Drawing import Color

doc = __rhino_doc__
D = Rhino.DocObjects
DMD = Rhino.Display.DisplayModeDescription

# ---------------------------------------------------------------- hatch patterns
def hatch_index(name):
    hp = doc.HatchPatterns.FindName(name)
    return hp.Index if hp is not None else -1


# A doc created without a template has ZERO hatch patterns. Add Rhino's built-ins from
# HatchPattern.Defaults, plus a custom line pattern built from HatchLine (what library JSON would map to).
def ensure_patterns():
    HP = D.HatchPattern
    for nm in ("Solid", "Hatch1", "Hatch2", "Hatch3", "Dash", "Grid", "Grid60", "Plus", "Squares"):
        if doc.HatchPatterns.FindName(nm) is None:
            doc.HatchPatterns.Add(getattr(HP.Defaults, nm))
    if doc.HatchPatterns.FindName("MC Fine45") is None:
        hp = HP()
        hp.Name = "MC Fine45"
        hp.FillType = D.HatchPatternFillType.Lines
        hl = D.HatchLine()
        hl.Angle = System.Math.PI / 4
        hl.BasePoint = Rhino.Geometry.Point2d(0, 0)
        hl.Offset = Rhino.Geometry.Vector2d(0, 0.125)   # 1/8" spacing in pattern units
        hp.AddHatchLine(hl)
        doc.HatchPatterns.Add(hp)


ensure_patterns()
HATCHES = {h.Name: h.Index for h in doc.HatchPatterns if h is not None and not h.IsDeleted}

# material layer -> (hatch name or None, hatch scale, rotation deg, boundary width scale)
STYLE = {
    "Brick":      ("MC Fine45", 1.0, 0.0, 2.0),
    "Insulation": ("Hatch3", 0.5, 0.0, 2.0),   # placeholder; real batt insulation needs a custom curve pattern
    "Sheathing":  (None, 1.0, 0.0, 2.0),
    "Stud":       ("Grid", 0.25, 0.0, 2.0),
    "Gypsum":     (None, 1.0, 0.0, 2.0),
    "Concrete":   (None, 1.0, 0.0, 3.0),
    "Ground":     ("Hatch2", 4.0, 45.0, 3.0),
    "Column":     (None, 1.0, 0.0, 3.0),
    "Furniture":  (None, 1.0, 0.0, 2.0),
}


def make_style(hatch, scale, rot, bscale):
    s = D.SectionStyle()
    s.BackgroundFillMode = D.SectionBackgroundFillMode.SolidColor
    s.BackgroundFillColor = Color.White
    s.BackgroundFillPrintColor = Color.White
    s.BoundaryVisible = True
    s.BoundaryColor = Color.Black
    s.BoundaryPrintColor = Color.Black
    s.BoundaryWidthScale = bscale
    s.SectionFillRule = D.ObjectSectionFillRule.SolidObjects
    idx = HATCHES.get(hatch, -1) if hatch else -1
    if idx >= 0:
        s.HatchIndex = idx
        s.HatchScale = scale
        s.HatchRotationRadians = System.Math.PI * rot / 180.0
        s.HatchPatternColor = Color.Black
        s.HatchPatternPrintColor = Color.Black
    else:
        # GOTCHA: HatchIndex = -1 does NOT mean "no hatch" - the display falls back to a SOLID
        # hatch drawn in HatchPatternColor (default black) -> black poche. For "white fill, no
        # hatch" use the Solid pattern in the fill colour.
        s.HatchIndex = HATCHES.get("Solid", -1)
        s.HatchPatternColor = Color.White
        s.HatchPatternPrintColor = Color.White
    return s


applied = {}
for name, st in STYLE.items():
    idx = doc.Layers.FindByFullPath("MC::" + name, -1)
    if idx < 0:
        continue
    L = doc.Layers.FindIndex(idx)
    L.SetCustomSectionStyle(make_style(*st))
    # all display colors black for a monochrome look (plot colour too)
    L.Color = Color.Black
    L.PlotColor = Color.Black
    # GOTCHA: setting the style on the table's Layer instance stores it (reads back fine) but the
    # display IGNORES it until the layer is committed with Layers.Modify().
    applied[name] = doc.Layers.Modify(L, idx, True)

# ---------------------------------------------------------------- display mode
MODE_NAME = "MC Section"
existing = DMD.FindByName(MODE_NAME)
if existing is not None:
    DMD.DeleteDisplayMode(existing.Id)
new_id = DMD.CopyDisplayMode(DMD.PenId, MODE_NAME)
dm = DMD.GetDisplayMode(new_id)
a = dm.DisplayAttributes
a.SetFill(Color.White)                       # FillMode -> SolidColor, white paper
a.ShowIsoCurves = False
a.ShowTangentEdges = False
a.ShowTangentSeams = False
a.UseSectionStyles = True
a.ShowClippingFills = True
a.ShowClippingEdges = True
a.ClippingEdgeColorUsage = Rhino.Display.DisplayPipelineAttributes.ClippingEdgeColorUse.SolidColor
a.ClippingEdgeColor = Color.Black
a.ClippingEdgeThickness = 1   # px; multiplied by SectionStyle.BoundaryWidthScale
a.ClippingPlaneFillColorUsage = Rhino.Display.DisplayPipelineAttributes.ClippingPlaneFillColorUse.SolidColor
a.ClippingFillColor = Color.White
a.ShowClippingPlanes = False
a.CastShadows = False
a.ShadowsOn = False
a.SurfaceEdgeColor = Color.Black
ok = DMD.UpdateDisplayMode(dm)
dm = DMD.GetDisplayMode(new_id)

# Silhouette/crease ("Technical") settings are NOT exposed in DisplayPipelineAttributes.
# They live in the [..\Objects\Technical] section of the exported .ini (TechnicalMask,
# THThickness = hidden?, TSiThickness = silhouette, TCThickness = crease, TEThickness = edges,
# TSThickness = seams, TIThickness = intersections). Edit via Export -> patch -> Import.
def patch_technical(mode, updates):
    tmp = os.path.join(os.environ.get("TEMP", "."), "mc_section_mode.ini")
    DMD.ExportToFile(mode, tmp)
    txt = open(tmp, encoding="utf-16").read()
    out = []
    for line in txt.splitlines():
        k = line.split("=", 1)[0]
        if k in updates:
            line = "%s=%s" % (k, updates[k])
        out.append(line)
    open(tmp, "w", encoding="utf-16").write("\r\n".join(out) + "\r\n")
    DMD.DeleteDisplayMode(mode.Id)
    return DMD.ImportFromFile(tmp)


new_id2 = patch_technical(dm, {"TSiThickness": 3, "TCThickness": 1, "TEThickness": 1, "TIThickness": 1})
dm = DMD.GetDisplayMode(new_id2) if new_id2 != System.Guid.Empty else DMD.FindByName(MODE_NAME)

view = doc.Views.ActiveView
view.ActiveViewport.DisplayMode = dm
doc.Views.Redraw()

SECTION_RESULT = {
    "styles_applied": applied,
    "mode_update_ok": ok,
    "mode_id": str(dm.Id) if dm else None,
    "mode_name": dm.EnglishName if dm else None,
    "hatches_available": sorted(HATCHES.keys()),
}
print(SECTION_RESULT)
