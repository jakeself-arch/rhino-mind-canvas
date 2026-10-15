"""Save a viewport capture to a PNG (for reviewing results outside Rhino).

    runpy.run_path(ROOT + r"\\tests\\capture.py")["capture"](__rhino_doc__, "name", view="Perspective")
"""

import os

import System
import Rhino

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "captures")


def capture(doc, name, view="Perspective", mode="Shaded", width=1000, height=600, zoom_extents=True,
            box=None):
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    v = doc.Views.Find(view, False)
    if v is None:
        v = doc.Views.ActiveView
    vp = v.ActiveViewport
    dm = Rhino.Display.DisplayModeDescription.FindByName(mode)
    if dm is not None:
        vp.DisplayMode = dm
    if box is not None:
        vp.ZoomBoundingBox(box)
    elif zoom_extents:
        vp.ZoomExtents()
    v.Redraw()
    bmp = v.CaptureToBitmap(System.Drawing.Size(width, height))
    path = os.path.join(OUT, name + ".png")
    bmp.Save(path, System.Drawing.Imaging.ImageFormat.Png)
    return path
