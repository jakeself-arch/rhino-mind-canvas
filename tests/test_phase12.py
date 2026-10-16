"""Phase 12: the visual assembly editor (drawn layer section, click / drag editing, typed option
fields, live preview sample).

Run inside Rhino (e.g. via the MCP run_python tool), in an EMPTY, unsaved document (it is cleared):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_phase12.py")["run"](__rhino_doc__, log=ROOT + r"\\phase12.log")

Covers: AssemblyModel additions (fitted thickness, member sizes + snapping, move_to, typed options and
settings with length / choice / bool / int parsing, advanced JSON, the roof's attic-ceiling stack);
the section layout (true relative thickness, minimum width for membranes, labels that never
overlap, hit tests, which layer an edge drag resizes); the controller's click / edge drag (1/16"
snapping, framing and I-joist member snapping) / reorder drag; the Eto visual editor driven through
its handlers (section clicks, layer fields, option widgets rebuilt when the schema changes, settings,
stack switch, kinds, save as, apply); the live preview (built from the unsaved assembly on its own
layer, never a driver / part, user objects untouched, rebuilt in place, removed with everything it
added on close, stale previews purged); the panel and MCAssemblyEditor opening the visual editor.
captures=True writes docs/captures/phase12_section_{wall,brick,floor,roof,drag}.png (the drawn section)
and phase12_preview.png (the preview next to a wall). Library entries the test writes are removed.
"""

import json
import os
import time

import Rhino

from mindcanvas import asmedit, asmfields, asmview, docutil, engine, library, meta, preview, units

G = Rhino.Geometry
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CAPS = os.path.join(ROOT, "docs", "captures")
LOG = [None]
TEST_ASM = "Test Phase12 - Wall (visual)"

WOOD = "Ext - 2x6 Wood, Fiber Cement"
METAL = "Ext - 6\" Metal Stud, Fiber Cement"
BRICK = "Ext - Brick Veneer / 6\" Metal Stud"
IJOIST = "Floor - 11-7/8\" I-Joist, OSB"
R_ATTIC = "Roof - Asphalt Shingle / 2x8 Rafters, Vented Attic"
W, H = 660, 420


def say(*a):
    msg = " ".join(str(x) for x in a)
    print(msg)
    if LOG[0]:
        with open(LOG[0], "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def _idx(m, name):
    return [i for i in range(len(m.layers)) if m.field(i, "name") == name][0]


def _near(a, b, tol=1e-6):
    return abs(a - b) <= tol


# -- model ----------------------------------------------------------------------------------------
def model_logic(lib):
    m = asmedit.AssemblyModel(lib, WOOD)
    fr, gy, sh = _idx(m, "Framing"), _idx(m, "Gypsum"), _idx(m, "Sheathing")
    assert _near(m.thickness_in(fr), 5.5)
    sizes = m.member_sizes(fr)
    depths = [d for d, n in sizes]
    assert 3.5 in depths and 5.5 in depths and 7.25 in depths, sizes
    assert m.snap(fr, 5.9) == (5.5, "2x6"), m.snap(fr, 5.9)
    assert m.snap(fr, 6.6)[1] == "2x8"
    assert m.member_sizes(gy) is None
    assert _near(m.snap(gy, 0.53)[0], 0.5) and _near(m.snap(gy, 0.53, fine=True)[0], 34 / 64.0)
    assert _near(m.snap(_idx(m, "WRB"), 0.03)[0], 2 / 64.0)          # below 1/16": 1/64 steps
    assert m.member(fr)[0] == "2x6" and not m.member(fr)[2]
    # typed options
    names = dict((f.key, f) for f in m.option_fields(fr))
    assert names["system"].value == "wood" and names["system"].type == "choice"
    assert names["spacing"].value == "16" and names["blocking"].type == "bool"
    assert names["cavity_fill"].value == "Fiberglass Batt" and names["cavity_fill"].choices[0] == asmfields.NONE
    assert "deflection_track" not in names                              # metal only
    assert m.set_option(fr, "system", "metal")
    assert _near(m.thickness_in(fr), 6.0) and m.member(fr)[2], m.thickness_in(fr)   # 2x6 -> 6" stud
    names = dict((f.key, f) for f in m.option_fields(fr))
    assert "deflection_track" in names and "gauge" in names
    m.set_option(fr, "gauge", "16")
    assert m.options(fr)["gauge"] == 16 and "16 ga" in m.member(fr)[0], m.member(fr)
    m.set_option(fr, "spacing", "1'-0\"")
    assert m.options(fr)["spacing"] == 12
    m.set_option(fr, "blocking", False)
    assert m.options(fr)["blocking"] is False
    m.set_option(fr, "cavity_fill", asmfields.NONE)
    assert "cavity_fill" not in m.options(fr)
    assert not m.set_option(fr, "cavity_fill", asmfields.NONE)          # unchanged -> False
    try:
        m.set_option(fr, "spacing", "abc")
        raise AssertionError("bad length accepted")
    except asmedit.EditError:
        pass
    m.set_option(fr, "top_plates", "1")
    assert m.options(fr)["top_plates"] == 1
    m.set_option(fr, "top_plates", "")
    assert "top_plates" not in m.options(fr)
    # unknown scalar keys get generic fields, dicts stay in the advanced JSON
    m.set_advanced_options(fr, json.dumps({"custom": {"a": 1}}))
    assert m.options(fr)["custom"] == {"a": 1} and m.options(fr)["system"] == "metal"
    assert json.loads(m.advanced_options(fr)) == {"custom": {"a": 1}}
    m.set_advanced_options(fr, "")
    assert "custom" not in m.options(fr)
    try:
        m.set_advanced_options(fr, "{bad")
        raise AssertionError("bad JSON accepted")
    except asmedit.EditError:
        pass
    # brick: choices from the masonry component, nested ties in the advanced JSON
    b = asmedit.AssemblyModel(lib, BRICK)
    bv = _idx(b, "Brick Veneer")
    bf = dict((f.key, f) for f in b.option_fields(bv))
    assert "flemish" in bf["bond"].choices and bf["joint"].value == "3/8" and bf["brick"].value == "modular"
    assert "ties" in json.loads(b.advanced_options(bv)) and "base" in json.loads(b.advanced_options(bv))
    b.set_option(bv, "bond", "flemish")
    assert b.options(bv)["bond"] == "flemish" and "ties" in b.options(bv)
    # settings
    sf = dict((f.key, f) for f in m.setting_fields())
    assert sf["default_reference"].value == "interior_face" and sf["default_height"].value == "10'-0\""
    m.set_setting("default_height", "9'-6\"")
    assert m.data["default_height"] == "9'-6\"" and _near(units.parse_length(m.data["default_height"]), 114)
    m.set_setting("default_reference", "core_center")
    assert m.data["default_reference"] == "core_center"
    try:
        m.set_setting("layers", "x")
        raise AssertionError("layers set as a setting")
    except asmedit.EditError:
        pass
    r = asmedit.AssemblyModel(lib, R_ATTIC)
    rf = dict((f.key, f) for f in r.setting_fields())
    assert rf["shape"].value == "gable" and rf["pitch"].value == "6" and rf["overhang"].value == "18"
    r.set_setting("pitch", "8")
    assert r.data["pitch"] == 8
    assert json.loads(r.advanced_settings() or "{}") == {} or "trim" in r.advanced_settings()
    # stacks: a roof's attic ceiling
    assert r.stacks() == ["layers", "ceiling"]
    n_layers = len(r.layers)
    r.set_stack("ceiling")
    assert len(r.layers) == 3 and r.field(1, "name") == "Ceiling Joists"
    cj = 1
    assert _near(r.thickness_in(cj), 5.5) and r.member_sizes(cj)
    r.move_to(0, 2)
    assert r.field(2, "name") == "Attic Insulation"
    r.set_stack("layers")
    assert len(r.layers) == n_layers
    r.set_stack("ceiling")
    while r.layers:
        r.remove(0)
    assert r.data["ceiling"] == [] and not r.problems(), r.problems()
    # move_to
    m2 = asmedit.AssemblyModel(lib, WOOD)
    order = [m2.field(i, "name") for i in range(len(m2.layers))]
    assert m2.move_to(0, 3) == 3
    assert [m2.field(i, "name") for i in range(len(m2.layers))] == order[1:4] + [order[0]] + order[4:]
    # floor: an I-joist layer that names its joist snaps to another I-joist and keeps the option
    f = asmedit.AssemblyModel(lib, IJOIST)
    j = _idx(f, "Framing")
    assert [n for d, n in f.member_sizes(j)] == ['9-1/2" I-Joist', '11-7/8" I-Joist', '14" I-Joist']
    t, mem = f.snap(j, 13.2)
    f.set_thickness_in(j, t, mem)
    assert f.options(j)["joist"] == '14" I-Joist' and _near(f.thickness_in(j), 14.0)
    say("  model: fitted thickness, member snapping, typed options / settings, stacks, move_to OK")


# -- layout + controller -------------------------------------------------------------------------
def layout_logic(lib):
    m = asmedit.AssemblyModel(lib, WOOD)
    c = asmview.SectionController(m, W, H)
    lay = c.layout
    assert lay.orient == "h" and len(lay.bands) == len(m.layers)
    for a, b in zip(lay.bands, lay.bands[1:]):
        assert _near(a.hi, b.lo)
    assert abs(lay.end - lay.x1) < 1e-6, (lay.end, lay.x1)
    wrb = _idx(m, "WRB")
    assert _near(lay.bands[wrb].hi - lay.bands[wrb].lo, asmview.MIN_PX)
    # true relative thickness for the rest
    fr, gy = _idx(m, "Framing"), _idx(m, "Gypsum")
    ratio = (lay.bands[fr].hi - lay.bands[fr].lo) / (lay.bands[gy].hi - lay.bands[gy].lo)
    assert abs(ratio - 5.5 / 0.5) < 1e-6, ratio
    # labels: a staircase below (the exterior one lowest), every label inside the drawing
    ys = [b.label_pos[1] for b in lay.bands]
    assert ys == sorted(ys, reverse=True), ys
    for b in lay.bands:
        assert 0 <= b.label_pos[0] and lay.label_rect(b)[0] + 6.6 * 12 < W and b.label_pos[1] + asmview.ROW <= H
    # hits
    for b in lay.bands:
        assert lay.hit(*c.band_point(b.index)) == ("band", b.index), (b, lay.hit(*c.band_point(b.index)))
    for k in range(len(lay.bands) + 1):
        assert lay.hit(*c.edge_point(k)) == ("edge", k)
    x, y = lay.bands[gy].label_pos
    assert lay.hit(x + 3, y + 5) == ("label", gy)
    assert lay.hit(5, 5) is None
    # which layer an edge resizes: the exterior-side one; a membrane hands it to its neighbor
    assert lay.edge_target(0) == (0, -1) and lay.edge_target(len(lay.bands)) == (len(lay.bands) - 1, 1)
    assert lay.edge_target(fr + 1) == (fr, 1)
    assert lay.edge_target(wrb + 1) == (wrb + 1, -1)
    # click
    assert c.down(*c.band_point(gy)) == "select" and c.up() == "select" and c.selected == gy
    # a small wobble is still a click, not a reorder
    x, y = c.band_point(sh_i(m))
    c.down(x, y)
    c.move(x + 2, y)
    assert c.up() == "select" and [m.field(i, "name") for i in range(len(m.layers))][0] == "Siding"
    # edge drags: framing snaps to members, gypsum to 1/16"
    assert c.drag_edge(fr + 1, 1.6) == "thickness" and _near(m.thickness_in(fr), 7.25), m.thickness_in(fr)
    assert m.field(fr, "thickness") == "7-1/4"
    assert c.drag_edge(gy + 1, 0.12) == "thickness" and m.field(gy, "thickness") == "5/8"
    assert c.drag_edge(gy + 1, -0.0) == "select"                       # no change
    assert c.drag_edge(0, 0.25) == "thickness" and m.field(0, "thickness") == "9/16", m.field(0, "thickness")
    # the dragged boundary follows the pointer while dragging (frozen scale), then fits again
    x, y = c.edge_point(gy + 1)
    c.down(x, y)
    c.move(x + 0.5 * c.drag["scale"], y)
    assert c.drag["value"] == 1.125 and _near(c.layout.bands[gy].hi - c.layout.bands[gy].lo, 1.125 * c.drag["scale"])
    c.cancel()
    assert m.field(gy, "thickness") == "5/8"
    # reorder
    names = [m.field(i, "name") for i in range(len(m.layers))]
    assert c.drag_band(0, 3) == "reorder"
    assert [m.field(i, "name") for i in range(len(m.layers))] == names[1:3] + [names[0]] + names[3:]
    assert c.selected == 2
    assert c.drag_band(2, 0) == "reorder" and [m.field(i, "name") for i in range(len(m.layers))] == names
    assert c.drag_band(len(names) - 1, len(names)) in ("select", "reorder")
    # floors / roofs: horizontal bands top -> bottom, labels spread apart
    f = asmedit.AssemblyModel(lib, IJOIST)
    cf = asmview.SectionController(f, W, H)
    assert cf.layout.orient == "v" and cf.layout.bands[0].lo < cf.layout.bands[-1].lo
    j = _idx(f, "Framing")
    assert cf.drag_edge(j + 1, 2.2) == "thickness" and f.options(j)["joist"] == '14" I-Joist'
    r = asmedit.AssemblyModel(lib, R_ATTIC)
    cr = asmview.SectionController(r, W, H)
    ly = [b.label_pos[1] for b in cr.layout.bands]
    assert all(b - a >= asmview.ROW - 1e-6 for a, b in zip(ly, ly[1:])), ly
    assert asmview.spread([10, 11, 12], 15, 0, 100) == [10, 25, 40]
    assert asmview.spread([95, 96], 15, 0, 100) == [85, 100]
    say("  layout: proportional bands, labels, hits, edge targets, click / edge drags / reorder OK")


def sh_i(m):
    return _idx(m, "Sheathing")


# -- the Eto editor + preview --------------------------------------------------------------------
def _wall(doc, lib, asm, x0, x1, y=0.0):
    s = units.inch_scale(doc)
    crv = G.LineCurve(G.Point3d(x0 * s, y * s, 0), G.Point3d(x1 * s, y * s, 0))
    obj = doc.Objects.FindId(doc.Objects.AddCurve(crv))
    return engine.create(doc, obj, asm, {"height": 96, "reference": "interior_face"}, lib)


def _snapshot(doc):
    """Ids + kinds of every object that is not a preview object."""
    out = {}
    for o in doc.Objects:
        if meta.get(o, meta.KIND) != preview.KIND:
            out[str(o.Id)] = (meta.get(o, meta.KIND), o.Attributes.LayerIndex)
    return out


def eto_editor(doc, lib, captures):
    from mindcanvas.eto import editor, visual
    user = _wall(doc, lib, WOOD, 0, 120)
    assert not [w_ for w_ in user.warnings if "tolerance" in w_], user.warnings
    before = _snapshot(doc)
    ed = visual.VisualAssemblyEditor(doc, lib, name=WOOD)
    m = ed.model
    ed.commit_pending()                      # untouched fields (10' shown as 10'-0") change nothing
    assert not m.dirty and "unsaved" not in ed.lb_status.Text, m.data
    assert ed.ctl.layout.orient == "h" and len(ed.ctl.layout.bands) == len(m.layers)
    # a click in the drawn section selects a layer and shows its fields
    sh = _idx(m, "Sheathing")
    r = ed.ctl.down(*ed.ctl.band_point(sh))
    ed.on_section(ed.ctl.up() or r)
    assert ed.index == sh and ed.tb_thick.Text == "7/16" and ed.tb_name.Text == "Sheathing", ed.tb_thick.Text
    ed.tb_thick.Text = "3/4"
    ed.on_layer_fields()
    assert m.field(sh, "thickness") == "3/4" and m.dirty
    ed.dd_mat.SelectedIndex = list(ed.dd_mat.DataStore).index("Plywood Sheathing")
    assert m.field(sh, "material") == "Plywood Sheathing", m.field(sh, "material")
    ed.tb_thick.Text = "abc"
    ed.on_layer_fields()
    assert "not a length" in ed.lb_status.Text and m.field(sh, "thickness") == "3/4"
    ed.tb_thick.Text = "3/4"
    # typed text not yet committed is written before a click in the drawing selects another layer
    ed.tb_name.Text = "Plywood"
    fr = _idx(m, "Framing")
    ed.commit_pending()
    ed.select_layer(fr)
    assert m.field(sh, "name") == "Plywood" and ed.index == fr
    # option widgets: a dropdown for the system; switching to metal adds the gauge (rebuilt widgets)
    f, dd = ed.opt_widgets["system"]
    assert "gauge" not in ed.opt_widgets or ed.opt_widgets["gauge"][0].explicit
    dd.SelectedIndex = list(dd.DataStore).index("metal")
    assert m.options(fr)["system"] == "metal" and _near(m.thickness_in(fr), 6.0)
    assert "deflection_track" in ed.opt_widgets and ed.tb_thick.Text == "6", ed.tb_thick.Text
    assert "Metal Stud" in ed.lb_member.Text
    f, ck = ed.opt_widgets["deflection_track"]
    ck.Checked = True
    assert m.options(fr)["deflection_track"] is True
    f, tb = ed.opt_widgets["spacing"]
    tb.Text = "24"
    ed.on_option("spacing")
    assert m.options(fr)["spacing"] == 24
    keep = ed.opt_widgets["spacing"][1]
    tb.Text = "2'"                          # the same value: no rebuild, no change
    ed.on_option("spacing")
    assert ed.opt_widgets["spacing"][1] is keep
    # a boundary drag in the drawing
    assert ed.ctl.drag_edge(fr + 1, 2.0) == "thickness"
    ed.on_section("thickness")
    assert _near(m.thickness_in(fr), 8.0) and ed.tb_thick.Text == "8", ed.tb_thick.Text
    # the Eto Drawable's own mouse handlers (what a real drag sends): gypsum boundary +1/4"
    import Eto.Drawing as ed_drawing
    import Eto.Forms as ed_forms
    gy = _idx(m, "Gypsum")

    import System

    def zero(member):          # the enum's 0 value ("None" is a Python keyword)
        return System.Enum.ToObject(member.GetType(), 0)

    def mouse(x, y, pressed=True):
        b = ed_forms.MouseButtons.Primary if pressed else zero(ed_forms.MouseButtons.Primary)
        return ed_forms.MouseEventArgs(b, zero(ed_forms.Keys.Shift), ed_drawing.PointF(float(x), float(y)))
    x, y = ed.ctl.edge_point(gy + 1)
    ed.view._down(None, mouse(x, y))
    dx = 0.25 * ed.ctl.drag["scale"]
    ed.view._move(None, mouse(x + dx / 2, y))
    ed.view._move(None, mouse(x + dx, y))
    ed.view._up(None, mouse(x + dx, y, False))
    assert m.field(gy, "thickness") == "3/4" and ed.tb_thick.Text == "3/4", (m.field(gy, "thickness"), ed.tb_thick.Text)
    x, y = ed.ctl.band_point(fr)
    ed.view._down(None, mouse(x, y))
    ed.view._up(None, mouse(x, y, False))
    assert ed.index == fr and ed.tb_name.Text == "Framing"
    # settings widgets
    f, tb = ed.set_widgets["default_height"]
    tb.Text = "9'"
    ed.on_setting("default_height")
    assert m.data["default_height"] == "9'-0\"", m.data["default_height"]
    # live preview: built from the unsaved model, on its own layer, never a driver / part
    t0 = time.time()
    res = ed.rebuild_preview()
    assert res is not None, ed.lb_preview.Text
    say("  preview wall: {} parts in {:.1f}s ({})".format(len(res.part_ids), time.time() - t0, ed.lb_preview.Text))
    objs = preview.find(doc, ed.preview.token)
    assert len(objs) == len(res.part_ids) + 1 and len(objs) > 10
    lidx = doc.Layers.FindByFullPath(preview.PREVIEW_LAYER, -1)
    assert lidx >= 0 and all(o.Attributes.LayerIndex == lidx for o in objs)
    assert not [o for o in objs if meta.is_driver(o) or meta.is_part(o)]
    assert all(str(d.Id) in before for d in meta.all_drivers(doc))
    assert preview.PREVIEW_ASSEMBLY not in lib.data["assemblies"]
    s = units.inch_scale(doc)
    bb = ed.preview.bounding_box()
    ub = doc.Objects.FindId(user.driver_id).Geometry.GetBoundingBox(True)
    assert bb.Min.X > ub.Max.X + 100 * s, (bb.Min.X / s, ub.Max.X / s)
    assert abs((bb.Max.Z - bb.Min.Z) / s - 108) < 2.0, (bb.Max.Z - bb.Min.Z) / s       # 9' default height
    mats = set(meta.get(o, meta.MATERIAL) for o in objs)
    assert "Plywood Sheathing" in mats and "Cold-Formed Steel" in mats, mats
    after = _snapshot(doc)
    assert all(k in after and after[k] == v for k, v in before.items()), "user objects changed"
    # a change rebuilds in place (old sample gone)
    ed.select_layer(_idx(m, "Gypsum"))
    ed.tb_thick.Text = "1"
    ed.on_layer_fields()
    res2 = ed.rebuild_preview()
    objs2 = preview.find(doc, ed.preview.token)
    assert len(objs2) == len(res2.part_ids) + 1 and not set(str(o.Id) for o in objs) & set(str(o.Id) for o in objs2)
    if captures:
        os.makedirs(CAPS, exist_ok=True)
        try:
            import runpy
            cap = runpy.run_path(os.path.join(HERE, "capture.py"))["capture"]
            box = G.BoundingBox(ub.Min, bb.Max)
            box.Inflate(36 * s)
            v = [x for x in doc.Views if x.ActiveViewport.Name == "Perspective"][0]
            say(cap(doc, "phase12_preview", mode="Shaded", zoom_extents=False, width=1400, height=800, box=box))
        except Exception as ex:
            say("  preview capture skipped:", ex)
    # a stale preview (another token) is purged when an editor opens; ours is kept
    ghost = doc.Objects.AddPoint(G.Point3d(0, 0, -100))
    go = doc.Objects.FindId(ghost)
    a = go.Attributes.Duplicate()
    a.SetUserString(meta.KIND, preview.KIND)
    a.SetUserString(preview.TOKEN, "stale")
    doc.Objects.ModifyAttributes(go, a, True)
    assert preview.purge(doc, [ed.preview.token]) == 1 and preview.find(doc, ed.preview.token)
    # an assembly that cannot be built keeps the old status message, not a crash
    core = [i for i in range(len(m.layers)) if m.field(i, "core")][0]
    ed.select_layer(core)
    ed.ck_core.Checked = False
    ed.on_layer_fields()
    assert ed.rebuild_preview() is None and "core" in ed.lb_preview.Text, ed.lb_preview.Text
    ed.ck_core.Checked = True
    ed.on_layer_fields()
    # reorder through the drawing, mirror / add / duplicate / remove buttons
    n = len(m.layers)
    assert ed.ctl.drag_band(0, 2) == "reorder"
    ed.on_section("reorder")
    ed.on_mirror()
    ed.on_mirror()
    ed.on_add()
    assert len(m.layers) == n + 1
    ed.on_duplicate()
    ed.on_remove()
    ed.on_remove()
    assert len(m.layers) == n
    ed.on_move(1)
    ed.on_move(-1)
    # pictures of the drawn section
    if captures:
        from mindcanvas.eto import sectionview
        for name, asm, sel in (("wall", WOOD, 4), ("brick", BRICK, 1), ("floor", IJOIST, 1), ("roof", R_ATTIC, 1)):
            ctl = asmview.SectionController(asmedit.AssemblyModel(lib, asm), 900, 520)
            ctl.select(sel)
            p = sectionview.render_png(ctl, os.path.join(CAPS, "phase12_section_{}.png".format(name)))
            assert os.path.getsize(p) > 5000, p
            say("  wrote", p)
        # a boundary drag in progress (the framing snapping to a 2x8)
        ctl = asmview.SectionController(asmedit.AssemblyModel(lib, WOOD), 900, 520)
        x, y = ctl.edge_point(5)
        ctl.down(x, y)
        ctl.move(x + 1.7 * ctl.drag["scale"], y)
        assert ctl.drag["member"] == "2x8"
        sectionview.render_png(ctl, os.path.join(CAPS, "phase12_section_drag.png"))
    p = ed.save_png(os.path.join(os.environ.get("TEMP", ROOT), "mc_phase12_section.png"))
    assert os.path.getsize(p) > 5000
    os.remove(p)
    # save as + apply to the user's wall
    ed.tb_save.Text = WOOD
    ed.on_save()
    assert "library assembly" in ed.lb_status.Text
    ed.tb_save.Text = TEST_ASM
    ed.on_save()
    assert TEST_ASM in lib.data["assemblies"] and not m.dirty, ed.lb_status.Text
    doc.Objects.UnselectAll()
    doc.Objects.Select(user.driver_id)
    ed.on_apply()
    assert meta.get(doc.Objects.FindId(user.driver_id), meta.ASSEMBLY) == TEST_ASM, ed.lb_status.Text
    doc.Objects.UnselectAll()
    # kinds: floor (horizontal stack + preview), roof (ceiling stack), curtain wall (settings only)
    ed.dd_kind.SelectedIndex = visual.KINDS.index("floor")
    assert ed.model.kind == "floor" and ed.ctl.layout.orient == "v"
    ed.dd_asm.SelectedIndex = list(ed.dd_asm.DataStore).index(IJOIST)
    fj = _idx(ed.model, "Framing")
    ed.select_layer(fj)
    assert ed.opt_widgets["joist"][0].value == '11-7/8" I-Joist' and "rim_plies" in ed.opt_widgets
    rf = ed.rebuild_preview()
    assert rf is not None and len(rf.part_ids) > 3, ed.lb_preview.Text
    ed.dd_kind.SelectedIndex = visual.KINDS.index("roof")
    ed.dd_asm.SelectedIndex = list(ed.dd_asm.DataStore).index(R_ATTIC)
    assert ed.dd_stack.Enabled and list(ed.dd_stack.DataStore) == ["Layers", "Attic ceiling"]
    assert "pitch" in ed.set_widgets and "shape" in ed.set_widgets
    ed.dd_stack.SelectedIndex = 1
    assert ed.model.stack_key == "ceiling" and ed.tb_name.Text == "Attic Insulation", ed.tb_name.Text
    rr = ed.rebuild_preview()
    assert rr is not None and len(rr.part_ids) > 5, ed.lb_preview.Text
    say("  preview roof: {} parts ({})".format(len(rr.part_ids), ed.lb_preview.Text))
    ed.dd_kind.SelectedIndex = visual.KINDS.index("curtain_wall")
    assert not ed.model.has_layers and "style" in ed.set_widgets and not ed.ctl.layout.bands
    f, dd = ed.set_widgets["style"]
    dd.SelectedIndex = list(dd.DataStore).index("ssg4")
    assert ed.model.data["style"] == "ssg4"
    rc = ed.rebuild_preview()
    say("  preview curtain wall: {}".format(ed.lb_preview.Text))
    # the old list editor stays reachable
    old = ed.on_list_editor()
    assert old is not None
    old.close()
    # close: the preview and everything it alone added are gone
    ed.show()
    ed.close()
    assert not preview.find(doc) and doc.Layers.FindByFullPath(preview.PREVIEW_LAYER, -1) < 0
    assert ed not in visual._OPEN
    after = _snapshot(doc)
    assert meta.get(doc.Objects.FindId(user.driver_id), meta.ASSEMBLY) == TEST_ASM
    say("  Eto visual editor: section clicks / drags, fields, options, settings, kinds, stacks, "
        "preview, save, apply, close OK")
    return user.driver_id


def untouched_clean(doc, lib):
    """Browsing every layer (and a roof's ceiling) of every library assembly without editing leaves
    it unchanged: the displayed values (10'-0", rounded member depths) read back as the same."""
    from mindcanvas.eto import visual
    n, dirty = 0, []
    for kind in visual.KINDS:
        for name in lib.assemblies(kind):
            ed = visual.VisualAssemblyEditor(doc, lib, name=name, live_preview=False)
            for si in range(len(ed.model.stacks()) or 1):
                if ed.dd_stack.Enabled:
                    ed.dd_stack.SelectedIndex = si
                for i in range(len(ed.model.layers)):
                    ed.select_layer(i)
                    n += 1
            ed.commit_pending()
            if ed.model.dirty:
                dirty.append(name)
            ed.close()
    assert not dirty, dirty
    say("  {} layers of every library assembly browsed: nothing changed OK".format(n))


def entry_points(doc, lib, wall_id):
    from mindcanvas.eto import panel, visual
    p = panel.MindCanvasPanel(doc, lib)
    doc.Objects.Select(wall_id)
    p.refresh_selection()
    ed = p.open_editor()
    assert isinstance(ed, visual.VisualAssemblyEditor) and ed.model.source == TEST_ASM, ed
    ed.close()
    p.close()
    doc.Objects.UnselectAll()
    import importlib
    mod = importlib.import_module("mindcanvas.cmd.assemblyeditor")
    assert "visual" in open(mod.__file__, encoding="utf-8").read()
    assert not preview.find(doc)
    say("  panel 'Edit assembly' + MCAssemblyEditor open the visual editor OK")


# -- run ------------------------------------------------------------------------------------------
def run(doc, clear=True, drawing_on=False, captures=True, log=None):
    assert not doc.Path, "test_phase12 clears the document: run it in an empty, unsaved model"
    LOG[0] = log
    if clear:
        for o in list(doc.Objects):
            doc.Objects.Delete(o, True)
        docutil.purge_unused_blocks(doc)
    engine.setup_document(doc)
    lib = library.get(force_reload=True)
    ua = os.path.join(lib.directory, "assemblies", library.USER_ASSEMBLIES)
    backup = open(ua, "r", encoding="utf-8").read() if os.path.exists(ua) else None
    t0 = time.time()
    try:
        say("-- model")
        model_logic(lib)
        say("-- layout")
        layout_logic(lib)
        say("-- editor")
        wall_id = eto_editor(doc, lib, captures)
        entry_points(doc, lib, wall_id)
        untouched_clean(doc, lib)
        engine.set_assembly(doc, doc.Objects.FindId(wall_id), WOOD, lib)
    finally:
        if backup is None:
            if os.path.exists(ua):
                os.remove(ua)
        else:
            with open(ua, "w", encoding="utf-8") as fh:
                fh.write(backup)
        lib.load()
    assert TEST_ASM not in library.get(force_reload=True).data["assemblies"]
    doc.Views.Redraw()
    say("total {:.1f}s".format(time.time() - t0))
    say("PHASE 12 OK")
