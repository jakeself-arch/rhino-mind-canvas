"""SVG writer: painter's order, true widths in mm, greys with depth.

Order: projected lines (by class order, far to near) -> ground stipple ->
ground cut regions -> ground lines + bands -> cut regions (large to small: fill,
hatch, dots) -> material loops -> union outline + surface cut lines.
Lines sharing a class and depth bin share one <path> (many subpaths); dots are
zero-length round-capped strokes, one path per bin. Groups are Inkscape /
Illustrator layers named after the line class.
"""

import os

BINS = 12


def _f(v):
    return ("%.2f" % v).rstrip("0").rstrip(".")


class _W(object):
    def __init__(self, dwg):
        self.d = dwg
        self.st = dwg.style
        self.H = dwg.size[1]
        self.out = []

    def P(self, x, y):
        return _f(x) + "," + _f(self.H - y)

    def poly(self, pts, close=False):
        s = "M" + " L".join(self.P(x, y) for x, y in pts)
        return s + ("Z" if close else "")

    def grey(self, dn):
        g = self.st.grey(dn)
        return "#%02X%02X%02X" % (g, g, g)

    def group(self, name):
        self.out.append('<g id="%s" inkscape:groupmode="layer" inkscape:label="%s">' % (name, name))

    def end(self):
        self.out.append("</g>")

    def path(self, d, stroke="#000000", width=0.1, fill="none", extra=""):
        if not d:
            return
        self.out.append('<path d="%s" fill="%s" stroke="%s" stroke-width="%s"%s/>' % (
            d, fill, stroke, _f(width) if width >= 0.01 else "%.3f" % width, extra))


def write(dwg, path):
    st = dwg.style
    w = _W(dwg)
    W, H = dwg.size
    o = w.out
    o.append('<?xml version="1.0" encoding="UTF-8"?>')
    o.append('<svg xmlns="http://www.w3.org/2000/svg" '
             'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
             'width="%smm" height="%smm" viewBox="0 0 %s %s">' % (_f(W), _f(H), _f(W), _f(H)))
    o.append("<title>%s</title>" % dwg.title.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;"))
    o.append('<rect x="0" y="0" width="%s" height="%s" fill="#FFFFFF"/>' % (_f(W), _f(H)))
    c = dwg.clip
    if c:
        o.append('<clipPath id="page"><rect x="%s" y="%s" width="%s" height="%s"/></clipPath>' % (
            _f(c[0]), _f(H - c[3]), _f(c[2] - c[0]), _f(c[3] - c[1])))
        o.append('<g clip-path="url(#page)">')

    # 1. projected lines
    groups = {}
    for pts, cls, dn in dwg.lines:
        groups.setdefault(cls, {}).setdefault(int(round(dn * (BINS - 1))), []).append(pts)
    for cls in sorted(groups, key=lambda k: st.cls(k).get("order", 20)):
        w.group(cls)
        dash = st.cls(cls).get("dash")
        extra = ' stroke-linecap="round" stroke-linejoin="round"'
        if dash:
            extra += ' stroke-dasharray="%s"' % ",".join(_f(x) for x in dash)
        for b in sorted(groups[cls], reverse=True):
            dn = b / float(BINS - 1)
            w.path(" ".join(w.poly(p) for p in groups[cls][b]), w.grey(dn), st.width(cls, dn), extra=extra)
        w.end()

    # 2. ground stipple beyond the cut
    dot_w = st.width("stipple", 0.0)
    rc = ' stroke-linecap="round"'
    if dwg.dots:
        w.group("stipple")
        bins = {}
        for x, y, dn in dwg.dots:
            bins.setdefault(int(round(dn * (BINS - 1))), []).append((x, y))
        for b in sorted(bins, reverse=True):
            dn = b / float(BINS - 1)
            d = " ".join("M%s h0.001" % w.P(x, y) for x, y in bins[b])
            w.path(d, w.grey(dn * 0.6), dot_w * (1.0 - 0.35 * dn), extra=rc)
        w.end()

    # 3. cut: ground regions, ground lines, then all other regions
    regs = dwg.painter_regions()
    hatch_w = st.width("cut_hatch")
    inner_w = st.width("cut_inner")
    cut_w = st.width("cut")
    w.group("cut")

    def region(r):
        spec = r.spec
        fill = spec.get("fill", "white")
        d = " ".join(w.poly(lp, True) for lp in r.loops)
        if fill == "black":
            w.path(d, "#000000", inner_w * 0.6, "#000000", ' fill-rule="evenodd" stroke-linejoin="round"')
        elif fill == "grey":
            g = int(255 * (1.0 - float(spec.get("grey", 0.5))))
            col = "#%02X%02X%02X" % (g, g, g)
            w.path(d, "none", 0, col, ' fill-rule="evenodd"')
        elif fill != "none":
            w.path(d, "none", 0, "#FFFFFF", ' fill-rule="evenodd"')
        if r.hatch:
            w.path(" ".join(w.poly(p) for p in r.hatch), "#000000", hatch_w, extra=' stroke-linecap="round"')
        if r.dots:
            w.path(" ".join("M%s h0.001" % w.P(x, y) for x, y in r.dots), "#000000", dot_w, extra=rc)

    for r in regs:
        if r.ground:
            region(r)
    for pts, dts in dwg.ground:
        if dts:
            w.path(" ".join("M%s h0.001" % w.P(x, y) for x, y in dts), "#000000", dot_w, extra=rc)
    for pts, dts in dwg.ground:
        closed = len(pts) > 3 and pts[0] == pts[-1]
        w.path(w.poly(pts, closed), "#000000", cut_w, extra=' stroke-linejoin="round" stroke-linecap="round"')
    for r in regs:
        if not r.ground:
            region(r)
    inner = [r for r in regs if not r.ground and not r.small and r.spec.get("inner", True)
             and r.spec.get("fill") != "black"]
    if inner:
        w.path(" ".join(w.poly(lp, True) for r in inner for lp in r.loops), "#000000", inner_w,
               extra=' stroke-linejoin="round"')
    if dwg.outlines:
        w.path(" ".join(w.poly(lp, True) for lp in dwg.outlines), "#000000", cut_w,
               extra=' stroke-linejoin="round"')
    if dwg.cut_lines:
        w.path(" ".join(w.poly(p) for p in dwg.cut_lines), "#000000", cut_w,
               extra=' stroke-linejoin="round" stroke-linecap="round"')
    w.end()

    if c:
        o.append("</g>")
    o.append("</svg>")
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(o))
    return path
