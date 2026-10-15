"""Curtain walls: a horizontal driver curve + a grid of mullions, transoms and infill panels.

Driver params (JSON on the driver curve; lengths in inches): height, base_offset, flip, lod,
plus any curtain-wall setting (style, reference, grid, spacing, bays, transoms, stack, slabs,
infill, mullion, transom, ssg_sides, ...) overriding the assembly's. See
mindcanvas/curtainwall/settings.py for every key.

Open curve: exterior on the LEFT of the drawing direction. Closed curve: exterior outside.
`flip` reverses either. Straight runs, polylines (corner mullions at kinks) and arcs (faceted
into straight bays) are supported.

Openings (doors) hosted by a curtain wall take a whole bay (place_opening snaps them to the
nearest bay); the builder gives that bay a head transom and leaves the cells below it open.
"""

from .. import geo, openings, units
from ..components.base import BuildContext, LayerBand
from ..curtainwall import build as cwbuild
from ..curtainwall import grid as cwgrid
from ..curtainwall import settings as cwsettings

KIND = "curtain_wall"
LODS = cwsettings.LODS
REFERENCES = cwsettings.REFERENCES
STYLES = cwsettings.STYLES

DEFAULTS = {
    "base_offset": 0,
    "flip": False,
    "lod": "detail",
}


def settings(lib, assembly, params):
    return cwsettings.merged(assembly, params)


def glass_y(S, reference, s):
    """y (signed offset from the driver, model units) of the exterior face of the glass."""
    if reference == "glass_center":
        return 0.5 * S.T * s
    if reference == "exterior_face":
        return S.q_front() * s
    if reference == "mullion_back":
        return S.q_back() * s
    return 0.0


def make_context(doc, lib, driver_obj, assembly_name, params):
    assembly = lib.assembly(assembly_name)
    tol = doc.ModelAbsoluteTolerance
    curve = driver_obj.Geometry
    geo.check_horizontal(curve, tol)
    curve = geo.orient_driver(curve)
    if params.get("flip"):
        curve.Reverse()
    s = units.inch_scale(doc)
    height = units.parse_length(params.get("height", assembly.get("default_height", "13'-4\""))) * s
    base_z = curve.PointAtStart.Z + units.parse_length(params.get("base_offset", 0)) * s
    lod = params.get("lod") or assembly.get("lod") or "detail"
    if lod not in LODS:
        raise ValueError("Unknown level of detail '{}'".format(lod))
    ctx = BuildContext(doc, lib, assembly_name, assembly, params, curve, base_z, height, lod)
    ctx.raw_curve = driver_obj.Geometry.DuplicateCurve()
    st = cwsettings.merged(assembly, params)
    S = cwsettings.Dims(lib, st)
    reference = st.get("reference", "glass")
    if reference not in REFERENCES:
        raise ValueError("Unknown curtain wall reference '{}'".format(reference))
    ctx.cw = st
    ctx.dims = S
    ctx.yG = glass_y(S, reference, s)
    d_ext = ctx.yG - S.q_front() * s
    d_int = ctx.yG - S.q_back() * s
    ctx.bands = [LayerBand(0, {"name": "Curtain Wall", "component": KIND, "material": S.mp["material"]},
                           d_ext, d_int)]
    ctx.grid = cwgrid.Grid(ctx, S)
    ctx.openings = openings.resolve(ctx, driver_obj, place_opening)
    return ctx


def place_opening(ctx, station, half):
    """(plane, s) for an opening: centred on the bay nearest `station` (model units along the
    driver as drawn). The builder then sizes the unit to the bay's clear width."""
    G = geo.G
    raw = ctx.raw_curve
    L = raw.GetLength()
    ok, t = raw.LengthParameter(min(max(station, 0.0), L))
    P = raw.PointAt(t)
    hit = ctx.grid.cell_at(P)
    bay = ctx.grid.bays[hit[0] if hit else 0]
    plane = bay.frame(0.5 * bay.c, 0.0)
    crv = ctx.curve
    ok, tc = crv.ClosestPoint(plane.Origin)
    sc = crv.GetLength(G.Interval(crv.Domain.T0, tc)) if tc - crv.Domain.T0 > 1e-12 else 0.0
    return plane, sc


def build(ctx):
    return cwbuild.Builder(ctx).run()


# -- summaries (MCSchedule) ---------------------------------------------------------------
def summary(ctx):
    """Panels per infill type with their nominal glass areas (ft2), mullion / transom lengths."""
    s = ctx.s
    g = ctx.grid
    b = cwbuild.Builder(ctx)
    b.ends = {}
    for bay in g.bays:
        b.ends[(bay.index, 0)] = b.bay_end(bay, bay.va, True)
        b.ends[(bay.index, 1)] = b.bay_end(bay, bay.vb, False)
    b._openings()
    rows = {}
    for bay in g.bays:
        eL, eR = b.ends[(bay.index, 0)], b.ends[(bay.index, 1)]
        hs = b.bay_horizontals(bay)
        for h0, h1 in zip(hs, hs[1:]):
            if getattr(h0, "door", False):
                continue
            row = b.grid_row(h0, h1)
            kind = g.infill(bay.index, row)
            z0 = b.zc(h0) + b.hsec[h0.kind].edge_pos * s
            z1 = b.zc(h1) + b.hsec[h1.kind].edge_neg * s
            W, H = eR.glass_u - eL.glass_u, z1 - z0
            if W <= 0 or H <= 0:
                continue
            r = rows.setdefault(kind, {"panel": kind, "count": 0, "area_ft2": 0.0})
            r["count"] += 1
            r["area_ft2"] += W * H / (s * s) / 144.0
    out = {
        "bays": len(g.bays),
        "rows": len(g.rows),
        "verticals": len(g.vertices),
        "corners": sum(1 for v in g.vertices if v.kind == "corner"),
        "panels": [rows[k] for k in sorted(rows)],
        "height_ft": ctx.height / s / 12.0,
        "length_ft": g.curve.GetLength() / s / 12.0,
        "openings": len(ctx.openings),
    }
    return out
