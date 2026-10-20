"""What an assembly looks like to the viewport tools: its outline (hover highlight), its drag
handles and its hover label. Pure geometry from the driver and the library; nothing is drawn or
changed here.

    shape_of(doc, lib, driver)   -> Shape or None
    Shape.outline                polylines (lists of Point3d) around the assembly
    Shape.handles                [Handle]; Handle.at(t, fine) -> Drag for a drag of t model units
                                 along the handle's axis (fine: Shift held)
    Shape.lines                  the hover label, line by line

A Drag carries the parameter changes the drag makes (applied by overlay.apply on release), ghost
polylines (the assembly at the new value) and the dimension tag text. Lengths snap to 1" (fine:
1/8"), pitches to 1/2 in 12 (fine: 1/8). Handles:

    wall           Height (top, up), Base (bottom, down; the top stays), Flip (click the arrow out
                   of the exterior face)
    curtain wall   Height, Base
    window / door  left / right edges (width; the other edge stays), head (height), sill (windows;
                   the head stays), center (slides along the wall)
    floor          Elevation (up / down)
    roof           Plate height, Overhang (out of an eave), Pitch (at the ridge / high side)
"""

import math

import Rhino

from .. import geo, meta, props, units

G = Rhino.Geometry
STEP_IN = 1.0
FINE_IN = 0.125
PITCH_STEP = 0.5
PITCH_FINE = 0.125
MIN_IN = 6.0          # smallest window / door size a drag makes
MIN_WALL_IN = 12.0    # lowest wall a drag makes


def snap(v, step):
    return round(v / step) * step if step > 0 else v


def length_step(fine):
    return FINE_IN if fine else STEP_IN


def fmt(inches):
    return units.format_inches(inches)


def pts(curve, z=None, n=48):
    """The curve as points (a closed curve repeats its first point)."""
    ok, pl = curve.TryGetPolyline()
    if ok:
        out = list(pl)
    else:
        ts = curve.DivideByCount(n, True)
        out = [curve.PointAt(t) for t in ts] if ts else [curve.PointAtStart, curve.PointAtEnd]
        if curve.IsClosed and out:
            out.append(G.Point3d(out[0]))
    if z is not None:
        out = [G.Point3d(p.X, p.Y, z) for p in out]
    return out


def at_z(poly, z):
    return [G.Point3d(p.X, p.Y, z) for p in poly]


def lifted(polys, dz):
    return [[G.Point3d(p.X, p.Y, p.Z + dz) for p in poly] for poly in polys]


def closed(points2d, z):
    out = [G.Point3d(x, y, z) for x, y in points2d]
    if out:
        out.append(G.Point3d(out[0]))
    return out


class Drag(object):
    def __init__(self, changes, ghost, text):
        self.changes = changes      # driver params to set ({} = no change)
        self.ghost = ghost          # polylines
        self.text = text


class Handle(object):
    """anchor: where the handle's arrow starts; axis: unit drag direction (also where the arrow
    points); at(t, fine) -> Drag. A click handle (flip) acts on a click: at(0, False)."""

    def __init__(self, key, label, anchor, axis, at, click=False):
        self.key, self.label = key, label
        self.anchor = G.Point3d(anchor)
        L = axis.Length or 1.0
        self.axis = G.Vector3d(axis.X / L, axis.Y / L, axis.Z / L)
        self.at = at
        self.click = click

    def __repr__(self):
        return "Handle({})".format(self.key)


class Shape(object):
    def __init__(self, kind, driver):
        self.kind, self.driver = kind, driver
        self.outline = []
        self.handles = []
        self.lines = []

    def handle(self, key):
        for h in self.handles:
            if h.key == key:
                return h
        return None


# -- walls / curtain walls ----------------------------------------------------------------------
def _box(faces, z0, z1, closed_curve):
    """Outline of a vertical assembly: each face polyline at z0 and z1, plus the end faces."""
    out = []
    for f in faces:
        out.append(at_z(f, z0))
        out.append(at_z(f, z1))
    if not closed_curve:
        a, b = faces[0], faces[-1]
        for i in (0, -1):
            p, q = a[i], b[i]
            out.append([G.Point3d(p.X, p.Y, z0), G.Point3d(p.X, p.Y, z1), G.Point3d(q.X, q.Y, z1),
                        G.Point3d(q.X, q.Y, z0), G.Point3d(p.X, p.Y, z0)])
    return out


def _vertical(shape, doc, curve, faces, z0, height_in, base_in, mid_offset):
    """Height and Base handles of a wall / curtain wall (z0 = base elevation, model units)."""
    s = units.inch_scale(doc)
    z1 = z0 + height_in * s
    cl = curve.IsClosed
    shape.outline = _box(faces, z0, z1, cl)
    ok, tm = curve.LengthParameter(0.5 * curve.GetLength())
    fr = geo.frame_at(curve, tm if ok else curve.Domain.Mid)
    c = fr.Origin + fr.YAxis * mid_offset

    def height(t, fine):
        dh = max(snap(t / s, length_step(fine)), MIN_WALL_IN - height_in)
        new = round(height_in + dh, 4)
        return Drag({"height": new}, _box(faces, z0, z1 + dh * s, cl), "Height " + fmt(new))

    def base(t, fine):
        db = max(snap(t / s, length_step(fine)), MIN_WALL_IN - height_in)    # down = positive
        nb, nh = round(base_in - db, 4), round(height_in + db, 4)
        return Drag({"base_offset": nb, "height": nh}, _box(faces, z0 - db * s, z1, cl),
                    "Base offset {}  (height {})".format(fmt(nb), fmt(nh)))

    shape.handles.append(Handle("height", "Height", G.Point3d(c.X, c.Y, z1), G.Vector3d.ZAxis, height))
    shape.handles.append(Handle("base", "Base", G.Point3d(c.X, c.Y, z0), -G.Vector3d.ZAxis, base))
    return fr


def _wall(doc, lib, d):
    from .. import masses
    tol = doc.ModelAbsoluteTolerance
    s = units.inch_scale(doc)
    info = masses.WallInfo(doc, lib, d)
    st = props.settings(lib, d)
    shape = Shape("wall", d)
    ext = pts(geo.offset(info.curve, info.y_ext, tol))
    itr = pts(geo.offset(info.curve, info.y_int, tol))
    h_in = info.height / s
    b_in = units.parse_length(st.get("base_offset", 0))
    fr = _vertical(shape, doc, info.curve, [ext, itr], info.base_z, h_in, b_in, 0.5 * (info.y_ext + info.y_int))
    flip = bool(st.get("flip"))
    zm = info.base_z + 0.5 * info.height
    o = fr.Origin + fr.YAxis * info.y_ext

    def do_flip(t, fine):
        return Drag({"flip": not flip}, [], "Flip: exterior to the other side")

    shape.handles.append(Handle("flip", "Flip", G.Point3d(o.X, o.Y, zm), fr.YAxis, do_flip, click=True))
    T = (info.y_ext - info.y_int) / s
    shape.lines = [meta.get(d, meta.ASSEMBLY) or "Wall",
                   "{} thick, {} high{}".format(fmt(T), fmt(h_in), ", base {}".format(fmt(b_in)) if abs(b_in) > 1e-6 else "")]
    return shape


def _curtain_wall(doc, lib, d):
    s = units.inch_scale(doc)
    st = props.settings(lib, d)
    crv = geo.orient_driver(d.Geometry)
    if st.get("flip"):
        crv.Reverse()
    h_in = units.parse_length(st.get("height", 120))
    b_in = units.parse_length(st.get("base_offset", 0))
    z0 = crv.PointAtStart.Z + b_in * s
    shape = Shape("curtain_wall", d)
    _vertical(shape, doc, crv, [pts(crv)], z0, h_in, b_in, 0.0)
    shape.lines = [meta.get(d, meta.ASSEMBLY) or "Curtain wall",
                   "{}, {} high, grid {}".format(props.label(st.get("style", "")), fmt(h_in),
                                                 fmt(units.parse_length(st.get("spacing", 60))))]
    return shape


# -- windows / doors ----------------------------------------------------------------------------
class OpeningFrame(object):
    """Where an opening sits in its wall (model units): origin O on the oriented wall curve at the
    opening's station, X along the wall, Y toward the exterior, base_z, the face offsets, and
    sgn = +1 when the station grows along X."""

    def __init__(self, doc, lib, host, station_in):
        from .. import masses
        s = units.inch_scale(doc)
        info = masses.WallInfo(doc, lib, host)
        raw = info.raw
        L = raw.GetLength()
        ok, tr = raw.LengthParameter(min(max(station_in * s, 0.0), L))
        P = raw.PointAt(tr)
        T = raw.TangentAt(tr)
        ok, tc = info.curve.ClosestPoint(P)
        fr = geo.frame_at(info.curve, tc)
        self.info = info
        self.O, self.X, self.Y = fr.Origin, fr.XAxis, fr.YAxis
        self.sgn = 1.0 if (self.X * T) >= 0 else -1.0
        self.base_z = info.base_z
        self.y_ext, self.y_int = info.y_ext, info.y_int
        self.s = s

    def point(self, x_in, y, z_in):
        """x_in, z_in in inches (along the wall from the station / above the base), y model."""
        p = self.O + self.X * (x_in * self.s) + self.Y * y
        return G.Point3d(p.X, p.Y, self.base_z + z_in * self.s)

    def rect(self, x0, x1, zb, zt):
        """A rough opening (inches) on both faces, with its four corner lines through the wall."""
        out = []
        for y in (self.y_ext, self.y_int):
            out.append([self.point(x0, y, zb), self.point(x1, y, zb), self.point(x1, y, zt),
                        self.point(x0, y, zt), self.point(x0, y, zb)])
        for x, z in ((x0, zb), (x1, zb), (x1, zt), (x0, zt)):
            out.append([self.point(x, self.y_ext, z), self.point(x, self.y_int, z)])
        return out


def opening_box(t, width, height, sill):
    """(half width, bottom, top) of the rough opening (inches) of a unit."""
    shim = units.parse_length(t["shim"])
    door = t.get("category") == "door"
    return 0.5 * width + shim, (sill if door else sill - shim), sill + height + shim


def _opening(doc, lib, d):
    from ..openings import core
    host = core.host_of(doc, d)
    name = meta.get(d, meta.ASSEMBLY) or "Opening"
    st = props.settings(lib, d)
    W, H, sill = [units.parse_length(st[k]) for k in ("width", "height", "sill")]
    shape = Shape("opening", d)
    shape.lines = [name, "{} x {}, sill {}".format(fmt(W), fmt(H), fmt(sill))]
    if host is None or meta.get(host, meta.TYPE) != "wall":
        return shape                  # curtain-wall doors: their bay sets the size
    t = core.merged_type(lib, name, meta.params(d))
    door = t.get("category") == "door"
    station = float(meta.params(d).get("station", 0.0))
    of = OpeningFrame(doc, lib, host, station)
    ro = meta.params(d).get("ro")
    if ro:
        half, zb, zt = 0.5 * float(ro["width"]), float(ro["bottom"]), float(ro["top"])
    else:
        half, zb, zt = opening_box(t, W, H, sill)
    shape.outline = of.rect(-half, half, zb, zt)
    sgn = of.sgn
    zm = 0.5 * (zb + zt)

    def widen(side):
        def at(tt, fine):
            dw = max(snap(tt / of.s, length_step(fine)), MIN_IN - W)
            new_w = round(W + dw, 4)
            ds = side * sgn * 0.5 * dw
            x0, x1 = (-half, half + dw) if side > 0 else (-half - dw, half)
            return Drag({"width": new_w, "station": round(station + ds, 4)}, of.rect(x0, x1, zb, zt),
                        "Width " + fmt(new_w))
        return at

    def head(tt, fine):
        dh = max(snap(tt / of.s, length_step(fine)), MIN_IN - H)
        new_h = round(H + dh, 4)
        return Drag({"height": new_h}, of.rect(-half, half, zb, zt + dh),
                    "Height {}  (head {})".format(fmt(new_h), fmt(sill + new_h)))

    def low(tt, fine):
        dd = snap(tt / of.s, length_step(fine))                 # down = positive
        dd = min(max(dd, MIN_IN - H), sill)                     # head stays; sill >= 0
        new_s, new_h = round(sill - dd, 4), round(H + dd, 4)
        return Drag({"sill": new_s, "height": new_h}, of.rect(-half, half, zb - dd, zt),
                    "Sill {}  (height {})".format(fmt(new_s), fmt(new_h)))

    def slide(tt, fine):
        dm = snap(tt / of.s, length_step(fine))
        return Drag({"station": round(station + sgn * dm, 4)}, of.rect(-half + dm, half + dm, zb, zt),
                    "Moved {}".format(fmt(dm)))

    y = of.y_ext
    shape.handles += [
        Handle("right", "Width", of.point(half, y, zm), of.X, widen(1)),
        Handle("left", "Width", of.point(-half, y, zm), -of.X, widen(-1)),
        Handle("head", "Height", of.point(0, y, zt), G.Vector3d.ZAxis, head),
        Handle("move", "Move", of.point(0, y, zm), of.X, slide),
    ]
    if not door:
        shape.handles.append(Handle("sill", "Sill", of.point(0, y, zb), -G.Vector3d.ZAxis, low))
    return shape


# -- floors / roofs -----------------------------------------------------------------------------
def _centroid(poly2d):
    n = len(poly2d)
    a = cx = cy = 0.0
    for i in range(n):
        (x0, y0), (x1, y1) = poly2d[i], poly2d[(i + 1) % n]
        c = x0 * y1 - x1 * y0
        a += c
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    if abs(a) < 1e-12:
        return sum(p[0] for p in poly2d) / n, sum(p[1] for p in poly2d) / n
    return cx / (3 * a), cy / (3 * a)


def _floor(doc, lib, d):
    from ..kinds import floor as floorkind
    s = units.inch_scale(doc)
    ctx = floorkind.make_context(doc, lib, d, meta.get(d, meta.ASSEMBLY), meta.params(d))
    z_top, z_bot = ctx.bands[0].d_ext, ctx.bands[-1].d_int
    poly = ctx.poly_world
    base = [closed(poly, z_top), closed(poly, z_bot)]
    st = props.settings(lib, d)
    b0 = units.parse_length(st.get("base_offset", 0))
    shape = Shape("floor", d)
    shape.outline = base
    cx, cy = _centroid(poly)

    def elev(tt, fine):
        dz = snap(tt / s, length_step(fine))
        nb = round(b0 + dz, 4)
        return Drag({"base_offset": nb}, lifted(base, dz * s),
                    "Elevation {}  (top {})".format(fmt(nb), fmt(z_top / s + dz)))

    shape.handles.append(Handle("elevation", "Elevation", G.Point3d(cx, cy, z_top), G.Vector3d.ZAxis, elev))
    shape.lines = [meta.get(d, meta.ASSEMBLY) or "Floor",
                   "top at {}, {} deep".format(fmt(z_top / s), fmt((z_top - z_bot) / s))]
    return shape


def _roof(doc, lib, d):
    from ..kinds import roof as roofkind
    s = units.inch_scale(doc)
    ctx = roofkind.make_context(doc, lib, d, meta.get(d, meta.ASSEMBLY), meta.params(d))
    st = ctx.st
    zp = ctx.base_z
    f = ctx.faces[0]
    px0, py0, px1, py1 = f.plate_bbox
    bx0 = f.bbox[0]
    ym = 0.5 * (py0 + py1)
    fw = f.frame.world
    plate = [closed(ctx.poly_world, zp)]
    shape_name = st.get("shape", "flat")
    pitch = float(st.get("pitch") or 0.0)
    over = units.parse_length(st.get("overhang", 0))
    b0 = units.parse_length(meta.params(d).get("base_offset", 0))
    sloped = shape_name != "flat" and pitch > 0
    xr = (f.v_ridge if f.v_ridge is not None else px1)
    run = max(xr - px0, 1e-6)
    gable = f.v_ridge is not None

    def profile(z_plate, p):
        """The roof's section at the ends and the middle of its ridge direction (+ the ridge line)."""
        if p <= 0:
            return []
        zr = z_plate + p / 12.0 * run
        out = []
        for y in (py0, ym, py1):
            line = [fw(px0, y, z_plate), fw(xr, y, zr)]
            if gable:
                line.append(fw(2 * xr - px0, y, z_plate))
            out.append(line)
        out.append([fw(xr, py0, zr), fw(xr, py1, zr)])
        return out

    shape = Shape("roof", d)
    shape.outline = plate + (profile(zp, pitch) if sloped else [])

    def plate_at(tt, fine):
        dz = snap(tt / s, length_step(fine))
        nb = round(b0 + dz, 4)
        return Drag({"base_offset": nb}, lifted(plate, dz * s) + (profile(zp + dz * s, pitch) if sloped else []),
                    "Plate height {}".format(fmt(nb)))

    def overhang_at(tt, fine):
        no = max(round(snap(over + tt / s, length_step(fine)), 4), 0.0)
        x = px0 - no * s
        line = [fw(x, py0, zp), fw(x, py1, zp)]
        return Drag({"overhang": no}, [line, [fw(px0, ym, zp), fw(x, ym, zp)]], "Overhang " + fmt(no))

    def pitch_at(tt, fine):
        rise = pitch / 12.0 * run + tt
        p = max(snap(12.0 * rise / run, PITCH_FINE if fine else PITCH_STEP), PITCH_STEP)
        return Drag({"pitch": round(p, 4)}, profile(zp, p), "Pitch {:g} in 12".format(p))

    shape.handles.append(Handle("plate", "Plate height", fw(px0, ym, zp), G.Vector3d.ZAxis, plate_at))
    shape.handles.append(Handle("overhang", "Overhang", fw(bx0, ym, zp), -f.frame.x, overhang_at))
    if sloped:
        shape.handles.append(Handle("pitch", "Pitch", fw(xr, ym, zp + pitch / 12.0 * run), G.Vector3d.ZAxis, pitch_at))
    desc = props.label(shape_name) + (", {:g} in 12".format(pitch) if sloped else "")
    shape.lines = [meta.get(d, meta.ASSEMBLY) or "Roof", "{}, plate {}".format(desc, fmt(b0))]
    return shape


BUILDERS = {"wall": _wall, "curtain_wall": _curtain_wall, "opening": _opening, "floor": _floor, "roof": _roof}


def shape_of(doc, lib, driver):
    """The Shape of an assembly driver (None for kinds without one or when it cannot be read)."""
    fn = BUILDERS.get(meta.get(driver, meta.TYPE))
    if fn is None:
        return None
    try:
        return fn(doc, lib, driver)
    except Exception:
        return None


def label_lines(doc, lib, driver):
    sh = shape_of(doc, lib, driver)
    if sh is not None and sh.lines:
        return sh.lines
    kind = meta.get(driver, meta.TYPE) or ""
    return [meta.get(driver, meta.ASSEMBLY) or props.label(kind), props.label(props.kind_name(kind))]
