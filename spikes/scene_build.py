"""Spike: build a representative test scene for the drawing spike.

Run inside Rhino 8 via run_python:
    exec(open(r"...\\spikes\\scene_build.py").read(), {"__rhino_doc__": __rhino_doc__, "__name__": "__main__"})

Units: inches. Two-storey box building 30' x 20', layered walls (brick / air / insulation /
sheathing / stud zone / gypsum), concrete slabs, studs + bricks as block instances, ground block,
a vertical clipping plane at y = 120" and a perspective camera looking into the cut.
Returns (via globals) SCENE dict with ids.
"""
import time
import Rhino
import System
from Rhino.Geometry import Point3d, Vector3d, Plane, Box, Interval, BoundingBox, Transform

doc = __rhino_doc__
t0 = time.time()

# ---------------------------------------------------------------- reset doc
doc.Objects.Clear() if hasattr(doc.Objects, "Clear") else None
for o in list(doc.Objects):
    doc.Objects.Delete(o, True)
for idef in list(doc.InstanceDefinitions):
    if idef is not None and not idef.IsDeleted:
        doc.InstanceDefinitions.Delete(idef.Index, True, True)
doc.InstanceDefinitions.Compact(True) if hasattr(doc.InstanceDefinitions, "Compact") else None
doc.ModelUnitSystem = Rhino.UnitSystem.Inches
doc.ModelAbsoluteTolerance = 0.01
doc.ModelAngleToleranceDegrees = 1.0

W, Dp = 360.0, 240.0          # footprint (x, y)
FTF = 144.0                    # floor to floor
SLAB = 8.0
CUT_Y = 120.0                  # section plane

# layer stack (exterior -> interior), thickness inches
STACK = [
    ("Brick", 3.625),
    ("AirGap", 1.5),
    ("Insulation", 2.0),
    ("Sheathing", 0.5),
    ("Stud", 3.5),
    ("Gypsum", 0.625),
]
COLORS = {
    "Brick": (170, 80, 60), "AirGap": (230, 230, 230), "Insulation": (240, 220, 120),
    "Sheathing": (200, 170, 120), "Stud": (210, 180, 130), "Gypsum": (245, 245, 245),
    "Concrete": (180, 180, 180), "Ground": (150, 130, 100), "Column": (120, 120, 120),
    "Furniture": (140, 140, 160), "Section": (0, 0, 0),
}


def layer(name):
    full = "MC::" + name
    idx = doc.Layers.FindByFullPath(full, -1)
    if idx >= 0:
        return idx
    parent = doc.Layers.FindByFullPath("MC", -1)
    if parent < 0:
        L = Rhino.DocObjects.Layer()
        L.Name = "MC"
        parent = doc.Layers.Add(L)
    L = Rhino.DocObjects.Layer()
    L.Name = name
    L.ParentLayerId = doc.Layers[parent].Id
    c = COLORS.get(name, (0, 0, 0))
    L.Color = System.Drawing.Color.FromArgb(*c)
    return doc.Layers.Add(L)


def attrs(lname):
    a = Rhino.DocObjects.ObjectAttributes()
    a.LayerIndex = layer(lname)
    return a


def box(x0, x1, y0, y1, z0, z1):
    return Box(Plane.WorldXY, Interval(x0, x1), Interval(y0, y1), Interval(z0, z1)).ToBrep()


def add_box(lname, *ext):
    return doc.Objects.AddBrep(box(*ext), attrs(lname))


ids = {"walls": [], "slabs": [], "bricks": [], "studs": [], "misc": []}

# ---------------------------------------------------------------- ground (cut too)
ids["ground"] = add_box("Ground", -600, W + 600, -600, Dp + 900, -48, 0)

# ---------------------------------------------------------------- slabs
for lvl in range(3):
    z = lvl * FTF
    ids["slabs"].append(add_box("Concrete", 0, W, 0, Dp, z, z + SLAB))
# parapet slab edge upstand on roof
ids["slabs"].append(add_box("Concrete", 0, W, Dp - 8, Dp, 2 * FTF + SLAB, 2 * FTF + 36))

# ---------------------------------------------------------------- block definitions
# Brick: definition geometry on the Brick layer (attributes by layer)
brick_geo = box(0, 7.625, 0, 3.625, 0, 2.25)
brick_def = doc.InstanceDefinitions.Add("MC_Brick", "", Point3d.Origin, [brick_geo], [attrs("Brick")])
# Stud: definition geometry on layer 0/Default with SectionAttributesSource = FromParent
# (to test which layer's section style applies inside blocks)
stud_h = FTF - SLAB
stud_geo = box(0, 1.5, 0, 3.5, 0, stud_h)
a0 = Rhino.DocObjects.ObjectAttributes()
a0.LayerIndex = 0
a0.SectionAttributesSource = Rhino.DocObjects.ObjectSectionAttributesSource.FromParent
a0.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromParent
stud_def = doc.InstanceDefinitions.Add("MC_Stud", "", Point3d.Origin, [stud_geo], [a0])


def place(defidx, lname, xf):
    return doc.Objects.AddInstanceObject(defidx, xf, attrs(lname))


# ---------------------------------------------------------------- walls
# Each wall: list of layer slabs; walls on x=0 (left, bricks as blocks), x=W (right),
# y=Dp (back). Front wall (y=0) exists too but is clipped away by the section plane.
def wall_x(x_ext, inward, y0, y1, z0, z1, brick_blocks):
    """wall parallel to Y at exterior face x_ext; inward = +1 or -1"""
    d = 0.0
    for name, t in STACK:
        xa, xb = x_ext + inward * d, x_ext + inward * (d + t)
        lo, hi = min(xa, xb), max(xa, xb)
        if name == "Brick" and brick_blocks:
            course = 2.25 + 0.375
            n_c = int((z1 - z0) / course)
            for c in range(n_c):
                off = 0.0 if c % 2 == 0 else 4.0
                y = y0 - off
                while y < y1:
                    xf = Transform.Translation(lo, y, z0 + c * course) * Transform.Rotation(
                        System.Math.PI / 2, Vector3d.ZAxis, Point3d.Origin) * Transform.Translation(0, -3.625, 0)
                    # rotated brick: length along Y, depth along X
                    ids["bricks"].append(place(brick_def, "Brick", xf))
                    y += 8.0
        elif name == "Stud":
            for lvl in range(2):
                zb = lvl * FTF + SLAB
                y = y0
                while y <= y1 - 1.5:
                    xf = Transform.Translation(lo + 3.5, y, zb) * Transform.Rotation(
                        System.Math.PI / 2, Vector3d.ZAxis, Point3d.Origin)
                    ids["studs"].append(place(stud_def, "Stud", xf))
                    y += 16.0
        elif name != "AirGap":
            ids["walls"].append(add_box(name, lo, hi, y0, y1, z0, z1))
        d += t


def wall_y(y_ext, inward, x0, x1, z0, z1):
    d = 0.0
    for name, t in STACK:
        ya, yb = y_ext + inward * d, y_ext + inward * (d + t)
        lo, hi = min(ya, yb), max(ya, yb)
        if name == "Stud":
            for lvl in range(2):
                zb = lvl * FTF + SLAB
                x = x0
                while x <= x1 - 1.5:
                    ids["studs"].append(place(stud_def, "Stud", Transform.Translation(x, lo, zb)))
                    x += 16.0
        elif name != "AirGap":
            ids["walls"].append(add_box(name, x0, x1, lo, hi, z0, z1))
        d += t


ZTOP = 2 * FTF + SLAB
wall_x(0.0, +1, 0, Dp, 0, ZTOP, brick_blocks=True)
wall_x(W, -1, 0, Dp, 0, ZTOP, brick_blocks=False)
wall_y(Dp, -1, 0, W, 0, ZTOP)
wall_y(0.0, +1, 0, W, 0, ZTOP)

# ---------------------------------------------------------------- columns, beam, stair-ish, furniture
for x in (120.0, 240.0):
    for y in (80.0, 160.0):
        for lvl in range(2):
            ids["misc"].append(add_box("Column", x - 6, x + 6, y - 6, y + 6, lvl * FTF + SLAB, (lvl + 1) * FTF))
    ids["misc"].append(add_box("Concrete", x - 6, x + 6, 0, Dp, FTF - 18, FTF))
    ids["misc"].append(add_box("Concrete", x - 6, x + 6, 0, Dp, 2 * FTF - 18, 2 * FTF))
# stair: 12 steps
for i in range(16):
    ids["misc"].append(add_box("Concrete", 280 + i * 4.5 * 0, 330, 140 + i * 10, 150 + i * 10,
                               SLAB, SLAB + (i + 1) * 8.0))
# tables
for i, x in enumerate((40, 90, 160, 200)):
    ids["misc"].append(add_box("Furniture", x, x + 36, 150, 186, SLAB + 28, SLAB + 30))
    ids["misc"].append(add_box("Furniture", x, x + 36, 150, 186, FTF + SLAB + 28, FTF + SLAB + 30))

# ---------------------------------------------------------------- clipping plane
# VERIFIED: geometry on the side the plane normal points TO stays visible; the other side is clipped.
# We keep y > CUT_Y (camera at y<0 looks +Y into the cut), so normal must be +Y: (-X) x Z = +Y.
cp_plane = Plane(Point3d(W / 2, CUT_Y, 150), Vector3d(-1, 0, 0), Vector3d(0, 0, 1))
views = [v.ActiveViewportID for v in doc.Views]
persp = None
for v in doc.Views:
    if v.ActiveViewport.Name == "Perspective":
        persp = v
cp_id = doc.Objects.AddClippingPlane(cp_plane, 1200.0, 900.0, [persp.ActiveViewportID])
ids["clip"] = cp_id

# ---------------------------------------------------------------- camera
vp = persp.ActiveViewport
vp.ChangeToPerspectiveProjection(True, 35.0)
cam = Point3d(W * 0.36, -330.0, 165.0)
tgt = Point3d(W * 0.52, Dp, 140.0)
vp.SetCameraLocations(tgt, cam)
vp.Camera35mmLensLength = 22.0
doc.Views.ActiveView = persp
persp.Maximized = True
doc.Views.Redraw()

SCENE = {k: v for k, v in ids.items()}
SCENE["cut_plane"] = cp_plane
SCENE["n_bricks"] = len(ids["bricks"])
SCENE["n_studs"] = len(ids["studs"])
print("scene built in %.2fs: %d bricks, %d studs, %d wall layers, %d misc" % (
    time.time() - t0, len(ids["bricks"]), len(ids["studs"]), len(ids["walls"]), len(ids["misc"])))
