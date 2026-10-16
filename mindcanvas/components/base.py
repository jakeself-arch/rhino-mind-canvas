"""Component framework.

A *component* turns one assembly layer (a LayerBand) into geometry Parts.
To add a new component type, create a module in this folder:

    from .base import Component, Part, register

    @register
    class MyThing(Component):
        name = "mything"            # used as "component": "mything" in assemblies
        def build(self, ctx, band):
            solids = ctx.solids(band.d_ext, band.d_int)
            return [Part(s, band.material, role="mything") for s in solids]

It is picked up automatically (see components/__init__.py).
"""

from .. import docutil, geo, units

REGISTRY = {}


def register(cls):
    REGISTRY[cls.name] = cls()
    return cls


def get(name):
    comp = REGISTRY.get(name)
    if comp is None:
        raise KeyError("Unknown component '{}'. Known: {}".format(name, ", ".join(sorted(REGISTRY))))
    return comp


class Part(object):
    """One generated object. Either `geometry` (a GeometryBase) or a block
    instance (`block` = definition index, `xform` = placement Transform)."""

    __slots__ = ("geometry", "material", "role", "block", "xform", "extra", "layer_name")

    def __init__(self, geometry=None, material=None, role="solid", block=None, xform=None,
                 extra=None, layer_name=None):
        self.geometry = geometry
        self.material = material
        self.role = role
        self.block = block
        self.xform = xform
        self.extra = extra or {}
        self.layer_name = layer_name  # filled in by the engine from the band


class LayerBand(object):
    """One assembly layer positioned relative to the driver curve.

    d_ext > d_int are signed offsets from the driver (positive = exterior)."""

    def __init__(self, index, spec, d_ext, d_int):
        self.index = index
        self.spec = spec
        self.name = spec.get("name") or spec.get("material") or "Layer {}".format(index + 1)
        self.material = spec.get("material")
        self.component = spec.get("component", "solid")
        self.d_ext = d_ext
        self.d_int = d_int

    @property
    def thickness(self):
        return self.d_ext - self.d_int

    @property
    def d_mid(self):
        return 0.5 * (self.d_ext + self.d_int)

    def __repr__(self):
        return "<Band {} '{}' {} [{:.4f}, {:.4f}]>".format(
            self.index, self.name, self.component, self.d_ext, self.d_int)


class BuildContext(object):
    def __init__(self, doc, lib, assembly_name, assembly, params, curve, base_z, height, lod):
        self.doc = doc
        self.lib = lib
        self.assembly_name = assembly_name
        self.assembly = assembly
        self.params = params
        self.curve = curve            # oriented driver (closed = clockwise)
        self.base_z = base_z          # model units
        self.height = height          # model units
        self.lod = lod                # "schematic" | "design" | "detail"
        self.tol = doc.ModelAbsoluteTolerance
        self.s = units.inch_scale(doc)
        self.bands = []
        self.warnings = []
        self.openings = []            # openings.core.Opening records hosted by this assembly
        self.joins = None             # joins.find.Joins of a wall (ends, notches, backers, z_top)
        self.join_partners = set()    # ids of assemblies joined to this one (rebuilt with it)

    # -- units ------------------------------------------------------------
    def u(self, value):
        """Library length (inches / imperial string) -> model units."""
        return units.parse_length(value) * self.s

    # -- options with per-wall overrides -------------------------------
    def option(self, band, key, default=None):
        """band options, overridden by params['overrides'][band.name][key]."""
        ov = self.params.get("overrides", {}).get(band.name, {})
        if key in ov:
            return ov[key]
        return band.spec.get("options", {}).get(key, default)

    def options(self, band):
        merged = dict(band.spec.get("options", {}))
        merged.update(self.params.get("overrides", {}).get(band.name, {}))
        return merged

    # -- stack navigation ---------------------------------------------
    def band(self, name):
        for b in self.bands:
            if b.name == name:
                return b
        return None

    def neighbor(self, band, step):
        i = band.index + step
        return self.bands[i] if 0 <= i < len(self.bands) else None

    # -- vertical extents ----------------------------------------------
    def z_range(self, band):
        """(z0, z1) for a band, honoring options extend_bottom / extend_top. Without an explicit
        extend_top, joins may move the top (over a floor rim, under a roof: ctx.joins.z_top)."""
        z0 = self.base_z - self.u(self.option(band, "extend_bottom", 0))
        top = self.option(band, "extend_top", None)
        if top is None:
            J = getattr(self, "joins", None)
            dz = J.z_top.get(band.index, 0.0) if J is not None else 0.0
        else:
            dz = self.u(top)
        z1 = self.base_z + self.height + dz
        return z0, z1

    # -- geometry shortcuts -------------------------------------------
    def solids(self, d_a, d_b, z0=None, z1=None):
        """Solids of the strip between offsets d_a and d_b; walls with joins stop at their join
        cuts and are notched where other walls join them (mindcanvas/joins)."""
        if z0 is None:
            z0 = self.base_z
        if z1 is None:
            z1 = self.base_z + self.height
        if getattr(self, "joins", None) is not None:
            from ..joins import geom as jgeom
            return jgeom.band_solids(self, d_a, d_b, z0, z1)
        return geo.band_solids(self.curve, d_a, d_b, z0, z1 - z0, self.tol)

    def material_layer(self, material):
        return docutil.ensure_material_layer(self.doc, self.lib, material)

    def block(self, name, geometries, material):
        """Block definition index for repeated members (created once per doc)."""
        return docutil.ensure_block(self.doc, name, geometries, self.material_layer(material))

    def warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)


class Component(object):
    name = None

    def build(self, ctx, band):
        """Return a list of Parts for this band."""
        raise NotImplementedError
