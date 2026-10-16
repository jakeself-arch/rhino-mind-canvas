"""Roofs: a closed horizontal boundary (the plate line: outside face of the wall framing) + a
shape (flat / shed / gable) + a layer stack on the roof plane + an optional ceiling stack.

Driver params (JSON on the boundary curve; lengths in inches):
    base_offset  plate height above the curve: the top of the wall plates the rafters bear on
    lod          schematic | design | detail
    shape, pitch, overhang, rake, ridge, flip, wall_depth, wall_ext, wall_int, trim
                 roof settings overriding the assembly's (mindcanvas/roofs/shape.py)
    overrides    {"<layer name>": {"<option>": value}}, e.g. {"Rafters": {"system": "metal"}}
    layers / ceiling   optional per-roof stacks replacing the assembly's

Assembly: "layers" = the roof-plane stack TOP -> BOTTOM; the layer with component "rafters" (or
"core": true) is the structure. Layers above it follow the roof plane out to the fascia; layers
below it (cathedral ceilings) cover the interior. "ceiling" = an optional horizontal stack under
an attic (component "joists" = ceiling joists beside the rafters, bottom at plate height;
layers above it are trimmed under the roof with a vent gap; layers below cover the interior).

Layer components: solid / membrane / void, shingles (courses at detail LOD: exposure, tip),
rafters (system wood | metal, rafter, spacing, cavity_fill, fill_depth). Options on any roof-plane
layer: taper (in / ft: tapered insulation, thickest at the high side; flat roofs), eave_membrane
({"material", "width"}: e.g. ice and water shield from the eave to `width` inside the wall),
region (overhang | interior).

Bands: LayerBand.d_ext / d_int = normal offsets (model units) above the rafter bottom; the lines of
each band on each face are face.lines[band.index] = (bottom, top). Ceiling bands carry absolute z.
Walls under a roof: set the roof's base_offset to the wall height. Joins (mindcanvas/joins): the
wall dimensions come from the walls along the plate line (unless set in the params); those walls
stop their exterior layers under the rafters and are filled up to the roof (gable ends, sheds).
"""

import math

import Rhino

from .. import geo, hgeo, units
from ..components.base import BuildContext, LayerBand
from ..roofs import build as rbuild
from ..roofs import shape as rshape
from . import wall as wallkind

G = Rhino.Geometry
KIND = "roof"
LODS = ("schematic", "design", "detail")
SHAPES = rshape.SHAPES

DEFAULTS = {
    "base_offset": 0,
    "lod": "detail",
}


def settings(assembly, params):
    return rshape.merged(assembly, params)


def _fitted(lib, spec, index, params, comps):
    if spec.get("component") not in comps:
        return spec
    name = wallkind.layer_name(spec, index)
    opts = dict(spec.get("options", {}))
    opts.update(params.get("overrides", {}).get(name, {}))
    try:
        t = rbuild.layer_thickness(lib, spec, opts)
    except Exception:
        return spec
    if t is None:
        return spec
    out = dict(spec)
    out["thickness"] = t
    return out


def make_context(doc, lib, driver_obj, assembly_name, params):
    assembly = lib.assembly(assembly_name)
    tol = doc.ModelAbsoluteTolerance
    curve = driver_obj.Geometry
    if not curve.IsClosed:
        raise geo.GeometryError("A roof boundary must be a closed curve.")
    geo.check_horizontal(curve, tol)
    curve = geo.orient_driver(curve)
    s = units.inch_scale(doc)
    lod = params.get("lod") or assembly.get("lod") or "detail"
    if lod not in LODS:
        raise ValueError("Unknown level of detail '{}'".format(lod))
    st = rshape.merged(assembly, params)
    z_plate = curve.PointAtStart.Z + units.parse_length(params.get("base_offset", 0)) * s
    ctx = BuildContext(doc, lib, assembly_name, assembly, params, curve, z_plate, 0.0, lod)
    ctx.raw_curve = driver_obj.Geometry.DuplicateCurve()
    ctx.st = st
    ctx.openings = []
    raw = params.get("layers") or assembly.get("layers") or []
    layers = [_fitted(lib, lib.resolve_layer(x), i, params, ("rafters",)) for i, x in enumerate(raw)]
    core = [i for i, l in enumerate(layers) if l.get("component") == "rafters"] or \
           [i for i, l in enumerate(layers) if l.get("core")]
    if not core:
        raise ValueError("Roof assembly '{}' has no 'rafters' layer.".format(assembly_name))
    c = core[0]
    th = [units.parse_length(l.get("thickness", 0)) * s for l in layers]
    for i, spec in enumerate(layers):
        lo = sum(th[i + 1:c + 1]) if i < c else -sum(th[c + 1:i + 1])
        ctx.bands.append(LayerBand(i, spec, lo + th[i], lo))
    ctx.structure = ctx.bands[c]
    # ceiling stack (absolute z): joist band bottom at plate height
    craw = params.get("ceiling") if "ceiling" in params else assembly.get("ceiling")
    cl = [_fitted(lib, lib.resolve_layer(x), i, params, ("joists", "framing")) for i, x in enumerate(craw or [])]
    ctx.ceiling_bands = []
    if cl:
        cc = [i for i, l in enumerate(cl) if l.get("component") in ("joists", "framing")]
        cc = cc[0] if cc else len(cl)
        cth = [units.parse_length(l.get("thickness", 0)) * s for l in cl]
        z_top = z_plate + sum(cth[:cc + 1]) if cc < len(cl) else z_plate + sum(cth[:cc])
        z = z_top
        for i, spec in enumerate(cl):
            ctx.ceiling_bands.append(LayerBand(100 + i, spec, z, z - cth[i]))
            z -= cth[i]
    # faces + layer lines
    ctx.poly_world = hgeo.curve_points(curve, tol)
    from .. import joins
    joins.attach_roof(ctx, driver_obj)        # wall_depth / wall_ext / wall_int from the walls under it
    sname, sysd, pname, prof, msg = rbuild.rafter_member(lib, ctx, ctx.structure)
    metal = sysd.get("type") == "metal"
    ctx.faces = rshape.faces(ctx, st, metal)
    for f in ctx.faces:
        f.zt = f.zb.up(ctx.structure.thickness)
        f.lines[c] = (f.zb, f.zt)
        bot = f.zt
        x_low = f.bbox[0]
        for i in range(c - 1, -1, -1):
            band = ctx.bands[i]
            t = band.thickness
            taper = float(ctx.option(band, "taper", 0) or 0)
            if taper > 0:
                b2 = bot.b + taper / 12.0
                z_low = bot(x_low) + t * math.sqrt(1 + bot.b * bot.b)
                top = hgeo.Line(z_low - b2 * x_low, b2)
            else:
                top = bot.up(t)
            f.lines[i] = (bot, top)
            bot = top
        top = f.zb
        for i in range(c + 1, len(ctx.bands)):
            bot = top.up(-ctx.bands[i].thickness)
            f.lines[i] = (bot, top)
            top = bot
    # vertical extents (section views)
    zs = []
    for f in ctx.faces:
        x0, y0, x1, y1 = f.bbox
        for x in (x0, x1):
            for lo, hi in f.lines.values():
                zs += [lo(x), hi(x)]
    zs += [cb.d_int for cb in ctx.ceiling_bands]
    ctx.z_lo = min(zs) - ctx.u(12)
    ctx.z_hi = max(zs)
    ctx.height = ctx.z_hi - z_plate
    return ctx


def build(ctx):
    return rbuild.Builder(ctx).run()


def face_at(ctx, point):
    for f in ctx.faces:
        q = f.frame.local(point)
        if hgeo.inside(f.poly, (q.X, q.Y)):
            return f
    return ctx.faces[0]


def section_frame(ctx, point):
    """Cut plane through `point` along the slope of the face under it (X = plane normal = ridge
    direction, Y = toward that face's eave, Z up) and the extents (eave to eave)."""
    f = face_at(ctx, point)
    o = G.Point3d(point.X, point.Y, ctx.base_z)
    frame = G.Plane(o, f.frame.y, -f.frame.x)
    q = f.frame.local(o)
    x0, y0, x1, y1 = f.bbox
    far = x1 if f.v_ridge is None else 2 * f.v_ridge - x0
    return frame, {"d_ext": q.X - x0, "d_int": q.X - far, "z0": ctx.z_lo, "z1": ctx.z_hi, "t": 0.0}


def summary(ctx):
    """Shape, pitch, roof area (sloped), rafter count / member / spacing, ridge and plate heights."""
    s = ctx.s
    b = rbuild.Builder(ctx)
    n = 0
    for f in ctx.faces:
        for y in b.ys(f):
            n += len([1 for x0, x1 in hgeo.chords(f.poly, y)])
    area = sum(abs(hgeo.area(f.poly)) / f.cos for f in ctx.faces) / (s * s) / 144.0
    top = ctx.bands[0]
    ridge = None
    if ctx.faces[0].v_ridge is not None:
        f = ctx.faces[0]
        ridge = f.lines[top.index][1](f.v_ridge) / s
    high = None
    if ctx.st["shape"] in ("shed",):
        f = ctx.faces[0]
        xh = f.plate_bbox[2]
        high = f.zb(xh) / s
    return {"shape": ctx.st["shape"], "pitch": ctx.st["pitch"] if ctx.st["shape"] != "flat" else 0,
            "area_ft2": area, "rafters": n, "member": b.prof_name, "spacing": b.spacing / s,
            "system": b.sys_name, "plate": ctx.base_z / s, "ridge": ridge, "high_plate": high,
            "overhang": units.parse_length(ctx.st["overhang"]), "rake": units.parse_length(ctx.st["rake"])}
