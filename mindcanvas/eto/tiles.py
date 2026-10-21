"""Tiles of the assembly palette (eto/palette.py): one small picture per library entry.

    walls, floors, roofs   the layer section of the Phase 12 editor in compact form
                           (asmview.SectionLayout(compact=True) + sectionview.paint_tile): material
                           tints, section hatches, batts, framing members at true size, bricks
    curtain walls          an elevation of three bays: mullions, transoms, vision / spandrel /
                           shadow-box rows (curtainwall.settings.merged)
    windows / doors        an elevation glyph: frame, glass, mullions, the operation (casement /
                           awning hinge lines, double-hung meeting rail, sliding arrow), door leaves
                           with lites and the hinge-side swing lines
    stairs                 a flight in section in the assembly's style (sloped soffit / solid mass /
                           open plates) and material, at its max riser and an 11" tread

    bitmap(lib, kind, name, width, height)   -> Eto Bitmap (cached per definition)
    render_png(lib, kind, name, path, ...)   the same into a file (tests)
"""

import json
import math

import Eto.Drawing as drawing
import System

from .. import units
from . import sectionview as sv

INK = (25, 25, 25)
GLASS = (205, 228, 242)
SPANDREL = (122, 136, 152)
SHADOW = (88, 98, 114)
LEAF = (196, 196, 190)
WOOD_LEAF = (214, 182, 136)
_CACHE = {}


def _key(lib, kind, name, w, h):
    if kind == "opening":
        from ..openings import core
        d = core.merged_type(lib, name)
    else:
        d = lib.assembly(name)
    return (kind, name, w, h, json.dumps(d, sort_keys=True, default=str))


def bitmap(lib, kind, name, width=168, height=92):
    k = _key(lib, kind, name, width, height)
    bmp = _CACHE.get(k)
    if bmp is None:
        bmp = drawing.Bitmap(int(width), int(height), drawing.PixelFormat.Format32bppRgba)
        g = drawing.Graphics(bmp)
        try:
            paint(g, lib, kind, name, width, height)
        finally:
            g.Dispose()
        _CACHE[k] = bmp
    return bmp


def render_png(lib, kind, name, path, width=168, height=92):
    bitmap(lib, kind, name, width, height).Save(path, drawing.ImageFormat.Png)
    return path


def paint(g, lib, kind, name, width, height):
    if kind == "opening":
        return _opening(g, lib, name, width, height)
    if kind == "curtain_wall":
        return _curtain_wall(g, lib, name, width, height)
    if kind == "stair":
        return _stair(g, lib, name, width, height)
    from .. import asmedit, asmview
    model = asmedit.AssemblyModel(lib, name)
    lay = asmview.SectionLayout(model, width, height, compact=True)
    if not sv.paint_tile(g, lay, width, height):
        p = sv.Painter(g)
        p.text("no layers", 6, 6, (120, 120, 120))


def _fit(w_in, h_in, width, height, margin=8.0):
    """(scale px / inch, x0, y0) fitting w_in x h_in inches centered in the tile."""
    s = min((width - 2 * margin) / max(w_in, 1e-6), (height - 2 * margin) / max(h_in, 1e-6))
    return s, 0.5 * (width - w_in * s), 0.5 * (height - h_in * s)


# -- curtain walls ---------------------------------------------------------------------------------
def _curtain_wall(g, lib, name, width, height):
    from ..curtainwall import settings as cws
    asm = lib.assembly(name)
    st = cws.merged(asm, {})
    p = sv.Painter(g)
    p.rect(sv.WHITE, 0, 0, width, height)
    H = units.parse_length(asm.get("default_height", 160))
    sp = units.parse_length(st.get("spacing", 60) or 60)
    bays = 3
    W = sp * bays
    s, x0, y0 = _fit(W, H, width, height)
    z = [0.0] + sorted(units.parse_length(t) for t in (st.get("transoms") or []) if 0 < units.parse_length(t) < H) + [H]
    rows = (st.get("infill") or {}).get("rows") or ["vision"]
    colors = {"vision": GLASS, "spandrel": SPANDREL, "shadow_box": SHADOW}
    for i in range(len(z) - 1):
        kind = rows[min(i, len(rows) - 1)]
        ya = y0 + (H - z[i + 1]) * s
        p.rect(colors.get(kind, GLASS), x0, ya, W * s, (z[i + 1] - z[i]) * s)
    style = st.get("style", "captured")
    mull = sv._pen(INK, 1.0 if style in ("butt", "ssg4") else 2.6)
    trans = sv._pen(INK, 1.0 if style in ("butt", "ssg4", "ssg2") else 2.6)
    for b in range(1, bays):
        x = x0 + b * sp * s
        p.line(mull, x, y0, x, y0 + H * s)
    for zz in z[1:-1]:
        y = y0 + (H - zz) * s
        p.line(trans, x0, y, x0 + W * s, y)
    p.frame(sv._pen(INK, 2.6), x0, y0, W * s, H * s)


# -- stairs ---------------------------------------------------------------------------------------
def _stair(g, lib, name, width, height, steps=6, tread=11.0):
    from ..kinds import stair as stairkind
    st = stairkind.settings(lib.assembly(name), {})
    m = lib.data["materials"].get(st["material"]) or {}
    fill = sv._tint(tuple(m.get("color") or (160, 160, 160)), 0.55)
    p = sv.Painter(g)
    p.rect(sv.WHITE, 0, 0, width, height)
    R, T, n = float(units.parse_length(st["max_riser"])), tread, steps
    land = 1.5 * T
    W, H = (n - 1) * T + land, n * R
    s, x0, y0 = _fit(W + T, H + R, width, height)
    x0 += 0.5 * T * s

    def pt(x, z):
        return drawing.PointF(float(x0 + x * s), float(y0 + (H + 0.5 * R - z) * s))

    heavy, thin = sv._pen(INK, 2.0), sv._pen(INK, 1.0)
    floor = sv._pen(INK, 1.0, "dash")
    p.line(floor, x0 - 0.5 * T * s, pt(0, 0).Y, x0 + (W + 0.5 * T) * s, pt(0, 0).Y)
    p.line(floor, x0 - 0.5 * T * s, pt(0, H).Y, x0 + (W + 0.5 * T) * s, pt(0, H).Y)
    if st["style"] == "open":
        t = max(1.0, float(units.parse_length(st["tread_thickness"])))
        for i in range(1, n + 1):
            x, ln = (i - 1) * T, (land if i == n else T + 1.0)
            a, b = pt(x - 1.0 if i < n else x, i * R), pt(x - 1.0 + ln if i < n else x + ln, i * R - t)
            p.rect(fill, a.X, a.Y, b.X - a.X, b.Y - a.Y)
            p.frame(heavy, a.X, a.Y, b.X - a.X, b.Y - a.Y)
        p.line(thin, pt(0, 0).X, pt(0, 0).Y, pt((n - 1) * T, H - t).X, pt((n - 1) * T, H - t).Y)
        return
    top = [(0.0, 0.0)]
    for i in range(n):
        top += [(i * T, (i + 1) * R), ((i + 1) * T if i < n - 1 else W, (i + 1) * R)]
    if st["style"] == "solid":
        bottom = [(W, 0.0)]
    else:
        waist = float(units.parse_length(st["waist"]))
        tl = waist if st["landing"] is None else float(units.parse_length(st["landing"]))
        off = waist / math.cos(math.atan2(R, T))     # vertical drop of the soffit under the tread roots
        x1 = min(W, (H - tl + off) * T / R)
        bottom = [(W, H - tl), (x1, H - tl), (min(x1, off * T / R), 0.0)]
    pts = [pt(x, z) for x, z in top + bottom]
    arr = System.Array[drawing.PointF](pts)
    g.FillPolygon(sv._c(fill), arr)
    g.DrawPolygon(heavy, arr)


# -- windows / doors -------------------------------------------------------------------------------
def _opening(g, lib, name, width, height):
    from ..openings import core
    t = core.merged_type(lib, name)
    p = sv.Painter(g)
    p.rect(sv.WHITE, 0, 0, width, height)
    W = units.parse_length(t["width"])
    H = units.parse_length(t["height"])
    s, x0, y0 = _fit(W, H, width, height)
    frame = sv._pen(INK, 2.2)
    thin = sv._pen(INK, 1.0)
    dash = sv._pen(INK, 0.9, "dash")
    fw = max(2.0, units.parse_length((t.get("frame") or {}).get("face", "1-3/4")) * s)
    X, Y, w, h = x0, y0, W * s, H * s
    if t.get("category") == "door":
        leaf = t.get("leaf") or {}
        n = int(leaf.get("leaves", 1) or 1)
        mat = str(leaf.get("material", ""))
        col = WOOD_LEAF if "Wood" in mat else LEAF
        if "Aluminum" in mat or "Storefront" in name or "Entrance" in name:
            col = GLASS
        lw = (w - 2 * fw) / n
        for i in range(n):
            lx = X + fw + i * lw
            p.rect(col, lx, Y + fw, lw, h - fw)
            p.frame(thin, lx, Y + fw, lw, h - fw)
            lite = leaf.get("lite")
            if lite and col is not GLASS:
                frac = 0.45 if "half" in str(lite).lower() or "Half" in name else 0.75
                p.rect(GLASS, lx + lw * 0.2, Y + fw + h * 0.08, lw * 0.6, h * frac)
                p.frame(thin, lx + lw * 0.2, Y + fw + h * 0.08, lw * 0.6, h * frac)
            if "Narrow Stile" not in name and col is GLASS:
                p.frame(thin, lx + lw * 0.12, Y + fw + h * 0.06, lw * 0.76, h * 0.86)
            # swing lines: from the hinge jamb's corners to the latch side's middle
            hinge_left = (i == 0) if n == 2 else (str(t.get("hinge", "left")) == "left")
            hx, ox = (lx, lx + lw) if hinge_left else (lx + lw, lx)
            p.line(dash, hx, Y + fw, ox, Y + fw + 0.5 * (h - fw))
            p.line(dash, hx, Y + h, ox, Y + fw + 0.5 * (h - fw))
        p.frame(frame, X, Y, w, h)
        return
    p.rect(GLASS, X, Y, w, h)
    mu = t.get("mullions") or {}
    nv, nh = int(mu.get("vertical", 0) or 0), int(mu.get("horizontal", 0) or 0)
    for i in range(1, nv + 1):
        x = X + w * i / (nv + 1.0)
        p.line(frame, x, Y, x, Y + h)
    for i in range(1, nh + 1):
        y = Y + h * i / (nh + 1.0)
        p.line(frame, X, y, X + w, y)
    op = str(t.get("operation", "fixed"))
    if op == "casement":
        p.line(dash, X + fw, Y + fw, X + w - fw, Y + 0.5 * h)
        p.line(dash, X + fw, Y + h - fw, X + w - fw, Y + 0.5 * h)
    elif op == "awning":
        yb = Y + (h * nh / (nh + 1.0) if nh else 0)       # the lowest panel (awning under a transom)
        p.line(dash, X + fw, Y + h - fw, X + 0.5 * w, yb + fw)
        p.line(dash, X + w - fw, Y + h - fw, X + 0.5 * w, yb + fw)
    elif op == "double_hung":
        y = Y + 0.5 * h
        p.line(frame, X, y, X + w, y)
        p.line(thin, X + 0.5 * w, y + 6, X + 0.5 * w, y + 16)
        p.line(thin, X + 0.5 * w - 3, y + 9, X + 0.5 * w, y + 6)
        p.line(thin, X + 0.5 * w + 3, y + 9, X + 0.5 * w, y + 6)
    elif op == "sliding":
        x = X + 0.5 * w
        p.line(frame, x, Y, x, Y + h)
        p.line(thin, X + 0.2 * w, Y + 0.5 * h, X + 0.4 * w, Y + 0.5 * h)
        p.line(thin, X + 0.4 * w - 4, Y + 0.5 * h - 3, X + 0.4 * w, Y + 0.5 * h)
        p.line(thin, X + 0.4 * w - 4, Y + 0.5 * h + 3, X + 0.4 * w, Y + 0.5 * h)
    p.frame(frame, X, Y, w, h)
    p.frame(thin, X + fw, Y + fw, w - 2 * fw, h - 2 * fw)
