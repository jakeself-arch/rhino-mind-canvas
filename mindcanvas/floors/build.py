"""Floor layer builders. Every band of a floor is horizontal: band.d_ext = top z, band.d_int =
bottom z (model units). Components (layer "component"):

    solid, membrane   slab over the boundary (option inset: inches inward, e.g. ceilings; with
                      walls along the boundary the inset follows each wall's interior face)
    void              nothing
    joists            rim + joists (design), + blocking / bridging + cavity fill (detail)
    deck              composite metal deck (ribs across the joists) + concrete in its flutes

Schematic LOD: every layer is a plain slab (joists: one framing slab).
"""

import Rhino

from .. import geo, hgeo, profiles, units
from ..components import framing as wallframing
from ..components.base import Part
from . import joists as jmod

G = Rhino.Geometry


def layout(ctx, band):
    cache = ctx.__dict__.setdefault("_mc_joists", {})
    if band.index not in cache:
        cache[band.index] = jmod.JoistLayout(ctx, band)
    return cache[band.index]


def region_curve(ctx, inset=0.0):
    if inset > ctx.tol:
        return geo.offset(ctx.curve, -inset, ctx.tol)
    return ctx.curve


def _area_in2(ctx, crv):
    amp = G.AreaMassProperties.Compute(crv)
    return amp.Area / (ctx.s * ctx.s) if amp else 0.0


def slab(ctx, z0, z1, inset=0.0):
    crv = region_curve(ctx, inset)
    regions = G.Brep.CreatePlanarBreps(crv, ctx.tol) or []
    return [geo.extrude_region(r, z0, z1 - z0, ctx.tol) for r in regions], crv


def edge_slab(ctx, z0, z1, poly, dists):
    """Slab over the boundary polygon (CCW) with every edge moved inward by its own distance
    (joins: ceilings and finish floors stop at the walls along each edge)."""
    pts = hgeo.offset_edges(poly, [-d for d in dists])
    crv = G.PolylineCurve([G.Point3d(x, y, 0) for x, y in pts + [pts[0]]])
    regions = G.Brep.CreatePlanarBreps(crv, ctx.tol) or []
    return [geo.extrude_region(r, z0, z1 - z0, ctx.tol) for r in regions], crv


def solid(ctx, band):
    if band.index in getattr(ctx, "absorbed", {}):
        return []          # a concrete topping poured with the deck flutes (see deck)
    o = ctx.options(band)
    joined = getattr(ctx, "join_insets", {}).get(band.index)
    if joined is not None:
        breps, crv = edge_slab(ctx, band.d_int, band.d_ext, *joined)
    else:
        breps, crv = slab(ctx, band.d_int, band.d_ext, ctx.u(o.get("inset", 0) or 0))
    extra = {"area": round(_area_in2(ctx, crv), 2)}
    role = o.get("role") or ("membrane" if band.component == "membrane" else "solid")
    return [Part(b, band.material, role=role, extra=dict(extra)) for b in breps]


# -- joists -------------------------------------------------------------------------------------
def _member_block(ctx, name, loops, length, material, plane):
    return ctx.block(name, [geo.extrude_profile(loops[0], plane, length)], material)


def joists(ctx, band):
    lay = layout(ctx, band)
    if ctx.lod == "schematic":
        breps, crv = slab(ctx, band.d_int, band.d_ext)
        return [Part(b, lay.material, role="framing") for b in breps]
    parts = _rim(ctx, lay) + _joists(ctx, lay)
    if ctx.lod == "detail":
        blk, rects = _blocking(ctx, lay)
        parts += blk
        parts += _cavity(ctx, lay, rects)
    return parts


def _rim(ctx, lay):
    z0, z1 = lay.z0, lay.z1
    L_in = round(ctx.curve.GetLength() / ctx.s, 4)
    if lay.metal:
        solids = wallframing._channel(ctx, 0.0, -lay.leg, z0, z1, lay.t, "int")
        member = lay.name("rim", lay.rim_name)
        return [Part(b, lay.rim_material, role="rim_joist", extra={"length": L_in, "member": member}) for b in solids]
    out = []
    member = lay.name("rim", lay.rim_name)
    for i in range(lay.plies):
        for b in ctx.solids(-i * lay.ply_t, -(i + 1) * lay.ply_t, z0, z1):
            out.append(Part(b, lay.rim_material, role="rim_joist", extra={"length": L_in, "member": member}))
    return out


def _joists(ctx, lay):
    loops = profiles.build(lay.joist, ctx.s)
    zc = lay.z0 + lay.t + 0.5 * lay.D
    plane = G.Plane(G.Point3d(0, 0, 0), G.Vector3d.YAxis, G.Vector3d.ZAxis)   # extrudes along +x
    member = lay.name("joist", lay.joist_name)
    blocks, out = {}, []
    for y, x0, x1 in lay.joists:
        L_in = round((x1 - x0) / ctx.s, 4)
        idx = blocks.get(L_in)
        if idx is None:
            bname = "MC Joist {} [{}] L{:.4f}".format(lay.joist_name.replace('"', "in"), wallframing._dims(lay.joist), L_in)
            idx = _member_block(ctx, bname, loops, L_in * ctx.s, lay.material, plane)
            blocks[L_in] = idx
        xf = lay.frame.placed(y, x0) * G.Transform.Translation(0, 0, zc)
        out.append(Part(material=lay.material, role="joist", block=idx, xform=xf,
                        extra={"length": L_in, "member": member}))
    return out


def _blocking(ctx, lay):
    """Rows of blocking between joists (wood: joist stock; metal: C pieces + a flat strap under the
    bottom flanges). Returns (parts, world plan rectangles of the blocks)."""
    if not lay.opt("blocking", True):
        return [], []
    rows = lay.rows()
    if not rows:
        return [], []
    w, D, t = lay.w, lay.D, lay.t
    z0 = lay.z0 + t
    member = lay.name("blocking", lay.joist_name)
    out, rects, blocks = [], [], {}
    gap_pad = ctx.u(1.0 / 16) if lay.metal else 0.0
    if lay.metal:
        loops = profiles.build(lay.joist, ctx.s)
        plane = G.Plane(G.Point3d(0, 0, 0), -G.Vector3d.XAxis, G.Vector3d.ZAxis)   # extrudes along +y
    for x in rows:
        pairs = lay.neighbors(x, 0.5 * w)
        for ya, yb in pairs:
            L = (yb - ya) - w - 2 * gap_pad
            if L < ctx.u(2):
                continue
            L_in = round(L / ctx.s, 4)
            idx = blocks.get(L_in)
            if idx is None:
                if lay.metal:
                    geom = geo.extrude_profile(loops[0], plane, L)
                    geom.Translate(G.Vector3d(0, 0, 0.5 * D))
                else:
                    geom = hgeo.prism_xz([(-0.5 * w, 0), (0.5 * w, 0), (0.5 * w, D), (-0.5 * w, D)], 0.0, L, ctx.tol)
                bname = "MC Blocking {} [{}] L{:.4f}".format(lay.joist_name.replace('"', "in"),
                                                            wallframing._dims(lay.joist), L_in)
                idx = ctx.block(bname, [geom], lay.material)
                blocks[L_in] = idx
            y0 = ya + 0.5 * w + gap_pad
            xf = lay.frame.placed(y0, x) * G.Transform.Translation(0, 0, z0)
            out.append(Part(material=lay.material, role="blocking", block=idx, xform=xf,
                            extra={"length": L_in, "member": member}))
            hw = 0.5 * w + ctx.u(1.0 / 16)
            rects.append(G.PolylineCurve([lay.frame.world(xx, yy) for xx, yy in (
                (x - hw, ya), (x + hw, ya), (x + hw, yb), (x - hw, yb), (x - hw, ya))]))
        if lay.metal and pairs and lay.sys.get("strap"):
            sp = ctx.lib.profile(lay.sys["strap"])
            sw, st = ctx.u(sp["width"]), ctx.u(sp["depth"])
            runs = []
            for ya, yb in pairs:
                if runs and abs(runs[-1][1] - ya) < 1e-9:
                    runs[-1][1] = yb
                else:
                    runs.append([ya, yb])
            for ya, yb in runs:
                y0, y1 = ya - 0.5 * w, yb + 0.5 * w
                b = hgeo.prism_xz([(x - 0.5 * sw, z0 - st), (x + 0.5 * sw, z0 - st), (x + 0.5 * sw, z0), (x - 0.5 * sw, z0)],
                                  y0, y1, ctx.tol)
                if b is not None:
                    b.Transform(lay.frame.xform)
                    out.append(Part(b, lay.material, role="bridging",
                                    extra={"length": round((y1 - y0) / ctx.s, 4),
                                           "member": lay.name("strap", lay.sys["strap"])}))
    return out, rects


def _cavity(ctx, lay, block_rects):
    fill = lay.opts.get("cavity_fill")
    if not fill or not lay.joists:
        return []
    depth = min(ctx.u(lay.opts.get("fill_depth") or 1e6), lay.D)
    z0 = lay.z0 + lay.t
    outer = G.PolylineCurve([lay.frame.world(x, y) for x, y in lay.inner + [lay.inner[0]]])
    cutters = lay.plan_rects(ctx.u(0.25)) + list(block_rects)
    try:
        pieces = G.Curve.CreateBooleanDifference(outer, cutters, ctx.tol) or []
    except Exception:
        pieces = []
    if not pieces:
        ctx.warn("Cavity fill between the joists failed; skipped.")
        return []
    out = []
    for crv in pieces:
        if not crv.IsClosed:
            continue
        a = _area_in2(ctx, crv)
        if a < 4.0:
            continue
        for r in G.Brep.CreatePlanarBreps(crv, ctx.tol) or []:
            out.append(Part(geo.extrude_region(r, z0, depth, ctx.tol), fill, role="insulation",
                            extra={"area": round(a, 2)}))
    return out


# -- composite metal deck -----------------------------------------------------------------------
def deck(ctx, band):
    o = ctx.options(band)
    fill = o.get("fill", "Concrete")
    if ctx.lod == "schematic":
        breps, crv = slab(ctx, band.d_int, band.d_ext)
        return [Part(b, fill or band.material, role="deck_fill") for b in breps]
    p = ctx.lib.profile(o.get("profile", "1-1/2\" Composite Deck, 20 ga"))
    u = ctx.u
    h = band.thickness
    P, wb, wt, t = u(p["pitch"]), u(p["bottom"]), u(p["top"]), u(p["t"])
    s = 0.5 * (P - wb - wt)
    if abs(u(p["depth"]) - h) > ctx.tol * 10:
        ctx.warn("Deck layer is {} thick but the {} ribs are {} deep.".format(
            units.format_inches(h / ctx.s), o.get("profile"), units.format_inches(units.parse_length(p["depth"]))))
    frame = hgeo.Frame(ctx.jdir)
    poly = hgeo.ccw(ctx.local_poly(frame))
    xa, ya, xb, yb = hgeo.bbox(poly)
    z0 = band.d_int
    path, fills = [], []
    x = xa
    while x < xb + P:
        path += [(x, z0), (x + wb, z0), (x + wb + s, z0 + h - t), (x + wb + s + wt, z0 + h - t)]
        fills.append([(x - s, z0 + h), (x, z0 + t), (x + wb, z0 + t), (x + wb + s, z0 + h)])
        x += P
    steel = hgeo.thicken(path, t, 1)
    z_top = getattr(ctx, "deck_top", {}).get(band.index)
    if z_top is not None:     # one pour: flutes + the topping above
        fills = [[(xa - P, z_top), (path[-1][0] + P, z_top)] + steel[len(path):]]

    def clip(pl):
        pl = hgeo.clip_halfplane(pl, lambda q: q[0] - xa)
        return hgeo.clip_halfplane(pl, lambda q: xb - q[0]) if pl else pl

    steel = clip(steel)
    breps = [hgeo.prism_xz(steel, ya, yb, ctx.tol)]
    fill_breps = []
    for f in fills:
        f = clip(f)
        if f and len(f) >= 3 and abs(hgeo.area(f)) > (ctx.u(0.05)) ** 2:
            fill_breps.append(hgeo.prism_xz(f, ya, yb, ctx.tol))
    if not hgeo.is_rect(poly, ctx.tol):
        prism = hgeo.prism_plan(poly, z0 - ctx.u(1), band.d_ext + ctx.u(1), ctx.tol)
        breps = hgeo.intersect(breps, prism, ctx.tol)
        fill_breps = hgeo.intersect(fill_breps, prism, ctx.tol)
        if breps is None or fill_breps is None:
            ctx.warn("Deck could not be trimmed to the boundary; built as slabs.")
            b1, _ = slab(ctx, z0, z0 + t)
            b2, _ = slab(ctx, z0 + t, band.d_ext)
            return [Part(b, band.material, role="deck") for b in b1] + [Part(b, fill, role="deck_fill") for b in b2]
    out = []
    area = round(_area_in2(ctx, ctx.curve), 2)
    for b in breps:
        if b is not None:
            b.Transform(frame.xform)
            out.append(Part(b, band.material, role="deck", extra={"area": area, "member": o.get("profile")}))
    if fill:
        for b in fill_breps:
            if b is not None:
                b.Transform(frame.xform)
                out.append(Part(b, fill, role="deck_fill"))
    return out


BUILDERS = {
    "solid": solid,
    "membrane": solid,
    "void": lambda ctx, band: [],
    "joists": joists,
    "framing": joists,
    "deck": deck,
}


def build_band(ctx, band):
    fn = BUILDERS.get(band.component)
    if fn is None:
        raise KeyError("Unknown floor component '{}'. Known: {}".format(band.component, ", ".join(sorted(BUILDERS))))
    return fn(ctx, band)
