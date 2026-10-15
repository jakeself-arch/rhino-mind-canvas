"""PNG preview rendered straight from the Drawing (System.Drawing), same painter's
order as the SVG. No SVG renderer is installed on the dev machine; this is what
you look at to judge a drawing quickly."""

import os

import System
from System.Drawing import Bitmap, Color, Graphics, Pen, PointF, RectangleF, SolidBrush
from System.Drawing.Drawing2D import FillMode, GraphicsPath, LineCap, LineJoin, SmoothingMode


def write(dwg, path, px_per_mm=None, max_px=4200):
    st = dwg.style
    W, H = dwg.size
    k = float(px_per_mm or st.page.get("png_px_per_mm", 8))
    if max(W, H) * k > max_px:
        k = max_px / max(W, H)
    bmp = Bitmap(max(1, int(W * k)), max(1, int(H * k)))
    g = Graphics.FromImage(bmp)
    g.SmoothingMode = SmoothingMode.AntiAlias
    g.Clear(Color.White)
    if dwg.clip:
        c = dwg.clip
        g.SetClip(RectangleF(float(c[0] * k), float((H - c[3]) * k), float((c[2] - c[0]) * k), float((c[3] - c[1]) * k)))

    def P(x, y):
        return PointF(float(x * k), float((H - y) * k))

    def pen(color, w_mm):
        p = Pen(color, float(max(w_mm * k, 0.6)))
        p.StartCap = LineCap.Round
        p.EndCap = LineCap.Round
        p.LineJoin = LineJoin.Round
        return p

    def grey(dn):
        v = st.grey(dn)
        return Color.FromArgb(v, v, v)

    def lines(pts_list, p):
        for pts in pts_list:
            if len(pts) >= 2:
                g.DrawLines(p, System.Array[PointF]([P(x, y) for x, y in pts]))

    def dots(pts, color, d_mm):
        r = max(d_mm * k * 0.5, 0.45)
        b = SolidBrush(color)
        for x, y in pts:
            q = P(x, y)
            g.FillEllipse(b, q.X - r, q.Y - r, 2 * r, 2 * r)

    def region_path(loops):
        gp = GraphicsPath(FillMode.Alternate)
        for lp in loops:
            if len(lp) >= 3:
                gp.AddPolygon(System.Array[PointF]([P(x, y) for x, y in lp]))
        return gp

    # projected lines, by class order then far -> near
    pens = {}
    for pts, cls, dn in sorted(dwg.lines, key=lambda l: (st.cls(l[1]).get("order", 20), -l[2])):
        key = (cls, int(dn * 40))
        if key not in pens:
            pens[key] = pen(grey(dn), st.width(cls, dn))
        lines([pts], pens[key])
    dot_w = st.width("stipple")
    for x, y, dn in dwg.dots:
        dots([(x, y)], grey(dn * 0.6), dot_w * (1.0 - 0.35 * dn))

    black = Color.Black
    hatch_pen = pen(black, st.width("cut_hatch"))
    inner_w = st.width("cut_inner")
    cut_pen = pen(black, st.width("cut"))
    regs = dwg.painter_regions()

    def region(r):
        fill = r.spec.get("fill", "white")
        gp = region_path(r.loops)
        if fill == "black":
            g.FillPath(SolidBrush(black), gp)
            g.DrawPath(pen(black, inner_w * 0.6), gp)
        elif fill == "grey":
            v = int(255 * (1.0 - float(r.spec.get("grey", 0.5))))
            g.FillPath(SolidBrush(Color.FromArgb(v, v, v)), gp)
        elif fill != "none":
            g.FillPath(SolidBrush(Color.White), gp)
        lines(r.hatch, hatch_pen)
        dots(r.dots, black, dot_w)

    for r in regs:
        if r.ground:
            region(r)
    for pts, dts in dwg.ground:
        dots(dts, black, dot_w)
    for pts, dts in dwg.ground:
        lines([pts], cut_pen)
    for r in regs:
        if not r.ground:
            region(r)
    inner_pen = pen(black, inner_w)
    for r in regs:
        if not r.ground and not r.small and r.spec.get("inner", True) and r.spec.get("fill") != "black":
            for lp in r.loops:
                lines([lp], inner_pen)
    for lp in dwg.outlines:
        lines([lp + lp[:1]], cut_pen)
    lines(dwg.cut_lines, cut_pen)
    g.Dispose()
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    bmp.Save(path)
    bmp.Dispose()
    return path
