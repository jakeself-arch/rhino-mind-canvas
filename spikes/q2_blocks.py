"""Spike Q2: which section style applies to geometry inside block instances?

Four 24" test cubes straddling the cut plane (y = 120), right of the building, each a block
instance with a different combination of definition-object layer / SectionAttributesSource and
instance layer. Layer styles (from live_view.py): Brick = fine 45deg hatch, Ground = coarse
45deg hatch (Hatch2), Concrete = plain white. Layer "Default" has no custom style.

  A: def geo on MC::Brick  (FromLayer)    instance on MC::Concrete
  B: def geo on Default    (FromParent)   instance on MC::Brick
  C: def geo on Default    (FromLayer)    instance on MC::Brick
  D: def geo on MC::Brick  (FromParent)   instance on MC::Ground
  E: def geo on Default, layer 0, ColorFromParent + FromParent, nested block inside a block on MC::Ground
"""
import Rhino
import System
from Rhino.Geometry import Box, Plane, Interval, Point3d, Transform

doc = __rhino_doc__
D = Rhino.DocObjects
SRC = D.ObjectSectionAttributesSource

for nm in ("Q2_A", "Q2_B", "Q2_C", "Q2_D", "Q2_E_inner", "Q2_E"):
    idef = doc.InstanceDefinitions.Find(nm)
    if idef is not None:
        doc.InstanceDefinitions.Delete(idef.Index, True, True)


def L(name):
    return doc.Layers.FindByFullPath(name, -1) if "::" in name else doc.Layers.FindByName(name, -1).Index if doc.Layers.FindName(name) else 0


def cube():
    return Box(Plane.WorldXY, Interval(0, 24), Interval(-12, 12), Interval(0, 24)).ToBrep()


def defattrs(layer_idx, src):
    a = D.ObjectAttributes()
    a.LayerIndex = layer_idx
    a.SectionAttributesSource = src
    return a


def inst_attrs(layer_idx):
    a = D.ObjectAttributes()
    a.LayerIndex = layer_idx
    return a


brick = doc.Layers.FindByFullPath("MC::Brick", -1)
conc = doc.Layers.FindByFullPath("MC::Concrete", -1)
ground = doc.Layers.FindByFullPath("MC::Ground", -1)
default = 0

cases = {
    "Q2_A": (brick, SRC.FromLayer, conc),
    "Q2_B": (default, SRC.FromParent, brick),
    "Q2_C": (default, SRC.FromLayer, brick),
    "Q2_D": (brick, SRC.FromParent, ground),
}
x = 400.0
ids = {}
for nm, (dl, src, il) in cases.items():
    di = doc.InstanceDefinitions.Add(nm, "", Point3d.Origin, [cube()], [defattrs(dl, src)])
    ids[nm] = doc.Objects.AddInstanceObject(di, Transform.Translation(x, 120, 6), inst_attrs(il))
    x += 40.0
# nested: inner def (FromParent) inside outer def (inner instance attrs FromParent) on MC::Ground
inner = doc.InstanceDefinitions.Add("Q2_E_inner", "", Point3d.Origin, [cube()], [defattrs(default, SRC.FromParent)])
ref = Rhino.Geometry.InstanceReferenceGeometry(doc.InstanceDefinitions[inner].Id, Transform.Identity)
outer = doc.InstanceDefinitions.Add("Q2_E", "", Point3d.Origin, [ref], [defattrs(default, SRC.FromParent)])
ids["Q2_E"] = doc.Objects.AddInstanceObject(outer, Transform.Translation(x, 120, 6), inst_attrs(ground))

doc.Views.Redraw()
Q2_IDS = ids
print({k: str(v) for k, v in ids.items()})
