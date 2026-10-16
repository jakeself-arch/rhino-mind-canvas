"""Geometry of joined walls: layer outlines that stop at their join cuts, T notches, the
centerline of a framing band, and the infill of a wall up to the roof over it."""

import Rhino

from .. import geo, hgeo
from ..components.base import Part

G = Rhino.Geometry


def ends(ctx):
    J = getattr(ctx, "joins", None)
    if J is None or ctx.curve.IsClosed:
        return {}
    return J.ends


def _move_end(crv, at_end, e, tol):
    """crv lengthened (e > 0, straight along the end tangent) or shortened (e < 0) at one end."""
    if abs(e) <= tol * 0.5:
        return crv
    if e > 0:
        ext = crv.Extend(G.CurveEnd.End if at_end else G.CurveEnd.Start, e, G.CurveExtensionStyle.Line)
        if ext is not None and abs(ext.GetLength() - crv.GetLength() - e) < tol * 10:
            return ext
        if at_end:
            p, tan = crv.PointAtEnd, crv.TangentAtEnd
            piece = G.LineCurve(p, p + tan * e)
        else:
            p, tan = crv.PointAtStart, crv.TangentAtStart
            piece = G.LineCurve(p - tan * e, p)
        joined = G.Curve.JoinCurves([crv, piece] if at_end else [piece, crv], tol * 2)
        return joined[0] if joined and len(joined) == 1 else None
    L = crv.GetLength()
    if -e >= L - tol:
        return None
    ok, t = crv.LengthParameter(L + e if at_end else -e)
    if not ok:
        return None
    dom = crv.Domain
    return crv.Trim(G.Interval(dom.T0, t) if at_end else G.Interval(t, dom.T1))


def adjusted(ctx, d, below=True):
    """Offset of the driver at d, its joined ends moved to their cuts (None: nothing is left)."""
    crv = geo.offset(ctx.curve, d, ctx.tol)
    for name, cut in ends(ctx).items():
        crv = _move_end(crv, name == "end", cut.ext(d, below), ctx.tol)
        if crv is None:
            return None
    return crv


def centerline(ctx, d):
    crv = adjusted(ctx, d) if ends(ctx) else None
    return crv if crv is not None else geo.offset(ctx.curve, d, ctx.tol)


def _polyline(pts, tol):
    clean = []
    for p in pts:
        if not clean or p.DistanceTo(clean[-1]) > tol:
            clean.append(p)
    return G.PolylineCurve(clean) if len(clean) >= 2 else None


def faces(ctx, d_a, d_b):
    """(upper face curve, lower face curve) of a band between offsets d_a, d_b, ends at the cuts."""
    hi, lo = max(d_a, d_b), min(d_a, d_b)
    ch, cl = adjusted(ctx, hi, True), adjusted(ctx, lo, False)
    if ch is None or cl is None:
        raise geo.GeometryError("A layer is shorter than its wall joins.")
    return ch, cl


def outline(ctx, d_a, d_b):
    """Closed plan outline of the band d_a..d_b of an open wall with joined ends."""
    tol = ctx.tol
    hi, lo = max(d_a, d_b), min(d_a, d_b)
    ch, cl = faces(ctx, hi, lo)
    z = ch.PointAtStart.Z
    P3 = lambda p: G.Point3d(p[0], p[1], z)
    E = ends(ctx)
    mid_end = [P3(p) for p in E["end"].cap(hi, lo)[1:-1]] if "end" in E else []
    mid_start = [P3(p) for p in E["start"].cap(lo, hi)[1:-1]] if "start" in E else []
    rev = cl.DuplicateCurve()
    rev.Reverse()
    pieces = [ch, _polyline([ch.PointAtEnd] + mid_end + [cl.PointAtEnd], tol), rev,
              _polyline([cl.PointAtStart] + mid_start + [ch.PointAtStart], tol)]
    joined = G.Curve.JoinCurves([p for p in pieces if p is not None], tol * 2)
    if not joined or len(joined) != 1 or not joined[0].IsClosed:
        raise geo.GeometryError("Could not close a joined layer outline.")
    return joined[0]


def band_solids(ctx, d_a, d_b, z0, z1, notch=True):
    """Solids of the band d_a..d_b from z0 to z1: stopped at the wall's join cuts and notched
    around walls joining it (T)."""
    if ends(ctx):
        regions = G.Brep.CreatePlanarBreps(outline(ctx, d_a, d_b), ctx.tol)
        if not regions:
            raise geo.GeometryError("Could not build a joined layer region.")
        solids = [geo.extrude_region(r, z0, z1 - z0, ctx.tol) for r in regions]
    else:
        solids = geo.band_solids(ctx.curve, d_a, d_b, z0, z1 - z0, ctx.tol)
    return notched(ctx, solids, d_a, d_b) if notch else solids


def notched(ctx, solids, d_a, d_b):
    J = getattr(ctx, "joins", None)
    if J is None or not J.notches:
        return solids
    hi, lo = max(d_a, d_b), min(d_a, d_b)
    tol = ctx.tol
    cutters = []
    for poly, n_lo, n_hi, z0, z1 in J.notches:
        if lo >= n_lo - tol and hi <= n_hi + tol:
            c = hgeo.prism_plan(poly, z0, z1, tol)
            if c is not None:
                cutters.append(c)
    if not cutters:
        return solids
    from ..openings import core as openings
    return openings.subtract(ctx, solids, cutters, "a layer at a wall join")


def band_polys(ctx, band):
    """Plan polygons (2D, one quad per straight piece) covering a band, for roof infill.
    Curved walls give []."""
    d_hi, d_lo = band.d_ext, band.d_int
    if ends(ctx):
        ch, cl = faces(ctx, d_hi, d_lo)
    else:
        ch, cl = geo.offset(ctx.curve, d_hi, ctx.tol), geo.offset(ctx.curve, d_lo, ctx.tol)
    ok_h, ph = ch.TryGetPolyline()
    ok_l, pl = cl.TryGetPolyline()
    if not (ok_h and ok_l) or ph.Count != pl.Count or ph.Count < 2:
        return []
    out = []
    for i in range(ph.Count - 1):
        quad = [(ph[i].X, ph[i].Y), (ph[i + 1].X, ph[i + 1].Y), (pl[i + 1].X, pl[i + 1].Y), (pl[i].X, pl[i].Y)]
        if abs(hgeo.area(quad)) > ctx.tol * ctx.tol:
            out.append(quad)
    return out


# -- infill up to a roof ----------------------------------------------------------------------------
def _slab_under_roof(ctx, rc, poly, z_bot, min_h):
    """Solids over a world plan polygon from z_bot up to the roof's rafter bottom line."""
    out = []
    for f in rc.faces:
        loc = []
        for x, y in poly:
            q = f.frame.local(G.Point3d(x, y, 0.0))
            loc.append((q.X, q.Y))
        if f.v_ridge is not None:
            vr = f.v_ridge
            loc = hgeo.clip_halfplane(loc, lambda q: vr - q[0])
        if len(loc) < 3 or abs(hgeo.area(loc)) < ctx.tol * ctx.tol:
            continue
        loc = hgeo.ccw(loc)
        for b in hgeo.slab_between(loc, [f.zb], [hgeo.Line(z_bot, 0.0)], ctx.tol) or []:
            bb = b.GetBoundingBox(True)
            if bb.Max.Z - bb.Min.Z < min_h:
                continue
            g = b.DuplicateBrep()
            g.Transform(f.frame.xform)
            out.append(g)
    return out


def _framing_infill(ctx, rc, band, z_bot, min_h):
    """Gable studs (on the wall's stud grid, cut to the rafter bottom line) and cavity fill."""
    from ..components import framing
    from .. import profiles
    lay = framing.layout(ctx, band)
    loops = profiles.build(lay.stud, ctx.s)
    pts0 = [loops[0].Point(i) for i in range(loops[0].PointCount)]
    if pts0[0].DistanceTo(pts0[-1]) < 1e-9:
        pts0 = pts0[:-1]
    member = lay.name("stud", lay.stud_name)
    parts = []
    z = lay.center.PointAtStart.Z
    for st in lay.studs:
        if st.opf is not None:
            continue
        fr = lay.frame(st, z)
        poly = []
        for p in pts0:
            w = fr.PointAt(p.X, p.Y)
            poly.append((w.X, w.Y))
        for b in _slab_under_roof(ctx, rc, poly, z_bot, min_h):
            bb = b.GetBoundingBox(True)
            parts.append(Part(b, lay.material, role="gable_stud",
                              extra={"length": round((bb.Max.Z - bb.Min.Z) / ctx.s, 4), "member": member}))
    fill = lay.opts.get("cavity_fill")
    if fill and ctx.lod == "detail":
        try:
            pieces = lay.cavity_pieces()
        except Exception:
            pieces = []
        for crv in pieces:
            ok, pl = crv.TryGetPolyline()
            if not ok:
                pc = crv.ToPolyline(ctx.tol, 0.1, 0.0, 0.0)
                if pc is None:
                    continue
                pl = pc.ToPolyline()
            poly = [(p.X, p.Y) for p in pl]
            if len(poly) > 3 and abs(poly[0][0] - poly[-1][0]) < 1e-9 and abs(poly[0][1] - poly[-1][1]) < 1e-9:
                poly = poly[:-1]
            for b in _slab_under_roof(ctx, rc, poly, z_bot, min_h):
                parts.append(Part(b, fill, role="insulation"))
    return parts


def roof_infill(ctx):
    """Every layer of a wall filled from its top up to the rafter bottom line of the roof over it
    (gable ends, the walls of shed roofs). Pieces lower than 1" are left out."""
    J = getattr(ctx, "joins", None)
    if J is None or not J.roofs:
        return []
    min_h = ctx.u(1)
    parts = []
    for rc in J.roofs:
        if all(f.p <= 1e-9 for f in rc.faces):
            continue
        curved = False
        for band in ctx.bands:
            if band.component == "void" or band.thickness <= ctx.tol:
                continue
            z_bot = ctx.z_range(band)[1]
            try:
                if band.component == "framing" and ctx.lod != "schematic":
                    new = _framing_infill(ctx, rc, band, z_bot, min_h)
                else:
                    polys = band_polys(ctx, band)
                    if not polys:
                        curved = True
                        continue
                    new = []
                    for poly in polys:
                        for b in _slab_under_roof(ctx, rc, poly, z_bot, min_h):
                            role = "masonry" if band.component == "masonry" else (
                                "membrane" if band.component == "membrane" else "solid")
                            new.append(Part(b, band.material, role=role, extra={"infill": "roof"}))
            except Exception as ex:
                ctx.warn("Infill of layer '{}' up to the roof failed ({}).".format(band.name, ex))
                continue
            for p in new:
                p.layer_name = band.name
            parts.extend(new)
        if curved:
            ctx.warn("Curved walls are not filled up to the roof.")
    return parts


def describe_ends(ctx):
    """[(end, kind, style, role, partner)] for reports."""
    return [(n, c.kind, c.style, c.role, c.partner) for n, c in sorted(ends(ctx).items())]
