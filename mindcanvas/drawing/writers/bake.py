"""Bake a Drawing into the document as 2D curves at model scale (a layout detail at
the drawing scale prints it at true size), on `MindCanvas Drawing::<class>`
layers with plot weights / plot colours per object.

Fixes from the spike: fills get a higher DisplayOrder than projected lines so
they cover them; cut hatches, cut dots and ground stipple are baked too (dots as
very short strokes whose plot weight is the dot diameter). Re-baking the same
drawing key replaces the previous one.
"""

import System
import Rhino

from ... import docutil, units
from .. import patterns

G = Rhino.Geometry
D = Rhino.DocObjects
ROOT = "MindCanvas Drawing"
KEY = "mc.drawing"
ORDER = {"tone": 1, "edge": 2, "junction": 2, "hidden": 2, "silhouette": 3, "entourage": 3, "stipple": 4,
         "fill": 10, "cut_hatch": 11, "cut_inner": 12, "cut": 13}
WHITE = System.Drawing.Color.White
BLACK = System.Drawing.Color.Black


def _layers(doc, style):
    out = {}
    for cls in list(style.classes) + ["fill"]:
        idx = docutil.ensure_layer(doc, ROOT + "::" + cls)
        L = doc.Layers[idx]
        w = float(style.cls(cls).get("w", 0.18)) if cls != "fill" else 0.0
        if abs(L.PlotWeight - w) > 1e-9 or L.Color != BLACK:
            L.PlotWeight = w
            L.Color = BLACK
            L.PlotColor = BLACK
            doc.Layers.Modify(L, idx, True)
        out[cls] = idx
    return out


def clear(doc, key):
    n = 0
    for o in doc.Objects.FindByUserString(KEY, key, True) or []:
        if doc.Objects.Delete(o, True):
            n += 1
    return n


def bake(doc, dwg, origin=None, key=None, max_dots=40000):
    """Returns (object count, origin point, group index)."""
    st = dwg.style
    key = key or dwg.title
    clear(doc, key)
    lidx = _layers(doc, st)
    k = units.inch_scale(doc) * st.scale / 25.4        # model units per paper mm
    if origin is None:
        bb = G.BoundingBox.Empty
        for o in doc.Objects:
            if not o.IsDeleted and not o.Attributes.GetUserString(KEY):
                bb.Union(o.Geometry.GetBoundingBox(False))
        origin = G.Point3d(bb.Max.X + 10 * k, bb.Min.Y, 0) if bb.IsValid else G.Point3d.Origin
    gidx = docutil.ensure_group(doc, "MC Drawing " + key[:40])
    solid = patterns.index(doc, "Solid")
    tol = doc.ModelAbsoluteTolerance
    count = [0]

    def P(x, y):
        return G.Point3d(origin.X + x * k, origin.Y + y * k, origin.Z)

    def attrs(cls, width=None, grey=0, order=None):
        a = D.ObjectAttributes()
        a.LayerIndex = lidx.get(cls, lidx["edge"])
        a.SetUserString(KEY, key)
        a.AddToGroup(gidx)
        col = System.Drawing.Color.FromArgb(grey, grey, grey)
        a.ColorSource = D.ObjectColorSource.ColorFromObject
        a.ObjectColor = col
        a.PlotColorSource = D.ObjectPlotColorSource.PlotColorFromObject
        a.PlotColor = col
        if width is not None:
            a.PlotWeightSource = D.ObjectPlotWeightSource.PlotWeightFromObject
            a.PlotWeight = float(width)
        try:
            a.DisplayOrder = ORDER.get(cls if order is None else order, 0)
        except Exception:
            pass
        return a

    def curve(pts, a, close=False):
        q = [P(x, y) for x, y in pts]
        if close and q[0].DistanceTo(q[-1]) > 1e-9:
            q.append(q[0])
        c = G.LineCurve(q[0], q[-1]) if len(q) == 2 else G.PolylineCurve(q)
        doc.Objects.AddCurve(c, a)
        count[0] += 1

    def dot(x, y, a):
        doc.Objects.AddCurve(G.LineCurve(P(x, y), P(x + 0.02, y)), a)
        count[0] += 1

    for pts, cls, dn in dwg.lines:
        curve(pts, attrs(cls, st.width(cls, dn), st.grey(dn)))
    n_dots = 0
    for x, y, dn in dwg.dots[:max_dots]:
        dot(x, y, attrs("stipple", st.width("stipple") * (1.0 - 0.35 * dn), st.grey(dn * 0.6)))
        n_dots += 1
    for r in dwg.painter_regions():
        fill = r.spec.get("fill", "white")
        crvs = [G.PolylineCurve([P(x, y) for x, y in lp]) for lp in r.loops if len(lp) >= 4]
        if fill != "none" and crvs and solid >= 0:
            a = attrs("fill", 0.0, 0 if fill == "black" else 255)
            if fill == "grey":
                v = int(255 * (1.0 - float(r.spec.get("grey", 0.5))))
                a.ObjectColor = a.PlotColor = System.Drawing.Color.FromArgb(v, v, v)
            for h in G.Hatch.Create(crvs, solid, 0.0, 1.0, tol) or []:
                doc.Objects.AddHatch(h, a)
                count[0] += 1
        for pl in r.hatch:
            curve(pl, attrs("cut_hatch", st.width("cut_hatch")))
        for x, y in r.dots:
            if n_dots < max_dots:
                dot(x, y, attrs("stipple", st.width("stipple"), 0, "cut_hatch"))
                n_dots += 1
        if not r.ground and not r.small and r.spec.get("inner", True):
            for lp in r.loops:
                curve(lp, attrs("cut_inner", st.width("cut_inner")), True)
    for pts, dts in dwg.ground:
        for x, y in dts:
            if n_dots < max_dots:
                dot(x, y, attrs("stipple", st.width("stipple"), 0, "cut_hatch"))
                n_dots += 1
        curve(pts, attrs("cut", st.width("cut")))
    for lp in dwg.outlines:
        curve(lp, attrs("cut", st.width("cut")), True)
    for pts in dwg.cut_lines:
        curve(pts, attrs("cut", st.width("cut")))
    doc.Views.Redraw()
    return count[0], origin, gidx
