"""Rammed earth: a solid layer laid up in horizontal lifts (strata) of different soils.

Options: "lifts" = [{"material", "height"}, ...] listed BOTTOM -> TOP; the list repeats up the
wall and the top lift is cut off at the wall top. "min_lift" (default 1") folds a thinner
sliver at the top into the lift below it. At schematic LOD the layer is one plain solid."""

from ..openings import core as openings
from .base import Component, Part, register


def lifts(ctx, band):
    """[(material, height in model units)] of a strata band, invalid entries skipped."""
    out = []
    for lift in ctx.option(band, "lifts") or []:
        try:
            h = ctx.u(lift.get("height", 6))
        except (ValueError, AttributeError):
            continue
        if h > 0:
            out.append((lift.get("material") or band.material, h))
    return out or [(band.material, ctx.u(6))]


def courses(ctx, band, z0, z1):
    """[(material, z_bottom, z_top)] filling z0..z1 bottom-up with the repeating lifts."""
    seq = lifts(ctx, band)
    sliver = ctx.u(ctx.option(band, "min_lift", 1))
    out, z, i = [], z0, 0
    while z1 - z > ctx.tol:
        mat, h = seq[i % len(seq)]
        top = min(z + h, z1)
        if z1 - top < sliver:
            top = z1
        out.append((mat, z, top))
        z, i = top, i + 1
    return out


@register
class Strata(Component):
    name = "strata"
    role = "strata"

    def build(self, ctx, band):
        z0, z1 = ctx.z_range(band)
        if ctx.lod == "schematic":
            layers = [(band.material, z0, z1)]
        else:
            layers = courses(ctx, band, z0, z1)
        parts = []
        for mat, a, b in layers:
            for s in openings.cut(ctx, ctx.solids(band.d_ext, band.d_int, a, b), band, z0):
                parts.append(Part(s, mat, role=self.role))
        return parts
