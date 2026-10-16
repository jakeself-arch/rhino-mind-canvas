"""Live view: section styles on the MindCanvas::<Material> layers for a drawing scale.

The material JSON gives each layer a default style (docutil). `apply` swaps in
the scale-dependent cut appearance from a drawing style so the clipped
viewport reads like the 2D drawing: white poche at building scales, material
hatches sized for paper at detail scales. Hatch scales are model units.
"""

import System
import Rhino

from .. import docutil
from . import patterns, styles

D = Rhino.DocObjects
STYLE_KEY = "mc.drawstyle"
WHITE = System.Drawing.Color.White
BLACK = System.Drawing.Color.Black


def material_layers(doc):
    root = docutil.ROOT_LAYER + "::"
    for layer in doc.Layers:
        if layer is None or layer.IsDeleted:
            continue
        path = layer.FullPath
        if path.startswith(root) and path.count("::") == 1 and path not in (docutil.DRIVER_LAYER, docutil.MASS_LAYER):
            yield layer.Index, layer.Name


def section_style(doc, cut, mm_per_unit, boundary_scale=2.0):
    ss = D.SectionStyle()
    ss.BackgroundFillMode = D.SectionBackgroundFillMode.SolidColor
    ss.SectionFillRule = D.ObjectSectionFillRule.SolidObjects
    ss.BoundaryVisible = True
    ss.BoundaryColor = BLACK
    ss.BoundaryPrintColor = BLACK
    ss.BoundaryWidthScale = float(boundary_scale)
    fill = cut.get("fill", "white")
    bg = BLACK if fill == "black" else WHITE
    if fill == "grey":
        g = int(255 * (1.0 - float(cut.get("grey", 0.5))))
        bg = System.Drawing.Color.FromArgb(g, g, g)
    ss.BackgroundFillColor = bg
    ss.BackgroundFillPrintColor = bg
    hatch = cut.get("hatch") or {}
    name, mm = hatch.get("pattern"), float(hatch.get("mm", 1.0))
    if not name and cut.get("batt"):
        name, mm = "MC Batt", 2.5
    elif not name and cut.get("cross"):
        name, mm = "MC Wood", 1.5
    elif not name and cut.get("ground"):
        name, mm = "MC Earth", 4.0
    idx = patterns.index(doc, name) if name else -1
    if idx >= 0 and fill != "black":
        ss.HatchIndex = idx
        ss.HatchScale = mm / mm_per_unit
        ss.HatchRotationRadians = Rhino.RhinoMath.ToRadians(float(hatch.get("rot", 0.0)))
        ss.HatchPatternColor = BLACK
        ss.HatchPatternPrintColor = BLACK
    else:
        # GOTCHA: HatchIndex -1 falls back to a black solid hatch; Solid in the fill colour
        ss.HatchIndex = patterns.index(doc, "Solid")
        ss.HatchPatternColor = bg
        ss.HatchPatternPrintColor = bg
    return ss


def apply(doc, style=None):
    """Section styles for every material layer at `style`'s scale. Returns the count."""
    st = styles.get(style)
    mm = st.mm_per_unit(doc)
    bscale = st.get("live", {}).get("boundary_width_scale", 2.0)
    n = 0
    for idx, name in list(material_layers(doc)):
        layer = doc.Layers[idx]
        layer.SetCustomSectionStyle(section_style(doc, st.material(name), mm, bscale))
        layer.SetUserString(STYLE_KEY, st.name)
        # GOTCHA: the display ignores the style until the layer is committed with Modify
        if doc.Layers.Modify(layer, idx, True):
            n += 1
    return n
