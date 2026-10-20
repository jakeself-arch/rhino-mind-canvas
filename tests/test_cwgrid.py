"""Visual curtain-grid editor (MCCurtainGrid) + doors in curtain walls.

Run inside Rhino (e.g. via the MCP run_python tool), in an EMPTY, unsaved document (it is cleared):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_cwgrid.py")["run"](__rhino_doc__)

Covers: reading a built grid into the editor model (equal grid, transoms, infill, doors); editing
(move / add / remove grid lines, partial transoms, painting, single + pair doors) and applying
(params grid = custom, opening drivers, one rebuild); the round trip; a flipped driver keeps its
grid lines in place; an L-shaped wall (corner locked) and an arc; a closed rectangle; unitized
stack joints; detail LOD timing; switching back to an equal grid; the editor window (handlers,
3D preview lines). captures=True writes docs/captures/cwgrid_editor.png (the drawn elevation) and
cwgrid_wall.png (the rebuilt wall).
"""

import collections
import os
import runpy
import time

import Rhino

from mindcanvas import engine, library, meta, units
from mindcanvas.curtainwall import gridedit as ge
from mindcanvas.curtainwall import gridio

G = Rhino.Geometry
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CAPTURES = os.path.join(ROOT, "docs", "captures")
ASM = "CW - Captured, Aluminum 2-1/2 x 6"
UNIT = "CW - Unitized, Aluminum 3 x 6"
LOG = [None]


def say(*a):
    msg = " ".join(str(x) for x in a)
    print(msg)
    if LOG[0]:
        with open(LOG[0], "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def _ft(doc, v):
    return units.to_model(doc, v * 12.0)


def _wall(doc, crv, asm=ASM, **params):
    obj = doc.Objects.FindId(doc.Objects.AddCurve(crv))
    p = {"height": 144, "lod": "design"}
    p.update(params)
    r = engine.create(doc, obj, asm, p)
    assert not _bad(r), r.warnings
    return doc.Objects.FindId(r.driver_id)


def _bad(r):
    return [w for w in r.warnings if "fail" in w.lower() or "could not" in w.lower() or "skipped" in w.lower()]


def _roles(doc, did):
    return collections.Counter(meta.get(o, meta.ROLE) for o in meta.parts_of(doc, did))


def _close(a, b, e=1e-3):
    return abs(a - b) < e


def run(doc, captures=True, log=None):
    LOG[0] = log
    t_all = time.time()
    assert doc.Path is None or doc.Path == "", "run the tests in an empty, unsaved document"
    doc.Objects.Clear()
    engine.setup_document(doc)
    lib = library.get()

    # -- straight wall: read, edit, apply, round trip ------------------------------------------
    drv = _wall(doc, G.LineCurve(G.Point3d(0, 0, 0), G.Point3d(_ft(doc, 30), 0, 0)), transoms=[30])
    ses = gridio.Session(doc, drv, lib)
    m = ses.model
    assert m.nbays == 6 and _close(m.L, 360) and _close(m.H, 144), (m.nbays, m.L, m.H)
    assert [round(v.u) for v in m.verts] == [0, 60, 120, 180, 240, 300, 360]
    assert m.verts[0].locked and m.verts[-1].locked and not m.verts[1].locked
    assert len(m.hlines) == 1 and m.hlines[0].bays == set(range(6))
    c = ge.GridController(m, 1000, 520, ses.door_info)
    types = ses.door_types()
    single = "Door - Aluminum Entrance, Full Lite"
    pair = "Door - Aluminum Entrance, Full Lite Pair"
    assert types[:2] == [single, pair], types
    # drag a grid line with the mouse
    c.mouse_down(c.x(60), c.y(70))
    c.mouse_move(c.x(48), c.y(70), down=True)
    assert c.mouse_up(c.x(48), c.y(70)) and _close(m.verts[1].u, 48)
    c.edit(lambda: m.remove_vertical(4))                     # 180..300: a 10' bay for a pair
    c.edit(lambda: m.add_hline(96, [0, 1]))
    c.edit(lambda: m.set_cell(0, 0, "spandrel"))
    c.door_type = single
    c.set_tool("door")
    c.mouse_down(c.x(150), c.y(10))
    c.door_type = pair
    c.door_swing = "out"
    c.mouse_down(c.x(240), c.y(10))
    assert set(m.doors) == {2, 3} and m.doors[3].leaves == 2 and m.doors[3].swing == "out", m.doors
    t0 = time.time()
    r = ses.apply(m)
    say("straight: applied {} parts in {:.2f} s".format(len(r.part_ids), time.time() - t0))
    assert not _bad(r), r.warnings
    p = meta.params(doc.Objects.FindId(drv.Id))
    assert p["grid"] == "custom" and p["verticals"] == [48.0, 120.0, 180.0, 300.0], p["verticals"]
    assert p["transoms"][0] == 30.0 and p["transoms"][1]["z"] == 96.0 and len(p["transoms"][1]["at"]) == 2
    ro = _roles(doc, drv.Id)
    assert ro["leaf"] == 3 and ro["swing"] == 6 and ro["threshold"] == 2, ro
    m2 = ses.model
    assert [round(v.u, 3) for v in m2.verts] == [0, 48, 120, 180, 300, 360]
    assert sorted((round(h.z), sorted(h.bays)) for h in m2.hlines) == [(30, [0, 1, 2, 3, 4]), (96, [0, 1])]
    assert m2.cell_type(0, 0) == "spandrel" and set(m2.doors) == {2, 3}
    assert _close(m2.doors[2].head, m.doors[2].head) and m2.doors[3].type == pair
    # the doors' clear widths come from their bays (builder): pair leaves ~ (120 - 2.5 - frame) / 2
    ctx = ses.ctx
    ops = sorted(ctx.openings, key=lambda o: o.s)
    assert len(ops) == 2
    if captures:
        from mindcanvas.eto import cwgridview
        os.makedirs(CAPTURES, exist_ok=True)
        cc = ge.GridController(m2, 1100, 520, ses.door_info)
        cc.sel = ("hline", m2.line_at(96, 0), 0)
        cc.set_tool("vertical")
        cc.ghost = ("vertical", 270.0)
        say("capture", cwgridview.render_png(cc, os.path.join(CAPTURES, "cwgrid_editor.png")))
        _capture_wall(doc, drv)
    # move the pair's bay edge: the door follows; remove the single door
    m2.move_vertical(3, 192)
    m2.remove_door(2)
    ses.apply(m2)
    assert len([o for o in ses.ctx.openings if o.door]) == 1
    assert _roles(doc, drv.Id)["leaf"] == 2

    # a flipped driver keeps its grid lines where they are (stations along the curve as drawn)
    before = sorted(round(v.P.X, 4) for v in ses.ctx.grid.vertices)
    engine.update_params(doc, doc.Objects.FindId(drv.Id), {"flip": True}, lib)
    ses.reload()
    after = sorted(round(v.P.X, 4) for v in ses.ctx.grid.vertices)
    assert before == after, (before, after)
    assert [round(v.u, 3) for v in ses.model.verts] == [0, 60, 168, 240, 312, 360], [v.u for v in ses.model.verts]
    say("flip: grid lines kept")

    # back to an equal grid with the numeric editor's params (partial transoms still work)
    r = engine.update_params(doc, doc.Objects.FindId(drv.Id), {"grid": "equal", "flip": False}, lib)
    assert not _bad(r), r.warnings
    ses.reload()
    assert ses.model.nbays == 6 and any(len(h.bays) < 6 for h in ses.model.hlines)

    # -- L-shaped wall: the corner is locked, lines on both legs ----------------------------------
    pl = G.PolylineCurve([G.Point3d(0, _ft(doc, 20), 0), G.Point3d(_ft(doc, 20), _ft(doc, 20), 0),
                          G.Point3d(_ft(doc, 20), _ft(doc, 40), 0)])
    drvL = _wall(doc, pl, spacing=60)
    sL = gridio.Session(doc, drvL, lib)
    mL = sL.model
    locked = [v for v in mL.verts if v.locked]
    assert len(locked) == 3 and locked[1].kind == "corner" and _close(locked[1].u, 240), locked
    cL = ge.GridController(mL, 1000, 520, sL.door_info)
    k = [i for i, v in enumerate(mL.verts) if v.kind == "corner"][0]
    assert cL.edit(lambda: mL.remove_vertical(k)) is None and "stay" in cL.status
    cL.edit(lambda: mL.add_vertical(250))      # 10" past the corner (closest: 5")
    cL.edit(lambda: mL.equalize(0))
    cL.edit(lambda: mL.add_door(mL.bay_of_u(300), 0, single, sL.door_info(single)["head"]))
    r = sL.apply(mL)
    assert not _bad(r), r.warnings
    assert sum(1 for v in sL.ctx.grid.vertices if v.kind == "corner") == 1
    assert _roles(doc, drvL.Id)["leaf"] == 1
    say("L wall: {} bays, corner kept".format(sL.model.nbays))

    # -- arc ------------------------------------------------------------------------------------------
    arc = G.ArcCurve(G.Arc(G.Point3d(_ft(doc, 40), 0, 0), G.Point3d(_ft(doc, 50), _ft(doc, 6), 0),
                           G.Point3d(_ft(doc, 60), 0, 0)))
    drvA = _wall(doc, arc, spacing=48)
    sA = gridio.Session(doc, drvA, lib)
    mA = sA.model
    n0 = mA.nbays
    ge.GridController(mA).edit(lambda: mA.divide_bay(0, 2))
    sA.apply(mA)
    assert sA.model.nbays == n0 + 1
    say("arc: {} -> {} bays".format(n0, sA.model.nbays))

    _curved(doc, lib, captures)

    # -- closed rectangle: the seam is a locked line at both ends ------------------------------------------
    rect = G.PolylineCurve([G.Point3d(0, -_ft(doc, 40), 0), G.Point3d(_ft(doc, 16), -_ft(doc, 40), 0),
                            G.Point3d(_ft(doc, 16), -_ft(doc, 30), 0), G.Point3d(0, -_ft(doc, 30), 0),
                            G.Point3d(0, -_ft(doc, 40), 0)])
    drvR = _wall(doc, rect, spacing=60, transoms=[36])
    sR = gridio.Session(doc, drvR, lib)
    mR = sR.model
    assert mR.closed and mR.verts[0].locked and mR.verts[-1].kind == "seam" and _close(mR.verts[-1].u, mR.L)
    nb = mR.nbays
    assert nb == len(sR.ctx.grid.bays), (nb, len(sR.ctx.grid.bays))
    cR = ge.GridController(mR)
    free = [i for i, v in enumerate(mR.verts) if not v.locked]
    cR.edit(lambda: mR.move_vertical(free[0], mR.verts[free[0]].u + 6))
    cR.edit(lambda: mR.add_hline(100, [nb - 1]))         # the bay that closes the loop
    r = sR.apply(mR)
    assert not _bad(r), r.warnings
    assert sR.model.nbays == nb and any(h.bays == {nb - 1} for h in sR.model.hlines), sR.model.hlines
    say("closed: {} bays, last-bay transom kept".format(nb))

    # -- unitized: stack joints are full-width lines that move ------------------------------------------
    drvU = _wall(doc, G.LineCurve(G.Point3d(0, _ft(doc, 50), 0), G.Point3d(_ft(doc, 20), _ft(doc, 50), 0)),
                 UNIT, stack=[72])
    sU = gridio.Session(doc, drvU, lib)
    mU = sU.model
    st = [i for i, h in enumerate(mU.hlines) if h.kind == "stack"]
    assert mU.has_stack and len(st) == 1, mU.hlines
    try:
        mU.split_hline(st[0], 0)
        assert False
    except ge.EditRefused:
        pass
    mU.move_hline(st[0], 80)
    sU.apply(mU)
    assert meta.params(doc.Objects.FindId(drvU.Id))["stack"] == [80.0]
    say("unitized: stack joint moved")

    # -- detail LOD timing (live editing feel) ------------------------------------------------------------
    engine.update_params(doc, doc.Objects.FindId(drv.Id), {"lod": "detail"}, lib)
    sD = gridio.Session(doc, doc.Objects.FindId(drv.Id), lib)
    t0 = time.time()
    sD.model.move_vertical(1, 54)
    r = sD.apply()
    say("detail: apply after a drag {:.2f} s ({} parts)".format(time.time() - t0, len(r.part_ids)))

    # -- the window ------------------------------------------------------------------------------------------
    from mindcanvas.eto import cwgrid
    ed = cwgrid.open_editor(doc, doc.Objects.FindId(drv.Id), lib)
    try:
        lines = cwgrid.preview_lines(ed.session, ed.ctl)
        assert len(lines) >= len(ed.ctl.m.verts)
        ed.ctl.sel = ("vertical", 1)
        ed.refresh()
        assert ed.lb_title.Text == "Grid line"
        ed._commit("prev", "5'")
        assert _close(ed.ctl.m.verts[1].u, 60)
        ed.rb_tool.SelectedIndex = 4
        assert ed.ctl.tool == "paint"
        ed.dd_view.SelectedIndex = 1
        assert ed.ctl.view == "interior"
        ed.dd_view.SelectedIndex = 0
        ed.apply()
        assert ed.applied == ed.ctl.version
    finally:
        ed.close()
    assert not cwgrid._OPEN
    say("test_cwgrid: OK in {:.1f} s".format(time.time() - t_all))
    return True


def _built_sag(ses):
    """Largest distance (inches) from the driver curve to a built bay chord, at mid-bay."""
    g, s = ses.ctx.grid, ses.ctx.s
    out = 0.0
    for b in g.bays:
        u0 = g.vertices[b.index].u
        u1 = g.vertices[b.index + 1].u if b.index + 1 < len(g.vertices) else g.length
        out = max(out, abs(b.local(g.point_at_u(0.5 * (u0 + u1)))[1]) / s)
    return out


def _curved(doc, lib, captures):
    """Curved walls: the editor's panel widths / deviation match the built facets; a removed line
    is flagged, Fit curve brings every panel back within the limit; doors in curved bays."""
    single = "Door - Aluminum Entrance, Full Lite"
    ft = lambda v: _ft(doc, v)
    pc = G.PolyCurve()
    pc.Append(G.LineCurve(G.Point3d(ft(70), 0, 0), G.Point3d(ft(80), 0, 0)))
    pc.Append(G.ArcCurve(G.Arc(G.Point3d(ft(80), 0, 0), G.Vector3d(1, 0, 0), G.Point3d(ft(90), ft(10), 0))))
    curves = [
        ("arc", G.ArcCurve(G.Arc(G.Point3d(0, ft(70), 0), G.Point3d(ft(15), ft(78), 0), G.Point3d(ft(30), ft(70), 0)))),
        ("circle", G.ArcCurve(G.Circle(G.Point3d(ft(50), ft(80), 0), ft(12)))),
        ("spline", G.Curve.CreateInterpolatedCurve([G.Point3d(0, ft(100), 0), G.Point3d(ft(10), ft(106), 0),
                                                    G.Point3d(ft(20), ft(98), 0), G.Point3d(ft(30), ft(104), 0)], 3)),
        ("line+arc", pc),
    ]
    for name, crv in curves:
        drv = _wall(doc, crv, transoms=[30])
        ses = gridio.Session(doc, drv, lib)
        m = ses.model
        assert m.curved, name
        # the model's panels are the built facets
        g = ses.ctx.grid
        for b in g.bays:
            assert abs(m.chord(b.index) - b.c / ses.ctx.s) < 1e-3, (name, b.index, m.chord(b.index), b.c)
        assert abs(max(m.deviation(b) for b in range(m.nbays)) - _built_sag(ses)) < 0.05, name
        c = ge.GridController(m, 1100, 480, ses.door_info)
        free = [i for i, v in enumerate(m.verts) if not v.locked]
        c.edit(lambda: m.remove_vertical(free[len(free) // 2]))
        c.edit(lambda: m.remove_vertical(free[len(free) // 2]))
        bad = m.over_limit()
        assert bad and "Fit curve" in c.status, (name, bad, c.status)
        if captures and name == "circle":
            say("capture", cwgridview_png(c, "cwgrid_curved_editor.png"))
        d = bad[0]
        c.edit(lambda: m.add_door(d, 0, single, ses.door_info(single)["head"]))
        n = c.edit(lambda: m.fit_curves())
        assert n and not m.over_limit(), (name, n, m.over_limit())
        r = ses.apply(m)
        assert not _bad(r), (name, r.warnings)
        built = _built_sag(ses)
        assert built <= m.max_dev + 0.05, (name, built)
        assert len(ses.model.doors) == 1 and _roles(doc, drv.Id)["leaf"] == 1, name
        # the door's frame sits on its bay's chord (flat), within the bay
        op = [o for o in ses.ctx.openings if o.door][0]
        bay = g_bay = ses.ctx.grid.bays[ses.ctx.grid.cell_at(op.plane.Origin)[0]]
        u, y = g_bay.local(op.plane.Origin)
        assert 0 < u < bay.c and abs(op.plane.XAxis * bay.X - 1.0) < 1e-6, (name, u, bay.c)
        say("curved {}: {} bays, panels within {} of the curve (built {:.2f}\"), door in bay {}".format(
            name, ses.model.nbays, ge.fmt(m.max_dev), built, list(ses.model.doors)[0] + 1))
    # a flipped arc keeps its grid lines (stations along the curve as drawn)
    arc = [d for d in meta.all_drivers(doc, "curtain_wall") if isinstance(d.Geometry, G.ArcCurve)
           and not d.Geometry.IsClosed][0]
    ses = gridio.Session(doc, arc, lib)
    before = sorted((round(v.P.X, 3), round(v.P.Y, 3)) for v in ses.ctx.grid.vertices)
    engine.update_params(doc, doc.Objects.FindId(arc.Id), {"flip": True}, lib)
    ses.reload()
    after = sorted((round(v.P.X, 3), round(v.P.Y, 3)) for v in ses.ctx.grid.vertices)
    assert before == after, (before, after)
    assert len(ses.model.doors) == 1
    engine.update_params(doc, doc.Objects.FindId(arc.Id), {"flip": False}, lib)
    if captures:
        _capture_top(doc, [d for d in meta.all_drivers(doc, "curtain_wall") if d.Geometry.IsClosed
                           and isinstance(d.Geometry, G.ArcCurve)][0], "cwgrid_curved_plan.png")


def cwgridview_png(ctl, name):
    from mindcanvas.eto import cwgridview
    os.makedirs(CAPTURES, exist_ok=True)
    return cwgridview.render_png(ctl, os.path.join(CAPTURES, name))


def _capture_top(doc, drv, name):
    import System
    v = doc.Views.Find("Top", False) or doc.Views.ActiveView
    vp = v.ActiveViewport
    vp.DisplayMode = Rhino.Display.DisplayModeDescription.FindByName("Shaded")
    bb = drv.Geometry.GetBoundingBox(True)
    bb.Inflate(_ft(doc, 1.5))
    vp.ZoomBoundingBox(bb)
    v.Redraw()
    path = os.path.join(CAPTURES, name)
    v.CaptureToBitmap(System.Drawing.Size(700, 700)).Save(path, System.Drawing.Imaging.ImageFormat.Png)
    say("capture", path)


def _capture_wall(doc, drv):
    import System
    v = doc.Views.Find("Perspective", False) or doc.Views.ActiveView
    vp = v.ActiveViewport
    vp.DisplayMode = Rhino.Display.DisplayModeDescription.FindByName("Shaded")
    vp.SetCameraLocations(G.Point3d(_ft(doc, 15), 0, _ft(doc, 5)), G.Point3d(_ft(doc, 9), _ft(doc, 30), _ft(doc, 7)))
    v.Redraw()
    bmp = v.CaptureToBitmap(System.Drawing.Size(1100, 520))
    path = os.path.join(CAPTURES, "cwgrid_wall.png")
    bmp.Save(path, System.Drawing.Imaging.ImageFormat.Png)
    say("capture", path)
