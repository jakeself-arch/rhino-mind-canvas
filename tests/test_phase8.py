"""Phase 8: UI + entourage (Eto panel, assembly editor, profile capture, line-drawn entourage).

Run inside Rhino (e.g. via the MCP run_python tool), in an EMPTY, unsaved document (it is cleared):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_phase8.py")["run"](__rhino_doc__, log=ROOT + r"\\phase8.log")

Covers: every library figure (people, trees, shrubs) generates at its height, becomes a block of
planar cards + line curves, shares blocks per shape, varies by seed, mirrors, turns to face a
view; figures draw as class "entourage" lines and hide what is behind them (and are hidden by
walls in front of them); capture of a figure and of a profile with a hole from curves; trims
(sweep component) on a polyline wall with a door (mitered, cut at the door, takeoff length), with
a captured profile, and removed again; the gable-wall gypsum stopping at an attic ceiling (Phase 7
open item); the assembly editor model (fields, add / duplicate / move / mirror / core / options /
settings JSON, save as, apply); the Eto assembly editor and the Mind Canvas panel driven through
their handlers (no clicks); every command module imports. Library files the test writes
(zz_test_phase8.json, zz_user_assemblies.json entries) are removed again.
drawing_on=True writes g_section_perspective_quarter, g_entourage_sheet_quarter,
g_trim_base_1-1-2 and g_trim_crown_1-1-2 to docs/drawings/.
"""

import importlib
import json
import math
import os
import runpy
import shutil
import tempfile
import time
from collections import Counter

import Rhino

from mindcanvas import asmedit, capture, docutil, engine, library, meta, profiles, trims, units
from mindcanvas.drawing import tags
from mindcanvas.entourage import place, shapes

G = Rhino.Geometry
D = Rhino.DocObjects
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "drawings")
LOG = [None]
TEST_FILE = "zz_test_phase8.json"
TEST_ASM = "Test Phase8 - Wall"
TEST_ASM2 = "Test Phase8 - Wall (Eto)"

WOOD = "Ext - 2x6 Wood, Fiber Cement"
R_ATTIC = "Roof - Asphalt Shingle / 2x8 Rafters, Vented Attic"
PLATE = 109.0


def say(*a):
    msg = " ".join(str(x) for x in a)
    print(msg)
    if LOG[0]:
        with open(LOG[0], "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def _ft(doc, v):
    return units.to_model(doc, v * 12.0)


def _add(doc, crv):
    return doc.Objects.FindId(doc.Objects.AddCurve(crv))


def _pl(doc, *pts_ft):
    f = lambda v: _ft(doc, v)
    return G.PolylineCurve([G.Point3d(f(x), f(y), 0) for x, y in pts_ft])


def _wall(doc, lib, asm, *pts, **prm):
    prm.setdefault("height", PLATE)
    prm.setdefault("reference", "interior_face")
    r = engine.create(doc, _add(doc, _pl(doc, *pts)), asm, prm, lib)
    assert not _bad(r), r.warnings
    return r


def _bad(r):
    return [w for w in r.warnings if "fail" in w.lower() or "could not" in w.lower() or "unknown" in w.lower()]


def roles(doc, drv_id):
    return Counter(meta.get(o, meta.ROLE) for o in meta.parts_of(doc, drv_id))


def _top_z(doc, drv_id, layer):
    zs = [o.Geometry.GetBoundingBox(True).Max.Z for o in meta.parts_of(doc, drv_id)
          if meta.get(o, meta.LAYER) == layer and not isinstance(o, D.InstanceObject)]
    return max(zs) / units.inch_scale(doc) if zs else None


def _view(doc, name):
    v = [x for x in doc.Views if x.ActiveViewport.Name == name][0]
    v.Maximized = True
    doc.Views.ActiveView = v
    return v


def _front(doc, target):
    """The Front view, reset to look along +y (section cuts of earlier runs turn it)."""
    v = _view(doc, "Front")
    vp = v.ActiveViewport
    vp.ChangeToParallelProjection(True)
    vp.SetCameraLocations(target, target - G.Vector3d(0, units.to_model(doc, 1200.0), 0))
    vp.CameraUp = G.Vector3d.ZAxis
    return v


def _clear_clips(doc):
    for o in list(doc.Objects.FindByObjectType(D.ObjectType.ClipPlane) or []):
        doc.Objects.Delete(o, True)


def _def_geoms(obj):
    return [o.Geometry for o in obj.InstanceDefinition.GetObjects()]


# -- entourage ------------------------------------------------------------------------------------
def entourage_shapes(lib):
    names = place.names(lib)
    assert len(names) >= 12, names
    gens = Counter(place.definition(lib, n).get("generator") for n in names)
    assert gens["person"] >= 5 and gens["tree"] >= 4 and gens["shrub"] >= 2, gens
    for n in names:
        d = place.definition(lib, n)
        layers = place.layers_for(lib, n)
        c = shapes.count(layers)
        assert c["loops"] >= 1, (n, c)
        x0, y0, x1, y1 = shapes.bounds(layers)
        H = units.parse_length(d.get("height", 0))
        assert y0 > -1.0, (n, y0)
        if d["generator"] == "person":
            assert abs(y1 - H) < 2.0, (n, y1, H)
        elif d["generator"] == "tree":
            assert abs(y1 - H) / H < 0.08, (n, y1, H)
            assert c["lines"] >= 4, (n, c)
        else:
            assert 0.9 * H < y1 < 1.35 * H, (n, y1, H)
        for ly in layers:
            for lp in ly.loops:
                assert len(lp) >= 3
    # seeds: same seed -> same shape, another seed -> another tree
    a = place.layers_for(lib, "Tree - Bare, 18 ft", seed=11)
    b = place.layers_for(lib, "Tree - Bare, 18 ft", seed=11)
    c = place.layers_for(lib, "Tree - Bare, 18 ft", seed=12)
    assert place._tag("t", a) == place._tag("t", b) and place._tag("t", a) != place._tag("t", c)
    # overrides: height scales a person
    tall = place.layers_for(lib, "Person - Standing, Suit", height=80)
    assert abs(shapes.bounds(tall)[3] - 80) < 2.0
    say("  {} figures generate ({})".format(len(names), dict(gens)))
    return names


def entourage_place(doc, lib, names, x0=-200.0, y0=-600.0):
    f = lambda v: _ft(doc, v)
    s = units.inch_scale(doc)
    objs = []
    x = x0
    for n in names:
        bx = shapes.bounds(place.layers_for(lib, n))
        x += -bx[0] / 12.0
        o = place.place(doc, lib, n, G.Point3d(f(x), f(y0), 0))
        objs.append(o)
        geoms = _def_geoms(o)
        breps = [g for g in geoms if isinstance(g, G.Brep)]
        crvs = [g for g in geoms if isinstance(g, G.Curve)]
        layers = place.layers_for(lib, n)
        assert breps, n
        assert len(crvs) == shapes.count(layers)["lines"], (n, len(crvs), shapes.count(layers))
        for b in breps:
            assert all(fc.IsPlanar(doc.ModelAbsoluteTolerance) for fc in b.Faces), n
        bb = o.Geometry.GetBoundingBox(True)
        assert abs(bb.Min.Z) < s * 1.0, (n, bb.Min.Z)
        assert place.is_entourage(o) and meta.get(o, place.NAME) == n
        assert "notone" in tags.flags(doc, o) and "nocut" in tags.flags(doc, o)
        x += bx[2] / 12.0 + 3
    # identical figures share a block
    o2 = place.place(doc, lib, names[0], G.Point3d(f(x0), f(y0 - 15), 0))
    assert o2.InstanceDefinition.Index == objs[0].InstanceDefinition.Index
    # face the Perspective camera, from any start angle
    v = [vv for vv in doc.Views if vv.ActiveViewport.Name == "Perspective"][0]
    vp = v.ActiveViewport
    vp.ChangeToPerspectiveProjection(True, 35)
    vp.SetCameraLocations(G.Point3d(f(x0 + 20), f(y0), f(5)), G.Point3d(f(x0 - 30), f(y0 - 80), f(12)))
    n = place.face_view(doc, [doc.Objects.FindId(o.Id) for o in objs], vp)
    assert n == len(objs)
    for o in objs:
        o = doc.Objects.FindId(o.Id)
        d = vp.CameraLocation - place.origin(o)
        d.Z = 0
        d.Unitize()
        assert place.facing(o) * d > 0.999, (meta.get(o, place.NAME), place.facing(o), d)
    # mirror + reseed keep the place, change the block
    o = doc.Objects.FindId(objs[-1].Id)
    p0 = place.origin(o)
    new = place.rebuild(doc, lib, o, seed=99, mirror=True)
    assert place.origin(new).DistanceTo(p0) < s * 0.01
    assert meta.params(new)["mirror"] is True and meta.params(new)["seed"] == 99
    assert new.InstanceXform.Determinant < 0, "mirrored figure should have a mirrored transform"
    doc.Objects.Delete(o2, True)
    say("  placed {} figures, FaceView / share / mirror / reseed OK".format(len(objs)))
    return [doc.Objects.FindId(o.Id) for o in objs[:-1]] + [new]


def entourage_hiding(doc, lib, x0=-500.0, y0=-160.0):
    """A figure behind a wall is hidden; one in front hides the wall's lines."""
    from mindcanvas.drawing import pipeline, styles
    f = lambda v: _ft(doc, v)
    w = _wall(doc, lib, WOOD, (x0 - 10, y0), (x0 + 10, y0), height=96, lod="schematic")
    st = styles.get("1/4", lib)
    view = _front(doc, G.Point3d(f(x0), f(y0), f(4)))
    _clear_clips(doc)
    box = G.BoundingBox(G.Point3d(f(x0 - 12), f(y0 - 30), f(-1)), G.Point3d(f(x0 + 12), f(y0 + 30), f(10)))

    def count():
        view.ActiveViewport.ZoomBoundingBox(box)
        doc.Views.Redraw()
        dwg = pipeline.make(doc, view, st, False, False, window=[box.Min, box.Max])
        return Counter(c for _, c, _ in dwg.lines)

    base = count()
    # the Front view looks along +y: y > the wall is behind it
    behind = place.place(doc, lib, "Person - Standing, Suit", G.Point3d(f(x0), f(y0 + 5), 0))
    c_behind = count()
    assert c_behind["entourage"] == 0, c_behind
    doc.Objects.Delete(behind, True)
    front = place.place(doc, lib, "Person - Standing, Suit", G.Point3d(f(x0), f(y0 - 5), 0))
    place.face_view(doc, [front], view.ActiveViewport)
    c_front = count()
    assert c_front["entourage"] >= 10, c_front
    say("  hiding: behind the wall {} entourage lines, in front {} (wall lines {} -> {})".format(
        c_behind["entourage"], c_front["entourage"], base["silhouette"] + base["edge"],
        c_front["silhouette"] + c_front["edge"]))
    doc.Objects.Delete(front, True)
    engine.delete_parts(doc, w.driver_id)
    doc.Objects.Delete(w.driver_id, True)


# -- capture --------------------------------------------------------------------------------------
def capture_figure(doc, lib):
    s = units.inch_scale(doc)
    front = G.Plane(G.Point3d(0, 0, 0), G.Vector3d.XAxis, G.Vector3d.ZAxis)
    P = lambda x, z: G.Point3d(x * s + 1000 * s, 0, z * s)
    outline = G.PolylineCurve([P(-6, 0), P(6, 0), P(4, 30), P(-4, 30), P(-6, 0)])
    head = G.ArcCurve(G.Circle(G.Plane(P(0, 36), G.Vector3d.XAxis, G.Vector3d.ZAxis), 5 * s))
    line = G.LineCurve(P(-3, 15), P(3, 15))
    d = capture.entourage_definition(doc, [outline, head, line], front, P(0, 0))
    assert len(d["loops"]) == 2 and len(d["lines"]) == 1, d
    assert abs(min(p[1] for p in d["loops"][0] + d["loops"][1])) < 1e-6
    assert abs(max(p[1] for lp in d["loops"] for p in lp) - 41) < 0.05
    lib.save_entry("entourage", "Test - Captured Figure", d, TEST_FILE)
    assert "Test - Captured Figure" in place.names(lib)
    o = place.place(doc, lib, "Test - Captured Figure", G.Point3d(-150 * 12 * s, -200 * 12 * s, 0))
    geoms = _def_geoms(o)
    assert sum(1 for g in geoms if isinstance(g, G.Brep)) >= 1 and sum(1 for g in geoms if isinstance(g, G.Curve)) == 1
    doc.Objects.Delete(o, True)
    say("  captured figure: {} loops, {} line".format(len(d["loops"]), len(d["lines"])))


def capture_profile(doc, lib):
    s = units.inch_scale(doc)
    P = lambda x, y: G.Point3d(x * s + 500 * s, y * s + 500 * s, 0)
    outer = G.PolylineCurve([P(0, 0), P(1, 0), P(1, 4), P(0.6, 4.5), P(0, 4.5), P(0, 0)])
    hole = G.ArcCurve(G.Circle(G.Plane(P(0.5, 2), G.Vector3d.ZAxis), 0.25 * s))
    d = capture.profile_definition(doc, [hole, outer], G.Plane.WorldXY, P(0, 0), family="trim", material="Wood Trim")
    assert len(d["loops"]) == 2, d
    assert d["loops"][0][0] == [0.0, 0.0], d["loops"][0][:2]
    loops = profiles.build(d, 1.0)
    assert len(loops) == 2
    w, h = profiles.size(d)
    assert abs(w - 1) < 1e-3 and abs(h - 4.5) < 1e-3, (w, h)
    lib.save_entry("profiles", "Test - Captured Trim", d, TEST_FILE)
    assert "Test - Captured Trim" in trims.profiles(lib)
    say("  captured profile: 2 loops, {:.3f} x {:.3f} in".format(w, h))
    return "Test - Captured Trim"


# -- trims ----------------------------------------------------------------------------------------
def trim_walls(doc, lib, captured, x0=0.0, y0=-260.0):
    f = lambda v: _ft(doc, v)
    s = units.inch_scale(doc)
    r = _wall(doc, lib, WOOD, (x0, y0), (x0, y0 + 12), (x0 + 16, y0 + 12), height=96)
    drv = doc.Objects.FindId(r.driver_id)
    op, rr = engine.add_opening(doc, drv, "Door - Wood Flush", {"station": 60}, None, lib)
    assert not _bad(rr), rr.warnings
    for prof, face, z in (("Trim - Base 3-1/2", "interior", "base"), ("Trim - Crown 3-5/8", "interior", "top"),
                          ("Trim - Water Table 6", "exterior", "base"), ("Trim - Chair Rail 2-1/2", "interior", 34)):
        rr = trims.add(doc, doc.Objects.FindId(r.driver_id), lib, prof, face, z)
        assert not _bad(rr), rr.warnings
    drv = doc.Objects.FindId(r.driver_id)
    assert len(trims.trims(drv)) == 4
    parts = [o for o in meta.parts_of(doc, r.driver_id) if meta.get(o, meta.ROLE) == "trim"]
    by = Counter(meta.get(o, meta.LAYER) for o in parts)
    assert by["Trim: Trim - Base 3-1/2 (interior, base)"] == 2, by        # cut at the door
    assert by["Trim: Trim - Crown 3-5/8 (interior, top)"] == 1, by
    assert by["Trim: Trim - Water Table 6 (exterior, base)"] == 2, by
    assert by['Trim: Trim - Chair Rail 2-1/2 (interior, 34")'] == 2, by    # the door is 6'-8" high
    for o in parts:
        assert o.Geometry.IsSolid, meta.get(o, meta.LAYER)
    # the base runs along the interior face: 12' + 16' less the wall thickness at the inside corner, less the door
    base_len = sum(float(o.Attributes.GetUserString("mc.x.length") or 0) for o in parts
                   if meta.get(o, meta.LAYER).startswith("Trim: Trim - Base"))
    assert 200 < base_len < 336 - 30, base_len
    # crown sits under the wall top, base on the floor
    crown = [o for o in parts if "Crown" in meta.get(o, meta.LAYER)][0].Geometry.GetBoundingBox(True)
    assert abs(crown.Max.Z / s - 96) < 0.01 and abs(crown.Min.Z / s - (96 - 3.625)) < 0.01, crown
    # a captured profile with a hole: volume = (outline - hole) x length
    rr = trims.add(doc, doc.Objects.FindId(r.driver_id), lib, captured, "interior", 86)    # between the 7' door head and the crown
    assert not _bad(rr), rr.warnings
    cap = [o for o in meta.parts_of(doc, r.driver_id) if captured in (meta.get(o, meta.LAYER) or "")]
    assert len(cap) == 1 and cap[0].Geometry.IsSolid, len(cap)
    vol = G.VolumeMassProperties.Compute(cap[0].Geometry).Volume / s ** 3
    L = float(cap[0].Attributes.GetUserString("mc.x.length"))
    area = 1 * 4 + 0.5 * (1 + 0.6) * 0.5 - math.pi * 0.25 ** 2
    assert abs(vol / L - area) / area < 0.05, (vol / L, area)
    rr = trims.remove(doc, doc.Objects.FindId(r.driver_id), lib, captured)
    assert rr is not None and len(trims.trims(doc.Objects.FindId(r.driver_id))) == 4
    say("  trims: base / crown / water table / chair rail + captured, cut at the door, base {:.1f}\"".format(base_len))
    return r.driver_id


# -- Phase 7 open item: gable gypsum --------------------------------------------------------------
def gable_gypsum(doc, lib, x0=60.0, y0=-260.0):
    W, Dp = 24.0, 16.0
    pts = [(x0, y0), (x0, y0 + Dp), (x0 + W, y0 + Dp), (x0 + W, y0), (x0, y0)]
    walls = [_wall(doc, lib, WOOD, pts[i], pts[i + 1], reference="core_exterior") for i in range(4)]
    r = engine.create(doc, _add(doc, _pl(doc, *pts)), R_ATTIC, {"base_offset": PLATE}, lib)
    assert not _bad(r), r.warnings
    gables = [w for w in walls if roles(doc, w.driver_id)["gable_stud"] > 0]
    assert len(gables) == 2
    for g in gables:
        gyp = _top_z(doc, g.driver_id, "Gypsum")
        sheath = _top_z(doc, g.driver_id, "Sheathing")
        assert gyp <= PLATE + 0.01, "gable gypsum runs into the attic ({:.2f})".format(gyp)
        assert sheath > PLATE + 24, sheath
    say("  gable walls: gypsum stops at {:.2f}\", sheathing up to {:.1f}\"".format(gyp, sheath))
    return r.driver_id, walls


# -- assembly editor ------------------------------------------------------------------------------
def editor_model(doc, lib, wall_id):
    m = asmedit.AssemblyModel(lib, WOOD)
    n = len(m.layers)
    assert m.has_layers and n >= 4 and m.kind == "wall"
    gyp = n - 1
    assert m.field(gyp, "material") == "Gypsum Board", m.field(gyp, "material")
    m.set_field(gyp, "thickness", "1/2")
    assert m.field(gyp, "thickness") == "1/2"
    m.set_field(gyp, "material", "Plywood Sheathing")
    m.set_field(gyp, "name", "Plywood Liner")
    i = m.add(None, {"name": "Gypsum", "component": "solid", "material": "Gypsum Board", "thickness": "5/8"})
    assert len(m.layers) == n + 1 and i == n
    j = m.duplicate(i)
    assert len(m.layers) == n + 2 and m.field(j, "name") != m.field(i, "name")
    m.remove(j)
    k = m.move(i, -1)
    assert m.field(k, "name") == "Gypsum"
    m.move(k, 1)
    rows = m.rows()
    m.mirror()
    assert m.rows()[0].split(".", 1)[1] == rows[-1].split(".", 1)[1]
    m.mirror()
    core = [x for x in range(len(m.layers)) if m.field(x, "core")]
    assert len(core) == 1
    m.set_field(0, "core", True)
    assert [x for x in range(len(m.layers)) if m.field(x, "core")] == [0]
    m.set_field(core[0], "core", True)
    try:
        m.set_field(0, "options", "{not json")
        raise AssertionError("bad JSON accepted")
    except asmedit.EditError:
        pass
    m.set_field(core[0], "options", json.dumps(dict(json.loads(m.field(core[0], "options")), spacing=24)))
    assert json.loads(m.field(core[0], "options"))["spacing"] == 24
    try:
        m.set_settings_json(json.dumps({"kind": "floor"}))
        raise AssertionError("kind change accepted")
    except asmedit.EditError:
        pass
    st = json.loads(m.settings_json())
    st["default_height"] = "9'"
    m.set_settings_json(json.dumps(st))
    assert m.data["default_height"] == "9'" and len(m.layers) == n + 1
    assert not m.problems(), m.problems()
    try:
        m.save_as(WOOD)
        raise AssertionError("library assembly overwritten")
    except asmedit.EditError:
        pass
    try:
        m.apply(doc, [])
        raise AssertionError("apply before save")
    except asmedit.EditError:
        pass
    path = m.save_as(TEST_ASM)
    assert lib.assembly(TEST_ASM)["based_on"] == WOOD and os.path.basename(path) == library.USER_ASSEMBLIES
    res = m.apply(doc, [doc.Objects.FindId(wall_id)])
    assert len(res) == 1 and not _bad(res[0]), res[0].warnings
    drv = doc.Objects.FindId(wall_id)
    assert meta.get(drv, meta.ASSEMBLY) == TEST_ASM
    layers = Counter(meta.get(o, meta.LAYER) for o in meta.parts_of(doc, wall_id))
    assert layers["Plywood Liner"] >= 1 and layers["Gypsum"] >= 1, layers
    # curtain walls: no layers, settings only
    cw = asmedit.AssemblyModel(lib, lib.assemblies("curtain_wall")[0])
    assert not cw.has_layers and "style" in json.loads(cw.settings_json())
    say("  assembly editor model: fields, stack edits, core, options, settings, save as, apply OK")


def editor_eto(doc, lib, wall_id):
    from mindcanvas.eto import editor
    ed = editor.AssemblyEditor(doc, lib, name=WOOD)
    m = ed.model
    sh = [i for i in range(len(m.layers)) if m.field(i, "name") == "Sheathing"][0]
    ed.lb_layers.SelectedIndex = sh
    assert ed.index == sh and ed.tb_thick.Text == "7/16", ed.tb_thick.Text
    ed.tb_thick.Text = "3/4"
    ed.on_fields()
    assert m.field(sh, "thickness") == "3/4" and m.dirty
    ed.cb_mat.Text = "Plywood Sheathing"
    ed.on_fields()
    assert m.field(sh, "material") == "Plywood Sheathing"
    ed.ta_opts.Text = "{bad"
    ed.on_fields()
    assert "JSON" in ed.lb_status.Text, ed.lb_status.Text
    ed.ta_opts.Text = m.field(sh, "options")
    n = len(m.layers)
    ed.on_add()
    assert len(m.layers) == n + 1
    ed.on_remove()
    ed.on_move(1)
    ed.on_move(-1)
    ed.tb_save.Text = TEST_ASM2
    ed.on_save()
    assert TEST_ASM2 in lib.data["assemblies"], ed.lb_status.Text
    doc.Objects.UnselectAll()
    doc.Objects.Select(wall_id)
    ed.on_apply()
    assert meta.get(doc.Objects.FindId(wall_id), meta.ASSEMBLY) == TEST_ASM2, ed.lb_status.Text
    doc.Objects.UnselectAll()
    ed.dd_kind.SelectedIndex = editor.KINDS.index("curtain_wall")
    assert ed.model.kind == "curtain_wall" and not ed.model.has_layers and "style" in ed.ta_settings.Text
    ed.dd_kind.SelectedIndex = editor.KINDS.index("roof")
    assert ed.model.kind == "roof" and ed.model.has_layers
    ed.show()
    ed.close()
    say("  Eto assembly editor: field edits, bad JSON, add / remove / move, save, apply, kinds OK")


def panel_eto(doc, lib, wall_id, figures):
    from mindcanvas.eto import panel
    p = panel.MindCanvasPanel(doc, lib)
    doc.Objects.UnselectAll()
    p.refresh_selection()
    assert "Nothing selected" in p.lb_sel.Text
    assert p.apply_selection() == []
    doc.Objects.Select(wall_id)
    p.refresh_selection()
    assert p.lb_sel.Text.startswith("1 selected"), p.lb_sel.Text
    p.tb_height.Text = "8'-6\""
    p.dd_lod.SelectedIndex = 1 + panel.LODS.index("design")
    res = p.apply_selection()
    assert len(res) == 1
    prm = meta.params(doc.Objects.FindId(wall_id))
    assert abs(prm["height"] - 102) < 1e-6 and prm["lod"] == "design", prm
    doc.Objects.UnselectAll()
    # drawing tab: draw the active view into a temporary folder
    tmp = tempfile.mkdtemp(prefix="mc_phase8_")
    try:
        p.tb_folder.Text = tmp
        p.ck_tone.Checked = False
        p.ck_stip.Checked = False
        p.ck_lod.Checked = False
        view = _view(doc, "Top")
        bb = doc.Objects.FindId(wall_id).Geometry.GetBoundingBox(True)
        bb.Inflate(units.inch_scale(doc) * 24)
        view.ActiveViewport.ZoomBoundingBox(bb)
        doc.Views.Redraw()
        paths = p.draw_now(view)
        assert paths and all(os.path.exists(x) for x in paths), (paths, p.status.Text)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # entourage tab
    names = place.names(lib)
    p.lb_ent.SelectedIndex = names.index("Person - Walking, Coat")
    p.tb_ent_h.Text = "5'-2\""
    st = p._ent_settings()
    assert st["name"] == "Person - Walking, Coat" and abs(st["height"] - 62) < 1e-6
    v = _view(doc, "Perspective")
    assert p.face_view() == len(place.all_figures(doc))
    # library tab, build buttons -> command scripts
    p.reload_library()
    assert "figures" in p.lb_lib.Text
    for label, cmd in panel.BUILD:
        assert os.path.exists(os.path.join(ROOT, "commands", cmd + ".py")), cmd
    p.show()
    p.close()
    say("  Eto panel: selection apply, draw now, entourage, library OK")


def commands_import():
    for name in ("entourage", "trim", "profilecapture", "assemblyeditor", "panel"):
        mod = importlib.import_module("mindcanvas.cmd." + name)
        assert hasattr(mod, "run"), name
        assert os.path.exists(os.path.join(ROOT, "commands", "MC{}.py".format(
            {"entourage": "Entourage", "trim": "Trim", "profilecapture": "ProfileCapture",
             "assemblyeditor": "AssemblyEditor", "panel": "Panel"}[name])))


# -- drawings -------------------------------------------------------------------------------------
def section_perspective(doc, lib):
    """A small gable house cut across its ridge, people inside and out, trees behind, ground stippled."""
    from mindcanvas.drawing import displaymode, pipeline, sectionstyle, styles
    f = lambda v: _ft(doc, v)
    x0, y0 = 400.0, 0.0
    W, Dp = 30.0, 20.0
    pts = [(x0, y0), (x0, y0 + Dp), (x0 + W, y0 + Dp), (x0 + W, y0), (x0, y0)]
    for i in range(4):
        _wall(doc, lib, WOOD, pts[i], pts[i + 1], reference="core_exterior", lod="design")
    r = engine.create(doc, _add(doc, _pl(doc, *pts)), R_ATTIC, {"base_offset": PLATE, "lod": "design"}, lib)
    assert not _bad(r), r.warnings
    conc = docutil.ensure_material_layer(doc, lib, "Concrete")
    a = D.ObjectAttributes()
    a.LayerIndex = conc
    a.SetUserString(meta.MATERIAL, "Concrete")
    doc.Objects.AddBrep(G.Box(G.Plane.WorldXY, G.Interval(f(x0), f(x0 + W)), G.Interval(f(y0), f(y0 + Dp)),
                              G.Interval(f(-0.5), 0)).ToBrep(), a)
    outer = G.Rectangle3d(G.Plane(G.Point3d(0, 0, f(-0.5)), G.Vector3d.ZAxis), G.Interval(f(x0 - 40), f(x0 + W + 60)),
                          G.Interval(f(y0 - 40), f(y0 + Dp + 40))).ToNurbsCurve()
    hole = G.Rectangle3d(G.Plane(G.Point3d(0, 0, f(-0.5)), G.Vector3d.ZAxis), G.Interval(f(x0 - 0.5), f(x0 + W + 0.5)),
                         G.Interval(f(y0 - 0.5), f(y0 + Dp + 0.5))).ToNurbsCurve()
    ground = G.Brep.CreatePlanarBreps([outer, hole], doc.ModelAbsoluteTolerance)[0]
    gid = doc.Objects.AddBrep(ground)
    tags.set_flags(doc, doc.Objects.FindId(gid), add=["ground"])
    figs = []
    # cut across the ridge at x0 + 15 (keeps x > the cut), looking +x from the street
    for n, x, y in (("Person - Standing, Suit", 19, 6), ("Person - Standing, Dress", 21.5, 9),
                    ("Person - Walking, Coat", 23, 13.5), ("Person - Child", 20.5, 16),
                    ("Person - Walking, Suit", 19, -7), ("Person - Standing, Coat", 24, 27),
                    ("Shrub - 3 ft", 22, -3), ("Shrub - 2 ft Hedge", 30, 24),
                    ("Tree - Canopy, 28 ft", 34, -14), ("Tree - Bare, 30 ft", 40, 32),
                    ("Tree - Conifer, 24 ft", 60, 10)):
        outside = not (0 < x < W and 0 < y < Dp)
        figs.append(place.place(doc, lib, n, G.Point3d(f(x0 + x), f(y0 + y), f(-0.5) if outside else 0), seed=7))
    st = styles.get("1/4", lib)
    view = _view(doc, "Perspective")
    vp = view.ActiveViewport
    _clear_clips(doc)
    plane = G.Plane(G.Point3d(f(x0 + W / 2), f(y0 + Dp / 2), f(8)), G.Vector3d.XAxis)
    cid = doc.Objects.AddClippingPlane(plane, f(200), f(80), [vp.Id])
    ca = doc.Objects.FindId(cid).Attributes.Duplicate()
    ca.SetUserString(pipeline.CLIP_KEY, "cut")
    doc.Objects.ModifyAttributes(cid, ca, True)
    vp.ChangeToPerspectiveProjection(True, 30.0)
    vp.SetCameraLocations(G.Point3d(f(x0 + W / 2 + 10), f(y0 + Dp / 2 + 1), f(9)), G.Point3d(f(x0 - 30), f(y0 + Dp / 2 - 3), f(10)))
    doc.Views.ActiveView = view
    displaymode.assign(view)
    sectionstyle.apply(doc, st)
    place.face_view(doc, [doc.Objects.FindId(o.Id) for o in figs], vp)
    doc.Views.Redraw()
    t = time.time()
    dwg = pipeline.make(doc, view, st, True, True, say)
    paths = pipeline.write(dwg, os.path.join(OUT, "g_section_perspective_quarter"))
    say("  drawing g_section_perspective_quarter: {:.1f}s {}".format(time.time() - t, dwg.stats))
    cls = Counter(c for _, c, _ in dwg.lines)
    assert cls["entourage"] > 300, cls
    assert dwg.stats["regions"] >= 6 and dwg.stats["dots"] > 200, dwg.stats
    _clear_clips(doc)
    return dwg


def entourage_sheet(doc, lib, figures):
    """Front elevation of every library figure at 1/4"."""
    from mindcanvas.drawing import pipeline, styles
    s = units.inch_scale(doc)
    st = styles.get("1/4", lib)
    first = doc.Objects.FindId(figures[0].Id)
    view = _front(doc, place.origin(first))
    _clear_clips(doc)
    place.face_view(doc, [doc.Objects.FindId(o.Id) for o in figures if doc.Objects.FindId(o.Id)], view.ActiveViewport)
    bb = G.BoundingBox.Empty
    for o in figures:
        o = doc.Objects.FindId(o.Id)
        if o is not None:
            bb.Union(o.Geometry.GetBoundingBox(True))
    lo = G.Point3d(bb.Min.X - 24 * s, bb.Min.Y - 24 * s, -12 * s)
    hi = G.Point3d(bb.Max.X + 24 * s, bb.Max.Y + 24 * s, bb.Max.Z + 12 * s)
    gid = doc.Objects.AddBrep(G.Box(G.Plane.WorldXY, G.Interval(lo.X, hi.X), G.Interval(bb.Min.Y - 12 * s, bb.Max.Y + 120 * s),
                                    G.Interval(-6 * s, 0)).ToBrep())
    view.ActiveViewport.ZoomBoundingBox(G.BoundingBox(lo, hi))
    doc.Views.Redraw()
    dwg = pipeline.make(doc, view, st, False, False, window=[lo, hi])
    pipeline.write(dwg, os.path.join(OUT, "g_entourage_sheet_quarter"))
    cls = Counter(c for _, c, _ in dwg.lines)
    say("  drawing g_entourage_sheet_quarter: {}".format(dict(cls)))
    assert cls["entourage"] > 500, cls
    doc.Objects.Delete(gid, True)


def trim_sections(doc, lib, wall_id):
    from mindcanvas.drawing import pipeline, sectioncut, styles
    st = styles.get("1-1/2", lib)
    s = units.inch_scale(doc)
    drv = doc.Objects.FindId(wall_id)
    crv = drv.Geometry
    t = crv.Domain.ParameterAt(0.82)       # on the 16' leg, away from the door
    p = crv.PointAt(t)
    tan = crv.TangentAt(t)
    n = G.Vector3d.CrossProduct(G.Vector3d.ZAxis, tan)
    n.Unitize()
    for name, z, lo_z, hi_z in (("g_trim_base_1-1-2", 6, -3, 15), ("g_trim_crown_1-1-2", 90, 82, 99)):
        _clear_clips(doc)
        view = _view(doc, "Front")
        at = G.Point3d(p.X, p.Y, z * s)
        sectioncut.make(doc, drv, at, view, name="phase8 " + name, depth_in=12.0, style=st)
        lo = G.Point3d(p.X, p.Y, lo_z * s) - n * (14 * s)
        hi = G.Point3d(p.X, p.Y, hi_z * s) + n * (14 * s)
        box = G.BoundingBox([lo, hi])
        view.ActiveViewport.ZoomBoundingBox(box)
        doc.Views.Redraw()
        dwg = pipeline.make(doc, view, st, True, False, window=[box.Min, box.Max])
        pipeline.write(dwg, os.path.join(OUT, name), px_per_mm=16)
        mats = set(r.material for r in dwg.regions)
        say("  drawing {}: {} regions, materials {}".format(name, dwg.stats["regions"], sorted(mats)))
        assert "Wood Trim" in mats, mats
    _clear_clips(doc)


# -- run ------------------------------------------------------------------------------------------
def _cleanup_library(lib, user_asm_backup):
    for section in ("entourage", "profiles"):
        path = os.path.join(lib.directory, section, TEST_FILE)
        if os.path.exists(path):
            os.remove(path)
    path = os.path.join(lib.directory, "assemblies", library.USER_ASSEMBLIES)
    if user_asm_backup is None:
        if os.path.exists(path):
            os.remove(path)
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(user_asm_backup)
    lib.load()


def run(doc, clear=True, drawing_on=True, captures=True, log=None):
    assert not doc.Path, "test_phase8 clears the document: run it in an empty, unsaved model"
    LOG[0] = log
    if clear:
        for o in list(doc.Objects):
            doc.Objects.Delete(o, True)
        for i in range(doc.NamedViews.Count - 1, -1, -1):
            doc.NamedViews.Delete(i)
        docutil.purge_unused_blocks(doc)
    engine.setup_document(doc)
    lib = library.get(force_reload=True)
    ua = os.path.join(lib.directory, "assemblies", library.USER_ASSEMBLIES)
    backup = open(ua, "r", encoding="utf-8").read() if os.path.exists(ua) else None
    t0 = time.time()
    try:
        say("-- entourage")
        names = entourage_shapes(lib)
        figures = entourage_place(doc, lib, names)
        entourage_hiding(doc, lib)
        say("-- capture")
        capture_figure(doc, lib)
        captured = capture_profile(doc, lib)
        say("-- trims")
        trim_id = trim_walls(doc, lib, captured)
        say("-- gable gypsum")
        gable_gypsum(doc, lib)
        say("-- assembly editor")
        ed_wall = _wall(doc, lib, WOOD, (-60, -320), (-40, -320), height=96).driver_id
        editor_model(doc, lib, ed_wall)
        editor_eto(doc, lib, ed_wall)
        say("-- panel")
        panel_eto(doc, lib, ed_wall, figures)
        commands_import()
        # the test assemblies go before the drawings; the wall goes back to its library assembly
        engine.set_assembly(doc, doc.Objects.FindId(ed_wall), WOOD, lib)
        if captures:
            try:
                cap = runpy.run_path(os.path.join(HERE, "capture.py"))["capture"]
                f = lambda v_: _ft(doc, v_)
                v = [x for x in doc.Views if x.ActiveViewport.Name == "Perspective"][0]
                vp = v.ActiveViewport
                vp.ChangeToPerspectiveProjection(True, 35)
                vp.SetCameraLocations(G.Point3d(f(1), f(-250), f(2.5)), G.Point3d(f(13), f(-259), f(6)))
                say(cap(doc, "phase8_trims", mode="Shaded", zoom_extents=False, width=1400, height=900))
            except Exception as ex:
                say("captures skipped:", ex)
        if drawing_on:
            say("-- drawings")
            trim_sections(doc, lib, trim_id)
            entourage_sheet(doc, lib, figures)
            section_perspective(doc, lib)
    finally:
        _cleanup_library(lib, backup)
    assert TEST_ASM not in library.get(force_reload=True).data["assemblies"]
    doc.Views.Redraw()
    say("total {:.1f}s".format(time.time() - t0))
    say("PHASE 8 OK")
