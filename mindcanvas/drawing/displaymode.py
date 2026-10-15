"""The "MC Section" display mode: a copy of Pen with white paper, section styles and
clipping fills on, no isocurves. Silhouette / crease thickness is only reachable
through the exported .ini ("Technical" settings), patched on creation."""

import os
import tempfile

import System
import Rhino

DMD = Rhino.Display.DisplayModeDescription
DPA = Rhino.Display.DisplayPipelineAttributes
NAME = "MC Section"
TECHNICAL = {"TSiThickness": 3, "TCThickness": 1, "TEThickness": 1, "TIThickness": 1}


def _patch_technical(mode, updates):
    path = os.path.join(tempfile.gettempdir(), "mc_section_mode.ini")
    if not DMD.ExportToFile(mode, path):
        return mode
    with open(path, encoding="utf-16") as fh:
        lines = fh.read().splitlines()
    out = []
    for line in lines:
        k = line.split("=", 1)[0]
        if k in updates:
            line = "{}={}".format(k, updates[k])
        out.append(line)
    with open(path, "w", encoding="utf-16") as fh:
        fh.write("\r\n".join(out) + "\r\n")
    DMD.DeleteDisplayMode(mode.Id)
    new_id = DMD.ImportFromFile(path)
    return DMD.GetDisplayMode(new_id) if new_id != System.Guid.Empty else DMD.FindByName(NAME)


def ensure(force=False, technical=True):
    """Find or create the display mode; force=True rebuilds it."""
    dm = DMD.FindByName(NAME)
    if dm is not None and not force:
        return dm
    if dm is not None:
        DMD.DeleteDisplayMode(dm.Id)
    dm = DMD.GetDisplayMode(DMD.CopyDisplayMode(DMD.PenId, NAME))
    a = dm.DisplayAttributes
    white, black = System.Drawing.Color.White, System.Drawing.Color.Black
    a.SetFill(white)
    a.ShowIsoCurves = False
    a.ShowTangentEdges = False
    a.ShowTangentSeams = False
    a.UseSectionStyles = True
    a.ShowClippingFills = True
    a.ShowClippingEdges = True
    a.ClippingEdgeColorUsage = DPA.ClippingEdgeColorUse.SolidColor
    a.ClippingEdgeColor = black
    a.ClippingEdgeThickness = 1
    a.ClippingPlaneFillColorUsage = DPA.ClippingPlaneFillColorUse.SolidColor
    a.ClippingFillColor = white
    a.ShowClippingPlanes = False
    a.CastShadows = False
    a.ShadowsOn = False
    a.SurfaceEdgeColor = black
    DMD.UpdateDisplayMode(dm)
    dm = DMD.GetDisplayMode(dm.Id)
    if technical:
        try:
            dm = _patch_technical(dm, TECHNICAL) or dm
        except Exception:
            dm = DMD.FindByName(NAME) or dm
    return dm


def assign(view, dm=None):
    dm = dm or ensure()
    view.ActiveViewport.DisplayMode = dm
    view.Redraw()
    return dm
