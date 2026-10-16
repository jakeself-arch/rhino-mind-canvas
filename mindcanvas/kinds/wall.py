"""Walls: a horizontal driver curve + a layer stack (exterior -> interior).

Driver params (stored as JSON on the driver curve; lengths in inches):
    height       wall height                      (default: assembly default_height or 10')
    base_offset  base elevation above the curve   (default 0)
    reference    where the driver sits in the stack:
                 exterior_face | interior_face | center |
                 core_exterior | core_interior | core_center
    flip         put the exterior on the other side
    lod          schematic | design | detail
    overrides    {"<layer name>": {"<option>": value}} per-wall option overrides
    layers       optional per-wall layer stack replacing the assembly's (MCLayers)
    joins        {"start": style, "end": style}: how each end joins another wall
                 (auto | wrap | miter | butt | none; see mindcanvas/joins)
    join_priority  the wall with the higher priority runs through at an L (default 0)

Openings hosted by the wall (mindcanvas/openings) are resolved into ctx.openings by
place_opening; every component cuts itself, and the units are built after the layers.

Open curve: exterior is on the LEFT of the drawing direction.
Closed curve: exterior is outside. `flip` reverses either.
"""

from .. import components, geo, meta, openings, units
from ..components.base import BuildContext, LayerBand
from ..openings import units as opening_units

REFERENCES = ("exterior_face", "interior_face", "center",
              "core_exterior", "core_interior", "core_center")
LODS = ("schematic", "design", "detail")

DEFAULTS = {
    "base_offset": 0,
    "flip": False,
    "lod": "detail",
}


def stack_boundaries(lib_layers):
    """Distances (inches) of every layer boundary from the exterior face."""
    s = [0.0]
    for layer in lib_layers:
        s.append(s[-1] + units.parse_length(layer.get("thickness", 0)))
    return s


def layer_specs(lib, assembly, params):
    """The wall's layer stack: a per-wall stack (params["layers"], set by
    MCLayers) or the assembly's, with presets expanded."""
    raw = params.get("layers") or assembly["layers"]
    return [lib.resolve_layer(spec) for spec in raw]


def effective_layers(lib, driver_obj):
    return layer_specs(lib, lib.assembly(meta.get(driver_obj, meta.ASSEMBLY)), meta.params(driver_obj))


def layer_name(spec, index):
    return spec.get("name") or spec.get("material") or "Layer {}".format(index + 1)


def reference_distance(layers, s, reference):
    """Distance from the exterior face (inches) of the reference line."""
    core = [i for i, l in enumerate(layers) if l.get("core")]
    c0, c1 = (core[0], core[-1] + 1) if core else (0, len(layers))
    return {
        "exterior_face": s[0],
        "interior_face": s[-1],
        "center": 0.5 * (s[0] + s[-1]),
        "core_exterior": s[c0],
        "core_interior": s[c1],
        "core_center": 0.5 * (s[c0] + s[c1]),
    }[reference]


def total_thickness(layers):
    return stack_boundaries(layers)[-1]


def fitted_layer(lib, spec, index, params):
    """Layer spec, with the thickness its component asks for if it defines
    layer_thickness(lib, spec, options) (framing follows its stud depth)."""
    fit = getattr(components.REGISTRY.get(spec.get("component", "solid")), "layer_thickness", None)
    if fit is None:
        return spec
    name = layer_name(spec, index)
    opts = dict(spec.get("options", {}))
    opts.update(params.get("overrides", {}).get(name, {}))
    try:
        t = fit(lib, spec, opts)
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
    geo.check_horizontal(curve, tol)
    curve = geo.orient_driver(curve)
    if params.get("flip"):
        curve.Reverse()

    s_scale = units.inch_scale(doc)
    height = units.parse_length(params.get("height", assembly.get("default_height", "10'"))) * s_scale
    base_z = curve.PointAtStart.Z + units.parse_length(params.get("base_offset", 0)) * s_scale
    lod = params.get("lod") or assembly.get("lod") or "detail"

    ctx = BuildContext(doc, lib, assembly_name, assembly, params, curve, base_z, height, lod)
    ctx.raw_curve = driver_obj.Geometry.DuplicateCurve()

    for i, (spec, d_ext, d_int) in enumerate(stack_offsets(lib, assembly, params, s_scale)):
        ctx.bands.append(LayerBand(i, spec, d_ext, d_int))
    ctx.openings = openings.resolve(ctx, driver_obj, place_opening)
    ctx.joins = None
    from .. import joins
    joins.attach_wall(ctx, driver_obj)
    return ctx


def stack_offsets(lib, assembly, params, s_scale):
    """[(layer spec, d_ext, d_int)] of the wall's stack: signed offsets (model units) of every
    layer's faces from the driver."""
    reference = params.get("reference") or assembly.get("default_reference") or "center"
    if reference not in REFERENCES:
        raise ValueError("Unknown wall reference '{}'".format(reference))
    layers = [fitted_layer(lib, spec, i, params) for i, spec in enumerate(layer_specs(lib, assembly, params))]
    s = stack_boundaries(layers)
    s_ref = reference_distance(layers, s, reference)
    return [(spec, (s_ref - s[i]) * s_scale, (s_ref - s[i + 1]) * s_scale) for i, spec in enumerate(layers)]


def place_opening(ctx, station, half):
    """(plane, s) of an opening centered `station` (model units along the driver as drawn):
    plane at the point on the oriented curve (z = 0, X tangent, Y exterior), s = distance along
    ctx.curve. The opening (half-width `half` incl. framing) is kept inside its run between
    corners, clear of the corner by the wall thickness."""
    raw = ctx.raw_curve
    L = raw.GetLength()
    ok, t_raw = raw.LengthParameter(min(max(station, 0.0), L))
    P = raw.PointAt(t_raw)
    crv = ctx.curve
    ok, t = crv.ClosestPoint(P)
    G = geo.G
    t0 = crv.Domain.T0
    Lc = crv.GetLength()
    s = crv.GetLength(G.Interval(t0, t)) if t - t0 > 1e-12 else 0.0
    kinks = sorted(crv.GetLength(G.Interval(t0, k)) for k in geo.kink_parameters(crv))
    thick = max(b.d_ext for b in ctx.bands) - min(b.d_int for b in ctx.bands)
    seam_corner = crv.IsClosed and G.Vector3d.VectorAngle(crv.TangentAtStart, crv.TangentAtEnd) > 0.02
    if crv.IsClosed and not kinks and not seam_corner:
        lo, hi = None, None
    else:
        bounds = [(0.0, crv.IsClosed and seam_corner)] + [(k, True) for k in kinks] + [(Lc, crv.IsClosed and seam_corner)]
        lo, hi = bounds[0], bounds[-1]
        for a, b in zip(bounds, bounds[1:]):
            if a[0] - 1e-9 <= s <= b[0] + 1e-9:
                lo, hi = a, b
                break
    if lo is not None:
        clear = lambda corner: (thick + ctx.u(2)) if corner else ctx.u(2)
        a = lo[0] + clear(lo[1]) + half
        b = hi[0] - clear(hi[1]) - half
        if a > b:
            ctx.warn("A wall run is too short for its opening.")
            s_new = 0.5 * (lo[0] + hi[0])
        else:
            s_new = min(max(s, a), b)
        if abs(s_new - s) > ctx.u(1.0 / 16):
            ctx.warn("An opening was moved {} to stay clear of a wall end or corner.".format(
                units.format_inches(abs(s_new - s) / ctx.s)))
        s = s_new
    ok, t = crv.LengthParameter(min(max(s, 0.0), Lc))
    plane = geo.frame_at(crv, t, 0.0)
    return plane, s


def build(ctx):
    parts = []
    for band in ctx.bands:
        if band.thickness <= ctx.tol and band.component != "void":
            ctx.warn("Layer '{}' has no thickness; skipped.".format(band.name))
            continue
        comp = components.get(band.component)
        for p in comp.build(ctx, band):
            p.layer_name = p.layer_name or band.name
            parts.append(p)
    # assembly-level extras that span several layers (ties, flashing, ...), then the wall's own
    # (params["extras"]: trims added with MCTrim)
    for i, spec in enumerate(ctx.assembly.get("extras", []) + (ctx.params.get("extras") or [])):
        band = LayerBand(-1 - i, spec, 0.0, 0.0)
        comp = components.get(band.component)
        for p in comp.build(ctx, band):
            p.layer_name = p.layer_name or band.name
            parts.append(p)
    # window / door units hosted by this wall
    for op in ctx.openings:
        parts.extend(opening_units.build(ctx, op))
    # wall tops filled up to a roof (gable ends, high shed walls)
    if getattr(ctx, "joins", None) is not None:
        from ..joins import geom as jgeom
        parts.extend(jgeom.roof_infill(ctx))
    return parts
