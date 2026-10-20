"""Eto view of the drawn layer section (Phase 12): paints an asmview.SectionLayout and forwards the
mouse to an asmview.SectionController. Everything that decides something (layout, hit tests, drag
math, snapping) is in mindcanvas/asmview.py.

Drawing: each band in a light tint of its material color with a simple version of its section
hatch (Hatch1 / Hatch2 = diagonals, Hatch3 = cross, Grid, Plus = dots; solid fills dark: membranes,
steel); batt insulation as the classic loop line; framing layers show their cavity fill and one
member at true size (wood: box with an X; metal: a C; I-joist: an I); brick shows its head joints.
Exterior / interior (top / bottom) are named, the core is boxed and tagged, a wall's location line
is dash-dotted, the overall thickness is dimensioned, and every layer is labeled with its name and
thickness. `render_png` draws the same into an Eto bitmap (tests, the PR picture).
"""

import math

import Eto.Drawing as drawing
import Eto.Forms as forms

from .. import asmfields, units

WHITE = (255, 255, 255)
INK = (25, 25, 25)
GRAY = (120, 120, 120)
SEL = (0, 120, 215)
REF = (200, 40, 40)
FRAMING = ("framing", "joists", "rafters")


def _c(rgb, a=255):
    return drawing.Color.FromArgb(int(rgb[0]), int(rgb[1]), int(rgb[2]), int(a))


def _tint(rgb, f):
    return tuple(int(255 - (255 - c) * f) for c in rgb)


def _pen(rgb, width=1.0, dash=None, a=255):
    p = drawing.Pen(_c(rgb, a), float(width))
    if dash == "dash":
        p.DashStyle = drawing.DashStyles.Dash
    elif dash == "dashdot":
        p.DashStyle = drawing.DashStyles.DashDot
    elif dash == "dot":
        p.DashStyle = drawing.DashStyles.Dot
    return p


class Painter(object):
    def __init__(self, g):
        self.g = g
        self.font = drawing.Fonts.Sans(8.0)
        self.bold = drawing.Fonts.Sans(8.0, drawing.FontStyle.Bold)
        self.small = drawing.Fonts.Sans(7.0)
        try:
            g.AntiAlias = True
        except Exception:
            pass

    def rect(self, rgb, x, y, w, h, a=255):
        if w > 0 and h > 0:
            self.g.FillRectangle(_c(rgb, a), float(x), float(y), float(w), float(h))

    def frame(self, pen, x, y, w, h):
        self.g.DrawRectangle(pen, float(x), float(y), float(w), float(h))

    def line(self, pen, x1, y1, x2, y2):
        self.g.DrawLine(pen, float(x1), float(y1), float(x2), float(y2))

    def text(self, s, x, y, rgb=INK, font=None, align="left"):
        font = font or self.font
        if align != "left":
            w = self.g.MeasureString(font, s).Width
            x = x - (w if align == "right" else w / 2.0)
        self.g.DrawText(font, drawing.SolidBrush(_c(rgb)), float(x), float(y), s)

    def measure(self, s, font=None):
        return self.g.MeasureString(font or self.font, s).Width

    def clip(self, x, y, w, h):
        self.g.SetClip(drawing.RectangleF(float(x), float(y), float(w), float(h)))

    def unclip(self):
        self.g.ResetClip()

    def hatch(self, x, y, w, h, angle, spacing, pen):
        """Parallel lines at angle (degrees) every spacing px inside the rectangle."""
        a = math.radians(angle)
        dx, dy = math.cos(a), math.sin(a)
        nx, ny = -dy, dx
        cx, cy = x + w / 2.0, y + h / 2.0
        r = math.hypot(w, h) / 2.0 + 2
        k = int(r / spacing) + 1
        self.clip(x, y, w, h)
        for i in range(-k, k + 1):
            px, py = cx + nx * i * spacing, cy + ny * i * spacing
            self.line(pen, px - dx * r, py - dy * r, px + dx * r, py + dy * r)
        self.unclip()

    def dots(self, x, y, w, h, spacing, rgb):
        self.clip(x, y, w, h)
        row = 0
        yy = y + spacing / 2.0
        while yy < y + h:
            xx = x + (spacing / 2.0 if row % 2 else spacing)
            while xx < x + w:
                self.g.FillEllipse(_c(rgb), float(xx - 1), float(yy - 1), 2.2, 2.2)
                xx += spacing * 1.3
            yy += spacing
            row += 1
        self.unclip()


# -- one band ---------------------------------------------------------------------------------------
def _pattern(p, rect, section, base_rgb):
    """Material section appearance in a rectangle: tint + hatch (or a dark fill)."""
    x, y, w, h = rect
    fill = section.get("fill", "white")
    if fill == "solid":
        p.rect(section.get("color") or INK, x, y, w, h)
        return
    p.rect(_tint(base_rgb, 0.45) if fill == "hatch" else WHITE, x, y, w, h)
    if fill != "hatch":
        return
    name = str(section.get("hatch") or "Hatch1")
    pen = _pen(GRAY, 0.8)
    if name == "Hatch1":
        p.hatch(x, y, w, h, 45, 6.0, pen)
    elif name == "Hatch2":
        p.hatch(x, y, w, h, -45, 4.0, pen)
    elif name == "Hatch3":
        p.hatch(x, y, w, h, 45, 7.0, pen)
        p.hatch(x, y, w, h, -45, 7.0, pen)
    elif name == "Grid":
        p.hatch(x, y, w, h, 0, 6.0, pen)
        p.hatch(x, y, w, h, 90, 6.0, pen)
    elif name == "Plus":
        p.dots(x, y, w, h, 6.0, GRAY)
    else:
        p.hatch(x, y, w, h, 45, 6.0, pen)


def _is_batt(material):
    m = (material or "").lower()
    return "batt" in m or "blown" in m


def _batt(p, lay, rect):
    """The insulation loop line along a band (a sine across its thickness)."""
    x, y, w, h = rect
    pen = _pen(GRAY, 1.0)
    if lay.orient == "h":
        u0, u1, v0, v1 = y, y + h, x, x + w
    else:
        u0, u1, v0, v1 = x, x + w, y, y + h
    a = (v1 - v0) / 2.0 - 1.5
    if a < 1.5:
        return
    period = max(8.0, min((v1 - v0) * 0.35, 200.0))
    vc = (v0 + v1) / 2.0
    p.clip(x, y, w, h)
    prev = None
    u = u0
    while u <= u1 + 2:
        v = vc + a * math.sin(2 * math.pi * (u - u0) / period)
        pt = (v, u) if lay.orient == "h" else (u, v)
        if prev:
            p.line(pen, prev[0], prev[1], pt[0], pt[1])
        prev = pt
        u += 2.0
    p.unclip()


def _members(p, lay, b):
    """One framing member (more if the spacing fits) at true size, centered along the band."""
    prof = b.member or {}
    sc = lay.scale
    try:
        width = units.parse_length(prof.get("width") or prof.get("flange") or 1.5)
    except ValueError:
        width = 1.5
    wpx = max(8.0, width * sc)
    try:
        spacing = units.parse_length(b.options.get("spacing") or 16) * sc
    except ValueError:
        spacing = 16 * sc
    x, y, w, h = b.rect
    if lay.orient == "h":
        u0, u1, v0, v1 = y, y + h, x, x + w
    else:
        u0, u1, v0, v1 = x, x + w, y, y + h
    mid = (u0 + u1) / 2.0
    centers = [mid]
    if spacing > wpx * 2:
        k = 1
        while mid - k * spacing - wpx / 2 > u0 or mid + k * spacing + wpx / 2 < u1:
            centers += [mid - k * spacing, mid + k * spacing]
            k += 1
    to_xy = (lambda u, v: (v, u)) if lay.orient == "h" else (lambda u, v: (u, v))
    ink = _pen(INK, 1.4)
    p.clip(x, y, w, h)
    for c in centers:
        a, z = c - wpx / 2.0, c + wpx / 2.0
        typ = prof.get("type")
        if typ == "c_stud" or b.metal:
            lip = max(2.0, units.parse_length(prof.get("lip", "1/2")) * sc)
            pts = [(z, v0 + lip), (z, v0), (a, v0), (a, v1), (z, v1), (z, v1 - lip)]
            for (u1_, w1_), (u2_, w2_) in zip(pts, pts[1:]):
                x1_, y1_ = to_xy(u1_, w1_)
                x2_, y2_ = to_xy(u2_, w2_)
                p.line(_pen(INK, 2.0), x1_, y1_, x2_, y2_)
        elif typ == "i_joist":
            fl = max(3.0, units.parse_length(prof.get("flange", "1-1/2")) * sc)
            wood = _tint((214, 178, 120), 0.6)
            for (fa, fb) in ((v0, v0 + fl), (v1 - fl, v1)):
                rx, ry = to_xy(a, fa)
                rx2, ry2 = to_xy(z, fb)
                p.rect(wood, min(rx, rx2), min(ry, ry2), abs(rx2 - rx), abs(ry2 - ry))
                p.frame(ink, min(rx, rx2), min(ry, ry2), abs(rx2 - rx), abs(ry2 - ry))
            web = max(2.0, units.parse_length(prof.get("web", "3/8")) * sc)
            rx, ry = to_xy(c - web / 2, v0 + fl)
            rx2, ry2 = to_xy(c + web / 2, v1 - fl)
            p.rect(wood, min(rx, rx2), min(ry, ry2), abs(rx2 - rx), abs(ry2 - ry))
            p.frame(ink, min(rx, rx2), min(ry, ry2), abs(rx2 - rx), abs(ry2 - ry))
        else:
            rx, ry = to_xy(a, v0)
            rx2, ry2 = to_xy(z, v1)
            X, Y, W, H = min(rx, rx2), min(ry, ry2), abs(rx2 - rx), abs(ry2 - ry)
            p.rect(_tint(b.color, 0.6), X, Y, W, H)
            p.line(ink, X, Y, X + W, Y + H)
            p.line(ink, X + W, Y, X, Y + H)
            p.frame(ink, X, Y, W, H)
    p.unclip()


def _brick_joints(p, lay, b):
    """Head joints across a masonry band every brick length + joint (8" modular)."""
    sc = lay.scale
    try:
        joint = units.parse_length(b.options.get("joint", "3/8"))
    except ValueError:
        joint = 0.375
    step = (8.0 if b.options.get("brick", "modular") in ("modular", "engineer") else 12.0) * sc
    if step < 12:
        return
    x, y, w, h = b.rect
    pen = _pen(WHITE, max(1.0, joint * sc))
    edge = _pen(GRAY, 0.6)
    u0, u1 = (y, y + h) if lay.orient == "h" else (x, x + w)
    u = u0 + step * 0.6
    while u < u1:
        if lay.orient == "h":
            p.line(pen, x, u, x + w, u)
            p.line(edge, x, u - joint * sc / 2, x + w, u - joint * sc / 2)
            p.line(edge, x, u + joint * sc / 2, x + w, u + joint * sc / 2)
        else:
            p.line(pen, u, y, u, y + h)
        u += step


def _strata(p, lay, b):
    """Rammed earth lifts as stripes, bottom-up (walls) or exterior-in (floors / roofs). True scale,
    shrunk when needed so one whole cycle of lifts shows in the band."""
    x, y, w, h = b.rect
    seq = []
    for rgb, height in b.lifts:
        try:
            t = units.parse_length(height)
        except ValueError:
            continue
        if t > 0:
            seq.append((rgb, t))
    if not seq:
        p.rect(b.color, x, y, w, h)
        return
    span = h if lay.orient == "h" else w
    sc = min(lay.scale, span / sum(t for _, t in seq))
    seq = [(rgb, t * sc) for rgb, t in seq]
    edge = _pen(_tint(INK, 0.5), 0.5)
    u, i = 0.0, 0
    while u < span:
        rgb, px = seq[i % len(seq)]
        d = min(px, span - u)
        if lay.orient == "h":
            p.rect(rgb, x, y + h - u - d, w, d)
            if u > 0:
                p.line(edge, x, y + h - u, x + w, y + h - u)
        else:
            p.rect(rgb, x + u, y, d, h)
            if u > 0:
                p.line(edge, x + u, y, x + u, y + h)
        u, i = u + d, i + 1


def _band(p, lay, b):
    rect = b.rect
    if b.component == "void":
        p.rect(WHITE, *rect)
        if (rect[2] if lay.orient == "h" else rect[3]) >= 22:
            cx, cy = rect[0] + rect[2] / 2.0, rect[1] + rect[3] / 2.0
            p.text("air", cx, cy - 6, GRAY, p.small, "center")
    elif b.component in FRAMING:
        p.rect(WHITE, *rect)
        if b.fill:
            name, rgb, sec = b.fill
            frect = rect
            try:
                depth = units.parse_length(b.options.get("fill_depth")) if b.options.get("fill_depth") else None
            except ValueError:
                depth = None
            if depth is not None and lay.orient == "v":      # floors / roofs: fill from the bottom up
                hpx = min(rect[3], depth * lay.scale)
                frect = (rect[0], rect[1] + rect[3] - hpx, rect[2], hpx)
            if _is_batt(name):
                p.rect(_tint(rgb, 0.45), *frect)
                _batt(p, lay, frect)
            else:
                _pattern(p, frect, sec, rgb)
        _members(p, lay, b)
    elif b.component == "strata":
        _strata(p, lay, b)
    else:
        if _is_batt(b.material):
            p.rect(_tint(b.color, 0.45), *rect)
            _batt(p, lay, rect)
        else:
            _pattern(p, rect, b.section, b.color)
        if b.component == "masonry":
            _brick_joints(p, lay, b)
    p.frame(_pen(INK, 0.7), *rect)


# -- the whole section ---------------------------------------------------------------------------
def paint(g, ctl, width=None, height=None):
    """Paint the controller's layout (selection, hover and drag state included)."""
    lay = ctl.layout
    p = Painter(g)
    W = width or lay.width
    H = height or lay.height
    p.rect(WHITE, 0, 0, W, H)
    if not lay.bands:
        p.text("No layer stack: a curtain wall is edited by its settings (right).", 16, 16, GRAY)
        return
    for b in lay.bands:
        _band(p, lay, b)
    heavy = _pen(INK, 2.2)
    first, last = lay.bands[0], lay.bands[-1]
    if lay.orient == "h":
        p.line(heavy, first.lo, lay.y0, first.lo, lay.y1)
        p.line(heavy, last.hi, lay.y0, last.hi, lay.y1)
        # ends + overall dimension
        p.text(lay.ends[0], first.lo, 4, INK, p.bold)
        p.text(lay.ends[1], last.hi, 4, INK, p.bold, "right")
        tot = 'total {}"'.format(asmfields.show_length(lay.total))
        p.text(tot, 0.5 * (first.lo + last.hi), 4, GRAY, p.font, "center")
        dim = _pen(GRAY, 0.8)
        yd = 26.0
        p.line(dim, first.lo, yd, last.hi, yd)
        for e in lay.edges():
            p.line(dim, e, yd - 4, e, yd + 4)
    else:
        p.line(heavy, lay.x0, first.lo, lay.x1, first.lo)
        p.line(heavy, lay.x0, last.hi, lay.x1, last.hi)
        tot = '{}   total {}"'.format(lay.ends[0], asmfields.show_length(lay.total))
        p.text(tot, lay.x0, 8, INK, p.bold)
        p.text(lay.ends[1], lay.x0, last.hi + 6, INK, p.bold)
        dim = _pen(GRAY, 0.8)
        xd = lay.x0 - 16.0
        p.line(dim, xd, first.lo, xd, last.hi)
        for e in lay.edges():
            p.line(dim, xd - 4, e, xd + 4, e)
    # core: dashed box + tag
    for b in lay.bands:
        if b.core:
            x, y, w, h = b.rect
            p.frame(_pen(INK, 1.2, "dash"), x - 2, y - 2, w + 4, h + 4)
            tw = p.measure("CORE", p.small) + 6
            tx, ty = (x + 3, y + 3) if w >= tw + 4 else (x + w + 4, y + 3)
            p.rect(INK, tx, ty, tw, 12)
            p.text("CORE", tx + 3, ty, WHITE, p.small)
    # wall location line
    ref, pos = lay.reference
    if pos is not None:
        pen = _pen(REF, 1.2, "dashdot")
        p.line(pen, pos, lay.y0 - 8, pos, lay.y1 + 4)
        tw = p.measure("location line", p.small)
        if pos + 3 + tw > W - 2:
            p.text("location line", pos - 3, lay.y0 - 12, REF, p.small, "right")
        else:
            p.text("location line", pos + 3, lay.y0 - 12, REF, p.small)
    # labels + leaders
    sel = ctl.selected
    for b in lay.bands:
        rgb = SEL if b.index == sel else INK
        pen = _pen(rgb if b.index == sel else GRAY, 0.8)
        for (x1, y1), (x2, y2) in zip(b.leader, b.leader[1:]):
            p.line(pen, x1, y1, x2, y2)
        x, y = b.label_pos
        p.text(b.label, x, y, rgb, p.bold if b.index == sel else p.font)
    # hover
    hv = ctl.hover if ctl.drag is None else None
    if hv and hv[0] == "edge":
        e = lay.edges()[hv[1]]
        _edge_line(p, lay, e, _pen(SEL, 2.0))
    elif hv and hv[0] in ("band", "label") and hv[1] != sel:
        p.frame(_pen(SEL, 1.0, a=140), *lay.bands[hv[1]].rect)
    # selection
    if 0 <= sel < len(lay.bands):
        r = lay.bands[sel].rect
        p.rect(SEL, r[0], r[1], r[2], r[3], 45)
        p.frame(_pen(SEL, 2.4), *r)
    # drag feedback
    d = ctl.drag
    if d and d["mode"] == "edge":
        b = lay.bands[d["index"]]
        e = b.hi if d["sign"] > 0 else b.lo
        _edge_line(p, lay, e, _pen(SEL, 2.4))
        msg = '{}: {}"'.format(b.name, asmfields.show_length(d["value"]))
        if d.get("member"):
            msg += "  ({})".format(d["member"])
        if lay.orient == "h":
            tx, ty = min(e + 6, lay.width - p.measure(msg) - 8), lay.y0 + 6
        else:
            tx, ty = lay.x0 + 6, e + 4
        p.rect(WHITE, tx - 3, ty - 1, p.measure(msg) + 6, 14, 230)
        p.frame(_pen(SEL, 1.0), tx - 3, ty - 1, p.measure(msg) + 6, 14)
        p.text(msg, tx, ty, SEL)
    elif d and d["mode"] == "reorder" and d.get("slot") is not None:
        r = lay.bands[d["index"]].rect
        p.rect(SEL, r[0], r[1], r[2], r[3], 70)
        _edge_line(p, lay, lay.slot_pos(d["slot"]), _pen(SEL, 3.5), 10)


def paint_tile(g, lay, width, height):
    """A compact layout (SectionLayout(..., compact=True)) for the assembly palette: the bands and
    the two finished faces heavy, no text. Returns False when there is no layer stack."""
    p = Painter(g)
    p.rect(WHITE, 0, 0, width, height)
    if not lay.bands:
        return False
    for b in lay.bands:
        _band(p, lay, b)
    heavy = _pen(INK, 1.8)
    first, last = lay.bands[0], lay.bands[-1]
    if lay.orient == "h":
        p.line(heavy, first.lo, lay.y0, first.lo, lay.y1)
        p.line(heavy, last.hi, lay.y0, last.hi, lay.y1)
    else:
        p.line(heavy, lay.x0, first.lo, lay.x1, first.lo)
        p.line(heavy, lay.x0, last.hi, lay.x1, last.hi)
    return True


def _edge_line(p, lay, pos, pen, over=4):
    if lay.orient == "h":
        p.line(pen, pos, lay.y0 - over, pos, lay.y1 + over)
    else:
        p.line(pen, lay.x0 - over, pos, lay.x1 + over, pos)


def render_png(ctl, path, width=None, height=None):
    """Draw the controller's section into a PNG (same painting as on screen). Returns the path."""
    if width and height:
        ctl.resize(width, height)
    w, h = int(ctl.layout.width), int(ctl.layout.height)
    bmp = drawing.Bitmap(w, h, drawing.PixelFormat.Format32bppRgba)
    g = drawing.Graphics(bmp)
    try:
        paint(g, ctl, w, h)
    finally:
        g.Dispose()
    bmp.Save(path, drawing.ImageFormat.Png)
    bmp.Dispose()
    return path


# -- the Drawable --------------------------------------------------------------------------------
class SectionView(object):
    """An Eto Drawable showing a SectionController; on_change(result) after a click / drag
    ("select", "thickness", "reorder")."""

    def __init__(self, controller, on_change=None, width=660, height=400):
        self.ctl = controller
        self.on_change = on_change
        self.before = None          # called before a press (the editor commits typed fields)
        self.painted, self.error = 0, None
        d = forms.Drawable()
        d.Size = drawing.Size(width, height)
        d.BackgroundColor = drawing.Colors.White
        d.Paint += self._paint
        d.MouseDown += self._down
        d.MouseMove += self._move
        d.MouseUp += self._up
        d.SizeChanged += self._resized
        self.control = d

    def invalidate(self):
        try:
            self.control.Invalidate()
        except Exception:
            pass

    def _paint(self, sender, e):
        try:
            paint(e.Graphics, self.ctl)
            self.painted += 1
        except Exception as ex:
            self.error = str(ex)
            print("Mind Canvas section view: {}".format(ex))

    def _resized(self, sender, e):
        s = self.control.Size
        if s.Width > 0 and s.Height > 0:
            self.ctl.resize(s.Width, s.Height)
            self.invalidate()

    def _cursor(self):
        h = self.ctl.hover
        try:
            if self.ctl.drag is not None and self.ctl.drag["mode"] == "reorder":
                c = forms.Cursors.Move
            elif h and h[0] == "edge":
                c = forms.Cursors.VerticalSplit if self.ctl.layout.orient == "h" else forms.Cursors.HorizontalSplit
            elif h:
                c = forms.Cursors.Pointer
            else:
                c = forms.Cursors.Default
            self.control.Cursor = c
        except Exception:
            pass

    def _down(self, sender, e):
        if self.before is not None:
            self.before()
        r = self.ctl.down(e.Location.X, e.Location.Y)
        e.Handled = True
        self.invalidate()
        if r and self.on_change:
            self.on_change(r)

    def _move(self, sender, e):
        try:
            fine = e.Modifiers.HasFlag(forms.Keys.Alt)
        except Exception:
            fine = False
        if self.ctl.drag is not None and not e.Buttons.HasFlag(forms.MouseButtons.Primary):
            self._up(sender, e)
            return
        if self.ctl.move(e.Location.X, e.Location.Y, fine):
            self._cursor()
            self.invalidate()

    def _up(self, sender, e):
        if self.ctl.drag is None:
            return
        r = self.ctl.up(e.Location.X, e.Location.Y)
        self.invalidate()
        if r and self.on_change:
            self.on_change(r)
