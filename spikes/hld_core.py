"""Spike Q3: HiddenLineDrawing (Make2D engine) on a perspective view with a clipping plane.

Defines:
  collect_scene(doc, layer_filter=None, max_instances=None) -> list of (geom, xform, tag)
      explodes block instances (nested) into (definition geometry, accumulated transform, tag);
      tag = dict(id=source top-level object id, layer=effective layer index, kind=...)
  compute_hld(doc, viewport, items, clip_planes, include_hidden=False) -> (hld, seconds)
  classify(hld, viewport) -> list of dict segments with keys
      curve2d, vis, sil, cls ('cut' | 'silhouette' | 'crease' | 'boundary' | 'hidden' | 'other'),
      tag, depth (distance camera->3D midpoint), depth_n (0 near .. 1 far)
"""
import time
import math
import Rhino
import System
from Rhino.Geometry import (HiddenLineDrawing, HiddenLineDrawingParameters, HiddenLineDrawingSegment,
                            SilhouetteType, Transform, Point3d)

doc = __rhino_doc__
D = Rhino.DocObjects
VIS = HiddenLineDrawingSegment.Visibility
SRC = D.ObjectSectionAttributesSource


def _effective_layer(obj_attrs, parent_layer):
    """layer rule we adopt for block geometry (mirrors Q2 result for SectionAttributesSource)."""
    if parent_layer is not None and obj_attrs.SectionAttributesSource == SRC.FromParent:
        return parent_layer
    if parent_layer is not None and obj_attrs.LayerIndex == 0:
        return parent_layer
    return obj_attrs.LayerIndex


def _explode(idef, xform, top_id, parent_layer, out, depth=0):
    for o in idef.GetObjects():
        lay = _effective_layer(o.Attributes, parent_layer)
        if isinstance(o, D.InstanceObject):
            _explode(o.InstanceDefinition, xform * o.InstanceXform, top_id, lay, out, depth + 1)
        else:
            out.append((o.Geometry, xform, {"id": top_id, "layer": lay, "block": True}))


def collect_scene(doc, layer_filter=None, max_instances=None, skip_types=(D.ClippingPlaneObject,)):
    items = []
    n_inst = 0
    for o in doc.Objects.GetObjectList(D.ObjectEnumeratorSettings()):
        if isinstance(o, skip_types) or not o.Visible:
            continue
        if layer_filter and not layer_filter(o):
            continue
        if isinstance(o, D.InstanceObject):
            n_inst += 1
            if max_instances is not None and n_inst > max_instances:
                continue
            _explode(o.InstanceDefinition, o.InstanceXform, o.Id, o.Attributes.LayerIndex, items)
        else:
            items.append((o.Geometry, Transform.Identity, {"id": o.Id, "layer": o.Attributes.LayerIndex, "block": False}))
    return items


def compute_hld(viewport, items, clip_planes=(), include_hidden=False, tangent_edges=False, tol=None, flatten=True):
    p = HiddenLineDrawingParameters()
    p.AbsoluteTolerance = tol or doc.ModelAbsoluteTolerance
    p.IncludeTangentEdges = tangent_edges
    p.IncludeTangentSeams = False
    p.IncludeHiddenCurves = include_hidden
    p.Flatten = flatten
    p.SetViewport(viewport)
    for pl in clip_planes:
        p.AddClippingPlane(pl)
    added = 0
    for geom, xf, tag in items:
        if p.AddGeometry(geom, xf, tag):
            added += 1
    t = time.time()
    hld = HiddenLineDrawing.Compute(p, True)
    return hld, time.time() - t, added


SIL_CLASS = {
    SilhouetteType.SectionCut: "cut",
    SilhouetteType.Projecting: "silhouette",
    SilhouetteType.TangentProjects: "silhouette",
    SilhouetteType.Tangent: "silhouette",
    SilhouetteType.Boundary: "boundary",
    SilhouetteType.Crease: "crease",
    SilhouetteType.NonSilhouetteCrease: "crease",
    SilhouetteType.NonSilhouetteTangent: "tangent",
    SilhouetteType.NonSilhouetteSeam: "seam",
}


def classify(hld, viewport):
    cam = viewport.CameraLocation
    segs = []
    for s in hld.Segments:
        vis = s.SegmentVisibility
        if vis not in (VIS.Visible, VIS.Hidden):
            continue
        crv = s.CurveGeometry
        if crv is None:
            continue
        pc = s.ParentCurve
        tag = pc.SourceObject.Tag if pc.SourceObject is not None else None
        sil = pc.SilhouetteType
        cls = "hidden" if vis == VIS.Hidden else SIL_CLASS.get(sil, "other")
        # depth: evaluate the 3D world curve at the segment's mid parameter
        depth = None
        w3 = pc.Curve  # 3D world-space curve this segment was generated from
        if w3 is not None:
            dom = crv.Domain
            # segment curve parameters are shared with the parent curve's domain
            t = 0.5 * (dom.T0 + dom.T1)
            try:
                pt = w3.PointAt(t)
                depth = pt.DistanceTo(cam)
            except Exception:
                depth = None
        segs.append({"curve2d": crv, "vis": vis, "sil": sil, "cls": cls, "tag": tag,
                     "depth": depth, "scene_sil": s.IsSceneSilhouette, "fills": s.CurveSideFills})
    ds = [x["depth"] for x in segs if x["depth"] is not None]
    if ds:
        lo, hi = min(ds), max(ds)
        for x in segs:
            x["depth_n"] = (x["depth"] - lo) / (hi - lo) if x["depth"] is not None and hi > lo else 0.0
    return segs
