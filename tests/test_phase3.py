"""Phase 3: drawing system - patterns, live section styles, display mode, MCSectionCut
logic, and the 2D pipeline on a scene built from the real library assemblies.

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_phase3.py")["run"](__rhino_doc__)

Writes docs/drawings/a_section_perspective_eighth.{svg,png} (building-scale section
perspective with tone + stipple) and b_wall_section_1-1-2.{svg,png} (wall section
detail through the two-sided brick wall). run(doc, parts="b") skips (a).
"""

import os
import runpy
import time

import Rhino

from mindcanvas import docutil, engine, library, meta, stack, units
from mindcanvas.drawing import displaymode, patterns, pipeline, sectioncut, sectionstyle, styles, tags
from mindcanvas.drawing.writers import bake

G = Rhino.Geometry
D = Rhino.DocObjects
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "drawings")
EXT = 'Ext - Brick Veneer / 6" Metal Stud'
PARTITION = 'Int - 3-5/8" Metal Stud Partition'
W, DP = 30.0, 20.0              # building, feet
INSET = 6.625 / 12.0            # core_exterior -> interior face (6" stud + 5/8" gypsum), feet
OUTSET = 8.28125 / 12.0         # core_exterior -> brick face, feet


def _ft(doc, v):
    return units.to_model(doc, v * 12.0)


def _add(doc, crv):
    return doc.Objects.FindId(doc.Objects.AddCurve(crv))


def _rect(doc, x0, y0, x1, y1, z=0.0):
    f = lambda v: _ft(doc, v)
    return G.Rectangle3d(G.Plane(G.Point3d(0, 0, f(z)), G.Vector3d.ZAxis),
                         G.Interval(f(x0), f(x1)), G.Interval(f(y0), f(y1))).ToNurbsCurve()


def _box(doc, x0, y0, z0, x1, y1, z1):
    f = lambda v: _ft(doc, v)
    return G.Box(G.Plane.WorldXY, G.Interval(f(x0), f(x1)), G.Interval(f(y0), f(y1)),
                 G.Interval(f(z0), f(z1))).ToBrep()


def _two_sided(doc, lib, drv):
    """Interior gypsum -> brick with an air space behind it (as tests/test_layers.py)."""
    layers = stack.current(lib, drv)
    gyp = len(layers) - 1
    brick = [spec for label, spec in stack.catalog(lib) if lib.resolve_layer(spec).get("component") == "masonry"][0]
    layers = stack.replace(layers, gyp, brick)
    air = [spec for label, spec in stack.catalog(lib) if label.startswith("Preset:") and spec.get("component") == "void"][0]
    layers = stack.insert(layers, gyp, air)
    return engine.set_layers(doc, drv, layers, lib)


def build_scene(doc, lib):
    t = time.time()
    f = lambda v: _ft(doc, v)
    walls = {}
    r = engine.create(doc, _add(doc, _rect(doc, 0, 0, W, DP)), EXT, {"height": "11'", "lod": "schematic"}, lib)
    walls["storey1"] = r.driver_id
    r = engine.create(doc, _add(doc, _rect(doc, 0, 0, W, DP, 11.0)), EXT, {"height": "10'", "lod": "schematic"}, lib)
    walls["storey2"] = r.driver_id
    line = G.LineCurve(G.Point3d(f(15), f(INSET), 0), G.Point3d(f(15), f(DP - INSET), 0))
    r = engine.create(doc, _add(doc, line), PARTITION, {"height": "10'-4\"", "lod": "design"}, lib)
    walls["partition"] = r.driver_id
    line = G.LineCurve(G.Point3d(f(40), f(4), 0), G.Point3d(f(40), f(16), 0))
    r = engine.create(doc, _add(doc, line), EXT, {"height": "8'", "lod": "design"}, lib)
    walls["garden"] = r.driver_id
    _two_sided(doc, lib, doc.Objects.FindId(r.driver_id))

    conc = docutil.ensure_material_layer(doc, lib, "Concrete")
    a = D.ObjectAttributes()
    a.LayerIndex = conc
    a.SetUserString(meta.MATERIAL, "Concrete")
    i0, i1 = INSET, W - INSET
    j0, j1 = INSET, DP - INSET
    for z0, z1 in ((-8 / 12.0, 0.0), (10 + 4 / 12.0, 11.0), (20 + 4 / 12.0, 21.0)):
        doc.Objects.AddBrep(_box(doc, i0, j0, z0, i1, j1, z1), a)

    site = docutil.ensure_layer(doc, "Site", (120, 120, 100))
    zg = -0.5
    outer = _rect(doc, -45, -40, 80, 70, zg)
    hole = _rect(doc, -OUTSET, -OUTSET, W + OUTSET, DP + OUTSET, zg)
    ground = G.Brep.CreatePlanarBreps([outer, hole], doc.ModelAbsoluteTolerance)[0]
    g = D.ObjectAttributes()
    g.LayerIndex = site
    gid = doc.Objects.AddBrep(ground, g)
    tags.set_flags(doc, doc.Objects.FindId(gid), add=["ground"])
    print("scene built in {:.1f}s".format(time.time() - t))
    return walls


def _view(doc, name):
    for v in doc.Views:
        if v.ActiveViewport.Name == name:
            return v
    return doc.Views.ActiveView


def _report(label, dwg, paths, t):
    print("{}: {:.1f}s  {}".format(label, t, dwg.stats))
    print("   timing:", dwg.timing)
    for w in dwg.warnings:
        print("   warning:", w)
    for p in paths:
        print("   ->", p)


def section_perspective(doc, lib):
    """(a) 1/8" section perspective across the building, tone + stipple."""
    st = styles.get("1/8", lib)
    f = lambda v: _ft(doc, v)
    view = _view(doc, "Perspective")
    view.Maximized = True
    vp = view.ActiveViewport
    for o in doc.Objects.FindByUserString(sectioncut.NAME_KEY, "test a", True) or []:
        doc.Objects.Delete(o, True)
    plane = G.Plane(G.Point3d(f(W / 2), f(8), f(10)), G.Vector3d(-1, 0, 0), G.Vector3d.ZAxis)
    cid = doc.Objects.AddClippingPlane(plane, f(200), f(80), [vp.Id])
    a = doc.Objects.FindId(cid).Attributes.Duplicate()
    a.SetUserString(pipeline.CLIP_KEY, "cut")
    a.SetUserString(sectioncut.NAME_KEY, "test a")
    doc.Objects.ModifyAttributes(cid, a, True)
    vp.ChangeToPerspectiveProjection(True, 28.0)
    vp.SetCameraLocations(G.Point3d(f(16.5), f(14), f(8.5)), G.Point3d(f(8), f(-24), f(17)))
    vp.Camera35mmLensLength = 26.0
    doc.Views.ActiveView = view
    displaymode.assign(view)
    sectionstyle.apply(doc, st)
    doc.Views.Redraw()

    t = time.time()
    n = pipeline.set_lod(doc, st, print)
    print("set_lod: {} walls in {:.1f}s".format(n, time.time() - t))
    t = time.time()
    dwg = pipeline.make(doc, view, st, True, True, print)
    paths = pipeline.write(dwg, os.path.join(OUT, "a_section_perspective_eighth"))
    dt = time.time() - t
    _report("(a) section perspective 1/8", dwg, paths, dt)
    s = dwg.stats
    assert s["regions"] >= 8, "too few cut regions: {}".format(s["regions"])
    assert s["outlines"] >= 2, s
    assert s["lines"] > 150, s
    assert s["dots"] > 300, "ground stipple missing: {}".format(s["dots"])
    assert sum(1 for l in dwg.lines if l[1] == "tone") > 50, "tone missing"
    assert s["ground_lines"] >= 1, "ground cut line missing"
    return dwg, dt


def wall_section(doc, lib, walls):
    """(b) 1-1/2" wall section through the two-sided brick wall (MCSectionCut logic)."""
    st = styles.get("1-1/2", lib)
    f = lambda v: _ft(doc, v)
    drv = doc.Objects.FindId(walls["garden"])
    t = time.time()
    engine.update_params(doc, drv, {"lod": "detail"})
    drv = doc.Objects.FindId(walls["garden"])
    print("garden wall at detail: {} parts in {:.1f}s".format(len(meta.parts_of(doc, drv.Id)), time.time() - t))
    view = _view(doc, "Front")
    view.Maximized = True
    doc.Views.ActiveView = view
    pt = G.Point3d(f(40), f(4) + units.to_model(doc, 74), f(3))
    r = sectioncut.make(doc, drv, pt, view, name="test b", depth_in=16.0, style=st)
    assert len(r["clip_ids"]) == 2, r
    assert doc.NamedViews.FindByName("test b") >= 0, "named view missing"
    roles = pipeline.clip_planes(doc, view.ActiveViewport)
    assert [x[1] for x in roles] == ["cut", "depth"], roles
    # tighter frame: the lower half of the wall, base flashing to mid height
    box = G.BoundingBox(G.Point3d(f(39), r["origin"].Y, f(-1.2)), G.Point3d(f(41), r["origin"].Y, f(8.6)))
    view.ActiveViewport.ZoomBoundingBox(box)
    doc.Views.Redraw()
    t = time.time()
    dwg = pipeline.make(doc, view, st, True, True, print, window=[box.Min, box.Max])
    paths = pipeline.write(dwg, os.path.join(OUT, "b_wall_section_1-1-2"))
    dt = time.time() - t
    _report("(b) wall section 1-1/2", dwg, paths, dt)
    s = dwg.stats
    mats = set(rg.material for rg in dwg.regions)
    print("   cut materials:", sorted(mats))
    assert s["regions"] >= 30, s
    assert any(rg.spec.get("fill") == "black" for rg in dwg.regions), "no steel / flashing / ties cut"
    assert any(m.startswith("Brick") for m in mats), mats
    assert s["hatch"] > 20, "material hatches missing: {}".format(s["hatch"])
    n, origin, _ = bake.bake(doc, dwg, key="test b")
    print("   baked {} objects".format(n))
    assert n > 100
    layers = [L.FullPath for L in doc.Layers if L.FullPath.startswith(bake.ROOT + "::")]
    assert any(p.endswith("::cut") for p in layers), layers
    return dwg, dt


def check_live(doc, lib):
    idx = patterns.ensure(doc)
    missing = [k for k, v in idx.items() if v < 0]
    assert not missing, "patterns missing: {}".format(missing)
    dm = displaymode.ensure()
    assert dm is not None and displaymode.DMD.FindByName(displaymode.NAME) is not None
    # white cut fill must not fall back to black poche (HatchIndex -1)
    mortar = doc.Layers.FindByFullPath(docutil.material_layer_path("Mortar"), -1)
    if mortar >= 0:
        ss = doc.Layers[mortar].GetCustomSectionStyle()
        assert ss is not None and ss.HatchIndex == idx["Solid"], "mortar section style hatch {}".format(
            ss.HatchIndex if ss else None)
        assert ss.HatchPatternColor.R == 255, "white fill hatches in {}".format(ss.HatchPatternColor)
    brick_defs = [d for d in doc.InstanceDefinitions if d is not None and not d.IsDeleted and d.Name.startswith("MC Brick")]
    if brick_defs:
        a = brick_defs[0].GetObjects()[0].Attributes
        assert a.SectionAttributesSource == D.ObjectSectionAttributesSource.FromParent, a.SectionAttributesSource
    for name in styles.names(lib):
        st = styles.get(name, lib)
        assert st.scale > 0 and st.lod in ("schematic", "design", "detail"), st
    print("styles:", styles.names(lib))


def run(doc, clear=True, parts="ab"):
    if clear:
        for o in list(doc.Objects):
            doc.Objects.Delete(o, True)
        for i in range(doc.NamedViews.Count - 1, -1, -1):
            doc.NamedViews.Delete(i)
    engine.setup_document(doc)
    lib = library.get(force_reload=True)
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    walls = build_scene(doc, lib)
    res = {}
    if "a" in parts:
        res["a"] = section_perspective(doc, lib)
    if "b" in parts:
        res["b"] = wall_section(doc, lib, walls)
    check_live(doc, lib)
    try:
        cap = runpy.run_path(os.path.join(HERE, "capture.py"))["capture"]
        print("live view:", cap(doc, "phase3_live_mc_section", view="Front", mode=displaymode.NAME,
                                zoom_extents=False))
    except Exception as ex:
        print("live capture skipped:", ex)
    for k, (dwg, dt) in sorted(res.items()):
        print("timing {}: {:.1f}s".format(k, dt))
    doc.Views.Redraw()
    print("PHASE 3 OK")
    return res
