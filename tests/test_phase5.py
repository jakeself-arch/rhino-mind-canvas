"""Phase 5: curtain walls.

Run inside Rhino (e.g. via the MCP run_python tool), in an EMPTY, unsaved document (it is cleared):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_phase5.py")["run"](__rhino_doc__)

Covers every joint style (captured, 4-side SSG, 2-side SSG, butt glazed, unitized) on straight,
L-shaped (90 degree corner, convex and concave) and arc drivers; grid edits (spacing, fixed module,
bay list, transoms, infill rows and cells, style swap); every LOD; slab anchors; a door in a bay;
the curtain-wall schedule. drawing_on=True writes 1-1/2" details to docs/drawings/:
d_curtainwall_plan_<style>.{svg,png} (plan at a vertical mullion) and
d_curtainwall_section_spandrel.{svg,png} (section at a transom / spandrel / slab edge).
log= a file path: progress is appended there (Rhino crashed once mid-build in an earlier phase).
"""

import os
import runpy
import time
from collections import Counter

import Rhino

from mindcanvas import engine, kinds, library, meta, schedule, units
from mindcanvas.kinds import curtainwall as cwkind

G = Rhino.Geometry
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASM = {
    "captured": "CW - Captured, Aluminum 2-1/2 x 6",
    "ssg4": "CW - 4-Side SSG, Aluminum 2-1/2 x 6",
    "ssg2": "CW - 2-Side SSG, Aluminum 2-1/2 x 6",
    "butt": "CW - Butt Glazed, Captured Head + Sill",
    "unitized": "CW - Unitized, Aluminum 3 x 6",
}
STYLE_ROLES = {
    "captured": ("mullion", "cap", "pressure_plate", "isolator", "gasket"),
    "ssg4": ("mullion", "structural_silicone", "weather_seal", "backer_rod", "spacer_tape"),
    "ssg2": ("mullion", "structural_silicone", "weather_seal", "cap", "pressure_plate"),
    "butt": ("butt_seal", "backer_rod", "cap", "sill", "head"),
    "unitized": ("mullion_female", "mullion_male", "weather_gasket", "air_seal", "starter_sill",
                 "head_receptor"),
}
LOG = [None]


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


def _roles(doc, drv_id):
    return Counter(meta.get(o, meta.ROLE) for o in meta.parts_of(doc, drv_id))


def _ctx(doc, lib, drv_id):
    drv = doc.Objects.FindId(drv_id)
    return cwkind.make_context(doc, lib, drv, meta.get(drv, meta.ASSEMBLY), meta.params(drv))


def _bad(r):
    return [w for w in r.warnings if "fail" in w.lower() or "could not" in w.lower()
            or "too small" in w.lower() or "unknown" in w.lower()]


def check(doc, lib, label, r, style, corners=0):
    assert not _bad(r), "{}: {}".format(label, r.warnings)
    ctx = _ctx(doc, lib, r.driver_id)
    g = ctx.grid
    roles = _roles(doc, r.driver_id)
    nc = sum(1 for v in g.vertices if v.kind == "corner")
    assert nc == corners, "{}: {} corners, expected {}".format(label, nc, corners)
    if ctx.lod == "detail":
        for role in STYLE_ROLES[style]:
            assert roles[role] > 0, "{}: no '{}' ({})".format(label, role, dict(roles))
        if corners and style != "butt":
            assert roles["corner_mullion"] >= corners, "{}: corner mullions {}".format(label, roles)
        if corners and style in ("ssg4", "butt"):
            assert roles["corner_seal"] >= corners, "{}: corner seals {}".format(label, roles)
    cells = len(g.bays) * len(g.rows) - sum(1 for _ in ctx.openings) * 0
    panels = schedule_panels(ctx)
    lites = roles["glass"] + roles["spandrel_glass"] + roles["panel"]
    assert panels == cells - opening_cells(ctx), "{}: {} panels for {} cells".format(label, panels, cells)
    if ctx.lod == "detail":
        assert roles["glass"] + roles["spandrel_glass"] == 2 * (panels - roles["panel"]), \
            "{}: lites {} for {} panels".format(label, lites, panels)
    say("  {:<36} {:4d} parts, {} bays x {} rows, {} corners, {:.2f}s".format(
        label, len(r.part_ids), len(g.bays), len(g.rows), nc, r.seconds))
    return ctx, roles


def schedule_panels(ctx):
    return sum(p["count"] for p in cwkind.summary(ctx)["panels"])


def opening_cells(ctx):
    n = 0
    for op in ctx.openings:
        n += sum(1 for h0, h1 in ctx.grid.rows if h0.z < op.rz1 + ctx.u(3))
    return n


def drivers(doc, f, x0, y0):
    """Straight 20' line, L (convex 90 corner), reversed L (concave), arc."""
    out = {}
    out["straight"] = G.LineCurve(G.Point3d(f(x0), f(y0), 0), G.Point3d(f(x0 + 20), f(y0), 0))
    # clockwise L: up the left side then right along the top: exterior outside = convex corner
    out["L convex"] = G.PolylineCurve([G.Point3d(f(x0 + 24), f(y0), 0), G.Point3d(f(x0 + 24), f(y0 + 10), 0),
                                       G.Point3d(f(x0 + 36), f(y0 + 10), 0)])
    out["L concave"] = G.PolylineCurve([G.Point3d(f(x0 + 52), f(y0 + 10), 0), G.Point3d(f(x0 + 40), f(y0 + 10), 0),
                                        G.Point3d(f(x0 + 40), f(y0), 0)])
    # clockwise arc: exterior on the convex side
    out["arc"] = G.ArcCurve(G.Arc(G.Point3d(f(x0 + 56), f(y0), 0), G.Point3d(f(x0 + 66), f(y0 + 8), 0),
                                  G.Point3d(f(x0 + 76), f(y0), 0)))
    return out


def styles_on_drivers(doc, lib):
    f = lambda v: _ft(doc, v)
    out = {}
    for i, (style, asm) in enumerate(sorted(ASM.items())):
        y0 = -30.0 * i
        for label, crv in drivers(doc, f, 0.0, y0).items():
            t = time.time()
            r = engine.create(doc, _add(doc, crv), asm, {"height": "13'-4\""} if style != "butt" else {}, lib)
            corners = 1 if label.startswith("L") else 0
            check(doc, lib, "{} / {}".format(style, label), r, style, corners)
            out[(style, label)] = r.driver_id
    return out


# -- drawings ---------------------------------------------------------------------------------
def _view(doc, name):
    v = [x for x in doc.Views if x.ActiveViewport.Name == name][0]
    v.Maximized = True
    doc.Views.ActiveView = v
    return v


def _clear_clips(doc):
    for o in list(doc.Objects.FindByObjectType(Rhino.DocObjects.ObjectType.ClipPlane) or []):
        doc.Objects.Delete(o, True)


def plan_detail(doc, lib, style, x0=200.0, y0=0.0, out_name=None, corner=False, extra=None):
    """1-1/2" plan detail at a vertical mullion (or at the corner of an L)."""
    from mindcanvas.drawing import pipeline, sectioncut, styles
    f = lambda v: _ft(doc, v)
    st = styles.get("1-1/2", lib)
    if corner:
        pts_ = [G.Point3d(f(x0), f(y0), 0), G.Point3d(f(x0), f(y0 + 10), 0), G.Point3d(f(x0 + 10), f(y0 + 10), 0)]
        if corner == "concave":
            pts_.reverse()
        crv = G.PolylineCurve(pts_)
        at = G.Point3d(f(x0), f(y0 + 10), f(5))
    else:
        crv = G.LineCurve(G.Point3d(f(x0), f(y0), 0), G.Point3d(f(x0 + 10), f(y0), 0))
        at = G.Point3d(f(x0 + 5), f(y0), f(5))
    prm = {"height": "10'", "lod": "detail", "transoms": [30], "infill": {"rows": ["vision"]}}
    prm.update(extra or {})
    r = engine.create(doc, _add(doc, crv), ASM[style], prm, lib)
    assert not _bad(r), r.warnings
    drv = doc.Objects.FindId(r.driver_id)
    _clear_clips(doc)
    view = _view(doc, "Top")
    res = sectioncut.make_plan(doc, drv, at, view, name="phase5 plan " + style, depth_in=6.0, style=st)
    fr = res["frame"]
    X, Y = fr.XAxis, fr.YAxis
    inch = units.inch_scale(doc)
    if corner:
        pts = [at + G.Vector3d(-12 * inch, -12 * inch, 0), at + G.Vector3d(12 * inch, 12 * inch, 0)]
    else:
        pts = [at + X * (-9 * inch) + Y * (4.5 * inch), at + X * (9 * inch) + Y * (-11 * inch)]
    box = G.BoundingBox(pts)
    view.ActiveViewport.ZoomBoundingBox(box)
    doc.Views.Redraw()
    t = time.time()
    dwg = pipeline.make(doc, view, st, False, False, say, window=[box.Min, box.Max])
    name = out_name or "d_curtainwall_plan_" + style
    paths = pipeline.write(dwg, os.path.join(ROOT, "docs", "drawings", name), px_per_mm=16)
    say("  plan {}: {:.1f}s {} -> {}".format(style, time.time() - t, dwg.stats, os.path.basename(paths[-1])))
    _clear_clips(doc)
    return dwg, r.driver_id


def section_detail(doc, lib, x0=200.0, y0=-40.0, style="captured", name="d_curtainwall_section_spandrel"):
    """1-1/2" vertical section at the spandrel: vision below, transom, spandrel (spandrel glass,
    insulation, back pan), slab edge with anchors + fire safing, transom, vision above."""
    from mindcanvas.drawing import pipeline, sectioncut, styles
    f = lambda v: _ft(doc, v)
    st = styles.get("1-1/2", lib)
    inch = units.inch_scale(doc)
    crv = G.LineCurve(G.Point3d(f(x0 + 10), f(y0), 0), G.Point3d(f(x0), f(y0), 0))
    # floor to floor 13'-4": slab top at 13'-4" (160"), spandrel from 10'-6" (126") to 14'-2" (170")
    prm = {"height": "20'", "lod": "detail", "transoms": [126, 170], "slabs": [160],
           "infill": {"rows": ["vision", "spandrel", "vision"]}}
    if style == "unitized":     # stack joint 10" over the slab, in the spandrel
        prm.update(transoms=[126], stack=[170])
    r = engine.create(doc, _add(doc, crv), ASM[style], prm, lib)
    assert not _bad(r), r.warnings
    drv = doc.Objects.FindId(r.driver_id)
    # context: the floor slab (concrete) behind the curtain wall
    ctx = _ctx(doc, lib, r.driver_id)
    qb = ctx.dims.q_back()
    gap = units.parse_length(ctx.cw["anchors"]["slab_gap"])
    yb = ctx.yG - (qb + gap) * inch          # slab edge (signed offset; exterior +)
    bay = ctx.grid.bays[0]
    p0 = bay.world(-f(2), yb, f(160 / 12.0) - 8 * inch)
    p1 = bay.world(bay.c + f(2), yb - f(4), f(160 / 12.0))
    slab = G.Box(G.BoundingBox([p0, p1])).ToBrep()
    la = Rhino.DocObjects.ObjectAttributes()
    from mindcanvas import docutil
    la.LayerIndex = docutil.ensure_material_layer(doc, lib, "Concrete")
    slab_id = doc.Objects.AddBrep(slab, la)
    _clear_clips(doc)
    view = _view(doc, "Front")
    # cut 3" from the middle mullion, looking at it: the anchor's foot is cut, its plate seen beyond
    at = bay.world(bay.c - 3 * inch, 0, f(13))
    res = sectioncut.make(doc, drv, at, view, name="phase5 section", depth_in=8.0, style=st)
    o, N = res["origin"], res["frame"].YAxis
    lo = G.Point3d(o.X, o.Y, 0) + N * (ctx.yG + 6 * inch)
    hi = G.Point3d(o.X, o.Y, 0) + N * (ctx.yG - 16 * inch)
    box = G.BoundingBox([G.Point3d(lo.X, lo.Y, f(124 / 12.0)), G.Point3d(hi.X, hi.Y, f(174 / 12.0))])
    view.ActiveViewport.ZoomBoundingBox(box)
    doc.Views.Redraw()
    t = time.time()
    dwg = pipeline.make(doc, view, st, False, False, say, window=[box.Min, box.Max])
    paths = pipeline.write(dwg, os.path.join(ROOT, "docs", "drawings", name), px_per_mm=16)
    say("  section {}: {:.1f}s {} -> {}".format(style, time.time() - t, dwg.stats, os.path.basename(paths[-1])))
    _clear_clips(doc)
    return dwg, r.driver_id, slab_id


# -- grid edits, LOD, schedule, door ------------------------------------------------------------
def grid_edits(doc, lib):
    f = lambda v: _ft(doc, v)
    asm = ASM["captured"]
    r = engine.create(doc, _add(doc, G.LineCurve(G.Point3d(0, f(-200), 0), G.Point3d(f(23), f(-200), 0))),
                      asm, {"height": "12'"}, lib)
    drv = lambda: doc.Objects.FindId(r.driver_id)
    ctx = _ctx(doc, lib, r.driver_id)
    assert len(ctx.grid.bays) == 5, "equal 60\": {} bays".format(len(ctx.grid.bays))   # 276/60 -> 5
    widths = [round(b.c / ctx.s, 3) for b in ctx.grid.bays]
    assert max(widths) - min(widths) < 1e-3, widths
    # fixed module: 60" bays from the start, the remainder last
    r = engine.update_params(doc, drv(), {"grid": "fixed", "spacing": 60}, lib)
    ctx = _ctx(doc, lib, r.driver_id)
    widths = [round(b.c / ctx.s, 3) for b in ctx.grid.bays]
    assert widths[:4] == [60.0] * 4 and abs(widths[-1] - 36.0) < 1e-3, widths
    # a sliver merges into the last bay
    r = engine.update_params(doc, drv(), {"grid": "fixed", "spacing": 68}, lib)
    widths = [round(b.c / units.inch_scale(doc), 3) for b in _ctx(doc, lib, r.driver_id).grid.bays]
    assert widths == [68.0, 68.0, 68.0, 72.0], widths
    # list of bay widths, repeated
    r = engine.update_params(doc, drv(), {"grid": "list", "bays": [48, 36]}, lib)
    widths = [round(b.c / units.inch_scale(doc), 3) for b in _ctx(doc, lib, r.driver_id).grid.bays]
    assert widths[:4] == [48.0, 36.0, 48.0, 36.0] and abs(sum(widths) - 276) < 1e-3, widths
    # transoms + infill rows + one cell override
    r = engine.update_params(doc, drv(), {"grid": "equal", "spacing": 60, "transoms": [36, 84, 120],
                                          "infill": {"rows": ["spandrel", "vision", "vision", "shadow_box"],
                                                     "cells": {"2,1": "spandrel"}}}, lib)
    assert not _bad(r), r.warnings
    ctx = _ctx(doc, lib, r.driver_id)
    assert len(ctx.grid.rows) == 4, ctx.grid.rows
    s = cwkind.summary(ctx)
    kinds_ = dict((p["panel"], p["count"]) for p in s["panels"])
    assert kinds_ == {"spandrel": 6, "vision": 9, "shadow_box": 5}, kinds_
    roles = _roles(doc, r.driver_id)
    assert roles["back_pan"] == 11 and roles["insulation"] == 11, roles
    # style swap keeps the grid
    for style in ("ssg4", "ssg2", "butt", "unitized", "captured"):
        r = engine.update_params(doc, drv(), {"style": style}, lib)
        assert not _bad(r), (style, r.warnings)
        check(doc, lib, "edit -> " + style, r, style)
    # a transom outside the wall is skipped with a warning
    r = engine.update_params(doc, drv(), {"transoms": [36, 400]}, lib)
    assert any("outside" in w for w in r.warnings), r.warnings
    say("  grid edits: equal / fixed / list / transoms / rows / cells / style swap OK")
    return r.driver_id


def lods(doc, lib):
    f = lambda v: _ft(doc, v)
    out = {}
    for k, style in enumerate(("captured", "unitized")):
        x = 40 + 30 * k
        r = engine.create(doc, _add(doc, G.LineCurve(G.Point3d(f(x), f(-200), 0), G.Point3d(f(x + 15), f(-200), 0))),
                          ASM[style], {"height": 320, "stack": [160], "slabs": [160],
                                       "transoms": [30, 126, 190, 286],
                                       "infill": {"rows": ["vision", "vision", "spandrel", "vision", "vision"]}}, lib)
        drv = doc.Objects.FindId(r.driver_id)
        for lod in ("schematic", "design", "detail"):
            r = engine.update_params(doc, drv, {"lod": lod}, lib)
            drv = doc.Objects.FindId(r.driver_id)
            ctx, roles = check(doc, lib, "{} lod {}".format(style, lod), r, style)
            out[(style, lod)] = roles
    c = lambda st, lod, role: out[(st, lod)][role]
    say("   ", dict(out[("captured", "detail")]))
    assert c("captured", "schematic", "cap") == 0 and c("captured", "schematic", "glass") == 12
    assert c("captured", "schematic", "back_pan") == 0
    assert c("captured", "design", "cap") > 0 and c("captured", "design", "gasket") == 0
    assert c("captured", "design", "glass") == 12 and c("captured", "design", "spacer") == 0
    assert c("captured", "detail", "gasket") > 0 and c("captured", "detail", "spacer") > 0
    assert c("captured", "detail", "anchor") == 4 * 4 and c("captured", "detail", "fire_safing") == 3
    assert c("captured", "detail", "setting_block") > 0 and c("captured", "detail", "perimeter_sealant") > 0
    assert c("unitized", "detail", "stack_male") == 3 and c("unitized", "detail", "stack_female") == 3
    assert c("unitized", "detail", "mullion_female") == 2 * 2 * 2, out[("unitized", "detail")]
    say("  LODs OK")


def door(doc, lib):
    """A door hosted in a curtain wall bay: unit sized to the bay, head transom, no sill."""
    f = lambda v: _ft(doc, v)
    r = engine.create(doc, _add(doc, G.LineCurve(G.Point3d(0, f(-230), 0), G.Point3d(f(20), f(-230), 0))),
                      ASM["captured"], {"height": 144}, lib)
    host = doc.Objects.FindId(r.driver_id)
    op, r = engine.add_opening(doc, host, "Door - Aluminum Entrance, Full Lite", {"height": 84},
                               G.Point3d(f(7), f(-230), 0), lib)
    assert not _bad(r), r.warnings
    roles = _roles(doc, r.driver_id)
    assert roles["leaf"] == 1 and roles["frame"] >= 3 and roles["swing"] == 2, roles
    ctx = _ctx(doc, lib, r.driver_id)
    op_ = ctx.openings[0]
    s = cwkind.summary(ctx)
    total = sum(p["count"] for p in s["panels"])
    # the door bay: door + head transom replace the two lower cells, one vision cell over the door
    assert total == len(ctx.grid.bays) * len(ctx.grid.rows) - 1, (total, s)
    sills = [o for o in meta.parts_of(doc, r.driver_id) if meta.get(o, meta.ROLE) == "sill"]
    assert len(sills) == len(ctx.grid.bays) - 1, len(sills)
    line = doc.Objects.FindId(op.Id).Geometry
    assert abs(line.GetLength() - op_.W) < 1e-6, "door line not resized to the bay"
    say("  door in bay {}: width {}".format(op_.cw_bay, units.format_inches(op_.W / ctx.s)))
    return r.driver_id


def cw_schedule(doc, lib, ids):
    rows = schedule.curtain_walls(doc, ids)
    say(schedule.format_curtain_walls(rows))
    assert rows and all(r["count"] > 0 and r["area_ft2"] > 0 for r in rows), rows
    take = schedule.takeoff(doc, ids)
    glass = [t for t in take if t["material"] == "Glass" and t["role"] == "glass"]
    assert glass and glass[0]["area_ft2"] > 0, "glass area missing in the takeoff"
    vision = sum(r["area_ft2"] for r in rows if r["panel"] == "vision")
    assert abs(glass[0]["area_ft2"] - vision) < 0.05 * vision, (glass[0]["area_ft2"], vision)
    say("  schedule: {} rows, vision glass {:.1f} ft2".format(len(rows), vision))


def run(doc, clear=True, drawing_on=True, captures=True, log=None):
    assert not doc.Path, "test_phase5 clears the document: run it in an empty, unsaved model"
    LOG[0] = log
    if clear:
        for o in list(doc.Objects):
            doc.Objects.Delete(o, True)
        for i in range(doc.NamedViews.Count - 1, -1, -1):
            doc.NamedViews.Delete(i)
    engine.setup_document(doc)
    lib = library.get(force_reload=True)
    t0 = time.time()
    say("-- styles x drivers")
    ids = styles_on_drivers(doc, lib)
    say("-- grid edits")
    grid_edits(doc, lib)
    say("-- LODs")
    lods(doc, lib)
    say("-- door in a bay")
    door(doc, lib)
    say("-- schedule")
    cw_schedule(doc, lib, [ids[("captured", "straight")], ids[("captured", "L convex")]])
    if captures:
        try:
            cap = runpy.run_path(os.path.join(HERE, "capture.py"))["capture"]
            v = [x for x in doc.Views if x.ActiveViewport.Name == "Perspective"][0]
            vp = v.ActiveViewport
            f = lambda v_: _ft(doc, v_)
            vp.ChangeToPerspectiveProjection(True, 35)
            vp.SetCameraLocations(G.Point3d(f(30), f(-50), f(6)), G.Point3d(f(70), f(-130), f(30)))
            say(cap(doc, "phase5_styles", zoom_extents=False))
            vp.SetCameraLocations(G.Point3d(f(30), f(-20), f(8)), G.Point3d(f(48), f(-36), f(12)))
            say(cap(doc, "phase5_corners", zoom_extents=False))
        except Exception as ex:
            say("captures skipped:", ex)
    if drawing_on:
        say("-- drawings")
        for i, style in enumerate(("captured", "ssg4", "ssg2", "butt", "unitized")):
            extra = {"spacing": 60} if style == "butt" else None
            dwg, _ = plan_detail(doc, lib, style, x0=200 + 20 * i, extra=extra)
            assert dwg.stats["regions"] >= 6, (style, dwg.stats)
        dwg, _ = plan_detail(doc, lib, "captured", x0=320, corner=True, out_name="d_curtainwall_plan_corner")
        assert dwg.stats["regions"] >= 12, dwg.stats
        dwg, _, _ = section_detail(doc, lib)
        mats = set(rg.material for rg in dwg.regions)
        say("   cut materials:", sorted(mats))
        for m in ("Glass", "Spandrel Glass", "Aluminum", "Gasket", "Back Pan", "Mineral Wool Board",
                  "Steel Angle", "Fire Safing", "Concrete"):
            assert m in mats, "{} missing from the spandrel section".format(m)
        section_detail(doc, lib, x0=240, style="unitized", name="d_curtainwall_section_unitized")
    doc.Views.Redraw()
    say("total {:.1f}s".format(time.time() - t0))
    say("PHASE 5 OK")
