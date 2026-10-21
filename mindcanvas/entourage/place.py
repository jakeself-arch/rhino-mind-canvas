"""Entourage models in the model: one block definition per library model, built from its OBJ file.

The block holds one mesh per material of the model, in model units, origin on the ground at the
footprint centre, front facing -Y (catalog.py). Meshes are welded and unwelded again at 40 degree
creases so drawings (MCDrawing) show the silhouette and the real creases, not every facet.
Each mesh takes its colour from the model's MTL file (Color = Model) or from the instance's
layer (Color = Gray, a second block "... (gray)").

Instances carry user text mc.kind = entourage, mc.entourage = library name, mc.params (height,
mirror, color), mc.role = entourage, mc.draw = nocut,notone; drawings class their lines
"entourage" (style classes.entourage).
"""

import hashlib
import json
import math
import os

import Rhino
import System

from .. import docutil, library, meta, units
from . import catalog, objfile

G = Rhino.Geometry
D = Rhino.DocObjects

KIND = "entourage"
NAME = "mc.entourage"
LAYER = docutil.ROOT_LAYER + "::Entourage"
BLOCK_PREFIX = "MC Entourage "
COLOR = (70, 70, 70)
CREASE = math.radians(40.0)
_MESHES = {}     # (path, mtime, scale) -> [(material, rgb, Mesh)]


def names(lib=None, category=None):
    return catalog.names(lib or library.get(), category)


# -- geometry -------------------------------------------------------------------------------
def meshes(doc, lib, name):
    """[(material, (r, g, b) or None, Mesh)] of a model in model units (cached per file)."""
    path = catalog.model_path(lib, name)
    s = units.inch_scale(doc)
    key = (path, os.path.getmtime(path), s)
    out = _MESHES.get(key)
    if out is not None:
        return out
    m = objfile.read(path)
    out = []
    for g in m.groups:
        mesh = G.Mesh()
        index = {}
        for f in g.faces:
            ids = []
            for i in f:
                j = index.get(i)
                if j is None:
                    v = m.vertices[i]
                    j = index[i] = mesh.Vertices.Add(v[0] * s, v[1] * s, v[2] * s)
                ids.append(j)
            if len(ids) == 4:
                mesh.Faces.AddFace(ids[0], ids[1], ids[2], ids[3])
            else:
                for k in range(1, len(ids) - 1):
                    mesh.Faces.AddFace(ids[0], ids[k], ids[k + 1])
        if mesh.Faces.Count == 0:
            continue
        mesh.Vertices.CombineIdentical(True, True)
        mesh.Normals.ComputeNormals()
        mesh.Unweld(CREASE, True)
        mesh.Compact()
        out.append((g.material, m.colors.get(g.material), mesh))
    _MESHES[key] = out
    return out


def ensure_layer(doc):
    return docutil.ensure_layer(doc, LAYER, COLOR)


def block_name(lib, name, gray=False):
    path = catalog.model_path(lib, name)
    stamp = "{}|{}".format(os.path.getsize(path), int(os.path.getmtime(path)))
    tag = hashlib.md5(stamp.encode("utf-8")).hexdigest()[:6]
    return "{}{}{} #{}".format(BLOCK_PREFIX, name, " (gray)" if gray else "", tag)


def block(doc, lib, name, gray=False):
    """Block definition index of a model (shared by all its instances)."""
    bname = block_name(lib, name, gray)
    idef = doc.InstanceDefinitions.Find(bname)
    if idef is not None and not idef.IsDeleted:
        return idef.Index
    parts = meshes(doc, lib, name)
    if not parts:
        raise ValueError("Entourage '{}' has no faces.".format(name))
    layer = ensure_layer(doc)
    geoms, attrs = [], []
    for mat, rgb, mesh in parts:
        a = D.ObjectAttributes()
        a.LayerIndex = layer
        a.Name = mat
        if rgb and not gray:
            a.ColorSource = D.ObjectColorSource.ColorFromObject
            a.ObjectColor = System.Drawing.Color.FromArgb(rgb[0], rgb[1], rgb[2])
        else:
            a.ColorSource = D.ObjectColorSource.ColorFromParent
        a.MaterialSource = D.ObjectMaterialSource.MaterialFromLayer
        a.PlotWeightSource = D.ObjectPlotWeightSource.PlotWeightFromParent
        a.PlotColorSource = D.ObjectPlotColorSource.PlotColorFromParent
        a.SectionAttributesSource = D.ObjectSectionAttributesSource.FromParent
        geoms.append(mesh.DuplicateMesh())
        attrs.append(a)
    return doc.InstanceDefinitions.Add(bname, "Rhino Mind Canvas entourage ({})".format(name),
                                       G.Point3d.Origin, geoms, attrs)


# -- placement ------------------------------------------------------------------------------
def size_factor(lib, name, height=None):
    if not height:
        return 1.0
    h = catalog.height(lib, name)
    return float(height) / h if h > 0 else 1.0


def xform(point, angle=0.0, mirror=False, k=1.0):
    """Model -> world: scale k, mirror left / right (x -> -x), turn by `angle` about Z, move to point."""
    xf = G.Transform.Translation(G.Vector3d(point)) * G.Transform.Rotation(angle, G.Vector3d.ZAxis, G.Point3d.Origin)
    if k != 1.0:
        xf = xf * G.Transform.Scale(G.Point3d.Origin, k)
    if mirror:
        xf = xf * G.Transform.Scale(G.Plane.WorldXY, -1, 1, 1)
    return xf


def place(doc, lib, name, point, angle=0.0, mirror=False, height=None, gray=False):
    """Insert a model at `point` (its base; the top for ceiling models), its front facing
    (sin a, -cos a). height: inches (None = the library size). Returns the object."""
    idx = block(doc, lib, name, gray)
    k = size_factor(lib, name, height)
    prm = {"mirror": bool(mirror), "color": "gray" if gray else "model"}
    if height:
        prm["height"] = float(height)
    attrs = D.ObjectAttributes()
    attrs.LayerIndex = ensure_layer(doc)
    attrs.Name = name
    for key, v in ((meta.KIND, KIND), (NAME, name), (meta.PARAMS, json.dumps(prm, sort_keys=True)),
                   (meta.ROLE, KIND), (meta.MATERIAL, "Entourage"), ("mc.draw", "nocut,notone")):
        attrs.SetUserString(key, v)
    oid = doc.Objects.AddInstanceObject(idx, xform(point, angle, mirror, k), attrs)
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
    """Horizontal unit vector the model's front faces (its block -Y axis)."""
    v = -G.Vector3d.YAxis
    v.Transform(obj.InstanceXform)
    v.Z = 0
    v.Unitize()
    return v


def angle_of(obj):
    f = facing(obj)
    return math.atan2(f.X, -f.Y)


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


def aim_angle(v, heading=False):
    """Turn that points a model's front (-Y), or with `heading` its nose (+X), along v."""
    if G.Vector3d(v.X, v.Y, 0).Length < 1e-9:
        return 0.0
    return math.atan2(v.Y, v.X) if heading else math.atan2(v.X, -v.Y)


def turn(doc, obj, angle):
    """Turn a model about its base point so its front faces angle `angle`."""
    k = size_factor(library.get(), meta.get(obj, NAME), meta.params(obj).get("height"))
    new = xform(origin(obj), angle, meta.params(obj).get("mirror", False), k)
    ok, inv = obj.InstanceXform.TryGetInverse()
    if ok:
        doc.Objects.Transform(obj.Id, new * inv, True)
    return ok


def face_view(doc, objs, vp):
    """Turn models about their base point to face the camera of `vp`. Returns the count."""
    n = 0
    for obj in objs:
        a = face_angle(obj, vp)
        if a is not None and turn(doc, obj, a):
            n += 1
    return n


def rebuild(doc, lib, obj, **changes):
    """Replace a model with the same placement and new settings (name, height, mirror, gray)."""
    prm = meta.params(obj)
    name = changes.get("name") or meta.get(obj, NAME)
    height = changes["height"] if "height" in changes else prm.get("height")
    mirror = changes["mirror"] if "mirror" in changes else prm.get("mirror", False)
    gray = changes["gray"] if "gray" in changes else prm.get("color") == "gray"
    o, a = origin(obj), angle_of(obj)
    attrs = obj.Attributes
    new = place(doc, lib, name, o, a, mirror, height, gray)
    if new is not None:
        na = new.Attributes.Duplicate()
        na.LayerIndex = attrs.LayerIndex
        doc.Objects.ModifyAttributes(new, na, True)
    doc.Objects.Delete(obj, True)
    return doc.Objects.FindId(new.Id) if new is not None else None


def preview(doc, lib, name):
    """Meshes for the placement ghost (model units, model coordinates)."""
    return [msh for _, _, msh in meshes(doc, lib, name)]
