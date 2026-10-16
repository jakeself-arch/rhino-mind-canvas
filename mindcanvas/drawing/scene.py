"""Scene collection: model objects and block instances (exploded recursively,
nothing baked) as Items with world transforms, material, flags and paper size.

Block geometry is cached per definition: the definition is flattened once, and
its Brep / render mesh / bounding box are computed once and transformed per
instance. A 20'x10' detail brick wall is ~3k instances of a handful of blocks.
"""

import Rhino

from .. import docutil, meta
from . import tags

G = Rhino.Geometry
D = Rhino.DocObjects
IDENT = G.Transform.Identity
DRAWING_ROOT = "MindCanvas Drawing"


class Item(object):
    """geom + xf (world transform of the raw geometry) for HLD; brep(key) + ixf
    (instance transform) for cuts and tone."""
    __slots__ = ("index", "geom", "xf", "ixf", "key", "obj_id", "material", "role", "flags",
                 "bbox", "size_mm", "small", "block")

    @property
    def ground(self):
        return "ground" in self.flags

    def tag(self):
        return {"i": self.index}


def _is_identity(xf):
    return xf.IsIdentity


def to_brep(geom):
    if isinstance(geom, G.Brep):
        return geom
    if isinstance(geom, G.Extrusion):
        return geom.ToBrep()
    if isinstance(geom, G.Surface):
        return G.Brep.CreateFromSurface(geom)
    if isinstance(geom, G.SubD):
        try:
            return geom.ToBrep(G.SubDToBrepOptions.Default)
        except Exception:
            return None
    return None


def xform_bbox(bb, xf):
    if xf.IsIdentity:
        return bb
    xs, ys, zs = [], [], []
    for c in bb.GetCorners():
        p = G.Point3d(c)
        p.Transform(xf)
        xs.append(p.X)
        ys.append(p.Y)
        zs.append(p.Z)
    return G.BoundingBox(min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def _material(doc, obj):
    m = meta.get(obj, meta.MATERIAL)
    if m:
        return m
    layer = doc.Layers[obj.Attributes.LayerIndex]
    return layer.Name if layer is not None else ""


DRAWABLE = (G.Brep, G.Extrusion, G.Surface, G.Mesh, G.SubD)
LINE_BLOCKS = "MC Entourage "    # block definitions whose curves are drawn (entourage/place.py)


class Scene(object):
    def __init__(self, doc):
        self.doc = doc
        self.items = []
        self._defs = {}
        self._geo = {}       # key -> (geom, local xform)
        self._brep = {}
        self._mesh = {}
        self._bbox = {}
        self.stats = {"objects": 0, "instances": 0, "items": 0, "culled": 0, "small": 0, "excluded": 0}

    # -- caches ---------------------------------------------------------
    def _flatten(self, idef):
        key = str(idef.Id)
        out = self._defs.get(key)
        if out is not None:
            return out
        out = []
        lines = idef.Name.startswith(LINE_BLOCKS)
        for o in idef.GetObjects():
            if isinstance(o, D.InstanceObject):
                for k, g, lxf in self._flatten(o.InstanceDefinition):
                    out.append((k, g, o.InstanceXform * lxf))
            elif isinstance(o.Geometry, DRAWABLE) or (lines and isinstance(o.Geometry, G.Curve)):
                k = key + ":" + str(o.Id)
                out.append((k, o.Geometry, IDENT))
        for k, g, lxf in out:
            self._geo.setdefault(k, (g, lxf))
        self._defs[key] = out
        return out

    def brep(self, key):
        """Brep in local (definition) coordinates, nested transforms applied."""
        if key not in self._brep:
            g, lxf = self._geo[key]
            b = to_brep(g)
            if b is not None and not lxf.IsIdentity:
                b = b.DuplicateBrep()
                b.Transform(lxf)
            self._brep[key] = b
        return self._brep[key]

    def world_brep(self, item):
        b = self.brep(item.key)
        if b is None or item.ixf.IsIdentity:
            return b
        b = b.DuplicateBrep()
        b.Transform(item.ixf)
        return b

    def local_bbox(self, key):
        bb = self._bbox.get(key)
        if bb is None:
            g, lxf = self._geo[key]
            bb = xform_bbox(g.GetBoundingBox(True), lxf)
            self._bbox[key] = bb
        return bb

    def mesh(self, key):
        if key not in self._mesh:
            g, lxf = self._geo[key]
            m = None
            if isinstance(g, G.Mesh):
                m = g.DuplicateMesh()
                if not lxf.IsIdentity:
                    m.Transform(lxf)
            else:
                b = self.brep(key)
                if b is not None:
                    m = G.Mesh()
                    for part in G.Mesh.CreateFromBrep(b, G.MeshingParameters.FastRenderMesh) or []:
                        m.Append(part)
            self._mesh[key] = m
        return self._mesh[key]

    def scene_mesh(self, items):
        big = G.Mesh()
        for it in items:
            m = self.mesh(it.key)
            if m is None:
                continue
            if not it.ixf.IsIdentity:
                m = m.DuplicateMesh()
                m.Transform(it.ixf)
            big.Append(m)
        return big

    # -- collection -----------------------------------------------------
    def _skip_layer(self, layer_index):
        layer = self.doc.Layers[layer_index]
        if layer is None or not layer.IsVisible:
            return True
        path = layer.FullPath
        return path.startswith(DRAWING_ROOT) or path in (docutil.DRIVER_LAYER, docutil.MASS_LAYER, docutil.PREVIEW_LAYER)

    def _add(self, geom, xf, ixf, key, obj, material, role, flags, bbox, block):
        it = Item()
        it.index = len(self.items)
        it.geom, it.xf, it.ixf, it.key = geom, xf, ixf, key
        it.obj_id = obj.Id
        it.material, it.role, it.flags = material, role, flags
        it.bbox, it.block = bbox, block
        it.size_mm, it.small = 0.0, False
        self.items.append(it)
        return it

    def collect(self, clips=(), size_fn=None, min_part_mm=0.0, keep=None, visible=None):
        """clips: display-convention planes (the normal side is kept); items wholly on
        the clipped side, or outside the view (visible(bbox) False), are dropped.
        size_fn(bbox) -> paper mm diagonal; parts under min_part_mm are flagged
        small (skipped by HLD and tone, still cut)."""
        doc = self.doc
        tol = doc.ModelAbsoluteTolerance
        st = self.stats
        settings = D.ObjectEnumeratorSettings()
        settings.HiddenObjects = False
        settings.LockedObjects = True
        for obj in doc.Objects.GetObjectList(settings):
            if obj.IsDeleted or isinstance(obj, D.ClippingPlaneObject):
                continue
            is_inst = isinstance(obj, D.InstanceObject)
            if not is_inst and not isinstance(obj.Geometry, DRAWABLE):
                continue
            if self._skip_layer(obj.Attributes.LayerIndex) or (keep is not None and not keep(obj)):
                continue
            flags = tags.flags(doc, obj)
            if "exclude" in flags:
                st["excluded"] += 1
                continue
            material = _material(doc, obj)
            role = meta.get(obj, meta.ROLE, "")
            st["objects"] += 1
            if is_inst:
                st["instances"] += 1
                ixf = obj.InstanceXform
                parts = [(k, g, lxf, xform_bbox(self.local_bbox(k), ixf))
                         for k, g, lxf in self._flatten(obj.InstanceDefinition)]
            else:
                ixf = IDENT
                k = str(obj.Id)
                self._geo[k] = (obj.Geometry, IDENT)
                parts = [(k, obj.Geometry, IDENT, obj.Geometry.GetBoundingBox(True))]
            for k, g, lxf, bb in parts:
                if not bb.IsValid or self._clipped(bb, clips, tol) or (visible is not None and not visible(bb)):
                    st["culled"] += 1
                    continue
                it = self._add(g, ixf * lxf if is_inst else IDENT, ixf, k, obj, material, role, flags, bb, is_inst)
                if size_fn is not None:
                    it.size_mm = size_fn(bb)
                    it.small = it.size_mm < min_part_mm and not it.ground
                    if it.small:
                        st["small"] += 1
        st["items"] = len(self.items)
        return self.items

    @staticmethod
    def _clipped(bb, clips, tol):
        if not clips:
            return False
        corners = bb.GetCorners()
        for pl in clips:
            if all(pl.DistanceTo(c) < -tol for c in corners):
                return True
        return False
