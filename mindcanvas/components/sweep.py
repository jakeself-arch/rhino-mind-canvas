"""Profiles swept along a wall face: base trim, chair rail, crown, cornice, coping, reveals.

Used as an assembly extra (or a per-wall extra in params["extras"], see MCTrim), not as a layer:

    {"component": "sweep", "name": "Base Trim", "material": "Wood Trim",
     "options": {"profile": "Trim - Base 3-1/2", "face": "interior", "z": "base"}}

The profile (library/profiles, any type; MCProfileCapture writes `custom` ones) is drawn with
X = out of the wall face and Y = up, its origin on the face at height `z`:
    face    interior (default) | exterior
    z       base (default) | top | inches above the wall base
    offset  inches out from the face (e.g. over a furring layer)
Polyline walls are swept around their corners (mitered); joined wall ends stop where the face
stops (joins.geom.centerline). Openings whose rough opening overlaps the profile's height cut it.
Schematic LOD leaves sweeps out.
"""

import Rhino

from .. import geo, profiles
from .base import Component, Part, register

G = Rhino.Geometry


def _rail(ctx, d):
    if getattr(ctx, "joins", None) is not None:
        from ..joins import geom as jgeom
        return jgeom.centerline(ctx, d)
    return geo.offset(ctx.curve, d, ctx.tol)


@register
class Sweep(Component):
    name = "sweep"
    role = "trim"

    def build(self, ctx, band):
        if ctx.lod == "schematic" or not ctx.bands:
            return []
        o = ctx.options(band)
        pname = o.get("profile")
        if not pname:
            ctx.warn("Sweep '{}' has no profile.".format(band.name))
            return []
        loops = profiles.build(ctx.lib.profile(pname), ctx.s)
        ext = o.get("face", "interior") == "exterior"
        sgn = 1.0 if ext else -1.0
        d = (ctx.bands[0].d_ext if ext else ctx.bands[-1].d_int) + sgn * ctx.u(o.get("offset", 0))
        zo = o.get("z", "base")
        if zo == "top":
            z = ctx.base_z + ctx.height
        elif zo == "base":
            z = ctx.base_z
        else:
            z = ctx.base_z + ctx.u(zo)
        rail = _rail(ctx, d)
        if rail is None:
            return []
        rail = rail.DuplicateCurve()
        rail.Translate(G.Vector3d(0, 0, z - rail.PointAtStart.Z))
        t0 = rail.Domain.Min
        tan = rail.TangentAt(t0)
        out = G.Vector3d.CrossProduct(G.Vector3d.ZAxis, tan)
        out.Unitize()
        out *= sgn
        plane = G.Plane(rail.PointAt(t0), out, G.Vector3d.ZAxis)
        xf = G.Transform.PlaneToPlane(G.Plane.WorldXY, plane)
        solids = []
        for i, lp in enumerate(loops):
            shape = lp.DuplicateCurve()
            shape.Transform(xf)
            breps = G.Brep.CreateFromSweep(rail, shape, rail.IsClosed, ctx.tol) or []
            caps = []
            for b in breps:
                if not b.IsSolid:
                    b = b.CapPlanarHoles(ctx.tol) or b
                if b.IsSolid and b.SolidOrientation == G.BrepSolidOrientation.Inward:
                    b.Flip()
                caps.append(b)
            if i == 0:
                solids = caps
            elif caps and solids:
                solids = list(G.Brep.CreateBooleanDifference(solids, caps, ctx.tol) or solids)
        if not solids:
            ctx.warn("Sweep '{}' ({}) failed.".format(band.name, pname))
            return []
        bb = G.BoundingBox.Empty
        for lp in loops:
            bb.Union(lp.GetBoundingBox(True))
        z0, z1 = z + bb.Min.Y, z + bb.Max.Y
        cut_ops = [op for op in ctx.openings if op.overlaps_z(z0, z1)]
        cutters = [op.cutter(ctx, -op.rx, op.rx, op.rz0, op.rz1, d - ctx.u(24), d + ctx.u(24)) for op in cut_ops]
        if cutters:
            cut = G.Brep.CreateBooleanDifference(solids, cutters, ctx.tol)
            if cut is not None:
                solids = list(cut)
        # the takeoff length (inches) goes on the first piece: the rail less the openings cut out
        length = max(0.0, rail.GetLength() - sum(2 * op.rx for op in cut_ops)) / ctx.s
        mat = band.material or ctx.lib.profile(pname).get("material") or "Wood Trim"
        return [Part(s, mat, role=self.role,
                     extra={"length": round(length, 3) if i == 0 else 0.0, "profile": pname})
                for i, s in enumerate(solids)]
