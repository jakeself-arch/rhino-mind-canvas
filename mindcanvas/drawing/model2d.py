"""The finished 2D drawing, in paper millimetres (x right, y UP, origin bottom-left).

    lines     [(pts, cls, dn)]    projected lines: silhouette | edge | junction | tone | hidden | entourage
    dots      [(x, y, dn)]        ground stipple beyond the cut
    regions   [cut.Region]        cut poche with hatch / dots, painted last
    ground    [(pts, dots)]       ground cut lines (heavy) + their stipple band
    outlines  [loop]              union outline of all cut regions (heavy)
    cut_lines [pts]               open cut lines of surfaces (heavy)
dn = normalised depth, 0 at the cut / nearest, 1 far.
"""


class Drawing(object):
    def __init__(self, style):
        self.style = style
        self.lines = []
        self.dots = []
        self.regions = []
        self.ground = []
        self.outlines = []
        self.cut_lines = []
        self.size = (0.0, 0.0)
        self.clip = None          # (x0, y0, x1, y1) visible area on the page
        self.timing = {}
        self.stats = {}
        self.warnings = []
        self.title = ""

    def translate(self, dx, dy):
        self.lines = [([(x + dx, y + dy) for x, y in pts], c, d) for pts, c, d in self.lines]
        self.dots = [(x + dx, y + dy, d) for x, y, d in self.dots]
        for r in self.regions:
            r.translate(dx, dy)
        self.ground = [([(x + dx, y + dy) for x, y in pts], [(x + dx, y + dy) for x, y in ds])
                       for pts, ds in self.ground]
        self.outlines = [[(x + dx, y + dy) for x, y in lp] for lp in self.outlines]
        self.cut_lines = [[(x + dx, y + dy) for x, y in lp] for lp in self.cut_lines]
        if self.clip:
            c = self.clip
            self.clip = (c[0] + dx, c[1] + dy, c[2] + dx, c[3] + dy)

    def painter_regions(self):
        """Ground first, then large to small, so small parts sit on top."""
        return sorted(self.regions, key=lambda r: (not r.ground, -r.area))

    def summary(self):
        return {"lines": len(self.lines), "dots": len(self.dots), "regions": len(self.regions),
                "outlines": len(self.outlines), "ground_lines": len(self.ground),
                "hatch": sum(len(r.hatch) for r in self.regions),
                "cut_dots": sum(len(r.dots) for r in self.regions) + sum(len(d) for _, d in self.ground),
                "page_mm": [round(self.size[0], 1), round(self.size[1], 1)]}
