"""Roof settings and faces.

Settings = DEFAULTS <- assembly <- driver params (dicts merge). Lengths in inches:

    shape        flat | shed | gable
    pitch        rise per 12 (flat: the structure is level; slope comes from 'taper' layers)
    overhang     eave overhang: plate line (boundary) to the outside face of the fascia
    rake         rake overhang (gable ends; the sides of shed and flat roofs)
    ridge        ridge direction (shed / flat: the direction of the eaves): long | short | <degrees>
    flip         shed / flat: put the high (uphill) side on the other side of the ridge direction
    wall_depth   depth of the bearing wall framing (birdsmouth seat, ceiling inset)
    wall_ext     thickness of the wall layers outside the framing (the soffit stops there)
    wall_int     thickness of the wall layers inside the framing (ceilings start there)
    trim         eave / rake trim: see TRIM below

Faces: one per roof plane (gable: two). A face has a local frame (x = uphill horizontal, y = the
ridge direction, z = world z), its overhang footprint `poly` (CCW, local), the boundary `plate`
in the same coordinates, `v_ridge` (gable: the ridge's x; None otherwise), slope p = pitch / 12
and `zb`, the rafter bottom line z = a + p x through the bearing (wood: the inner edge of the
eave wall at plate height, so the birdsmouth seat is the full wall depth; metal: the outer edge).
"""

import copy
import math

import Rhino

from .. import hgeo, units

G = Rhino.Geometry
SHAPES = ("flat", "shed", "gable")

TRIM = {
    "fascia": True, "fascia_t": 0.75, "fascia_drop": 0.75, "fascia_material": "Wood Trim",
    "subfascia": True, "subfascia_t": 1.5,
    "soffit": True, "soffit_t": 0.375, "soffit_material": "Soffit Panel",
    "soffit_vent": 2.0, "vent_material": "Soffit Vent", "soffit_nailer": "2x2",
    "drip_edge": True, "drip_t": 0.025, "drip_material": "Flashing",
    "gutter": "k", "gutter_size": 5.0, "gutter_t": 0.032, "gutter_material": "Gutter",
    "rake_board": True, "barge": True, "lookout": "2x4", "lookout_spacing": 24.0,
    "bird_block": True, "vent_gap": 1.5, "baffle_gap": 1.5,
    "ridge_cap": True, "ridge_cap_width": 6.0, "ridge_cap_t": 0.25,
    "edge_nailer": "2x6",
}

DEFAULTS = {
    "shape": "gable",
    "pitch": 6.0,
    "overhang": 18.0,
    "rake": 12.0,
    "ridge": "long",
    "flip": False,
    "wall_depth": 5.5,
    "wall_ext": 1.5,
    "wall_int": 0.5,
    "trim": TRIM,
}


def merged(assembly, params):
    out = copy.deepcopy(DEFAULTS)
    for src in (assembly, params):
        for k, v in (src or {}).items():
            if k not in DEFAULTS:
                continue
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k].update(v)
            else:
                out[k] = copy.deepcopy(v)
    return out


def ridge_direction(poly, ridge):
    try:
        a = math.radians(float(ridge))
        return G.Vector3d(math.cos(a), math.sin(a), 0)
    except (TypeError, ValueError):
        pass
    best, e = -1.0, None
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        L = math.hypot(x1 - x0, y1 - y0)
        if L > best + 1e-9:
            best, e = L, G.Vector3d((x1 - x0) / L, (y1 - y0) / L, 0)
    if ridge == "short":
        return G.Vector3d.CrossProduct(G.Vector3d.ZAxis, e)
    return e


def edge_kind(a, b, tol):
    """eave (along y) | rake (along x) | oblique, for a local edge a -> b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    if abs(dx) <= max(tol, 0.02 * L):
        return "eave"
    if abs(dy) <= max(tol, 0.02 * L):
        return "rake"
    return "oblique"


class Edge(object):
    __slots__ = ("kind", "a", "b", "out")

    def __init__(self, kind, a, b, out):
        self.kind, self.a, self.b, self.out = kind, a, b, out

    @property
    def x(self):
        return 0.5 * (self.a[0] + self.b[0])

    @property
    def y(self):
        return 0.5 * (self.a[1] + self.b[1])

    @property
    def yrange(self):
        return min(self.a[1], self.b[1]), max(self.a[1], self.b[1])

    @property
    def xrange(self):
        return min(self.a[0], self.b[0]), max(self.a[0], self.b[0])


class Face(object):
    def __init__(self, index, frame, poly, plate, v_ridge, p, tol):
        self.index = index
        self.frame = frame
        self.poly = hgeo.ccw(poly)
        self.plate = hgeo.ccw(plate)
        self.v_ridge = v_ridge
        self.p = p
        self.tol = tol
        self.rect = hgeo.is_rect(self.poly, tol)
        self.bbox = hgeo.bbox(self.poly)
        self.plate_bbox = hgeo.bbox(self.plate)
        self.lines = {}        # band index -> (bottom Line, top Line)
        self.zb = None
        self.zt = None

    @property
    def cos(self):
        return 1.0 / math.sqrt(1.0 + self.p * self.p)

    def edges(self):
        """Classified footprint edges with their outward direction (local unit vector);
        the gable's ridge cut is left out."""
        out = []
        n = len(self.poly)
        for i in range(n):
            a, b = self.poly[i], self.poly[(i + 1) % n]
            if math.hypot(b[0] - a[0], b[1] - a[1]) < self.tol * 10:
                continue
            k = edge_kind(a, b, self.tol)
            if self.v_ridge is not None and k == "eave" and abs(a[0] - self.v_ridge) < self.tol * 10:
                continue
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy)
            out.append(Edge(k, a, b, (dy / L, -dx / L)))      # CCW: outward = right of the edge
        return out

    def is_ridge_end(self, x):
        return self.v_ridge is not None and abs(x - self.v_ridge) < self.tol * 10

    def plane(self, line):
        """World plane z = line(x) of this face, normal up."""
        o = self.frame.world(0.0, 0.0, line.a)
        n = self.frame.x * (-line.b) + G.Vector3d(0, 0, 1)
        n.Unitize()
        return G.Plane(o, n)


def faces(ctx, st, metal):
    """Faces of the roof (model units)."""
    tol = ctx.tol
    shape = st["shape"]
    if shape not in SHAPES:
        raise ValueError("Unknown roof shape '{}' (flat | shed | gable).".format(shape))
    pts = ctx.poly_world
    r = ridge_direction(pts, st["ridge"])
    v = G.Vector3d.CrossProduct(G.Vector3d.ZAxis, r)
    if st.get("flip") and shape != "gable":
        v = -v
    F = hgeo.Frame(v)
    plate = hgeo.ccw([(F.local(G.Point3d(x, y, 0)).X, F.local(G.Point3d(x, y, 0)).Y) for x, y in pts])
    eave, rake = ctx.u(st["overhang"]), ctx.u(st["rake"])
    dists = []
    n = len(plate)
    for i in range(n):
        k = edge_kind(plate[i], plate[(i + 1) % n], tol)
        dists.append(rake if k == "rake" else eave)
    over = hgeo.offset_edges(plate, dists)
    p = 0.0 if shape == "flat" else float(st["pitch"]) / 12.0
    if shape != "flat" and p <= 0:
        raise ValueError("A {} roof needs a pitch > 0.".format(shape))
    xmin, ymin, xmax, ymax = hgeo.bbox(plate)
    out = []
    if shape == "gable":
        vr = 0.5 * (xmin + xmax)
        f1 = hgeo.clip_halfplane(over, lambda q: vr - q[0])
        out.append(Face(0, F, f1, plate, vr, p, tol))
        F2 = hgeo.Frame(-v)
        over2 = [(-x, -y) for x, y in over]
        plate2 = [(-x, -y) for x, y in plate]
        f2 = hgeo.clip_halfplane(over2, lambda q: -vr - q[0])
        out.append(Face(1, F2, f2, plate2, -vr, p, tol))
    else:
        out.append(Face(0, F, over, plate, None, p, tol))
    wd = ctx.u(st["wall_depth"])
    for f in out:
        x_plate = f.plate_bbox[0]
        x0 = x_plate + (0.0 if metal else wd)
        f.zb = hgeo.Line(ctx.base_z - x0 * p, p)
    return out
