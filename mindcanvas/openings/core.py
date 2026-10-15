"""Opening drivers and their placement in a host.

An opening is its own driver object: a short horizontal line across the unit width at the
unit's sill elevation, lying on the host's driver curve. User text:

    mc.kind = driver      mc.type = opening      mc.assembly = <opening type name>
    mc.host = <host driver id>                   mc.params = JSON (inches):
        width, height     unit (frame outside) size
        sill              unit bottom above the host base (doors: 0)
        station           distance along the host driver curve, as drawn, to the opening center
        swing in|out, hinge left|right (seen from the exterior)        doors
        head  none|soldier|sailor                                       brick course over the lintel
        overrides         {"<type key>": value} merged over the opening type

The opening's parts belong to the host (mc.driver = host id, mc.x.opening = opening id), so a
host rebuild regenerates everything. Moving the line re-reads station / sill / width from it
(sync_from_geometry); editing the host curve moves the line (it follows its station).

Opening types live in library/openings/*.json and are merged over DEFAULTS[category].
"""

import copy
import json

import System
import Rhino

from .. import docutil, geo, meta, units

G = Rhino.Geometry
KIND = "opening"
HOST = "mc.host"
OPENING_KEY = "opening"            # Part.extra key -> user text mc.x.opening on every opening part
LAYER = docutil.ROOT_LAYER + "::_Openings"
SNAP_IN = 1.0 / 64

_COMMON = {
    "shim": "1/2",          # rough opening clearance around the unit (jambs, head, window sill)
    "joint": "3/8",         # sealant joint between cladding and frame
    "frame": {"material": "Aluminum", "face": "1-3/4", "depth": "3-1/4"},
    "position": "weather",  # weather: frame face at the insulation / weather line (first solid
                            # layer behind the cladding's cavity); brick: in the masonry opening,
    "set": "1-1/4",         # its face `set` in front of the back of the brick
    "masonry": {
        "lintel": "auto",               # profile name or auto (smallest family "lintel" angle spanning it)
        "lintel_material": "Steel Angle",
        "bearing": 6,                   # lintel bearing on the brick each side
        "head": "none",                 # none | soldier | sailor  course over the lintel
        "sill": "rowlock",              # rowlock | none           (doors: none)
        "sill_slope": 15,               # degrees
        "sill_projection": "1-1/2",     # minimum projection of the rowlock past the brick face
        "flashing": True,               # head + sill flashing (exterior brick, detail)
        "flashing_material": "Flashing",
        "upturn": 8,                    # head flashing up the backup
        "end_dam": 1,                   # end dam height
        "weeps": 24,                    # weep spacing in the course over the lintel
    },
    "trim": {"liner": "3/4", "stool": "3/4", "stool_projection": "3/4", "material": "Wood Trim"},
    "sill_pan": {"material": "Flashing - Membrane", "thickness": "1/32", "back_dam": 1, "drip": "3/8"},
    "head_flashing": {"material": "Flashing", "thickness": "1/32", "upturn": 2, "drip": "3/8"},
    "closure": {"material": "Aluminum", "thickness": "1/16", "recess": "1/2"},   # brick returns, frame
                                                                               # at the insulation line
    "sealant": "Sealant",
    "backer": "Backer Rod",
}

DEFAULTS = {
    "window": dict(copy.deepcopy(_COMMON), **{
        "category": "window", "width": "3'", "height": "4'", "sill": "3'",
        "operation": "fixed",
        "sash": {"material": "Aluminum", "face": "2", "depth": "1-3/4"},
        "mullions": {"vertical": 0, "horizontal": 0, "face": "1-3/4"},
        "glazing": {"lites": 2, "glass": "1/4", "space": "1/2", "bite": "1/2",
                    "material": "Glass", "spacer": "Aluminum"},
    }),
    "door": dict(copy.deepcopy(_COMMON), **{
        "category": "door", "width": "3'", "height": "7'", "sill": 0,
        "frame": {"material": "Hollow Metal", "face": "2", "depth": "auto", "stop": "5/8"},
        "leaf": {"thickness": "1-3/4", "material": "Hollow Metal Door", "undercut": "3/4", "clearance": "1/8",
                 "lite": None},
        "threshold": {"material": "Aluminum", "width": "5", "height": "1/2"},
        "swing": "in", "hinge": "left",
        "glazing": {"lites": 2, "glass": "1/4", "space": "1/2", "bite": "1/2",
                    "material": "Glass", "spacer": "Aluminum"},
    }),
}
DEFAULTS["door"]["masonry"]["sill"] = "none"
DEFAULTS["door"]["trim"]["stool"] = None
DEFAULTS["door"]["frame"]["max_wrap"] = "8-3/4"   # walls up to this thick get a full-depth frame


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def type_def(lib, name):
    t = lib.data.get("openings", {}).get(name)
    if t is None:
        raise KeyError("Opening type '{}' not found in library/openings".format(name))
    return t


def type_names(lib, category=None):
    return sorted(n for n, t in lib.data.get("openings", {}).items()
                  if category is None or t.get("category", "window") == category)


def merged_type(lib, name, params=None):
    """DEFAULTS[category] <- library type <- params["overrides"]."""
    t = type_def(lib, name)
    out = _merge(DEFAULTS.get(t.get("category", "window"), DEFAULTS["window"]), t)
    return _merge(out, (params or {}).get("overrides"))


# -- drivers ----------------------------------------------------------------
def is_opening(obj):
    return meta.is_driver(obj) and meta.get(obj, meta.TYPE) == KIND


def hosted(doc, host_id):
    found = doc.Objects.FindByUserString(HOST, str(host_id), True) or []
    return [o for o in found if is_opening(o) and not o.IsDeleted]


def host_of(doc, obj):
    hid = meta.get(obj, HOST)
    if not hid:
        return None
    h = doc.Objects.FindId(System.Guid(hid))
    return h if (h is not None and not h.IsDeleted and meta.is_driver(h)) else None


def opening_of(doc, obj):
    """The opening driver for an opening driver or one of its parts, else None."""
    if is_opening(obj):
        return obj
    if meta.is_part(obj):
        oid = meta.get(obj, meta.EXTRA_PREFIX + OPENING_KEY)
        if oid:
            o = doc.Objects.FindId(System.Guid(json.loads(oid) if oid.startswith('"') else oid))
            return o if is_opening(o) else None
    return None


def station_of(raw_curve, point):
    """Distance along a curve (as drawn) to the point closest to `point` (model units)."""
    p = G.Point3d(point.X, point.Y, raw_curve.PointAtStart.Z)
    ok, t = raw_curve.ClosestPoint(p)
    if t - raw_curve.Domain.T0 < 1e-12:
        return 0.0
    return raw_curve.GetLength(G.Interval(raw_curve.Domain.T0, t))


def write(doc, obj, type_name, prm, host_id):
    attrs = obj.Attributes.Duplicate()
    attrs.SetUserString(meta.KIND, meta.DRIVER_KIND)
    attrs.SetUserString(meta.TYPE, KIND)
    attrs.SetUserString(meta.ASSEMBLY, type_name)
    attrs.SetUserString(meta.PARAMS, json.dumps(prm, sort_keys=True))
    attrs.SetUserString(HOST, str(host_id))
    attrs.LayerIndex = docutil.ensure_layer(doc, LAYER, (0, 170, 220))
    doc.Objects.ModifyAttributes(obj, attrs, True)


def create(doc, host_obj, type_name, params=None, point=None, lib=None):
    """Add an opening driver to a host (not built yet). `point`: where along the host (any
    point; it is projected onto the host curve), else params["station"] (inches)."""
    from .. import library
    lib = lib or library.get()
    t = merged_type(lib, type_name, params)
    prm = {"width": t["width"], "height": t["height"], "sill": t["sill"]}
    if t.get("category") == "door":
        prm.update(swing=t.get("swing", "in"), hinge=t.get("hinge", "left"))
    prm.update(params or {})
    for k in ("width", "height", "sill"):
        prm[k] = round(units.parse_length(prm[k]), 4)
    if point is not None:
        prm["station"] = round(units.to_inches(doc, station_of(host_obj.Geometry, point)), 4)
    prm.setdefault("station", 0.0)
    z = host_obj.Geometry.PointAtStart.Z
    p0 = G.Point3d(0, 0, z)
    oid = doc.Objects.AddCurve(G.LineCurve(p0, G.Point3d(units.to_model(doc, prm["width"]), 0, z)))
    obj = doc.Objects.FindId(oid)
    write(doc, obj, type_name, prm, host_obj.Id)
    return doc.Objects.FindId(oid)


def host_base_z(doc, host_obj):
    prm = meta.params(host_obj)
    return host_obj.Geometry.PointAtStart.Z + units.to_model(doc, prm.get("base_offset", 0))


def sync_from_geometry(doc, op_obj, host_obj):
    """Re-read station, sill and width from the (moved / scaled) opening line. Returns True
    if the params changed."""
    crv = op_obj.Geometry
    if not isinstance(crv, G.Curve):
        return False
    s = units.inch_scale(doc)
    prm = meta.params(op_obj)
    mid = crv.PointAt(crv.Domain.Mid)
    new = dict(prm)
    new["station"] = round(units.to_inches(doc, station_of(host_obj.Geometry, mid)), 4)
    new["sill"] = round((mid.Z - host_base_z(doc, host_obj)) / s, 4)
    length = crv.GetLength() / s
    if abs(length - float(prm.get("width", length))) > SNAP_IN:
        new["width"] = round(length, 4)
    changed = any(abs(float(new[k]) - float(prm.get(k, 0) or 0)) > SNAP_IN
                  for k in ("station", "sill", "width"))
    if changed:
        write(doc, op_obj, meta.get(op_obj, meta.ASSEMBLY), new, host_obj.Id)
    return changed


def update(doc, op_obj, changes):
    prm = meta.params(op_obj)
    for k, v in changes.items():
        if v is None:
            prm.pop(k, None)
        else:
            prm[k] = v
    write(doc, op_obj, meta.get(op_obj, meta.ASSEMBLY), prm, meta.get(op_obj, HOST))


def set_type(doc, op_obj, type_name):
    write(doc, op_obj, type_name, meta.params(op_obj), meta.get(op_obj, HOST))


# -- placement in a host build ---------------------------------------------------
class Opening(object):
    """An opening resolved in a host's BuildContext (model units).

    plane: origin on the host's oriented driver curve at z = 0 (world), X along the host,
    Y toward the exterior, Z up. Local coordinates (x, y, z): x along X (the unit spans
    -W/2..W/2), y = signed offset like LayerBand d (positive = exterior), z = world elevation.
    """

    def __init__(self, ctx, obj, place):
        self.obj = obj
        self.id = obj.Id
        self.name = meta.get(obj, meta.ASSEMBLY)
        self.params = p = meta.params(obj)
        self.t = t = merged_type(ctx.lib, self.name, p)
        self.category = t.get("category", "window")
        self.door = self.category == "door"
        u = ctx.u
        self.W = u(p.get("width", t["width"]))
        self.H = u(p.get("height", t["height"]))
        self.sill_in = units.parse_length(p.get("sill", t["sill"]))
        self.shim = u(t["shim"])
        self.joint = u(t["joint"])
        self.z0 = ctx.base_z + self.sill_in * ctx.s
        self.z1 = self.z0 + self.H
        self.rx = 0.5 * self.W + self.shim
        self.rz0 = self.z0 if self.door else self.z0 - self.shim
        self.rz1 = self.z1 + self.shim
        self.swing = str(p.get("swing", t.get("swing", "in"))).lower()
        self.hinge = str(p.get("hinge", t.get("hinge", "left"))).lower()
        self.head = str(p.get("head", t["masonry"].get("head", "none"))).lower()
        if self.W <= ctx.tol or self.H <= ctx.tol:
            raise ValueError("width and height must be positive")
        self.plane, self.s = place(ctx, u(p.get("station", 0.0)), self.rx + u(4))
        self.sag = self._sagitta(ctx)
        bands = [b for b in ctx.bands if b.thickness > ctx.tol]
        self.y_ext = max(b.d_ext for b in bands)
        self.y_int = min(b.d_int for b in bands)
        self._frame_position(ctx, bands)
        top = ctx.base_z + ctx.height
        if self.rz1 > top - u(1):
            ctx.warn("Opening '{}' reaches the top of the wall.".format(self.name))
        if self.z0 < ctx.base_z - ctx.tol:
            ctx.warn("Opening '{}' starts below the wall base.".format(self.name))

    def __repr__(self):
        return "<Opening {} {}x{} @ {:.3f}>".format(self.name, self.W, self.H, self.s)

    # -- coordinates ---------------------------------------------------------
    def pt(self, x, y, z):
        o = self.plane.Origin + self.plane.XAxis * x + self.plane.YAxis * y
        return G.Point3d(o.X, o.Y, z)

    def local(self, p):
        v = G.Point3d(p.X, p.Y, 0) - self.plane.Origin
        return v * self.plane.XAxis, v * self.plane.YAxis, p.Z

    def box(self, x0, x1, y0, y1, z0, z1):
        return geo.box(self.plane, min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1),
                       min(z0, z1), max(z0, z1))

    def jamb_plane(self, x):
        return G.Plane(self.pt(x, 0, 0), self.plane.XAxis)

    def _sagitta(self, ctx):
        """Largest |y| of the host curve within the rough opening (curved hosts)."""
        crv = ctx.curve
        out = 0.0
        for x in (-self.rx - ctx.u(4), self.rx + ctx.u(4)):
            ok, t = crv.LengthParameter(min(max(self.s + x, 0.0), crv.GetLength()))
            if ok:
                out = max(out, abs(self.local(crv.PointAt(t))[1]))
        return out

    def _frame_position(self, ctx, bands):
        """y of the unit's exterior (y_fe) and interior (y_fi) frame faces."""
        from ..components import masonry
        u = ctx.u
        f = self.t["frame"]
        thick = self.y_ext - self.y_int
        depth = f.get("depth", "3-1/4")
        if depth == "auto":
            depth = "wall" if thick <= u(f.get("max_wrap", "8-3/4")) + ctx.tol else "4-3/4"
        self.masonry_ext = None
        ext_brick = [b for b in bands if b.component == "masonry" and masonry.exposed_side(ctx, b) > 0]
        if depth == "wall":
            self.y_fe, self.y_fi = self.y_ext, self.y_int
            return
        D = u(depth)
        if ext_brick:
            self.masonry_ext = max(ext_brick, key=lambda b: b.d_ext)
        if ext_brick and str(self.t.get("position", "weather")).lower() == "brick":
            y_fe = self.masonry_ext.d_int + u(self.t.get("set", "1-1/4"))
        else:
            y_fe = self.y_ext
            seen_solid = False
            ordered = sorted(bands + [b for b in ctx.bands if b.component == "void"], key=lambda b: -b.d_ext)
            for i, b in enumerate(ordered):
                if b.component == "void":
                    if seen_solid:
                        nxt = [c for c in ordered[i + 1:] if c.component != "void"]
                        if nxt:
                            y_fe = nxt[0].d_ext
                        break
                else:
                    seen_solid = True
        self.y_fe = min(y_fe, self.y_ext)
        self.y_fi = max(self.y_fe - D, self.y_int)

    @property
    def behind_brick(self):
        """True when the frame sits behind the exterior brick (at the insulation line)."""
        return self.masonry_ext is not None and self.y_fe <= self.masonry_ext.d_int + 1e-9

    # -- zones and cutters ------------------------------------------------------
    def cladding(self, band):
        """True for a band entirely in front of the unit's frame (cut to the masonry opening)."""
        return band.d_int >= self.y_fe - 1e-9

    def hole(self, ctx, band, z_lo=None):
        """(x0, x1, z0, z1) of the hole in a band: rough opening in the backup, unit + sealant
        joint in the cladding."""
        if self.cladding(band):
            hx = 0.5 * self.W + self.joint
        else:
            hx = self.rx
        z0, z1 = self.rz0, self.rz1
        if z_lo is not None and z0 <= z_lo + ctx.tol:
            z0 = z_lo - ctx.u(1)
        return -hx, hx, z0, z1

    def cutter(self, ctx, x0, x1, z0, z1, y0=None, y1=None):
        m = self.sag + ctx.u(1)
        y0 = self.y_int - m if y0 is None else y0
        y1 = self.y_ext + m if y1 is None else y1
        return self.box(x0, x1, y0, y1, z0, z1)

    def overlaps_z(self, z0, z1):
        return self.rz0 < z1 and self.rz1 > z0

    def driver_line(self):
        return G.LineCurve(self.pt(-0.5 * self.W, 0, self.z0), self.pt(0.5 * self.W, 0, self.z0))


def resolve(ctx, host_obj, place):
    """Opening records for every opening hosted by host_obj (bad ones are skipped with a warning;
    an opening overlapping an earlier one is skipped)."""
    out = []
    for o in sorted(hosted(ctx.doc, host_obj.Id), key=lambda o: meta.params(o).get("station", 0)):
        try:
            op = Opening(ctx, o, place)
        except Exception as ex:
            ctx.warn("Opening '{}' skipped: {}".format(meta.get(o, meta.ASSEMBLY), ex))
            continue
        clash = [q for q in out if abs(q.s - op.s) < q.rx + op.rx + ctx.u(3)
                 and q.rz0 < op.rz1 and q.rz1 > op.rz0]
        if clash:
            ctx.warn("Opening '{}' overlaps another opening; skipped.".format(op.name))
            continue
        out.append(op)
    return out


# -- cutting ---------------------------------------------------------------------------
def _bb_hit(a, b):
    return (a.Min.X <= b.Max.X and b.Min.X <= a.Max.X and a.Min.Y <= b.Max.Y and b.Min.Y <= a.Max.Y
            and a.Min.Z <= b.Max.Z and b.Min.Z <= a.Max.Z)


def subtract(ctx, breps, cutters, what="layer"):
    """Boolean-difference each brep with the cutters that touch it. On failure the brep is
    kept whole with a warning."""
    if not cutters:
        return list(breps)
    tol = ctx.tol
    boxes = [(c, c.GetBoundingBox(True)) for c in cutters]
    out = []
    for b in breps:
        if isinstance(b, G.Extrusion):
            b = b.ToBrep()
        bb = b.GetBoundingBox(True)
        hits = [c for c, cb in boxes if _bb_hit(bb, cb)]
        if not hits:
            out.append(b)
            continue
        res = G.Brep.CreateBooleanDifference([b], hits, tol)
        if res is None:
            cur = [b]
            for c in hits:
                nxt = G.Brep.CreateBooleanDifference(cur, [c], tol)
                if nxt is None:
                    cur = None
                    break
                cur = list(nxt)
            res = cur
        if res is None:
            ctx.warn("Could not cut an opening through {}; left whole.".format(what))
            out.append(b)
            continue
        out.extend(res)
    return out


def cut(ctx, breps, band, z_lo=None):
    """Cut every opening of the context out of a band's solids (rough opening in the backup,
    unit + sealant joint in the cladding)."""
    ops = getattr(ctx, "openings", None) or []
    if not ops:
        return list(breps)
    if z_lo is None:
        z_lo = ctx.z_range(band)[0]
    cutters = []
    for op in ops:
        x0, x1, z0, z1 = op.hole(ctx, band, z_lo)
        cutters.append(op.cutter(ctx, x0, x1, z0, z1))
    return subtract(ctx, breps, cutters, "'{}'".format(band.name))
