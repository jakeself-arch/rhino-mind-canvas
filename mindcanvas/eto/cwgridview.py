"""The drawn elevation of the visual curtain-grid editor: paints a curtainwall.gridedit
GridController (panels, mullions and transoms at their true width, doors with their leaves and
swing marks, dimensions, the selection, the hover and a ghost of what a click would add) and
forwards mouse / key events to it. render_png paints the same into a file (tests, captures)."""

import Eto.Drawing as drawing
import Eto.Forms as forms

from ..curtainwall import gridedit as ge

INK = (30, 32, 36)
PAPER = (255, 255, 255)
DIM = (110, 114, 120)
FILL = {ge.VISION: (200, 226, 243), ge.SPANDREL: (152, 160, 170), ge.SHADOW: (112, 126, 146)}
DOOR = (226, 233, 238)
FRAME = (66, 70, 78)
LOCKED = (18, 18, 20)
SEL = (240, 128, 0)
HOVER = (0, 122, 230)
GHOST = (0, 122, 230)
BAD = (215, 40, 40)
MIN_BAR = 2.0


def _c(rgb, a=255):
    return drawing.Color.FromArgb(rgb[0], rgb[1], rgb[2], a)


def _pen(rgb, width=1.0, dash=False, a=255):
    p = drawing.Pen(_c(rgb, a), float(width))
    if dash:
        p.DashStyle = drawing.DashStyles.Dash
    return p


class Painter(object):
    def __init__(self, g):
        self.g = g
        self.font = drawing.Font(drawing.SystemFont.Default, 8)
        self.bold = drawing.Font(drawing.SystemFont.Bold, 8)

    def rect(self, rgb, x, y, w, h, a=255):
        if w > 0 and h > 0:
            self.g.FillRectangle(_c(rgb, a), float(x), float(y), float(w), float(h))

    def frame(self, pen, x, y, w, h):
        self.g.DrawRectangle(pen, float(x), float(y), float(w), float(h))

    def line(self, pen, x1, y1, x2, y2):
        self.g.DrawLine(pen, float(x1), float(y1), float(x2), float(y2))

    def text(self, s, x, y, rgb=INK, align="left", bold=False):
        f = self.bold if bold else self.font
        if align != "left":
            w = self.g.MeasureString(f, s).Width
            x -= w if align == "right" else 0.5 * w
        self.g.DrawText(f, _c(rgb), float(x), float(y), s)

    def hatch(self, x, y, w, h, spacing, pen):
        """Diagonal lines over a rectangle (clipped)."""
        if w <= 0 or h <= 0:
            return
        self.g.SaveTransform()
        self.g.SetClip(drawing.RectangleF(float(x), float(y), float(w), float(h)))
        k = -h
        while k < w:
            self.line(pen, x + k, y + h, x + k + h, y)
            k += spacing
        self.g.ResetClip()
        self.g.RestoreTransform()


def paint(g, ctl):
    p = Painter(g)
    m = ctl.m
    sc = ctl.sc
    p.rect(PAPER, 0, 0, ctl.W, ctl.Hpx)
    wv = max(MIN_BAR, m.wv * sc)
    wh = max(MIN_BAR, m.wh * sc)
    # panels
    for b in range(m.nbays):
        for z0, z1, r in m.visible_cells(b):
            x, y, w, h = ctl.rect(b, z0, z1)
            kind = m.cell_type(b, r)
            p.rect(FILL.get(kind, FILL[ge.VISION]), x, y, w, h)
            if kind == ge.SHADOW:
                p.hatch(x, y, w, h, 7, _pen((80, 92, 110), 1.0))
            elif kind == ge.VISION and w > 30 and h > 30:
                p.line(_pen((255, 255, 255), 1.5, a=170), x + 0.2 * w, y + 0.55 * h, x + 0.45 * w, y + 0.2 * h)
        d = m.doors.get(b)
        if d is not None:
            _door(p, ctl, b, d)
    # horizontals
    for b in range(m.nbays):
        xa, xb = ctl.bay_rect(b)
        p.rect(FRAME, xa, ctl.y(m.wh), xb - xa, wh)                      # sill
        p.rect(FRAME, xa, ctl.y(m.H), xb - xa, wh)                       # head
        for li in m.lines_in(b):
            if m.hidden(b, li):
                continue
            h = m.hlines[li]
            yy = ctl.y(h.z) - 0.5 * wh
            p.rect(FRAME if h.kind == "transom" else (40, 90, 120), xa, yy, xb - xa, wh)
        d = m.doors.get(b)
        if d is not None:
            p.rect(FRAME, xa, ctl.y(d.head) - 0.5 * wh, xb - xa, wh)
    # verticals
    for k, v in enumerate(m.verts):
        x = ctl.x(v.u)
        if v.kind == "start":
            x0 = min(x, ctl.x(m.wv))
        elif v.kind == "end":
            x0 = min(x, ctl.x(m.L - m.wv))
        else:
            x0 = x - 0.5 * wv
        p.rect(LOCKED if v.locked else FRAME, x0, ctl.y(m.H), wv, m.H * sc)
        if v.kind in ("corner", "kink", "seam"):
            p.text(v.kind, x, ctl.y(m.H) - 13, DIM, "center")
    # curved walls: panels straying too far from the curve, the angle at each grid line
    for b in m.over_limit():
        x, y, w, h = ctl.rect(b, 0.0, m.H)
        p.frame(_pen(BAD, 2.0, True), x + 3, y + 3, w - 6, h - 6)
        p.text("!", x + 0.5 * w, y + 6, BAD, "center", bold=True)
    if m.curved:
        for k, v in enumerate(m.verts):
            t = m.turn(k)
            if abs(t) >= 0.05 and not v.locked or (v.kind == "kink" and abs(t) >= 0.05):
                p.text("{:.1f}°".format(abs(t)), ctl.x(v.u), ctl.y(m.H) - 13, DIM, "center")
    # outline
    xa, xb = sorted((ctl.x(0), ctl.x(m.L)))
    p.frame(_pen(INK, 1.0), xa, ctl.y(m.H), xb - xa, m.H * sc)
    # hover + selection
    if ctl.hover and ctl.drag is None and ctl.hover != ctl.sel:
        _outline(p, ctl, ctl.hover, _pen(HOVER, 1.5))
    if ctl.sel:
        _outline(p, ctl, ctl.sel, _pen(SEL, 2.5))
    # ghost of the add tools
    gh = ctl.ghost
    if gh:
        if gh[0] == "vertical":
            i = m.bay_of_u(gh[1])
            u0, u1 = m.span(i)
            ok = gh[1] - u0 >= m.gap_v - 1e-9 and u1 - gh[1] >= m.gap_v - 1e-9
            x = ctl.x(gh[1])
            p.line(_pen(GHOST if ok else BAD, 2.0, True), x, ctl.y(m.H), x, ctl.y(0))
            p.text(ge.fmt(gh[1]), x + 4, ctl.y(0) + 4, GHOST if ok else BAD)
        else:
            z = gh[1]
            for b in gh[2]:
                xa_, xb_ = ctl.bay_rect(b)
                ok = m.margin_h <= z <= m.H - m.margin_h and not any(
                    abs(m.hlines[i].z - z) < m.gap_h - 1e-9 and abs(m.hlines[i].z - z) > ge.EPS for i in m.lines_in(b))
                p.line(_pen(GHOST if ok else BAD, 2.0, True), xa_, ctl.y(z), xb_, ctl.y(z))
            p.text(ge.fmt(z), max(ctl.x(0), ctl.x(m.L)) + 6, ctl.y(z) - 6, GHOST)
    _dims(p, ctl)


def _door(p, ctl, b, d):
    m = ctl.m
    u0, u1 = m.span(b)
    u0, u1 = u0 + 0.5 * m.wv, u1 - 0.5 * m.wv
    zt = d.head - 0.5 * m.wh
    x, y, w, h = ctl.rect(b, 0.0, d.head)
    p.rect(DOOR, x, y, w, h)
    frame = _pen(INK, 1.0)
    leaves = []
    if d.leaves >= 2:
        um = 0.5 * (u0 + u1)
        leaves = [(u0, um, u0), (um, u1, u1)]
    else:
        leaves = [(u0, u1, u1 if d.hinge == "left" else u0)]
    stile = 4.0
    for a, c, hinge in leaves:
        xa, xb = sorted((ctl.x(a), ctl.x(c)))
        ya, yb = ctl.y(zt), ctl.y(0.5)
        p.frame(frame, xa, ya, xb - xa, yb - ya)
        s = stile * ctl.sc
        if xb - xa > 3 * s and yb - ya > 6 * s:
            p.rect(FILL[ge.VISION], xa + s, ya + s, xb - xa - 2 * s, yb - ya - 3.5 * s)
            p.frame(_pen(INK, 0.8), xa + s, ya + s, xb - xa - 2 * s, yb - ya - 3.5 * s)
        # swing mark (elevation): from the latch side corners to the middle of the hinge side
        xh = ctl.x(hinge)
        xl = ctl.x(c if hinge == a else a)
        dash = _pen(DIM, 1.0, True)
        ym = 0.5 * (ya + yb)
        p.line(dash, xl, ya, xh, ym)
        p.line(dash, xl, yb, xh, ym)
    p.text("{} {}".format("OUT" if d.swing == "out" else "IN", "PAIR" if d.leaves >= 2 else ""), x + 4, y + 4,
           INK, bold=True)


def _outline(p, ctl, h, pen):
    m = ctl.m
    if h[0] == "vertical":
        if h[1] >= len(m.verts):
            return
        x = ctl.x(m.verts[h[1]].u)
        w = max(MIN_BAR, m.wv * ctl.sc) + 4
        p.frame(pen, x - 0.5 * w, ctl.y(m.H) - 2, w, m.H * ctl.sc + 4)
    elif h[0] == "hline":
        li, bay = h[1], h[2]
        if li is None or li >= len(m.hlines):
            return
        hl = m.hlines[li]
        wh = max(MIN_BAR, m.wh * ctl.sc) + 4
        for b in sorted(hl.bays):
            xa, xb = ctl.bay_rect(b)
            p.frame(pen if b == bay else _pen(SEL, 1.0, True), xa, ctl.y(hl.z) - 0.5 * wh, xb - xa, wh)
    elif h[0] in ("door", "door_head"):
        d = m.doors.get(h[1])
        if d is None:
            return
        x, y, w, hh = ctl.rect(h[1], 0.0, d.head)
        p.frame(pen, x + 1, y + 1, w - 2, hh - 2)
    elif h[0] == "cell":
        rows = m.rows(h[1])
        if h[2] >= len(rows):
            return
        z0, z1 = rows[h[2]]
        x, y, w, hh = ctl.rect(h[1], z0, z1)
        p.frame(pen, x + 2, y + 2, w - 4, hh - 4)


def _dims(p, ctl):
    m = ctl.m
    yb = ctl.y(0) + 8
    pen = _pen(DIM, 1.0)
    for k, v in enumerate(m.verts):
        x = ctl.x(v.u)
        p.line(pen, x, yb, x, yb + 10)
    for x, t, dev, bad in ctl.bay_dims():
        p.text(t, x, yb + 1, DIM, "center")
        if dev:
            p.text(dev, x, yb + 13, BAD if bad else DIM, "center", bold=bad)
    xa, xb = sorted((ctl.x(0), ctl.x(m.L)))
    p.line(pen, xa, yb + 30, xb, yb + 30)
    p.text("{} overall{}".format(ge.fmt(m.L), " along the curve" if m.curved else ""), 0.5 * (xa + xb),
           yb + 32, DIM, "center")
    # rows of the selected (else the first) bay at the right
    bay = ctl.selected_bay()
    bay = 0 if bay is None else bay
    xr = xb + 8
    for k, (z0, z1) in enumerate(m.rows(bay)):
        p.line(pen, xr, ctl.y(z0), xr + 8, ctl.y(z0))
    p.line(pen, xr, ctl.y(m.H), xr + 8, ctl.y(m.H))
    for y, t in ctl.row_dims(bay):
        p.text(t, xr + 12, y - 6, DIM)
    p.text("rows: bay {}".format(bay + 1), xr, ctl.y(m.H) - 26, DIM)
    # orientation
    left = "EXTERIOR VIEW" if ctl.view == "exterior" else "INTERIOR VIEW"
    if m.curved:
        left += " (unfolded: every panel is flat)"
    p.text(left, xa, ctl.y(m.H) - 26, INK, bold=True)
    p.text("start", ctl.x(0) + (-4 if ctl.view == "exterior" else 4), ctl.y(0) + 46, DIM,
           "right" if ctl.view == "exterior" else "left")


def render_png(ctl, path, width=None, height=None):
    if width and height:
        ctl.resize(width, height)
    bmp = drawing.Bitmap(int(ctl.W), int(ctl.Hpx), drawing.PixelFormat.Format32bppRgba)
    g = drawing.Graphics(bmp)
    try:
        paint(g, ctl)
    finally:
        g.Dispose()
    bmp.Save(path, drawing.ImageFormat.Png)
    return path


class GridView(object):
    """An Eto Drawable over a GridController. on_change(edited) after every event that changed
    something (edited: the model changed; else only the view)."""

    def __init__(self, controller, on_change=None, width=900, height=520):
        self.ctl = controller
        self.on_change = on_change
        self.control = d = forms.Drawable()
        d.Size = drawing.Size(width, height)
        d.CanFocus = True
        d.Paint += self._paint
        d.SizeChanged += self._resized
        d.MouseDown += self._down
        d.MouseMove += self._move
        d.MouseUp += self._up
        d.MouseLeave += self._leave
        d.KeyDown += self._key

    def invalidate(self):
        try:
            self.control.Invalidate()
        except Exception:
            pass

    def _notify(self, v0):
        self.invalidate()
        if self.on_change:
            self.on_change(self.ctl.version != v0)

    def _paint(self, sender, e):
        try:
            paint(e.Graphics, self.ctl)
        except Exception as ex:
            print("Mind Canvas grid editor paint: {}".format(ex))

    def _resized(self, sender, e):
        s = self.control.Size
        self.ctl.resize(s.Width, s.Height)
        self.invalidate()

    @staticmethod
    def _mods(e):
        m = e.Modifiers
        return {"ctrl": m.HasFlag(forms.Keys.Control), "shift": m.HasFlag(forms.Keys.Shift),
                "alt": m.HasFlag(forms.Keys.Alt)}

    def _down(self, sender, e):
        self.control.Focus()
        if e.Buttons != forms.MouseButtons.Primary:
            return
        v0 = self.ctl.version
        self.ctl.mouse_down(e.Location.X, e.Location.Y, **self._mods(e))
        self._notify(v0)

    def _move(self, sender, e):
        v0 = self.ctl.version
        down = e.Buttons == forms.MouseButtons.Primary
        self.ctl.mouse_move(e.Location.X, e.Location.Y, down, **self._mods(e))
        self.invalidate()
        if self.on_change and self.ctl.version != v0:
            self.on_change(None)            # dragging: preview only

    def _up(self, sender, e):
        v0 = self.ctl.version
        changed = self.ctl.mouse_up(e.Location.X, e.Location.Y)
        self.invalidate()
        if self.on_change:
            self.on_change(bool(changed) or self.ctl.version != v0)

    def _leave(self, sender, e):
        self.ctl.hover = None
        self.ctl.ghost = None
        self.invalidate()

    def _key(self, sender, e):
        v0 = self.ctl.version
        mods = self._mods(e)
        if self.ctl.key(e.Key.ToString(), mods["ctrl"], mods["shift"]):
            e.Handled = True
            self._notify(v0)
