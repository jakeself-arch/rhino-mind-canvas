"""Phase 6: floors + roofs.

Run inside Rhino (e.g. via the MCP run_python tool), in an EMPTY, unsaved document (it is cleared):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_phase6.py")["run"](__rhino_doc__)

Covers floors (wood 2x10, I-joist, metal C-joists, concrete on metal deck) on rectangular and
L-shaped boundaries in both span directions, the wood <-> metal swap, every LOD; roofs (gable with a
vented attic, cathedral gable, shed, low-slope flat with tapered insulation) on rectangular, L-shaped
and irregular boundaries, pitch / overhang / shape / ridge edits, the metal swap, every LOD; the
schedules. drawing_on=True writes 1-1/2" details to docs/drawings/: e_roof_eave_section_1-1-2
(eave: rafter, birdsmouth, fascia, sub-fascia, soffit, gutter, drip edge, shingles, ice shield,
ceiling joist, attic insulation, the wall below), e_floor_section_1-1-2 (platform frame: wall,
rim joist, joist, subfloor, finish floor, ceiling, wall above), e_floor_deck_section_1-1-2
(concrete on composite metal deck over C-joists) and e_roof_flat_edge_1-1-2 (low-slope edge).
log= a file path: progress is appended there.
"""

import os
import runpy
import time
from collections import Counter

import Rhino

from mindcanvas import docutil, engine, library, meta, schedule, units
from mindcanvas.kinds import floor as floorkind
from mindcanvas.kinds import roof as roofkind

G = Rhino.Geometry
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = [None]

F_WOOD = "Floor - 2x10 Wood Joists, Plywood"
F_IJOIST = "Floor - 11-7/8\" I-Joist, OSB"
F_METAL = "Floor - 10\" Metal Joists, Plywood"
F_DECK = "Floor - Concrete on Metal Deck / 10\" Metal Joists"
R_ATTIC = "Roof - Asphalt Shingle / 2x8 Rafters, Vented Attic"
R_CATH = "Roof - Asphalt Shingle / 2x10 Rafters, Cathedral"
R_SHED = "Roof - Asphalt Shingle / 2x10 Rafters, Shed"
R_FLAT = "Roof - Low Slope Membrane / 2x10 Joists"
WALL = "Ext - 2x6 Wood, Fiber Cement"
PLATE = 109.0     # wall height = plate height (inches)


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


def _poly(doc, pts_ft, z=0.0):
    f = lambda v: _ft(doc, v)
    pts = [G.Point3d(f(x), f(y), z) for x, y in pts_ft]
    return G.PolylineCurve(pts + [pts[0]])


def rect(doc, x, y, w, h):
    return _poly(doc, [(x, y), (x + w, y), (x + w, y + h), (x, y + h)])


def ell(doc, x, y):
    """L: 30' x 24' with a 14' x 12' notch (top right)."""
    return _poly(doc, [(x, y), (x + 30, y), (x + 30, y + 12), (x + 16, y + 12), (x + 16, y + 24), (x, y + 24)])


def roles(doc, drv_id):
    return Counter(meta.get(o, meta.ROLE) for o in meta.parts_of(doc, drv_id))


def _bad(r):
    return [w for w in r.warnings if "fail" in w.lower() or "could not" in w.lower() or "unknown" in w.lower()]


def _ctx(doc, lib, drv_id):
    drv = doc.Objects.FindId(drv_id)
    kmod = floorkind if meta.get(drv, meta.TYPE) == "floor" else roofkind
    return kmod.make_context(doc, lib, drv, meta.get(drv, meta.ASSEMBLY), meta.params(drv))


def _center(o):
    """World bounding-box center of a part (block instances: their definition, placed)."""
    if isinstance(o, Rhino.DocObjects.InstanceObject):
        bb = G.BoundingBox.Empty
        for x in o.InstanceDefinition.GetObjects():
            bb.Union(x.Geometry.GetBoundingBox(True))
        c = bb.Center
        c.Transform(o.InstanceXform)
        return c
    return o.Geometry.GetBoundingBox(True).Center


def _check_solids(doc, drv_id, label):
    """Every plain brep part is a closed solid (block definitions are checked once per definition)."""
    seen = set()
    for o in meta.parts_of(doc, drv_id):
        if isinstance(o, Rhino.DocObjects.InstanceObject):
            idef = o.InstanceDefinition
            if idef.Index in seen:
                continue
            seen.add(idef.Index)
            geoms = [x.Geometry for x in idef.GetObjects()]
        else:
            geoms = [o.Geometry]
        for g in geoms:
            if isinstance(g, G.Brep):
                assert g.IsSolid, "{}: open brep ({} / {})".format(label, meta.get(o, meta.ROLE), meta.get(o, meta.MATERIAL))


# -- drawings ---------------------------------------------------------------------------------------
def _view(doc, name):
    v = [x for x in doc.Views if x.ActiveViewport.Name == name][0]
    v.Maximized = True
    doc.Views.ActiveView = v
    return v


def _clear_clips(doc):
    for o in list(doc.Objects.FindByObjectType(Rhino.DocObjects.ObjectType.ClipPlane) or []):
        doc.Objects.Delete(o, True)


def _draw(doc, lib, drv_id, at, lo, hi, name, depth_in=30.0, view_name="Front"):
    """Section through drv at `at`; crop to the world box lo..hi; write docs/drawings/<name>."""
    from mindcanvas.drawing import pipeline, sectioncut, styles
    st = styles.get("1-1/2", lib)
    drv = doc.Objects.FindId(drv_id)
    _clear_clips(doc)
    view = _view(doc, view_name)
    sectioncut.make(doc, drv, at, view, name="phase6 " + name, depth_in=depth_in, style=st)
    box = G.BoundingBox([lo, hi])
    view.ActiveViewport.ZoomBoundingBox(box)
    doc.Views.Redraw()
    t = time.time()
    dwg = pipeline.make(doc, view, st, True, False, say, window=[box.Min, box.Max])
    paths = pipeline.write(dwg, os.path.join(ROOT, "docs", "drawings", name), px_per_mm=16)
    say("  drawing {}: {:.1f}s {} -> {}".format(name, time.time() - t, dwg.stats, os.path.basename(paths[-1])))
    _clear_clips(doc)
    return dwg


def eave_detail(doc, lib, x0=0.0, y0=-120.0):
    """Gable roof (vented attic) on a 2x6 wall: section at the eave between two rafters."""
    f = lambda v: _ft(doc, v)
    inch = units.inch_scale(doc)
    w = engine.create(doc, _add(doc, G.LineCurve(G.Point3d(f(x0 + 30), f(y0), 0), G.Point3d(f(x0), f(y0), 0))),
                      WALL, {"height": PLATE, "reference": "core_exterior"}, lib)
    assert not _bad(w), w.warnings
    r = engine.create(doc, _add(doc, rect(doc, x0, y0, 30, 20)), R_ATTIC, {"base_offset": PLATE}, lib)
    assert not _bad(r), r.warnings
    # between the rafters at 168" and 192" from the gable end at x0 + 30'
    xs = x0 * 12 + 360 - 180.0
    at = G.Point3d(xs * inch, f(y0) + 3 * inch, PLATE * inch)
    lo = G.Point3d(xs * inch, f(y0) - 30 * inch, (PLATE - 22) * inch)
    hi = G.Point3d(xs * inch, f(y0) + 34 * inch, (PLATE + 24) * inch)
    dwg = _draw(doc, lib, r.driver_id, at, lo, hi, "e_roof_eave_section_1-1-2", depth_in=26.0)
    return dwg, r.driver_id, w.driver_id


def floor_detail(doc, lib, asm=F_WOOD, x0=0.0, y0=-170.0, name="e_floor_section_1-1-2"):
    """Platform frame: 2x6 wall, floor on its plates, wall above; section along the joists between two."""
    f = lambda v: _ft(doc, v)
    inch = units.inch_scale(doc)
    fl = engine.create(doc, _add(doc, rect(doc, x0, y0, 28, 14)), asm, {"base_offset": PLATE}, lib)
    assert not _bad(fl), fl.warnings
    ctx = _ctx(doc, lib, fl.driver_id)
    top_in = (ctx.base_z + ctx.height) / inch
    sub = [b for b in ctx.bands if b.name in ("Subfloor", "Topping")]
    base_in = sub[0].d_ext / inch if sub else top_in
    depth_in = top_in - PLATE
    ext = {"extend_top": depth_in}
    line = lambda: _add(doc, G.LineCurve(G.Point3d(f(x0 + 28), f(y0), 0), G.Point3d(f(x0), f(y0), 0)))
    w1 = engine.create(doc, line(), WALL, {"height": PLATE, "reference": "core_exterior",
                                           "overrides": {"Siding": ext, "WRB": ext, "Sheathing": ext}}, lib)
    w2 = engine.create(doc, line(), WALL, {"height": 60, "base_offset": base_in, "reference": "core_exterior"}, lib)
    assert not _bad(w1) and not _bad(w2), (w1.warnings, w2.warnings)
    xs = x0 * 12 + 336 - 168.0           # between the joists at 160" and 176"
    at = G.Point3d(xs * inch, f(y0) + 3 * inch, PLATE * inch)
    lo = G.Point3d(xs * inch, f(y0) - 6 * inch, (PLATE - 14) * inch)
    hi = G.Point3d(xs * inch, f(y0) + 30 * inch, (top_in + 14) * inch)
    dwg = _draw(doc, lib, fl.driver_id, at, lo, hi, name, depth_in=20.0)
    return dwg, fl.driver_id


def flat_detail(doc, lib, x0=80.0, y0=-120.0):
    """Low-slope roof on a 2x6 wall: section at the low eave (tapered insulation, membrane, edge metal)."""
    f = lambda v: _ft(doc, v)
    inch = units.inch_scale(doc)
    engine.create(doc, _add(doc, G.LineCurve(G.Point3d(f(x0 + 24), f(y0), 0), G.Point3d(f(x0), f(y0), 0))),
                  WALL, {"height": PLATE, "reference": "core_exterior"}, lib)
    r = engine.create(doc, _add(doc, rect(doc, x0, y0, 24, 16)), R_FLAT, {"base_offset": PLATE, "ridge": 0}, lib)
    assert not _bad(r), r.warnings
    xs = x0 * 12 + 288 - 152.0          # between joists
    at = G.Point3d(xs * inch, f(y0) + 3 * inch, PLATE * inch)
    lo = G.Point3d(xs * inch, f(y0) - 22 * inch, (PLATE - 18) * inch)
    hi = G.Point3d(xs * inch, f(y0) + 30 * inch, (PLATE + 22) * inch)
    return _draw(doc, lib, r.driver_id, at, lo, hi, "e_roof_flat_edge_1-1-2", depth_in=20.0), r.driver_id


def run_drawings(doc, lib):
    dwg, rid, wid = eave_detail(doc, lib)
    mats = set(rg.material for rg in dwg.regions)
    say("   eave cut materials:", sorted(mats))
    for m in ("Asphalt Shingles", "Plywood Sheathing", "Wood Trim", "Wood Framing", "Soffit Panel", "Gutter",
              "Gypsum Board", "Blown Insulation", "Fiber Cement Siding", "Ice and Water Shield", "Flashing"):
        assert m in mats, "{} missing from the eave section".format(m)
    dwg, fid = floor_detail(doc, lib)
    mats = set(rg.material for rg in dwg.regions)
    say("   floor cut materials:", sorted(mats))
    for m in ("Wood Flooring", "Plywood Sheathing", "Wood Framing", "Gypsum Board", "OSB Sheathing"):
        assert m in mats, "{} missing from the floor section".format(m)
    dwg, _ = floor_detail(doc, lib, F_DECK, x0=40.0, name="e_floor_deck_section_1-1-2")
    mats = set(rg.material for rg in dwg.regions)
    for m in ("Concrete", "Metal Deck", "Cold-Formed Steel"):
        assert m in mats, "{} missing from the deck section".format(m)
    dwg, _ = flat_detail(doc, lib)
    mats = set(rg.material for rg in dwg.regions)
    say("   flat edge cut materials:", sorted(mats))
    for m in ("Roof Membrane", "Cover Board", "Polyiso Tapered Insulation", "Polyiso Board", "Plywood Sheathing"):
        assert m in mats, "{} missing from the flat roof edge".format(m)


# -- floors -----------------------------------------------------------------------------------------
def _joists(doc, drv_id):
    return [o for o in meta.parts_of(doc, drv_id) if meta.get(o, meta.ROLE) == "joist"]


def _len(o):
    return float(meta.get(o, meta.EXTRA_PREFIX + "length"))


def floors(doc, lib, y0=60.0):
    out = {}
    # rectangle 28' x 14', joists across the short way: 20 joists at 16" from the edge, 14' - 2 rims long
    r = engine.create(doc, _add(doc, rect(doc, 0, y0, 28, 14)), F_WOOD, {}, lib)
    assert not _bad(r) and not r.warnings, r.warnings
    js = _joists(doc, r.driver_id)
    assert len(js) == 20 and all(abs(_len(j) - 165.0) < 1e-3 for j in js), (len(js), set(_len(j) for j in js))
    rl = roles(doc, r.driver_id)
    assert rl["rim_joist"] == 1 and rl["blocking"] == 19, rl     # one mid-span row (14' < 2 x 8')
    _check_solids(doc, r.driver_id, "wood rect")
    s = floorkind.summary(_ctx(doc, lib, r.driver_id))
    assert s["joists"] == 20 and abs(s["max_span_ft"] - 165 / 12.0) < 1e-3, s
    say("  wood rect: {} parts, {} joists, span {:.2f} ft, {:.2f}s".format(len(r.part_ids), len(js), s["max_span_ft"], r.seconds))
    drv = lambda: doc.Objects.FindId(r.driver_id)
    # the other span direction: 10 joists, 28' long (over the table: warned)
    r = engine.update_params(doc, drv(), {"span": "long"}, lib)
    js = _joists(doc, r.driver_id)
    assert len(js) == 10 and all(abs(_len(j) - 333.0) < 1e-3 for j in js), (len(js), set(_len(j) for j in js))
    assert any("exceeds" in w for w in r.warnings), r.warnings
    rl = roles(doc, r.driver_id)
    assert rl["blocking"] == 9 * 3, rl                          # 28' -> three rows
    # an explicit angle == short
    r = engine.update_params(doc, drv(), {"span": 90}, lib)
    assert len(_joists(doc, r.driver_id)) == 20
    # wood <-> metal: one line; 2x10 -> 10" C-joists in a track, the layer grows by 2 x t
    r = engine.set_override(doc, drv(), "Framing", "system", "metal", lib)
    assert not _bad(r), r.warnings
    ctx = _ctx(doc, lib, r.driver_id)
    band = floorkind.framing_band(ctx)
    assert abs(band.thickness / ctx.s - (10 + 2 * 0.0566)) < 1e-6, band.thickness / ctx.s
    js = _joists(doc, r.driver_id)
    assert js and all("Metal Joist" in meta.get(j, meta.EXTRA_PREFIX + "member") for j in js)
    rl = roles(doc, r.driver_id)
    assert rl["bridging"] > 0 and rl["blocking"] > 0, rl
    _check_solids(doc, r.driver_id, "metal swap")
    r = engine.set_override(doc, drv(), "Framing", "system", "wood", lib)
    assert len(_joists(doc, r.driver_id)) == 20
    out["wood"] = r.driver_id
    # LODs
    for lod, want, never in (("schematic", {"framing", "solid"}, {"joist", "blocking"}),
                             ("design", {"joist", "rim_joist", "solid"}, {"blocking", "framing"}),
                             ("detail", {"joist", "rim_joist", "blocking"}, {"framing"})):
        r = engine.update_params(doc, drv(), {"lod": lod}, lib)
        rl = set(roles(doc, r.driver_id))
        assert want <= rl and not (never & rl), (lod, rl)
    say("  wood rect: span long / angle / metal swap / LODs OK")
    # L-shapes: every joist sits inside the boundary and clear of the notch
    for asm, span, key in ((F_WOOD, "short", "L wood"), (F_METAL, "long", "L metal"), (F_IJOIST, "short", "L I-joist")):
        x = {"L wood": 40, "L metal": 80, "L I-joist": 120}[key]
        crv = ell(doc, x, y0)
        r = engine.create(doc, _add(doc, crv), asm, {"span": span}, lib)
        assert not _bad(r), (key, r.warnings)
        js = _joists(doc, r.driver_id)
        assert len(js) > 8, (key, len(js))
        for j in js:
            c = _center(j)
            pc = crv.Contains(G.Point3d(c.X, c.Y, 0), G.Plane.WorldXY, doc.ModelAbsoluteTolerance)
            assert pc == G.PointContainment.Inside, (key, "joist outside the boundary")
        _check_solids(doc, r.driver_id, key)
        rl = roles(doc, r.driver_id)
        if asm == F_IJOIST:
            assert rl["insulation"] > 0 and "Wood I-Joist" in set(meta.get(o, meta.MATERIAL) for o in js), rl
        out[key] = r.driver_id
        say("  {}: {} parts, {} joists, {:.2f}s".format(key, len(r.part_ids), len(js), r.seconds))
    # concrete on metal deck: one pour (topping absorbed into the flute fill)
    r = engine.create(doc, _add(doc, rect(doc, 160, y0, 20, 12)), F_DECK, {}, lib)
    assert not _bad(r), r.warnings
    rl = roles(doc, r.driver_id)
    assert rl["deck"] == 1 and rl["deck_fill"] == 1, rl
    assert not [o for o in meta.parts_of(doc, r.driver_id) if meta.get(o, meta.LAYER) == "Topping"]
    _check_solids(doc, r.driver_id, "deck")
    r2 = engine.create(doc, _add(doc, ell(doc, 190, y0)), F_DECK, {}, lib)
    assert not _bad(r2), r2.warnings
    assert roles(doc, r2.driver_id)["deck"] >= 1
    out["deck"] = r.driver_id
    say("  deck: rect + L OK")
    return out


# -- roofs ------------------------------------------------------------------------------------------
def _ridge(doc, lib, drv_id):
    return roofkind.summary(_ctx(doc, lib, drv_id))


def _role_len(doc, drv_id, role):
    return sorted(set(round(_len(o), 3) for o in meta.parts_of(doc, drv_id) if meta.get(o, meta.ROLE) == role))


def roofs(doc, lib, y0=120.0):
    out = {}
    prm = {"base_offset": PLATE}
    # gable, vented attic: 30' x 20', ridge along the 30' side, rafters 24" o.c. (16 per side incl. the
    # end rafters over the gable walls), barge rafters at the rakes, ceiling joists beside every rafter
    r = engine.create(doc, _add(doc, rect(doc, 0, y0, 30, 20)), R_ATTIC, prm, lib)
    assert not _bad(r) and not r.warnings, r.warnings
    rl = roles(doc, r.driver_id)
    assert rl["rafter"] == 32 and rl["barge_rafter"] == 4 and rl["ceiling_joist"] == 32 and rl["ridge"] == 1, rl
    for role in ("fascia", "subfascia", "soffit", "soffit_vent", "gutter", "drip_edge", "rake_board", "lookout",
                 "bird_block", "shingle_course", "eave_membrane", "ridge_cap", "insulation"):
        assert rl[role] > 0, (role, rl)
    assert len(_role_len(doc, r.driver_id, "rafter")) == 1, _role_len(doc, r.driver_id, "rafter")
    _check_solids(doc, r.driver_id, "gable attic")
    s = _ridge(doc, lib, r.driver_id)
    assert s["rafters"] == 32 and s["ridge"] > PLATE + 120 * 0.5, s
    say("  gable attic: {} parts, ridge {}, {:.2f}s".format(len(r.part_ids), units.format_inches(s["ridge"]), r.seconds))
    drv = lambda: doc.Objects.FindId(r.driver_id)
    # pitch / overhang edits
    L0 = _role_len(doc, r.driver_id, "rafter")[0]
    r = engine.update_params(doc, drv(), {"pitch": 9}, lib)
    s9 = _ridge(doc, lib, r.driver_id)
    assert abs(s9["ridge"] - s["ridge"] - 114.5 * 0.25) < 2.0, (s["ridge"], s9["ridge"])   # 9:12 over the 9'-6 1/2" run
    L9 = _role_len(doc, r.driver_id, "rafter")[0]
    assert L9 > L0, (L0, L9)
    r = engine.update_params(doc, drv(), {"pitch": 6, "overhang": 24}, lib)
    L24 = _role_len(doc, r.driver_id, "rafter")[0]
    assert abs((L24 - L0) - 6 * 1.25 ** 0.5) < 0.01, (L0, L24)       # 6" more run along a 6:12 slope
    # ridge the short way: 20 rafters... per side of the 20' run
    r = engine.update_params(doc, drv(), {"overhang": 18, "ridge": "short"}, lib)
    assert not _bad(r), r.warnings
    assert roles(doc, r.driver_id)["rafter"] == 2 * 11, roles(doc, r.driver_id)["rafter"]
    # shape edits
    r = engine.update_params(doc, drv(), {"ridge": "long", "shape": "shed", "pitch": 3}, lib)
    assert not _bad(r), r.warnings
    rl = roles(doc, r.driver_id)
    assert rl["rafter"] == 16 and rl["ridge"] == 0 and rl["gutter"] == 1, rl
    r = engine.update_params(doc, drv(), {"shape": "flat"}, lib)
    rl = roles(doc, r.driver_id)
    assert rl["roof_joist"] == 16 and rl["shingle_course"] == 0, rl      # shingles need slope: slab
    r = engine.update_params(doc, drv(), {"shape": None, "pitch": None}, lib)
    assert roles(doc, r.driver_id)["rafter"] == 32
    # wood <-> metal: one line
    r = engine.set_override(doc, drv(), "Rafters", "system", "metal", lib)
    assert not _bad(r), r.warnings
    rf = [o for o in meta.parts_of(doc, r.driver_id) if meta.get(o, meta.ROLE) == "rafter"]
    assert len(rf) == 32 and all("Metal Joist" in meta.get(o, meta.EXTRA_PREFIX + "member") for o in rf), \
        set(meta.get(o, meta.EXTRA_PREFIX + "member") for o in rf)
    assert roles(doc, r.driver_id)["bird_block"] == 0
    _check_solids(doc, r.driver_id, "gable metal")
    r = engine.set_override(doc, drv(), "Rafters", "system", None, lib)
    # LODs
    for lod, want, never in (("schematic", {"framing", "solid", "roofing"}, {"rafter", "fascia"}),
                             ("design", {"rafter", "ridge", "fascia", "ceiling_joist", "roofing"},
                              {"shingle_course", "gutter", "bird_block"}),
                             ("detail", {"rafter", "shingle_course", "gutter", "bird_block"}, {"framing"})):
        r = engine.update_params(doc, drv(), {"lod": lod}, lib)
        rl = set(roles(doc, r.driver_id))
        assert want <= rl and not (never & rl), (lod, rl)
    out["attic"] = r.driver_id
    say("  gable attic: pitch / overhang / ridge / shape / metal / LOD edits OK")
    # cathedral gable: batts between the rafters, vapor retarder + gypsum under them
    r = engine.create(doc, _add(doc, rect(doc, 40, y0, 30, 20)), R_CATH, prm, lib)
    assert not _bad(r), r.warnings
    rl = roles(doc, r.driver_id)
    mats = set(meta.get(o, meta.MATERIAL) for o in meta.parts_of(doc, r.driver_id))
    assert rl["insulation"] > 0 and "Gypsum Board" in mats and "Vapor Retarder" in mats and rl["ceiling_joist"] == 0, rl
    _check_solids(doc, r.driver_id, "cathedral")
    out["cathedral"] = r.driver_id
    # shed: high plate reported, gutter on the low side only
    r = engine.create(doc, _add(doc, rect(doc, 80, y0, 24, 14)), R_SHED, prm, lib)
    assert not _bad(r), r.warnings
    s = _ridge(doc, lib, r.driver_id)
    assert s["high_plate"] and abs(s["high_plate"] - (PLATE + (168 - 5.5) * 0.25)) < 0.01, s
    assert roles(doc, r.driver_id)["gutter"] == 1
    _check_solids(doc, r.driver_id, "shed")
    out["shed"] = r.driver_id
    # flat (low slope) on an L: tapered insulation thickens away from the low eave
    r = engine.create(doc, _add(doc, ell(doc, 0, y0 + 30)), R_FLAT, prm, lib)
    assert not _bad(r), r.warnings
    tap = [o for o in meta.parts_of(doc, r.driver_id) if meta.get(o, meta.MATERIAL) == "Polyiso Tapered Insulation"]
    assert tap, "no tapered insulation"
    bb = tap[0].Geometry.GetBoundingBox(True)
    assert (bb.Max.Z - bb.Min.Z) / units.inch_scale(doc) > 3.0, "taper missing"
    assert roles(doc, r.driver_id)["roof_joist"] > 10
    _check_solids(doc, r.driver_id, "flat L")
    out["flat L"] = r.driver_id
    # shed on an L, gable on an irregular footprint (oblique rakes)
    r = engine.create(doc, _add(doc, ell(doc, 40, y0 + 30)), R_SHED, prm, lib)
    assert not _bad(r), r.warnings
    _check_solids(doc, r.driver_id, "shed L")
    out["shed L"] = r.driver_id
    trap = _poly(doc, [(80, y0 + 30), (110, y0 + 30), (106, y0 + 50), (84, y0 + 50)])
    r = engine.create(doc, _add(doc, trap), R_ATTIC, prm, lib)
    assert not _bad(r), r.warnings
    rl = roles(doc, r.driver_id)
    assert rl["rafter"] > 20 and rl["fascia"] >= 4, rl
    _check_solids(doc, r.driver_id, "gable trapezoid")
    out["gable trapezoid"] = r.driver_id
    say("  cathedral / shed / flat L / shed L / gable trapezoid OK")
    return out


def schedules(doc, lib, ids):
    rows = schedule.floors_roofs(doc, ids)
    say(schedule.format_floors_roofs(rows))
    assert all("error" not in r for r in rows), rows
    mem = schedule.framing_members(doc, ids)
    say(schedule.format_framing_members(mem))
    rafters = sum(r["count"] for r in mem if r["role"] == "rafter")
    joists = sum(r["count"] for r in mem if r["role"] == "joist")
    assert rafters == 32 and joists == 20, (rafters, joists)
    take = schedule.takeoff(doc, ids)
    assert any(t["role"] == "joist" and t["length_ft"] > 0 for t in take)
    say("  schedules OK")


def lod_switch(doc, lib):
    from mindcanvas.drawing import pipeline
    n = pipeline.set_lod(doc, "1/8")
    fr = [d for d in meta.all_drivers(doc) if meta.get(d, meta.TYPE) in ("floor", "roof")]
    assert n >= len(fr) and all(meta.params(d).get("lod") == "schematic" for d in fr)
    pipeline.set_lod(doc, "1-1/2")
    assert all(meta.params(d).get("lod") == "detail" for d in fr)
    say("  SetLOD over floors + roofs OK ({} rebuilt)".format(n))


def run(doc, clear=True, drawing_on=True, captures=True, log=None, only=None):
    assert not doc.Path, "test_phase6 clears the document: run it in an empty, unsaved model"
    LOG[0] = log
    if clear:
        for o in list(doc.Objects):
            doc.Objects.Delete(o, True)
        for i in range(doc.NamedViews.Count - 1, -1, -1):
            doc.NamedViews.Delete(i)
        docutil.purge_unused_blocks(doc)
    engine.setup_document(doc)
    lib = library.get(force_reload=True)
    t0 = time.time()
    if only == "drawings":
        run_drawings(doc, lib)
        say("total {:.1f}s".format(time.time() - t0))
        return
    say("-- floors")
    fl = floors(doc, lib)
    say("-- roofs")
    rf = roofs(doc, lib)
    say("-- schedules")
    schedules(doc, lib, [fl["wood"], rf["attic"]])
    say("-- SetLOD")
    lod_switch(doc, lib)
    if captures:
        try:
            cap = runpy.run_path(os.path.join(HERE, "capture.py"))["capture"]
            v = [x for x in doc.Views if x.ActiveViewport.Name == "Perspective"][0]
            vp = v.ActiveViewport
            vp.ConstructionGridVisible = False
            vp.ConstructionAxesVisible = False
            f = lambda v_: _ft(doc, v_)
            vp.ChangeToPerspectiveProjection(True, 35)
            vp.SetCameraLocations(G.Point3d(f(55), f(148), f(10)), G.Point3d(f(5), f(75), f(70)))
            say(cap(doc, "phase6_roofs", zoom_extents=False, width=1400, height=900))
            hidden = []
            for o in doc.Objects:
                if meta.get(o, meta.MATERIAL) == "Gypsum Board" and meta.get(o, meta.DRIVER) in (str(fl["wood"]), str(fl["L wood"]), str(fl["L metal"])):
                    hidden.append(o.Id)
                    doc.Objects.Hide(o, True)
            vp.SetCameraLocations(G.Point3d(f(100), f(73), f(0)), G.Point3d(f(70), f(30), f(-30)))
            say(cap(doc, "phase6_floors_below", zoom_extents=False, width=1400, height=900))
            for i in hidden:
                doc.Objects.Show(i, True)
        except Exception as ex:
            say("captures skipped:", ex)
    if drawing_on:
        say("-- drawings")
        run_drawings(doc, lib)
    doc.Views.Redraw()
    say("total {:.1f}s".format(time.time() - t0))
    say("PHASE 6 OK")
