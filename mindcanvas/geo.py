"""Shared geometry helpers.

Convention: signed offsets are measured from a driver curve with
POSITIVE = EXTERIOR = LEFT of the curve direction (Z x tangent).
Closed drivers are oriented clockwise so their left side is outside.
"""

import Rhino

G = Rhino.Geometry


class GeometryError(Exception):
    pass


def check_horizontal(curve, tol):
    bb = curve.GetBoundingBox(True)
    if bb.Max.Z - bb.Min.Z > tol:
        raise GeometryError("Driver curve must be flat and horizontal (constant Z).")


def orient_driver(curve):
    """Duplicate of the driver; closed curves forced clockwise (exterior outside)."""
    c = curve.DuplicateCurve()
    if c.IsClosed:
        if c.ClosedCurveOrientation(G.Vector3d.ZAxis) == G.CurveOrientation.CounterClockwise:
            c.Reverse()
    return c


def horizontal_plane(z):
    return G.Plane(G.Point3d(0, 0, z), G.Vector3d.ZAxis)


def offset(curve, d, tol):
    """Curve offset by signed distance d (positive = exterior/left)."""
    if abs(d) < tol * 0.5:
        return curve.DuplicateCurve()
    z = curve.PointAtStart.Z
    res = curve.Offset(horizontal_plane(z), -d, tol, G.CurveOffsetCornerStyle.Sharp)
    if not res:
        raise GeometryError("Offset failed at distance {:.4f}".format(d))
    if len(res) > 1:
        joined = G.Curve.JoinCurves(res, tol * 2)
        res = joined if joined else res
    return max(res, key=lambda c: c.GetLength())


def band_outline_open(curve, d_a, d_b, tol):
    """Closed outline of the strip between two offsets of an open curve."""
    ca = offset(curve, d_a, tol)
    cb = offset(curve, d_b, tol)
    pieces = [ca, G.LineCurve(ca.PointAtEnd, cb.PointAtEnd)]
    cb_rev = cb.DuplicateCurve()
    cb_rev.Reverse()
    pieces += [cb_rev, G.LineCurve(cb.PointAtStart, ca.PointAtStart)]
    joined = G.Curve.JoinCurves(pieces, tol * 2)
    if not joined or not joined[0].IsClosed:
        raise GeometryError("Could not close wall band outline.")
    return joined[0]


def band_region(curve, d_a, d_b, tol):
    """Planar region(s) between signed offsets d_a and d_b, at the curve's Z."""
    if abs(d_a - d_b) < tol:
        raise GeometryError("Zero-thickness band.")
    if curve.IsClosed:
        curves = [offset(curve, d_a, tol), offset(curve, d_b, tol)]
    else:
        curves = [band_outline_open(curve, d_a, d_b, tol)]
    breps = G.Brep.CreatePlanarBreps(curves, tol)
    if not breps:
        raise GeometryError("Could not build planar band region.")
    return list(breps)


def extrude_region(region, z0, height, tol):
    """Extrude a horizontal planar region from elevation z0 by height."""
    r = region.DuplicateBrep()
    rz = r.GetBoundingBox(True).Min.Z
    r.Translate(G.Vector3d(0, 0, z0 - rz))
    path = G.LineCurve(G.Point3d(0, 0, 0), G.Point3d(0, 0, height))
    solid = r.Faces[0].CreateExtrusion(path, True)
    if solid is None:
        raise GeometryError("Extrusion failed.")
    if solid.SolidOrientation == G.BrepSolidOrientation.Inward:
        solid.Flip()
    return solid


def band_solids(curve, d_a, d_b, z0, height, tol):
    return [extrude_region(r, z0, height, tol) for r in band_region(curve, d_a, d_b, tol)]


def frame_at(curve, t, z=None):
    """Plane at curve parameter t: X = tangent, Y = exterior (left), Z = up."""
    p = curve.PointAt(t)
    if z is not None:
        p = G.Point3d(p.X, p.Y, z)
    tan = curve.TangentAt(t)
    tan = G.Vector3d(tan.X, tan.Y, 0)
    tan.Unitize()
    left = G.Vector3d.CrossProduct(G.Vector3d.ZAxis, tan)
    return G.Plane(p, tan, left)


def kink_parameters(curve, tol_angle_deg=1.0):
    """Interior parameters where the curve has a corner (polyline vertices etc.)."""
    out = []
    t0, t1 = curve.Domain.T0, curve.Domain.T1
    t = t0
    while True:
        ok, t = curve.GetNextDiscontinuity(G.Continuity.G1_continuous, t, t1)
        if not ok:
            break
        if t1 - t > 1e-9:
            out.append(t)
        else:
            break
    return out


def box(plane, x0, x1, y0, y1, z0, z1):
    """Brep box in a local plane frame from interval bounds."""
    b = G.Box(plane, G.Interval(x0, x1), G.Interval(y0, y1), G.Interval(z0, z1))
    return b.ToBrep()


def extrude_profile(profile_curve, plane, height):
    """Extrude a closed planar profile (drawn in World XY) placed on `plane`
    along the plane's Z axis. Returns a capped Brep."""
    c = profile_curve.DuplicateCurve()
    c.Transform(G.Transform.PlaneToPlane(G.Plane.WorldXY, plane))
    ext = G.Extrusion.Create(c, height, True)
    if ext is None:
        raise GeometryError("Profile extrusion failed.")
    brep = ext.ToBrep()
    # Extrusion.Create extrudes along -normal for positive height in some
    # orientations; force it to run from the plane upward.
    bb = brep.GetBoundingBox(plane)
    if bb.Min.Z < -1e-6:
        brep.Translate(plane.ZAxis * (-bb.Min.Z))
    return brep
