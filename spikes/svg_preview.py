"""Tiny SVG -> PNG rasterizer (System.Drawing) for previewing vector output inside Rhino.
Handles what Rhino's CaptureToSvg and our own writer emit: <path d="M L C z" stroke fill
stroke-width>, <circle>. Not a general SVG renderer.

svg_to_png(svg_path, png_path, scale=2.0)
"""
import re
import System
from System.Drawing import Bitmap, Graphics, Pen, SolidBrush, Color, PointF
from System.Drawing.Drawing2D import GraphicsPath, SmoothingMode, LineCap

_num = r"-?\d*\.?\d+(?:[eE][-+]?\d+)?"


def _color(s, default):
    if s is None or s == "none":
        return None
    s = s.strip()
    if s.startswith("#") and len(s) == 7:
        return Color.FromArgb(int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))
    try:
        return Color.FromName(s)
    except Exception:
        return default


def _attr(tag, name):
    m = re.search(r'\b' + name + r'="([^"]*)"', tag)
    return m.group(1) if m else None


def svg_to_png(svg_path, png_path, scale=2.0, min_px=0.6):
    txt = open(svg_path, encoding="utf-8", errors="ignore").read()
    m = re.search(r'viewBox="([^"]+)"', txt)
    vb = [float(x) for x in m.group(1).split()] if m else [0, 0, 1000, 1000]
    W, H = int(vb[2] * scale), int(vb[3] * scale)
    bmp = Bitmap(W, H)
    g = Graphics.FromImage(bmp)
    g.SmoothingMode = SmoothingMode.AntiAlias
    g.Clear(Color.White)
    ox, oy = vb[0], vb[1]
    for tag in re.findall(r"<(?:path|circle|polyline)\b[^>]*>", txt):
        fill = _color(_attr(tag, "fill"), Color.Black)
        stroke = _color(_attr(tag, "stroke"), None)
        sw = _attr(tag, "stroke-width")
        sw = float(sw) if sw else 1.0
        if tag.startswith("<circle"):
            cx = (float(_attr(tag, "cx")) - ox) * scale
            cy = (float(_attr(tag, "cy")) - oy) * scale
            r = max(float(_attr(tag, "r")) * scale, 0.5)
            g.FillEllipse(SolidBrush(fill or Color.Black), cx - r, cy - r, 2 * r, 2 * r)
            continue
        d = _attr(tag, "d") or ""
        if tag.startswith("<polyline"):
            d = "M" + (_attr(tag, "points") or "").replace(" ", " L")
        gp = GraphicsPath()
        cur = None
        start = None
        for cmd, args in re.findall(r"([MLCZmlcz])([^MLCZmlcz]*)", d):
            v = [float(x) for x in re.findall(_num, args)]
            pts = [PointF((v[i] - ox) * scale, (v[i + 1] - oy) * scale) for i in range(0, len(v) - 1, 2)]
            if cmd == "M":
                gp.StartFigure()
                cur = start = pts[0] if pts else cur
                for p in pts[1:]:
                    gp.AddLine(cur, p)
                    cur = p
            elif cmd == "L":
                for p in pts:
                    gp.AddLine(cur, p)
                    cur = p
            elif cmd == "C":
                for i in range(0, len(pts) - 2, 3):
                    gp.AddBezier(cur, pts[i], pts[i + 1], pts[i + 2])
                    cur = pts[i + 2]
            elif cmd in "Zz":
                gp.CloseFigure()
                cur = start
        if fill is not None and _attr(tag, "fill") is not None:
            g.FillPath(SolidBrush(fill), gp)
        if stroke is not None and sw > 0:
            pen = Pen(stroke, max(sw * scale, min_px))
            pen.StartCap = pen.EndCap = LineCap.Round
            g.DrawPath(pen, gp)
    g.Dispose()
    bmp.Save(png_path)
    return png_path
