"""Floors: a closed horizontal boundary curve + a layer stack (TOP -> BOTTOM).

The boundary is the outside face of the rim (= the outside face of the wall framing it bears on).

Driver params (JSON on the boundary curve; lengths in inches):
    base_offset  elevation of the datum above the curve (default 0)
    reference    which face of the stack sits at the datum:
                 framing_bottom (default: the joists bear on wall plates at this height) |
                 framing_top | top | bottom
    span         joist direction: "short" (default: joists across the short way, perpendicular to
                 the longest boundary edge) | "long" | <degrees from world X>
    lod          schematic | design | detail
    overrides    {"<layer name>": {"<option>": value}}, e.g. {"Framing": {"system": "metal"}}
    layers       optional per-floor layer stack replacing the assembly's

Bands: LayerBand.d_ext = top z, d_int = bottom z (model units). Components: see floors/build.py.
Walls below / above are positioned by height + base_offset (Phase 7 will join them).
"""

import math

import Rhino

from .. import geo, hgeo, units
from ..components.base import BuildContext, LayerBand
from ..floors import build as fbuild
from ..floors import joists as jmod
from . import wall as wallkind

G = Rhino.Geometry
KIND = "floor"
REFERENCES = ("framing_bottom", "framing_top", "top", "bottom")
SPANS = ("short", "long")
LODS = ("schematic", "design", "detail")

DEFAULTS = {
    "base_offset": 0,
    "reference": "framing_bottom",
    "span": "short",
    "lod": "detail",
}


def fitted_layer(lib, spec, index, params):
    if spec.get("component") not in ("joists", "framing"):
        return spec
    name = wallkind.layer_name(spec, index)
    opts = dict(spec.get("options", {}))
    opts.update(params.get("overrides", {}).get(name, {}))
    try:
        t = jmod.layer_thickness(lib, spec, opts)
    except Exception:
        return spec
    if t is None:
        return spec
    out = dict(spec)
    out["thickness"] = t
    return out


def span_direction(poly, span):
    """Unit plan vector of the joist direction."""
    try:
        ang = float(span)
        return G.Vector3d(math.cos(math.radians(ang)), math.sin(math.radians(ang)), 0)
    except (TypeError, ValueError):
        pass
    best, e = -1.0, None
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        L = math.hypot(x1 - x0, y1 - y0)
        if L > best + 1e-9:
            best, e = L, G.Vector3d((x1 - x0) / L, (y1 - y0) / L, 0)
    if span == "long":
        return e
    return G.Vector3d.CrossProduct(G.Vector3d.ZAxis, e)


def angle_of(vec):
    a = math.degrees(math.atan2(vec.Y, vec.X)) % 180.0
    return round(a, 4)


def make_context(doc, lib, driver_obj, assembly_name, params):
    assembly = lib.assembly(assembly_name)
    tol = doc.ModelAbsoluteTolerance
    curve = driver_obj.Geometry
    if not curve.IsClosed:
        raise geo.GeometryError("A floor boundary must be a closed curve.")
    geo.check_horizontal(curve, tol)
    curve = geo.orient_driver(curve)
    s = units.inch_scale(doc)
    lod = params.get("lod") or assembly.get("lod") or "detail"
    if lod not in LODS:
        raise ValueError("Unknown level of detail '{}'".format(lod))
    layers = [fitted_layer(lib, spec, i, params) for i, spec in enumerate(wallkind.layer_specs(lib, assembly, params))]
    th = [units.parse_length(l.get("thickness", 0)) for l in layers]
    cum = [0.0]
    for t in th:
        cum.append(cum[-1] + t)
    core = [i for i, l in enumerate(layers) if l.get("core") or l.get("component") in ("joists", "framing")]
    c = core[0] if core else 0
    reference = params.get("reference") or assembly.get("default_reference") or "framing_bottom"
    if reference not in REFERENCES:
        raise ValueError("Unknown floor reference '{}'".format(reference))
    z_ref = curve.PointAtStart.Z + units.parse_length(params.get("base_offset", 0)) * s
    z_top = z_ref + {"framing_bottom": cum[c + 1], "framing_top": cum[c], "top": 0.0, "bottom": cum[-1]}[reference] * s
    ctx = BuildContext(doc, lib, assembly_name, assembly, params, curve, z_top - cum[-1] * s, cum[-1] * s, lod)
    ctx.raw_curve = driver_obj.Geometry.DuplicateCurve()
    for i, spec in enumerate(layers):
        ctx.bands.append(LayerBand(i, spec, z_top - cum[i] * s, z_top - cum[i + 1] * s))
    # a concrete topping right above a deck with the same fill is poured with it (one solid)
    ctx.absorbed, ctx.deck_top = set(), {}
    for b in ctx.bands:
        if b.component == "deck" and b.index > 0 and lod != "schematic":
            up = ctx.bands[b.index - 1]
            if up.component == "solid" and up.material == ctx.options(b).get("fill", "Concrete"):
                ctx.absorbed.add(up.index)
                ctx.deck_top[b.index] = up.d_ext
    ctx.poly_world = hgeo.curve_points(curve, tol)
    ctx.jdir = span_direction(ctx.poly_world, params.get("span", "short"))
    ctx.local_poly = lambda frame: [(frame.local(G.Point3d(x, y, 0)).X, frame.local(G.Point3d(x, y, 0)).Y)
                                    for x, y in ctx.poly_world]
    ctx.openings = []
    return ctx


def build(ctx):
    parts = []
    for band in ctx.bands:
        if band.thickness <= ctx.tol and band.component != "void":
            ctx.warn("Layer '{}' has no thickness; skipped.".format(band.name))
            continue
        for p in fbuild.build_band(ctx, band):
            p.layer_name = p.layer_name or band.name
            parts.append(p)
    return parts


def framing_band(ctx):
    for b in ctx.bands:
        if b.component in ("joists", "framing"):
            return b
    return None


def section_frame(ctx, point):
    """Cut plane along the joists through `point` (X = plane normal = joist spacing direction,
    Y = against the joist direction, Z up) and the extents for a section view."""
    f = hgeo.Frame(ctx.jdir)
    o = G.Point3d(point.X, point.Y, ctx.base_z)
    frame = G.Plane(o, f.y, -f.x)
    ds = [(G.Point3d(x, y, ctx.base_z) - o) * frame.YAxis for x, y in ctx.poly_world]
    return frame, {"d_ext": max(ds), "d_int": min(ds), "z0": ctx.base_z, "z1": ctx.base_z + ctx.height, "t": 0.0}


def summary(ctx):
    """Area, joist count / member / spacing / longest span (MCSchedule)."""
    s = ctx.s
    amp = G.AreaMassProperties.Compute(ctx.curve)
    out = {"area_ft2": (amp.Area if amp else 0.0) / (s * s) / 144.0, "joists": 0, "member": "", "spacing": 0.0,
           "max_span_ft": 0.0, "system": "", "direction": angle_of(ctx.jdir),
           "top": (ctx.base_z + ctx.height) / s, "bottom": ctx.base_z / s}
    band = framing_band(ctx)
    if band is not None:
        lay = fbuild.layout(ctx, band)
        out.update(joists=len(lay.joists), member=lay.joist_name, spacing=lay.spacing / s,
                   max_span_ft=lay.max_span / s / 12.0, system=lay.system_name, rows=len(lay.rows()))
    return out
