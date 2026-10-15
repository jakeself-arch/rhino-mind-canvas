"""Continuous layers: sheathing, gypsum board, rigid insulation, membranes, air gaps.
Openings are cut out (rough opening, or unit + sealant joint for cladding in front of the frame)."""

from ..openings import core as openings
from .base import Component, Part, register


@register
class Solid(Component):
    """A continuous slab of material filling the whole band."""
    name = "solid"
    role = "solid"

    def build(self, ctx, band):
        z0, z1 = ctx.z_range(band)
        solids = openings.cut(ctx, ctx.solids(band.d_ext, band.d_int, z0, z1), band, z0)
        return [Part(s, band.material, role=self.role) for s in solids]


@register
class Membrane(Solid):
    """Thin sheet goods (WRB, vapor retarder, flashing)."""
    name = "membrane"
    role = "membrane"


@register
class Void(Component):
    """Air gap / cavity: occupies thickness but makes no geometry."""
    name = "void"

    def build(self, ctx, band):
        return []
