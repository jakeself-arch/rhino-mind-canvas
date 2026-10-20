"""Live preview of an edited, unsaved assembly (Phase 12, the visual assembly editor).

A short sample is built in the document from the editor's data: a 4' wall at its default height,
a 4' x 4' floor, an 8' x 6' roof, a 10' curtain wall. It is built by the normal engine with a
library view that has one extra in-memory assembly (PREVIEW_ASSEMBLY, never saved), then every
object of it is re-tagged: `mc.kind = preview` (so it is no driver / part: MCUpdate, joins,
schedules and live mode never see it), `mc.preview = <token>` (the editor that owns it), moved to
the layer MindCanvas::_Preview (object color + render material from its material layer; skipped by
drawings). The sample sits right of everything else in the model (10' gap, chosen at the first
build and kept), joins off, so it never touches user objects. `clear()` deletes it; `close()` also
removes what the preview alone created (empty material layers, unused MC blocks).
"""

import copy
import time
import uuid

import System
import Rhino

from . import docutil, engine, live, meta, units

PREVIEW_LAYER = docutil.PREVIEW_LAYER
KIND = "preview"
TOKEN = "mc.preview"
PREVIEW_ASSEMBLY = "MC Preview (unsaved)"
GAP_IN = 120.0
WALL_LENGTH_IN = 48.0

G = Rhino.Geometry
D = Rhino.DocObjects


def library_view(lib, data):
    """A shallow copy of the library with `data` as PREVIEW_ASSEMBLY (the shared one is untouched)."""
    v = copy.copy(lib)
    v.data = dict(lib.data)
    v.data["assemblies"] = dict(lib.data["assemblies"])
    v.data["assemblies"][PREVIEW_ASSEMBLY] = copy.deepcopy(data)
    v.warnings = []
    v.refresh = lambda: v
    return v


def find(doc, token=None):
    """Preview objects (of one editor, or all)."""
    found = doc.Objects.FindByUserString(meta.KIND, KIND, True)
    out = list(found) if found else []
    if token is not None:
        out = [o for o in out if meta.get(o, TOKEN) == token]
    return out


def purge(doc, keep=()):
    """Delete preview objects not owned by an open editor (left by a crash). Returns the count."""
    n = 0
    for o in find(doc):
        if meta.get(o, TOKEN) not in keep and doc.Objects.Delete(o, True):
            n += 1
    return n


def _root_layers(doc):
    out = set()
    for layer in doc.Layers:
        if layer is not None and not layer.IsDeleted and layer.FullPath.startswith(docutil.ROOT_LAYER):
            out.add(layer.FullPath)
    return out


class Preview(object):
    def __init__(self, doc):
        self.doc = doc
        self.token = uuid.uuid4().hex[:12]
        self.origin = None
        self.ids = []
        self.groups = []
        self.result = None
        self.seconds = 0.0
        self._layers_before = _root_layers(doc)

    # -- placement ------------------------------------------------------------------------------
    def _origin(self):
        if self.origin is None:
            bb = G.BoundingBox.Empty
            for o in self.doc.Objects:
                if o is None or o.IsDeleted or meta.get(o, meta.KIND) == KIND:
                    continue
                b = o.Geometry.GetBoundingBox(True) if o.Geometry is not None else None
                if b is not None and b.IsValid:
                    bb.Union(b)
            s = units.inch_scale(self.doc)
            self.origin = G.Point3d(bb.Max.X + GAP_IN * s, bb.Min.Y, 0.0) if bb.IsValid else G.Point3d(0, 0, 0)
        return self.origin

    def _curve(self, kind):
        s = units.inch_scale(self.doc)
        o = self._origin()
        pt = lambda x, y: G.Point3d(o.X + x * s, o.Y + y * s, o.Z)
        if kind == "floor":
            return G.PolylineCurve([pt(0, 0), pt(48, 0), pt(48, 48), pt(0, 48), pt(0, 0)])
        if kind == "roof":
            return G.PolylineCurve([pt(0, 0), pt(96, 0), pt(96, 72), pt(0, 72), pt(0, 0)])
        length = 120.0 if kind == "curtain_wall" else WALL_LENGTH_IN
        return G.LineCurve(pt(0, 0), pt(length, 0))

    @staticmethod
    def _params(kind):
        if kind in ("wall", "curtain_wall"):
            return {"joins": {"start": "none", "end": "none"}}
        return {}

    # -- build / clear ----------------------------------------------------------------------------
    def build(self, lib, data):
        """(Re)build the sample from assembly data (the editor's model.data). Returns the
        engine's BuildResult (warnings included); raises if the assembly cannot be built."""
        t0 = time.time()
        self.clear()
        kind = data.get("kind", "wall")
        plib = library_view(lib, data)
        doc = self.doc
        with live.quiet():
            cid = doc.Objects.AddCurve(self._curve(kind))
            obj = doc.Objects.FindId(cid)
            self.ids = [cid]
            try:
                res = engine.create(doc, obj, PREVIEW_ASSEMBLY, self._params(kind), plib)
            except Exception:
                self.clear()
                raise
            self.ids += list(res.part_ids)
            self._retag(res)
        self.result = res
        self.seconds = time.time() - t0
        doc.Views.Redraw()
        return res

    def _retag(self, res):
        doc = self.doc
        lidx = docutil.ensure_layer(doc, PREVIEW_LAYER, (90, 150, 230))
        layer = doc.Layers[lidx]
        if layer.PlotWeight != -1:
            layer.PlotWeight = -1
            doc.Layers.Modify(layer, lidx, True)
        name = "MC Preview " + self.token
        gidx = docutil.ensure_group(doc, name)
        self.groups = [name]
        for oid in self.ids:
            o = doc.Objects.FindId(oid)
            if o is None:
                continue
            a = o.Attributes.Duplicate()
            src = doc.Layers[a.LayerIndex]
            a.ColorSource = D.ObjectColorSource.ColorFromObject
            a.ObjectColor = src.Color
            if src.RenderMaterialIndex >= 0:
                a.MaterialSource = D.ObjectMaterialSource.MaterialFromObject
                a.MaterialIndex = src.RenderMaterialIndex
            a.LayerIndex = lidx
            a.SetUserString(meta.KIND, KIND)
            a.SetUserString(TOKEN, self.token)
            a.RemoveFromAllGroups()
            a.AddToGroup(gidx)
            doc.Objects.ModifyAttributes(o, a, True)
        # the engine's own group (MC <kind> <id>) is empty now
        g = doc.Groups.FindName("MC {} {}".format(meta.get(doc.Objects.FindId(self.ids[0]), meta.TYPE) or "wall",
                                                  str(self.ids[0])[:8]))
        if g is not None and not g.IsDeleted:
            doc.Groups.Delete(g.Index)

    def clear(self):
        """Delete this preview's objects (only objects tagged with its token)."""
        n = 0
        with live.quiet():
            for o in find(self.doc, self.token):
                if self.doc.Objects.Delete(o, True):
                    n += 1
            # a failed build leaves our sample curve (and maybe parts of it) untagged
            if self.ids:
                left = [self.doc.Objects.FindId(self.ids[0])] + meta.parts_of(self.doc, self.ids[0])
                for o in left:
                    if o is not None and not o.IsDeleted and self.doc.Objects.Delete(o, True):
                        n += 1
        for name in self.groups:
            g = self.doc.Groups.FindName(name)
            if g is not None and not g.IsDeleted:
                self.doc.Groups.Delete(g.Index)
        self.ids, self.groups = [], []
        return n

    def close(self):
        """Clear, then remove what the preview alone left: unused MC blocks, empty layers it added."""
        self.clear()
        docutil.purge_unused_blocks(self.doc)
        added = sorted((_root_layers(self.doc) - self._layers_before) | {PREVIEW_LAYER}, key=lambda p: -p.count("::"))
        for path in added:
            idx = self.doc.Layers.FindByFullPath(path, -1)
            if idx < 0:
                continue
            layer = self.doc.Layers[idx]
            if self.doc.Objects.FindByLayer(layer) or any(
                    c is not None and not c.IsDeleted for c in (layer.GetChildren() or [])):
                continue
            try:
                self.doc.Layers.Delete(idx, True)
            except Exception:
                pass
        self.doc.Views.Redraw()

    def bounding_box(self):
        bb = G.BoundingBox.Empty
        for o in find(self.doc, self.token):
            bb.Union(o.Geometry.GetBoundingBox(True))
        return bb

    def zoom(self, view=None):
        bb = self.bounding_box()
        if not bb.IsValid:
            return False
        view = view or self.doc.Views.ActiveView
        bb.Inflate(units.inch_scale(self.doc) * 24)
        view.ActiveViewport.ZoomBoundingBox(bb)
        view.Redraw()
        return True
