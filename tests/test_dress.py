"""Dressing massing solids (mindcanvas/dress.py, MCDress): one solid = one story.

Run inside Rhino (e.g. via the MCP run_python tool), in an EMPTY, unsaved document (it is cleared):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_dress.py")["run"](__rhino_doc__, captures=True)

Covers: two stacked boxes -> two closed walls (perimeter wall masses, exterior face on the box)
and one floor whose top is the shared face; the lower wall stops at the floor framing's bottom
(top_cut = the floor's depth through its joists), the joins see the wall under the floor and the
floor's rim inset; the floor boundary is the lower outline set in to the wall core; live mode (the
idle handler is called directly): pushing the upper box's top only rebuilds the upper story, moving
the shared face (both boxes) moves the floor and both walls follow; an L-shaped upper story on a
rectangle; a third story; Floor=None gives no floor and no cut; GroundFloor; deleting the top box
removes its floor and the lower walls go back to full height; a sloped top is reported; re-dressing
changes the wall assembly; captures of a dressed three-story block.
"""

import os
import time

import scriptcontext
import System
import Rhino

from mindcanvas import dress, engine, library, live, meta, props, units, wallmasses
from mindcanvas.kinds import floor as fk
from mindcanvas.kinds import wall as wk

G = Rhino.Geometry
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CAPTURES = os.path.join(ROOT, "docs", "captures")
WOOD = "Ext - 2x6 Wood, Fiber Cement"
BRICK = 'Ext - Brick Veneer / 6" Metal Stud'
FLOOR = "Floor - 2x10 Wood Joists, Plywood"
FAILS = []


def say(*a):
    print(" ".join(str(x) for x in a))


def check(cond, label):
    say(("ok   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def near(a, b, tol=1.0 / 32):
    return abs(float(a) - float(b)) < tol


def _ft(doc, v):
    return units.to_model(doc, v * 12.0)


def _box(doc, x0, x1, y0, y1, z0, z1):
    f = lambda v: _ft(doc, v)
    b = G.Box(G.Plane.WorldXY, G.Interval(f(x0), f(x1)), G.Interval(f(y0), f(y1)), G.Interval(f(z0), f(z1))).ToBrep()
    return doc.Objects.FindId(doc.Objects.AddBrep(b))


def _prism(doc, pts_ft, z0, z1):
    f = lambda v: _ft(doc, v)
    crv = G.PolylineCurve([G.Point3d(f(x), f(y), f(z0)) for x, y in list(pts_ft) + [pts_ft[0]]])
    region = G.Brep.CreatePlanarBreps([crv], doc.ModelAbsoluteTolerance)[0]
    solid = region.Faces[0].CreateExtrusion(G.LineCurve(G.Point3d(0, 0, 0), G.Point3d(0, 0, f(z1 - z0))), True)
    if solid.SolidOrientation == G.BrepSolidOrientation.Inward:
        solid.Flip()
    return doc.Objects.FindId(doc.Objects.AddBrep(solid))


def _idle():
    st = scriptcontext.sticky[live.STICKY_KEY]
    st["handlers"][2](None, None)


def _replace(doc, obj, xf):
    g = obj.Geometry.Duplicate()
    g.Transform(xf)
    doc.Objects.Replace(obj.Id, g)          # what a gumball edit does: live queues it
    _idle()


def _height(lib, doc, m):
    return units.parse_length(props.settings(lib, wallmasses.wall_of(doc, doc.Objects.FindId(m.Id)))["height"])


def _floors(doc):
    return dress.dress_floors(doc)


def run(doc, lib=None, captures=False):
    del FAILS[:]
    assert not doc.Path, "run the test in an empty, unsaved document"
    t0 = time.time()
    doc.Objects.Clear()
    engine.setup_document(doc)
    lib = lib or library.get()
    if not live.is_on():
        live.enable()
    s = units.inch_scale(doc)
    depth = dress.floor_depth(lib, FLOOR)
    say("floor depth to framing bottom: {}\"".format(depth))

    say("-- two stories")
    a = _box(doc, 0, 24, 0, 16, 0, 10)
    b = _box(doc, 0, 24, 0, 16, 10, 19)
    (ma, mb), sr, notes = dress.make(doc, [a, b], WOOD, FLOOR, False, lib)
    check(sr.created == 1 and len(_floors(doc)) == 1, "one floor between them ({})".format(sr))
    check(dress.is_dressed(ma) and dress.is_dressed(mb), "both boxes are dressed wall masses")
    check(near(_height(lib, doc, ma), 120 - depth), "lower wall stops at the floor framing ({}\")".format(_height(lib, doc, ma)))
    check(near(_height(lib, doc, mb), 108), "upper wall: the full box height")
    f = _floors(doc)[0]
    fctx = fk.make_context(doc, lib, f, meta.get(f, meta.ASSEMBLY), meta.params(f))
    check(near(fctx.bands[0].d_ext / s, 120), "floor top = the shared face (10')")
    wa = wallmasses.wall_of(doc, ma)
    wctx = wk.make_context(doc, lib, wa, meta.get(wa, meta.ASSEMBLY), meta.params(wa))
    check(any("under floor" in n for n in wctx.joins.notes), "the lower wall joins under the floor ({})".format(wctx.joins.notes))
    inset = dress.wall_inset(doc, lib, dress.Story(doc, ma)) / s
    bb = f.Geometry.GetBoundingBox(True)
    check(near(bb.Min.X / s, inset) and near(bb.Max.X / s, 288 - inset), "floor boundary = outline set in {}\" to the core".format(inset))
    check(bool(fctx.join_insets), "the floor sees the walls on its edges")

    say("-- live: push / pull")
    mb = doc.Objects.FindId(mb.Id)
    xf = G.Transform.Scale(G.Plane(G.Point3d(0, 0, _ft(doc, 10)), G.Vector3d.ZAxis), 1, 1, 11.0 / 9.0)
    _replace(doc, mb, xf)
    check(near(_height(lib, doc, mb), 132), "pushing the top box up: its wall is 11'")
    check(near(_height(lib, doc, ma), 120 - depth) and len(_floors(doc)) == 1, "the lower story and floor stay")
    # move the shared face up 1': stretch the lower box, move the upper one
    _replace(doc, doc.Objects.FindId(ma.Id), G.Transform.Scale(G.Plane.WorldXY, 1, 1, 1.1))
    _replace(doc, doc.Objects.FindId(mb.Id), G.Transform.Translation(0, 0, _ft(doc, 1)))
    f = _floors(doc)[0]
    fctx = fk.make_context(doc, lib, f, meta.get(f, meta.ASSEMBLY), meta.params(f))
    check(len(_floors(doc)) == 1 and near(fctx.bands[0].d_ext / s, 132), "moving the shared face moves the floor (top {}\")".format(fctx.bands[0].d_ext / s))
    check(near(_height(lib, doc, ma), 132 - depth), "... the lower wall follows ({})".format(_height(lib, doc, ma)))
    # a gap: the upper box lifted off -> no floor, full height below
    _replace(doc, doc.Objects.FindId(mb.Id), G.Transform.Translation(0, 0, _ft(doc, 2)))
    check(not _floors(doc) and near(_height(lib, doc, ma), 132), "lifted off: no floor, the lower wall full height")
    _replace(doc, doc.Objects.FindId(mb.Id), G.Transform.Translation(0, 0, _ft(doc, -2)))
    check(len(_floors(doc)) == 1 and near(_height(lib, doc, ma), 132 - depth), "set back down: the floor returns")

    say("-- more stories, shapes, options")
    c = _prism(doc, [(0, 0), (24, 0), (24, 8), (12, 8), (12, 16), (0, 16)], 22, 31)      # an L on top
    (mc,), sr, _ = dress.make(doc, [c], WOOD, FLOOR, False, lib)
    check(len(_floors(doc)) == 2, "a third (L-shaped) story adds a floor")
    check(near(_height(lib, doc, mb), 132 - depth), "the middle wall now stops under the floor above")
    d = _box(doc, 40, 60, 0, 12, 0, 10)
    (md,), sr, _ = dress.make(doc, [d], WOOD, None, True, lib)
    check(len(_floors(doc)) == 2, "Floor=None: no floor (ground or above)")
    e = _box(doc, 40, 60, 0, 12, 10, 19)
    (me,), sr, _ = dress.make(doc, [e], WOOD, None, False, lib)
    check(len(_floors(doc)) == 2 and near(_height(lib, doc, md), 120), "a story with Floor=None on top: no floor, no cut")
    g = _box(doc, 70, 90, 0, 12, 0, 10)
    (mg,), sr, _ = dress.make(doc, [g], WOOD, FLOOR, True, lib)
    gf = [x for x in _floors(doc) if meta.get(x, dress.FLOOR_OF).startswith("|")]
    check(len(gf) == 1 and near(gf[0].Geometry.PointAtStart.Z / s, 0), "GroundFloor: a floor at the bottom")
    check(near(_height(lib, doc, mg), 120), "... its walls keep the full height")
    tent = G.Brep.CreateFromBox([G.Point3d(_ft(doc, 100), 0, 0), G.Point3d(_ft(doc, 120), 0, 0), G.Point3d(_ft(doc, 120), _ft(doc, 10), 0),
                                  G.Point3d(_ft(doc, 100), _ft(doc, 10), 0), G.Point3d(_ft(doc, 100), 0, _ft(doc, 10)),
                                  G.Point3d(_ft(doc, 120), 0, _ft(doc, 10)), G.Point3d(_ft(doc, 120), _ft(doc, 5), _ft(doc, 14)),
                                  G.Point3d(_ft(doc, 100), _ft(doc, 5), _ft(doc, 14))])
    t = doc.Objects.FindId(doc.Objects.AddBrep(tent)) if tent is not None else None
    if t is not None:
        objs, sr, notes = dress.make(doc, [t], WOOD, FLOOR, False, lib)
        check(any("sloped top" in n for n in notes), "a sloped top is reported (no roof yet)")
    (ma2,), sr, _ = dress.make(doc, [doc.Objects.FindId(ma.Id)], BRICK, FLOOR, False, lib)
    check(meta.get(wallmasses.wall_of(doc, ma2), meta.ASSEMBLY) == BRICK, "dressing again changes the wall assembly")
    f_low = [x for x in _floors(doc) if meta.get(x, dress.FLOOR_OF).startswith(str(ma.Id))]
    check(len(f_low) == 1, "... and its floor follows the new core line")

    say("-- deleting")
    n0 = len(_floors(doc))
    doc.Objects.Delete(doc.Objects.FindId(mc.Id), True)
    _idle()
    check(len(_floors(doc)) == n0 - 1, "deleting the top story removes its floor")
    check(near(_height(lib, doc, mb), 132), "... and the story below gets its full height back")

    if captures:
        view = [v for v in doc.Views if v.ActiveViewport.Name == "Perspective"][0]
        doc.Views.ActiveView = view
        # rebuild the three-story L for the picture
        c2 = _prism(doc, [(0, 0), (24, 0), (24, 8), (12, 8), (12, 16), (0, 16)], 22, 31)
        dress.make(doc, [c2], WOOD, FLOOR, False, lib)
        view.ActiveViewport.SetCameraLocations(G.Point3d(_ft(doc, 12), _ft(doc, 8), _ft(doc, 14)),
                                               G.Point3d(_ft(doc, 60), _ft(doc, -50), _ft(doc, 40)))
        view.ActiveViewport.DisplayMode = Rhino.Display.DisplayModeDescription.FindByName("Shaded")
        from mindcanvas import masses
        masses.set_visible(doc, False)           # the walls and floors, not the solids
        try:
            bmp = view.CaptureToBitmap(System.Drawing.Size(900, 640))
        finally:
            masses.set_visible(doc, True)
        path = os.path.join(CAPTURES, "dress_stories.png")
        bmp.Save(path)
        say("capture", path)
    say("{} checks failed; {:.1f}s".format(len(FAILS), time.time() - t0))
    for x in FAILS:
        say("  FAIL " + x)
    return not FAILS
