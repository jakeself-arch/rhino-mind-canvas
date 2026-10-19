"""Stairs: an open horizontal curve = the LEFT or RIGHT side of the stair's plan boundary, drawn
(or flipped) in the direction of travel UP; the floor-to-floor height sets the risers.

Driver params (JSON on the curve; lengths in inches):
    height       floor-to-floor height (default 120)
    base_offset  elevation of the lower floor above the curve (default 0)
    side         "left" (default: the curve is the stair's left side, the stair is on its right) |
                 "right"
    width        stair width (default 42)
    flip         the stair goes up from the curve's END
    max_riser / risers / style / material / waist / landing / tread_thickness: override the assembly

Assembly settings (library/assemblies/stairs.json): style = slab (sloped soffit, `waist` thick
under the tread roots, landings `landing` thick) | solid (stepped mass down to the lower floor) |
open (plates `tread_thickness` thick, no risers); material; max_riser (risers = ceil(height /
max_riser) unless `risers` > 0). Treads are fitted to the curve (mindcanvas/stairs/plan.py);
corners of the curve become landings, curved segments curved flights. No railings.
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


def make_context(doc, lib, driver_obj, assembly_name, params):
    assembly = lib.assembly(assembly_name)
    tol = doc.ModelAbsoluteTolerance
    curve = driver_obj.Geometry
    if not isinstance(curve, G.Curve):
        raise geo.GeometryError("A stair is driven by a curve.")
    if curve.IsClosed:
        raise geo.GeometryError("A stair line must be an open curve (one side of the stair).")
    geo.check_horizontal(curve, tol)
    curve = curve.DuplicateCurve()
    if params.get("flip"):
        curve.Reverse()
    s = units.inch_scale(doc)
    st = settings(assembly, params)
    if st["style"] not in STYLES:
        raise ValueError("Unknown stair style '{}' (slab, solid, open).".format(st["style"]))
    side = params.get("side", "left")
    if side not in SIDES:
        raise ValueError("Stair side must be 'left' or 'right'.")
    height = units.parse_length(params.get("height", DEFAULTS["height"]))
    width = units.parse_length(params.get("width", DEFAULTS["width"]))
    base_z = curve.PointAtStart.Z + units.parse_length(params.get("base_offset", 0)) * s
    ctx = BuildContext(doc, lib, assembly_name, assembly, params, curve, base_z, height * s, "design")
    ctx.settings = st
    ctx.sigma = -1 if side == "left" else 1
    try:
        ctx.layout = splan.layout(sbuild.segments(curve, s, tol), width, height, ctx.sigma,
                                  units.parse_length(st["max_riser"]), int(st["risers"] or 0))
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
    parts = []
    for a, b, bottoms in pieces:
        mesh = sbuild.piece_mesh(lay, a, b, bottoms, ctx.s, ctx.base_z)
        geom, ok = sbuild.solid(mesh, ctx.tol)
        if not ok:
            ctx.warn("A stair piece is not a closed solid; it was added as a mesh.")
        flat = all(lay.levels[c] == lay.levels[a] for c in range(a, b)) and any(
            e.flat and e.level0 == lay.levels[a] for e in lay.elements)
        p = Part(geom, st["material"], role="landing" if role == "tread" and flat else role, layer_name=LAYER)
        parts.append(p)
    if parts:
        parts[0].extra.update(summary_extra(lay))
    return parts


def summary_extra(lay):
    out = {"risers": lay.risers, "riser": round(lay.R, 4), "run": round(lay.run, 4), "width": round(lay.width, 4),
           "treads": [f.treads for f in lay.flights], "tread": [round(f.depth, 4) for f in lay.flights],
           "landings": len(lay.landings)}
    return out


def describe(ctx):
    """One line for the command line: 17 risers @ 7-1/16", 16 treads @ 11-1/4", 1 landing."""
    lay = ctx.layout
    fl = lay.flights
    treads = sum(f.treads for f in fl)
    depths = sorted(set(units.format_inches(f.depth) for f in fl))
    txt = "{} risers @ {}, {} treads @ {}".format(lay.risers, units.format_inches(lay.R), treads,
                                                " / ".join(depths) if depths else "-")
    nl = sum(1 for e in lay.elements if e.kind == "landing")
    if nl:
        txt += ", {} landing{}".format(nl, "" if nl == 1 else "s")
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
