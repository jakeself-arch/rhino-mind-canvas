"""Stairs: a horizontal curve = the LEFT or RIGHT side of the stair's plan boundary, walked in the
direction of travel UP; the floor-to-floor height sets the risers.

Open curve: the stair runs from its start (`flip`: from its end). Closed curve (a circle or a rounded
rectangle around an elevator): the stair starts at `start` and goes round `laps` times, each lap
higher (a helix in plan overlapping itself).

Driver params (JSON on the curve; lengths in inches):
    height         floor-to-floor height (default 120)
    floors         floors climbed (default 1): total rise = floors x height, a landing at every
                   intermediate floor level, at equal walking distances
    base_offset    elevation of the lower floor above the curve (default 0)
    side           "left" (default: the curve is the stair's left side, the stair is on its right) |
                   "right"
    width          stair width (default 42)
    flip           the stair goes the other way round (open: up from the curve's END)
    start          closed curves: where the stair starts, inches along the curve as drawn
    laps           closed curves: times around (default 1; fractions allowed)
    landings       landing centers, inches along the curve as drawn (closed: on every lap)
    landing_count  extra landings per floor, evenly spaced (default 0)
    landing_depth  landing length on the walkline (default: the width)
    max_riser / risers / style / material / waist / landing / tread_thickness: override the assembly

Assembly settings (library/assemblies/stairs.json): style = slab (sloped soffit, `waist` thick
under the tread roots, landings `landing` thick) | solid (stepped mass down to the lower floor) |
open (plates `tread_thickness` thick, no risers); material; max_riser (risers per floor =
ceil(height / max_riser) unless `risers` > 0). Treads are fitted to the curve
(mindcanvas/stairs/plan.py); corners of the curve become landings, curved segments curved flights
with true curved edges (mindcanvas/stairs/build.py). No railings.
"""

import Rhino

from .. import geo, hgeo, units
from ..components.base import BuildContext, Part
from ..stairs import build as sbuild
from ..stairs import plan as splan

G = Rhino.Geometry
KIND = "stair"
SIDES = ("left", "right")
STYLES = ("slab", "solid", "open")
LAYER = "Stair"

DEFAULTS = {
    "height": 120,
    "base_offset": 0,
    "side": "left",
    "width": 42,
    "flip": False,
}

SETTINGS = {
    "style": "slab",
    "material": "Concrete",
    "max_riser": 7,
    "risers": 0,
    "waist": 6,
    "landing": None,          # landing thickness (slab); None = the waist
    "tread_thickness": 2,     # open stairs
}


def settings(assembly, params):
    """SETTINGS <- assembly <- driver params."""
    out = dict(SETTINGS)
    for src in (assembly, params):
        for k in SETTINGS:
            if src.get(k) is not None:
                out[k] = src[k]
    return out


def path_curve(curve, params, s):
    """The driver curve as walked: seam at `start` (closed), reversed when flipped."""
    c = curve.DuplicateCurve()
    if c.IsClosed:
        start = units.parse_length(params.get("start", 0) or 0) * s
        L = c.GetLength()
        if L > 0 and start % L > 1e-9:
            ok, t = c.LengthParameter(start % L)
            if ok:
                c.ChangeClosedCurveSeam(t)
    if params.get("flip"):
        c.Reverse()
    return c


def landing_positions(curve, params, s, laps):
    """params["landings"] (inches along the curve as drawn) -> distances along the walked path."""
    pos = [units.parse_length(p) for p in (params.get("landings") or [])]
    if not pos:
        return []
    L = curve.GetLength() / s
    out = []
    if not curve.IsClosed:
        for p in pos:
            out.append(L - p if params.get("flip") else p)
        return out
    start = units.parse_length(params.get("start", 0) or 0)
    for p in pos:
        rel = (p - start) % L
        if params.get("flip"):
            rel = (L - rel) % L
        k = 0
        while rel + k * L <= laps * L + 1e-6:
            out.append(rel + k * L)
            k += 1
    return out


def make_context(doc, lib, driver_obj, assembly_name, params):
    assembly = lib.assembly(assembly_name)
    tol = doc.ModelAbsoluteTolerance
    drawn = driver_obj.Geometry
    if not isinstance(drawn, G.Curve):
        raise geo.GeometryError("A stair is driven by a curve.")
    geo.check_horizontal(drawn, tol)
    s = units.inch_scale(doc)
    curve = path_curve(drawn, params, s)
    st = settings(assembly, params)
    if st["style"] not in STYLES:
        raise ValueError("Unknown stair style '{}' (slab, solid, open).".format(st["style"]))
    side = params.get("side", "left")
    if side not in SIDES:
        raise ValueError("Stair side must be 'left' or 'right'.")
    height = units.parse_length(params.get("height", DEFAULTS["height"]))
    width = units.parse_length(params.get("width", DEFAULTS["width"]))
    floors = max(1, int(params.get("floors") or 1))
    laps = float(params.get("laps") or 1.0) if drawn.IsClosed else 0.0
    base_z = curve.PointAtStart.Z + units.parse_length(params.get("base_offset", 0)) * s
    ctx = BuildContext(doc, lib, assembly_name, assembly, params, curve, base_z, height * floors * s, "design")
    ctx.settings = st
    ctx.sigma = -1 if side == "left" else 1
    ctx.closed, ctx.laps = drawn.IsClosed, laps
    ctx.curved = sbuild.is_curved(curve, tol)
    if laps > 1.0 + 1e-6 and st["style"] == "solid":
        st["style"] = "slab"
        ctx.warn("A solid stair cannot overlap itself (laps > 1): built with a sloped soffit instead.")
    depth = params.get("landing_depth")
    try:
        ctx.layout = splan.layout(
            sbuild.segments(curve, s, tol, laps or 1.0), width, height, ctx.sigma,
            units.parse_length(st["max_riser"]), int(st["risers"] or 0), floors=floors,
            landing_count=int(params.get("landing_count") or 0),
            landing_depth=units.parse_length(depth) if depth else None,
            landing_at=landing_positions(drawn, params, s, laps), laps=laps)
    except splan.PlanError as ex:
        raise geo.GeometryError(str(ex))
    for w in ctx.layout.warnings:
        ctx.warn(w)
    return ctx


def build(ctx):
    st, lay = ctx.settings, ctx.layout
    pieces = lay.pieces(st["style"], units.parse_length(st["waist"]),
                        None if st["landing"] is None else units.parse_length(st["landing"]),
                        units.parse_length(st["tread_thickness"]))
    role = "tread" if st["style"] == "open" else "stair"
    bands = None
    if ctx.curved:
        try:
            bands = sbuild.band(ctx.curve, ctx.sigma, lay.width * ctx.s, ctx.base_z - ctx.s,
                                ctx.base_z + ctx.height + ctx.s, ctx.tol)
        except Exception as ex:
            ctx.warn("The curved edges could not be made exact ({}); they are faceted.".format(ex))
    parts = []
    for a, b, bottoms in pieces:
        bot = dict((a + i, z) for i, z in enumerate(bottoms))
        flat = all(lay.levels[c] == lay.levels[a] for c in range(a, b)) and any(
            e.flat and e.level0 == lay.levels[a] for e in lay.elements)
        for geom in _solids(ctx, lay, a, b, bot, bands):
            parts.append(Part(geom, st["material"], role="landing" if role == "tread" and flat else role,
                              layer_name=LAYER))
    if parts:
        parts[0].extra.update(summary_extra(lay))
    return parts


def _smooth(ctx, lay, a, b, bot, bands):
    """Curved stairs: the piece built wider on its coarse cuts, intersected with the true band."""
    js = lay.coarse(a, b)
    geom, ok = sbuild.solid(sbuild.piece_mesh(lay, js, bot, ctx.s, ctx.base_z, lay.extended(js)), ctx.tol)
    if not ok:
        return None
    return sbuild.trimmed(geom, bands, ctx.tol)


def _solids(ctx, lay, a, b, bot, bands=None):
    """Closed Breps for cuts a..b: smooth (curved stairs), else one faceted solid; when that fails
    (flights touching side by side, e.g. a U stair without a gap) each flight / landing on its own,
    unioned if possible."""
    if bands:
        out = _smooth(ctx, lay, a, b, bot, bands)
        if out:
            return out
        ctx.warn("A curved part of the stair could not be trimmed to the exact curves; it is faceted.")
    js = list(range(a, b + 1))
    geom, ok = sbuild.solid(sbuild.piece_mesh(lay, js, bot, ctx.s, ctx.base_z), ctx.tol)
    if ok:
        return [geom]
    subs = [(max(a, i), min(b, j)) for i, j in lay.ranges() if min(b, j) > max(a, i)]
    if len(subs) < 2:
        ctx.warn("A stair piece is not a closed solid; it was added as a mesh.")
        return [geom]
    out = []
    for i, j in subs:
        g, ok = sbuild.solid(sbuild.piece_mesh(lay, list(range(i, j + 1)), bot, ctx.s, ctx.base_z), ctx.tol)
        if not ok:
            ctx.warn("A stair piece is not a closed solid; it was added as a mesh.")
        out.append(g)
    breps = [g for g in out if isinstance(g, G.Brep)]
    if len(breps) == len(out):
        u = G.Brep.CreateBooleanUnion(breps, ctx.tol)
        if u and all(x.IsSolid for x in u):
            for x in u:
                x.MergeCoplanarFaces(ctx.tol)
            return list(u)
    return out


def summary_extra(lay):
    return {"risers": lay.risers, "riser": round(lay.R, 4), "run": round(lay.run, 4), "width": round(lay.width, 4),
            "floors": lay.floors, "treads": [f.treads for f in lay.flights],
            "tread": [round(f.depth, 4) for f in lay.flights], "landings": lay.landing_runs}


def describe(ctx):
    """One line for the command line: 18 risers @ 6-11/16", 16 treads @ 11", 1 landing, ..."""
    lay = ctx.layout
    fl = lay.flights
    treads = sum(f.treads for f in fl)
    depths = sorted(set(units.format_inches(f.depth) for f in fl))
    txt = "{} risers @ {}".format(lay.per_floor, units.format_inches(lay.R))
    if lay.floors > 1:
        txt = "{} floors x {}".format(lay.floors, txt)
    txt += ", {} treads @ {}".format(treads, " / ".join(depths) if depths else "-")
    narrow = [f.narrow for f in fl if f.depth - f.narrow > 0.5]
    if narrow:
        txt += " ({} at the inside)".format(units.format_inches(min(narrow)))
    nl = lay.landing_runs
    if nl:
        txt += ", {} landing{}".format(nl, "" if nl == 1 else "s")
    if getattr(ctx, "closed", False):
        txt += ", {:g} lap{}".format(ctx.laps, "" if abs(ctx.laps - 1) < 1e-9 else "s")
    return txt + ", width {}, run {}".format(units.format_inches(lay.width), units.format_inches(lay.run))


def section_frame(ctx, point):
    """Cut plane along the direction of travel at the cut nearest `point` (X = plane normal,
    Y = against the direction of travel, Z up) and the extents for a section view."""
    lay, s = ctx.layout, ctx.s
    p = (point.X / s, point.Y / s)
    j = min(range(len(lay.cuts)), key=lambda i: (lay.cuts[i].mid[0] - p[0]) ** 2 + (lay.cuts[i].mid[1] - p[1]) ** 2)
    a, b = (j, j + 1) if j + 1 < len(lay.cuts) else (j - 1, j)
    ma, mb = lay.cuts[a].mid, lay.cuts[b].mid
    f = hgeo.Frame(G.Vector3d(mb[0] - ma[0], mb[1] - ma[1], 0))
    o = G.Point3d(point.X, point.Y, ctx.base_z)
    frame = G.Plane(o, f.y, -f.x)
    ds = [(G.Point3d(q[0] * s, q[1] * s, ctx.base_z) - o) * frame.YAxis for c in lay.cuts for q in (c.c, c.o)]
    return frame, {"d_ext": max(ds), "d_int": min(ds), "z0": ctx.base_z, "z1": ctx.base_z + ctx.height, "t": 0.0}
