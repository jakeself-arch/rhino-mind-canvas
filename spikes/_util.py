"""Shared helpers for spike scripts. exec() this file first; it defines capture_png(), run_spike()."""
import os
import Rhino

ROOT = r"C:\Users\jakob\Desktop\BAC\Rhino Mind Canvas"
OUT = os.path.join(ROOT, "docs", "spike-output")
os.makedirs(OUT, exist_ok=True)


def run_spike(name, g):
    """exec another spike file into globals g"""
    exec(open(os.path.join(ROOT, "spikes", name)).read(), g)


def capture_png(doc, fname, w=1400, h=900, view=None):
    v = view or doc.Views.ActiveView
    vc = Rhino.Display.ViewCapture()
    vc.Width, vc.Height = w, h
    vc.ScaleScreenItems = False
    vc.DrawAxes = vc.DrawGrid = vc.DrawGridAxes = False
    vc.TransparentBackground = False
    bmp = vc.CaptureToBitmap(v)
    p = os.path.join(OUT, fname)
    bmp.Save(p)
    return p
