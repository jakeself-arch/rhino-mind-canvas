"""Continuous layers: sheathing, gypsum board, rigid insulation, membranes, air gaps."""

from .base import Component, Part, register


@register
class Solid(Component):
    """A continuous slab of material filling the whole band."""
    name = "solid"
    role = "solid"

    def build(self, ctx, band):
        z0, z1 = ctx.z_range(band)
        return [Part(s, band.material, role=self.role) for s in ctx.solids(band.d_ext, band.d_int, z0, z1)]


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
