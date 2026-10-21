"""Entourage model library in Rhino (MCEntourage, MCEntourageLibrary, entourage/place.py).

Run inside Rhino (e.g. via the MCP run_python tool), in an EMPTY, unsaved document (it is cleared):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_entourage.py")["run"](__rhino_doc__)

Covers: every library model places as one shared block of meshes (model colours; a separate gray
block), base on the ground (ceiling models: top at the click), at its catalog size; Height
scales, Mirror mirrors, FaceView turns people to the camera, rebuild swaps the model in place;
the library window fills, filters, searches, picks and swaps (no clicks); the command modules
import. drawing_on=True: a front elevation of a row of people, trees, a car and furniture
(docs/drawings/g_entourage_sheet_quarter) draws class "entourage" lines, and a figure behind a
wall draws none.
"""

import importlib
import math
import os
import time
from collections import Counter

import Rhino

from mindcanvas import docutil, engine, library, meta, units
from mindcanvas.drawing import tags
from mindcanvas.entourage import catalog, place

G = Rhino.Geometry
D = Rhino.DocObjects
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "drawings")
WOOD = "Ext - 2x6 Wood, Fiber Cement"


def say(*a):
    print(" ".join(str(x) for x in a))


def _ft(doc, v):
    return units.to_model(doc, v * 12.0)


def _front(doc, target):
    v = [x for x in doc.Views if x.ActiveViewport.Name == "Front"][0]
    v.Maximized = True
    doc.Views.ActiveView = v
    vp = v.ActiveViewport
    vp.ChangeToParallelProjection(True)
    vp.SetCameraLocations(target, target - G.Vector3d(0, units.to_model(doc, 1200.0), 0))
    vp.CameraUp = G.Vector3d.ZAxis
    return v


def _clear(doc):
    for o in list(doc.Objects):
        doc.Objects.Delete(o, True)
    docutil.purge_unused_blocks(doc)


def _clear_clips(doc):
    for o in list(doc.Objects.FindByObjectType(D.ObjectType.ClipPlane) or []):
        doc.Objects.Delete(o, True)


def place_all(doc, lib):
    s = units.inch_scale(doc)
    tol = 0.6 * s
    objs = []
    for row, cat in enumerate(catalog.categories(lib)):
        x = 0.0
        for n in catalog.names(lib, cat):
            d = catalog.entry(lib, n)
            w = d["size"][0] * s
            p = G.Point3d(x + w / 2.0, -row * 60 * 12 * s, 0)
            o = place.place(doc, lib, n, p)
            assert place.is_entourage(o) and meta.get(o, place.NAME) == n, n
            assert "nocut" in tags.flags(doc, o) and "notone" in tags.flags(doc, o), n
            bb = o.Geometry.GetBoundingBox(True)
            size = [bb.Max.X - bb.Min.X, bb.Max.Y - bb.Min.Y, bb.Max.Z - bb.Min.Z]
            for a, b in zip(size, d["size"]):
                assert abs(a / s - b) < 0.6, (n, [v / s for v in size], d["size"])
            if d.get("mount") == "ceiling":
                assert abs(bb.Max.Z) < tol, (n, bb.Max.Z)
            else:
                assert abs(bb.Min.Z) < tol, (n, bb.Min.Z)
            geoms = [g.Geometry for g in o.InstanceDefinition.GetObjects()]
            assert geoms and all(isinstance(g, G.Mesh) for g in geoms), n
            objs.append(o)
            x += w + 24 * s
    blocks = set(o.InstanceDefinition.Index for o in objs)
    assert len(blocks) == len(objs), (len(blocks), len(objs))
    say("  placed all {} models ({} blocks)".format(len(objs), len(blocks)))
    return objs


def options(doc, lib):
    s = units.inch_scale(doc)
    p0 = G.Point3d(0, 200 * 12 * s, 0)
    a = place.place(doc, lib, "Man - Standing", p0)
    b = place.place(doc, lib, "Man - Standing", p0 + G.Vector3d(36 * s, 0, 0))
    assert a.InstanceDefinition.Index == b.InstanceDefinition.Index
    # colours: model colours by default, a separate gray block
    parts = a.InstanceDefinition.GetObjects()
    assert any(o.Attributes.ColorSource == D.ObjectColorSource.ColorFromObject for o in parts)
    g = place.place(doc, lib, "Man - Standing", p0 + G.Vector3d(72 * s, 0, 0), gray=True)
    assert g.InstanceDefinition.Index != a.InstanceDefinition.Index
    assert all(o.Attributes.ColorSource == D.ObjectColorSource.ColorFromParent for o in g.InstanceDefinition.GetObjects())
    # height
    h = place.place(doc, lib, "Woman - Standing", p0 + G.Vector3d(108 * s, 0, 0), height=60.0)
    bb = h.Geometry.GetBoundingBox(True)
    assert abs((bb.Max.Z - bb.Min.Z) / s - 60.0) < 0.1, (bb.Max.Z - bb.Min.Z) / s
    assert meta.params(h)["height"] == 60.0
    # turn + mirror
    t = place.place(doc, lib, "Car - Sedan", p0 + G.Vector3d(0, 240 * s, 0), math.radians(90), mirror=True)
    assert t.InstanceXform.Determinant < 0
    f = place.facing(t)
    assert abs(f.X - 1) < 1e-6, f
    # Aim: a vehicle's nose (+X) points at the target, a person's front (-Y) does
    assert catalog.entry(lib, "Car - Sedan").get("heading") and not catalog.entry(lib, "Man - Standing").get("heading")
    car = place.place(doc, lib, "Car - Sedan", p0, place.aim_angle(G.Vector3d(0, 5, 0), True))
    nose = G.Vector3d.XAxis
    nose.Transform(car.InstanceXform)
    assert nose.Y > 0.999, nose
    man = place.place(doc, lib, "Man - Standing", p0, place.aim_angle(G.Vector3d(-5, 0, 0)))
    assert place.facing(man).X < -0.999, place.facing(man)
    doc.Objects.Delete(car, True)
    doc.Objects.Delete(man, True)
    # face the view
    v = [x for x in doc.Views if x.ActiveViewport.Name == "Perspective"][0]
    vp = v.ActiveViewport
    vp.ChangeToPerspectiveProjection(True, 35)
    vp.SetCameraLocations(p0, p0 + G.Vector3d(-300 * s, -500 * s, 70 * s))
    objs = [doc.Objects.FindId(o.Id) for o in (a, b, h)]
    assert place.face_view(doc, objs, vp) == 3
    for o in objs:
        o = doc.Objects.FindId(o.Id)
        d = vp.CameraLocation - place.origin(o)
        d.Z = 0
        d.Unitize()
        assert place.facing(o) * d > 0.999, (place.facing(o), d)
    hb = doc.Objects.FindId(h.Id)
    assert abs((hb.Geometry.GetBoundingBox(True).Max.Z) / s - 60.0) < 0.1, "FaceView kept the height"
    # swap the model, keep place and turn
    o = doc.Objects.FindId(a.Id)
    o0, f0 = place.origin(o), place.facing(o)
    new = place.rebuild(doc, lib, o, name="Woman - Walking")
    assert meta.get(new, place.NAME) == "Woman - Walking"
    assert place.origin(new).DistanceTo(o0) < 0.01 * s and place.facing(new) * f0 > 0.9999
    # ceiling model hangs from the click
    c = place.place(doc, lib, "Pendant - Dome", p0 + G.Vector3d(0, -120 * s, 108 * s))
    cb = c.Geometry.GetBoundingBox(True)
    assert abs(cb.Max.Z / s - 108) < 0.1 and cb.Min.Z / s < 100, (cb.Min.Z / s, cb.Max.Z / s)
    say("  shared block, gray, height, turn + mirror, FaceView, swap, ceiling mount OK")


def window(doc, lib):
    from mindcanvas.eto import entourage as ew
    from mindcanvas.cmd import entourage as cmd
    win = ew.EntourageWindow()
    try:
        assert win.tiles and len(win.tiles) == len(catalog.names(lib, win.cat()))
        win.category.SelectedIndex = win.category.DataStore.index("Trees")
        assert all(catalog.entry(lib, t.name)["category"] == "Trees" for t in win.tiles)
        grp = [g for g in win.group.DataStore if g != ew.ALL][0]
        win.group.SelectedIndex = win.group.DataStore.index(grp)
        assert all(catalog.entry(lib, t.name)["group"] == grp for t in win.tiles), grp
        win.search.Text = "bus"
        assert win.tiles and all("Bus" in t.name for t in win.tiles), [t.name for t in win.tiles]
        win.search.Text = ""
        win.pick("Tree - Pine 2 (38 ft)")
        assert cmd.current(lib) == "Tree - Pine 2 (38 ft)"
        o = place.place(doc, lib, "Tree - Birch 1 (36 ft)", G.Point3d(0, -900 * 12 * units.inch_scale(doc), 0))
        doc.Objects.UnselectAll()
        doc.Objects.Select(o.Id, True)
        win.refresh()
        assert win.selected == {"Tree - Birch 1 (36 ft)"}, win.selected
        win.swap()
        swapped = [x for x in place.all_figures(doc) if meta.get(x, place.NAME) == "Tree - Pine 2 (38 ft)"]
        assert swapped, "swap"
        bmp = ew.bitmap(catalog.thumb_path(lib, "Tree - Pine 2 (38 ft)"))
        assert bmp is not None and bmp.Width == 160
    finally:
        win.form.Close()
    for name in ("entourage", "entouragelibrary"):
        mod = importlib.import_module("mindcanvas.cmd." + name)
        assert hasattr(mod, "run")
    say("  library window: categories, groups, search, pick, swap OK")


def drawing(doc, lib):
    from mindcanvas.drawing import pipeline, styles
    s = units.inch_scale(doc)
    st = styles.get("1/4", lib)
    y0 = 2000 * 12 * s
    row = ["Tree - Deciduous 1 (30 ft)", "Man - Standing", "Woman - Walking", "Car - Sedan", "Bicycle",
           "Tree - Bare Branching 1 (26 ft)", "Bench - Painted Wood", "Woman - Sitting", "Street Lamp - Classic",
           "Shrub - Round 1", "Tree - Pine 4 (34 ft)", "Man - Waving", "Planter Box 1", "Tree - Model Oak (30 ft)"]
    x = 0.0
    objs = []
    for n in row:
        w = catalog.entry(lib, n)["size"][0] * s
        objs.append(place.place(doc, lib, n, G.Point3d(x + w / 2, y0, 0)))
        x += w + 12 * s
    view = _front(doc, G.Point3d(x / 2, y0, 10 * 12 * s))
    _clear_clips(doc)
    place.face_view(doc, [doc.Objects.FindId(o.Id) for o in objs if catalog.entry(lib, meta.get(o, place.NAME)).get("face_view")],
                    view.ActiveViewport)
    gid = doc.Objects.AddBrep(G.Box(G.Plane.WorldXY, G.Interval(-24 * s, x + 24 * s), G.Interval(y0 - 60 * s, y0 + 240 * s),
                                    G.Interval(-6 * s, 0)).ToBrep())
    lo = G.Point3d(-24 * s, y0 - 60 * s, -12 * s)
    hi = G.Point3d(x + 24 * s, y0 + 60 * s, 40 * 12 * s)
    view.ActiveViewport.ZoomBoundingBox(G.BoundingBox(lo, hi))
    doc.Views.Redraw()
    t = time.time()
    dwg = pipeline.make(doc, view, st, False, False, window=[lo, hi])
    pipeline.write(dwg, os.path.join(OUT, "g_entourage_sheet_quarter"))
    cls = Counter(c for _, c, _ in dwg.lines)
    say("  drawing g_entourage_sheet_quarter: {:.1f}s {}".format(time.time() - t, dict(cls)))
    assert cls["entourage"] > 800, cls
    doc.Objects.Delete(gid, True)


def hiding(doc, lib):
    """A figure behind a wall draws no lines; in front of it, it does."""
    from mindcanvas.drawing import pipeline, styles
    s = units.inch_scale(doc)
    y0 = -3000 * 12 * s
    crv = G.PolylineCurve([G.Point3d(-120 * s, y0, 0), G.Point3d(120 * s, y0, 0)])
    r = engine.create(doc, doc.Objects.FindId(doc.Objects.AddCurve(crv)), WOOD,
                      {"height": 96.0, "reference": "interior_face", "lod": "schematic"}, lib)
    st = styles.get("1/4", lib)
    view = _front(doc, G.Point3d(0, y0, 48 * s))
    _clear_clips(doc)
    box = G.BoundingBox(G.Point3d(-140 * s, y0 - 360 * s, -12 * s), G.Point3d(140 * s, y0 + 360 * s, 120 * s))

    def count():
        view.ActiveViewport.ZoomBoundingBox(box)
        doc.Views.Redraw()
        dwg = pipeline.make(doc, view, st, False, False, window=[box.Min, box.Max])
        return Counter(c for _, c, _ in dwg.lines)
    behind = place.place(doc, lib, "Man - Standing", G.Point3d(0, y0 + 60 * s, 0))
    c_behind = count()
    doc.Objects.Delete(behind, True)
    front = place.place(doc, lib, "Man - Standing", G.Point3d(0, y0 - 60 * s, 0))
    c_front = count()
    say("  hiding: behind the wall {} entourage lines, in front {}".format(c_behind["entourage"], c_front["entourage"]))
    assert c_behind["entourage"] == 0 and c_front["entourage"] >= 20, (c_behind, c_front)
    doc.Objects.Delete(front, True)
    engine.delete_parts(doc, r.driver_id)
    doc.Objects.Delete(r.driver_id, True)


def run(doc, clear=True, drawing_on=True):
    assert not doc.Path, "test_entourage clears the document: run it in an empty, unsaved model"
    if clear:
        _clear(doc)
    engine.setup_document(doc)
    lib = library.get(force_reload=True)
    t0 = time.time()
    say("-- entourage library")
    place_all(doc, lib)
    options(doc, lib)
    window(doc, lib)
    if drawing_on:
        say("-- drawings")
        _clear(doc)
        hiding(doc, lib)
        _clear(doc)
        drawing(doc, lib)
    doc.Views.Redraw()
    say("total {:.1f}s".format(time.time() - t0))
    say("ENTOURAGE OK")
