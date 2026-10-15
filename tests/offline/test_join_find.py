"""Offline check of join detection (mindcanvas/joins/find.py) against a fake Rhino.Geometry
(tests/offline/fake: straight polylines, offsets, transforms). Prints the joins it finds; no
geometry is built. Run with plain Python 3: python tests/offline/test_join_find.py"""
import sys, json
import os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "fake"), os.path.join(HERE, "..", "..")]
import System
import Rhino
G = Rhino.Geometry
from mindcanvas import library, meta
from mindcanvas.kinds import wall as wallkind
from mindcanvas.joins import find

class Attrs(object):
    def __init__(self): self.d = {}
    def GetUserString(self, k): return self.d.get(k)
    def SetUserString(self, k, v): self.d[k] = v
class Obj(object):
    def __init__(self, geom, kind, asm, params):
        self.Id = System.Guid(); self.Geometry = geom; self.Attributes = Attrs(); self.IsDeleted = False
        a = self.Attributes; a.SetUserString(meta.KIND, "driver"); a.SetUserString(meta.TYPE, kind)
        a.SetUserString(meta.ASSEMBLY, asm); a.SetUserString(meta.PARAMS, json.dumps(params))
class Objects(object):
    def __init__(self): self.objs = []
    def FindByUserString(self, k, v, b): return [o for o in self.objs if o.Attributes.GetUserString(k) == v]
    def FindId(self, i): return next((o for o in self.objs if o.Id == i), None)
class Doc(object):
    RuntimeSerialNumber = 1; ModelAbsoluteTolerance = 0.001 / 12; ModelUnitSystem = "ft"
    def __init__(self): self.Objects = Objects()
doc = Doc(); lib = library.get()
W = "Ext - 2x6 Wood, Fiber Cement"
P = lambda *xy: G.PolylineCurve([G.Point3d(x, y, 0) for x, y in xy])
def add(geom, asm=W, **prm):
    prm.setdefault("height", 109)
    o = Obj(geom, "wall", asm, prm); doc.Objects.objs.append(o); return o
# rectangle of 4 separate walls drawn on the interior face, clockwise (exterior on the left -> outside)
# clockwise around a 20x14 ft box: (0,0)->(0,14)->(20,14)->(20,0)->(0,0); left of +y travel is -x: outside. good.
a = add(P((0, 0), (0, 14)))
b = add(P((0, 14), (20, 14)))
c = add(P((20, 14), (20, 0)))
d = add(P((20, 0), (0, 0)))
# partition T into wall b from inside, ending at b's interior face (drawn on center)
t = add(P((10, 2), (10, 14)), asm="Int - 2x4 Wood Partition")
def ctx_of(o):
    return wallkind.make_context(doc, lib, o, meta.get(o, meta.ASSEMBLY), meta.params(o))
for name, o in (("a", a), ("b", b), ("t", t)):
    ctx = ctx_of(o)
    print(name, "warnings", ctx.warnings)
    for n in ctx.joins.notes: print("   ", n)
    for e, cut in sorted(ctx.joins.ends.items()):
        print("   ", e, cut.kind, cut.style, cut.role, "core ext(+)=%.4f in" % (cut.ext(-2.75/12) * 12),
              "ext face=%.4f in" % (cut.ext(ctx.bands[0].d_ext) * 12), "int face=%.4f in" % (cut.ext(ctx.bands[-1].d_int) * 12))
    print("    backers", len(ctx.joins.backers), "notches", len(ctx.joins.notches), "partners", len(ctx.join_partners))
print("---- probes (inches past the driver end)")
for name, o in (("a", a), ("t", t)):
    ctx = ctx_of(o)
    for e, cut in sorted(ctx.joins.ends.items()):
        row = []
        for bnd in ctx.bands:
            row.append("%s %.3f/%.3f" % (bnd.name[:6], cut.ext(bnd.d_ext, True) * 12, cut.ext(bnd.d_int, False) * 12))
        print(name, e, cut.role, " | ".join(row))
ctx = ctx_of(b)
print("notch", [(round(x*12,3), round(y*12,3)) for x, y in ctx.joins.notches[0][0]], [round(v*12,3) for v in ctx.joins.notches[0][1:3]])
from mindcanvas.joins import plan
fb = [bd for bd in ctx.bands if bd.component == "framing"][0]
print("backers at", [tuple(round(v*12, 3) for v in bk.point(fb.d_mid, 1.5/12)) for bk in ctx.joins.backers])
print("---- floor")
F = "Floor - 2x10 Wood Joists, Plywood"
fl = Obj(P((-0.5, -0.5), (-0.5, 14.5), (20.5, 14.5), (20.5, -0.5), (-0.5, -0.5)), "floor", F, {"base_offset": 109})
doc.Objects.objs.append(fl)
up = add(P((0, 0), (0, 14)), base_offset=109 + 9.25 + 0.75, height=96)
from mindcanvas.kinds import floor as floorkind
try:
    fctx = floorkind.make_context(doc, lib, fl, F, meta.params(fl))
    print("floor warnings", fctx.warnings)
    for k, (poly, dists) in fctx.join_insets.items():
        print(" band", fctx.bands[k].name, [round(x * 12, 3) for x in dists])
    print(" partners", len(fctx.join_partners))
except Exception as ex:
    import traceback; traceback.print_exc()
ctx = ctx_of(a)
print("wall a z_top (in)", {ctx.bands[k].name: round(v * 12, 3) for k, v in ctx.joins.z_top.items()}, ctx.joins.notes[-1:])
print("---- roof")
doc.Objects.objs = [o for o in doc.Objects.objs if o is not fl and o is not up]
R = "Roof - Asphalt Shingle / 2x8 Rafters, Vented Attic"
rf = Obj(P((-0.5, -0.5), (-0.5, 14.5), (20.5, 14.5), (20.5, -0.5), (-0.5, -0.5)), "roof", R, {"base_offset": 109})
doc.Objects.objs.append(rf)
from mindcanvas.kinds import roof as roofkind
try:
    rctx = roofkind.make_context(doc, lib, rf, R, meta.params(rf))
    print("roof st", {k: rctx.st[k] for k in ("wall_depth", "wall_ext", "wall_int")}, "partners", len(rctx.join_partners), rctx.warnings)
    for nm, o in (("a (gable end?)", a), ("b", b)):
        ctx = ctx_of(o)
        print(nm, ctx.warnings, {ctx.bands[k].name: round(v * 12, 3) for k, v in ctx.joins.z_top.items()}, len(ctx.joins.roofs))
except Exception:
    import traceback; traceback.print_exc()
print("---- infill")
from mindcanvas import hgeo
from mindcanvas.joins import geom as jgeom
calls = []
def fake_slab(poly, below, above, tol):
    # report the height range of zb over the polygon above the bottom line
    zs = [below[0](x) - above[0](x) for x, y in poly]
    calls.append((round(max(zs) * 12, 2), round(min(zs) * 12, 2)))
    return []
hgeo.slab_between = fake_slab
for nm, o in (("a gable", a), ("b eave", b)):
    ctx = ctx_of(o)
    calls[:] = []
    ctx.lod = "schematic"
    jgeom.roof_infill(ctx)
    print(nm, "max/min infill height per (band, face) polygon (in):", calls[:12], ctx.warnings)
