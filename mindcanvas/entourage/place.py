"""Entourage figures in the model: block definitions built from entourage/shapes.py layers.

A figure is a block whose definition stands in the XZ plane (x across, z up, origin on the
ground at the figure's centre). Each shapes.Layer becomes one flat card at y = depth x GAP
(the loops of a layer are unioned into planar Breps) plus its lines (curves on the card). The
figure faces -Y: a front arm (depth -1) sits nearer a viewer on the -Y side. In drawings the
cards hide what is behind them and draw their outlines; the lines are drawn on top
(drawing/scene.py collects the curves of entourage blocks; class "entourage").

Instances carry user text mc.kind = entourage, mc.entourage = library name, mc.params (seed,
height, mirror, ...), mc.role = entourage, mc.draw = notone,nocut.
"""

import hashlib
import json
import math

import Rhino

from .. import docutil, library, meta, units
from . import shapes

G = Rhino.Geometry
D = Rhino.DocObjects

KIND = "entourage"
NAME = "mc.entourage"
LAYER = docutil.ROOT_LAYER + "::Entourage"
BLOCK_PREFIX = "MC Entourage "
GAP = 0.25               # inches between stacked cards
COLOR = (70, 70, 70)
OVERRIDES = ("height", "pose", "dress", "style", "spread", "bag", "arm", "facing", "width")


def names(lib=None, generator=None):
    lib = lib or library.get()
    return sorted(n for n, d in lib.data["entourage"].items()
                  if generator is None or d.get("generator", "custom") == generator)


def definition(lib, name):
    d = lib.data["entourage"].get(name)
    if d is None:
        raise library.LibraryError("Entourage '{}' not found in library/entourage".format(name))
    return d


def layers_for(lib, name, seed=None, **ov):
    return shapes.build(definition(lib, name), seed, **dict((k, v) for k, v in ov.items() if k in OVERRIDES))


def _tag(name, layers):
    raw = json.dumps([(ly.depth, ly.loops, ly.lines) for ly in layers], sort_keys=True)
    return "{}{} #{}".format(BLOCK_PREFIX, name, hashlib.md5(raw.encode("utf-8")).hexdigest()[:8])


def geometry(doc, layers):
    """[(GeometryBase)] of a figure in model units: card Breps + line curves."""
    s = units.inch_scale(doc)
    tol = doc.ModelAbsoluteTolerance
    out = []
    for ly in layers:
        y = ly.depth * GAP * s
        P = lambda q: G.Point3d(q[0] * s, y, q[1] * s)
        crvs = []
        for lp in ly.loops:
            pts = [P(q) for q in lp]
            pts.append(pts[0])
            c = G.PolylineCurve(pts)
            if c.IsClosed and c.GetLength() > tol * 10:
                crvs.append(c)
        if len(crvs) > 1:
            u = G.Curve.CreateBooleanUnion(crvs, tol)
            if u:
                crvs = list(u)
        breps = G.Brep.CreatePlanarBreps(crvs, tol) or []
        if not breps and crvs:
            breps = [b for c in crvs for b in (G.Brep.CreatePlanarBreps(c, tol) or [])]
        out.extend(breps)
        for ln in ly.lines:
            c = G.PolylineCurve([P(q) for q in ln])
            if c.GetLength() > tol:
                out.append(c)
    return out


def ensure_layer(doc):
    idx = docutil.ensure_layer(doc, LAYER, COLOR)
    return idx


def block(doc, lib, name, seed=None, **ov):
    """Block definition index for a figure (shared by every instance with the same shape)."""
    layers = layers_for(lib, name, seed, **ov)
    bname = _tag(name, layers)
    idef = doc.InstanceDefinitions.Find(bname)
    if idef is not None and not idef.IsDeleted:
        return idef.Index
    geoms = geometry(doc, layers)
    if not geoms:
        raise ValueError("Entourage '{}' made no geometry.".format(name))
    return docutil.ensure_block(doc, bname, geoms, ensure_layer(doc), "Rhino Mind Canvas entourage")


def xform(point, angle=0.0, mirror=False):
    xf = G.Transform.Translation(G.Vector3d(point)) * G.Transform.Rotation(angle, G.Vector3d.ZAxis, G.Point3d.Origin)
    if mirror:
        xf = xf * G.Transform.Scale(G.Plane.WorldXY, -1, 1, 1)
    return xf


def place(doc, lib, name, point, angle=0.0, mirror=False, seed=None, **ov):
    """Insert a figure at `point` (on the ground), facing (sin a, -cos a). Returns the object."""
    idx = block(doc, lib, name, seed, **ov)
    prm = dict((k, v) for k, v in ov.items() if k in OVERRIDES and v is not None)
    prm.update({"seed": seed, "mirror": bool(mirror)})
    attrs = D.ObjectAttributes()
    attrs.LayerIndex = ensure_layer(doc)
    for k, v in ((meta.KIND, KIND), (NAME, name), (meta.PARAMS, json.dumps(prm, sort_keys=True)),
                 (meta.ROLE, KIND), (meta.MATERIAL, "Entourage"), ("mc.draw", "nocut,notone")):
        attrs.SetUserString(k, v)
    oid = doc.Objects.AddInstanceObject(idx, xform(point, angle, mirror), attrs)
    return doc.Objects.FindId(oid)


def is_entourage(obj):
    return obj is not None and meta.get(obj, meta.KIND) == KIND


def all_figures(doc):
    return [o for o in doc.Objects if not o.IsDeleted and is_entourage(o)]


def origin(obj):
    p = G.Point3d.Origin
    p.Transform(obj.InstanceXform)
    return p


def facing(obj):
    """Horizontal unit vector the figure faces (its block -Y axis)."""
    v = -G.Vector3d.YAxis
    v.Transform(obj.InstanceXform)
    v.Z = 0
    v.Unitize()
    return v


def face_angle(obj, vp):
    o = origin(obj)
    if vp.IsParallelProjection:
        d = -G.Vector3d(vp.CameraDirection)
    else:
        d = vp.CameraLocation - o
    d.Z = 0
    if d.Length < 1e-9:
        return None
    d.Unitize()
    return math.atan2(d.X, -d.Y)


def face_view(doc, objs, vp):
    """Turn figures about their base point to face the camera of `vp`. Returns the count."""
    n = 0
    for obj in objs:
        a = face_angle(obj, vp)
        if a is None:
            continue
        prm = meta.params(obj)
        new = xform(origin(obj), a, prm.get("mirror", False))
        ok, inv = obj.InstanceXform.TryGetInverse()
        if ok:
            doc.Objects.Transform(obj.Id, new * inv, True)
            n += 1
    return n


def rebuild(doc, lib, obj, **changes):
    """Replace a figure with the same placement and new params (seed, height, mirror, ...)."""
    prm = meta.params(obj)
    prm.update(dict((k, v) for k, v in changes.items()))
    name = changes.get("name") or meta.get(obj, NAME)
    o = origin(obj)
    f = facing(obj)
    angle = math.atan2(f.X, -f.Y)
    ov = dict((k, prm.get(k)) for k in OVERRIDES if prm.get(k) is not None)
    new = place(doc, lib, name, o, angle, prm.get("mirror", False), prm.get("seed"), **ov)
    doc.Objects.Delete(obj, True)
    return new
