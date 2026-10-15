"""Geometry helpers for openings, in an Opening's local frame (x along the host, y = signed
offset, positive = exterior, z = world elevation). All values model units."""

import math

import Rhino

G = Rhino.Geometry


def _capped(srf_brep, tol):
    b = srf_brep.CapPlanarHoles(tol) or srf_brep
    if b.SolidOrientation == G.BrepSolidOrientation.Inward:
        b.Flip()
    return b


def _poly(points):
    pts = list(points)
    if pts[0].DistanceTo(pts[-1]) > 1e-12:
        pts.append(pts[0])
    return G.PolylineCurve(pts)


def extrude(points, vector, tol):
    """Closed planar polygon (Point3d list) extruded by a vector, capped."""
    crv = _poly(points)
    srf = G.Surface.CreateExtrusion(crv, vector)
    if srf is None:
        return None
    return _capped(srf.ToBrep(), tol)


def prism_x(op, poly_yz, x0, x1, tol):
    """(y, z) polygon swept straight along the opening's X from x0 to x1."""
    return extrude([op.pt(x0, y, z) for y, z in poly_yz], op.plane.XAxis * (x1 - x0), tol)


def prism_y(op, poly_xz, y0, y1, tol):
    """(x, z) polygon extruded through the wall from y0 to y1."""
    return extrude([op.pt(x, y0, z) for x, z in poly_xz], op.plane.YAxis * (y1 - y0), tol)


def prism_z(op, poly_xy, z0, z1, tol):
    """(x, y) polygon extruded up from z0 to z1."""
    return extrude([op.pt(x, y, z0) for x, y in poly_xy], G.Vector3d(0, 0, z1 - z0), tol)


def box(op, x0, x1, y0, y1, z0, z1):
    return op.box(x0, x1, y0, y1, z0, z1)


def rect(a0, a1, b0, b1):
    return [(a0, b0), (a1, b0), (a1, b1), (a0, b1)]


def trim(op, curve, x0, x1, tol):
    """Piece of a host curve between the planes x = x0 and x = x1 of the opening frame."""
    ts = []
    for x in (x0, x1):
        pl = op.jamb_plane(x)
        hits = G.Intersect.Intersection.CurvePlane(curve, pl, tol)
        best = None
        if hits:
            p0 = op.pt(x, 0, curve.PointAtStart.Z)
            for ev in hits:
                d = ev.PointA.DistanceTo(p0)
                if best is None or d < best[0]:
                    best = (d, ev.ParameterA)
        if best is None:
            ok, t = curve.ClosestPoint(op.pt(x, 0, curve.PointAtStart.Z))
            best = (0, t)
        ts.append(best[1])
    c = curve
    if c.IsClosed:
        c = c.DuplicateCurve()
        ok, tm = c.ClosestPoint(op.pt(0.5 * (x0 + x1), 0, c.PointAtStart.Z))
        c.ChangeClosedCurveSeam(tm + 0.5 * (c.Domain.Length) if tm + 0.5 * c.Domain.Length < c.Domain.T1
                                else tm - 0.5 * c.Domain.Length)
        ts = [c.ClosestPoint(curve.PointAt(t))[1] for t in ts]
    a, b = sorted(ts)
    if b - a < 1e-12:
        return None
    return c.Trim(G.Interval(a, b))


def sweep(ctx, op, poly_yz, x0, x1, curve=None):
    """(y, z) section swept along the host between x0 and x1: straight prism on a straight host,
    else lofted along the trimmed host curve (y = signed offset from that curve)."""
    from ..components.masonry import profile_solids
    crv = curve if curve is not None else ctx.curve
    piece = trim(op, crv, x0, x1, ctx.tol)
    if piece is None:
        return []
    if piece.IsLinear(ctx.tol) and curve is None:
        b = prism_x(op, poly_yz, x0, x1, ctx.tol)
        return [b] if b is not None else []
    return profile_solids(ctx, poly_yz, piece)


# -- mitered frames -------------------------------------------------------------------
def _member(op, A, sdir, ndir, L, profile, y_face, miter0, miter1, tol):
    """One side of a frame: profile (p inward from the outer edge, q from y_face toward the
    interior) swept along the side; ends mitered at 45 degrees (or square)."""
    ends = []
    for at_end in (False, True):
        pts = []
        for p, q in profile:
            s = (L - p if miter1 else L) if at_end else (p if miter0 else 0.0)
            x = A[0] + sdir[0] * s + ndir[0] * p
            z = A[1] + sdir[1] * s + ndir[1] * p
            pts.append(op.pt(x, y_face - q, z))
        pts.append(pts[0])
        ends.append(G.PolylineCurve(pts))
    res = G.Brep.CreateFromLoft(ends, G.Point3d.Unset, G.Point3d.Unset, G.LoftType.Straight, False)
    if not res:
        return None
    return _capped(res[0], tol)


def frame_ring(op, x0, x1, z0, z1, profile, y_face, tol, sides=("head", "sill", "left", "right"),
               miter_bottom=True):
    """Mitered rectangular frame (outer edges x0..x1, z0..z1). Returns {side: Brep}.
    Without a sill (doors) the jambs run square to z0."""
    out = {}
    W, H = x1 - x0, z1 - z0
    sill = "sill" in sides
    spec = {
        "head": ((x0, z1), (1, 0), (0, -1), W, True, True),
        "sill": ((x0, z0), (1, 0), (0, 1), W, True, True),
        "left": ((x0, z0), (0, 1), (1, 0), H, sill and miter_bottom, True),
        "right": ((x1, z0), (0, 1), (-1, 0), H, sill and miter_bottom, True),
    }
    for side in sides:
        A, sd, nd, L, m0, m1 = spec[side]
        b = _member(op, A, sd, nd, L, profile, y_face, m0, m1, tol)
        if b is not None:
            out[side] = b
    return out


# -- section shapes ----------------------------------------------------------------------
def thicken(path, t):
    from ..components.veneer import thicken as _thicken
    return _thicken(path, t)


def ellipse(cy, cz, ry, rz, n=16):
    return [(cy + ry * math.cos(a), cz + rz * math.sin(a)) for a in [i * 2 * math.pi / n for i in range(n)]]
