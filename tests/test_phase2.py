"""Phase 2: brick veneer - bricks, bonds, mortar, ties, flashing, weeps, shelf angle.

Run inside Rhino (e.g. via the MCP run_python tool):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_phase2.py")["run"](__rhino_doc__)

The library assemblies use the `framing` component for the stud layer. The tests build copies
whose framing layer is a plain solid ("_test ..." assemblies, registered in memory only), so they
never depend on the framing component; run(doc, real=True) also builds the real assemblies.
"""

import copy
import os
import runpy
import time
from collections import Counter

import Rhino

from mindcanvas import docutil, engine, library, meta, units

G = Rhino.Geometry
HERE = os.path.dirname(os.path.abspath(__file__))
CAPTURE = runpy.run_path(os.path.join(HERE, "capture.py"))["capture"]

STEEL = "Ext - Brick Veneer / 6\" Metal Stud"
SHELF = "Ext - Brick Veneer / 6\" Metal Stud, Shelf Angle"
REAL = [STEEL, SHELF, "Ext - Brick Veneer / 2x6 Wood", "Ext - Brick Veneer / 3-5/8\" Metal Stud, 3\" CI"]
BONDS = ["running", "third", "stack", "flemish", "english", "common"]
BRICK_ROLES = ("brick", "brick_half", "brick_header", "brick_closure", "brick_soldier", "brick_rowlock",
               "brick_sailor", "brick_shiner")


def _test_assembly(lib, name):
    """Copy of a library assembly with the framing layer as a plain solid."""
    a = copy.deepcopy(lib.assembly(name))
    for layer in a["layers"]:
        if layer.get("component") == "framing":
            layer["component"] = "solid"
            layer.pop("options", None)
    tname = "_test " + name
    lib.data["assemblies"][tname] = a
    return tname


def _variant(lib, base, suffix, veneer=None, brick_layer=None, extras=None):
    a = copy.deepcopy(lib.assembly(base))
    if veneer is not None:
        a["layers"][0].setdefault("options", {}).update(veneer)
    if brick_layer is not None:
        a["layers"][0].update(brick_layer)
    if extras is not None:
        a["extras"] = extras
    name = base + " " + suffix
    lib.data["assemblies"][name] = a
    return name


def _ft(doc, feet):
    return units.to_model(doc, feet * 12.0)


def _add(doc, curve):
    return doc.Objects.FindId(doc.Objects.AddCurve(curve))


def _parts(doc, r):
    return meta.parts_of(doc, r.driver_id)


def _roles(doc, r):
    return Counter(meta.get(o, meta.ROLE) for o in _parts(doc, r))


_VOL = {}


def _def_volume(idef):
    if idef.Index not in _VOL:
        v = 0.0
        for o in idef.GetObjects():
            g = o.Geometry
            mp = G.VolumeMassProperties.Compute(g.ToBrep() if isinstance(g, G.Extrusion) else g)
            v += abs(mp.Volume) if mp else 0.0
        _VOL[idef.Index] = v
    return _VOL[idef.Index]


def brick_equivalents(doc, r, brick_in=(7.625, 2.25, 3.625)):
    s = units.inch_scale(doc)
    unit = brick_in[0] * brick_in[1] * brick_in[2] * s ** 3
    vol = 0.0
    for o in _parts(doc, r):
        if meta.get(o, meta.ROLE) in BRICK_ROLES and isinstance(o, Rhino.DocObjects.InstanceObject):
            vol += _def_volume(o.InstanceDefinition)
    return vol / unit


def _boxes(doc, r, roles):
    out = []
    for o in _parts(doc, r):
        if meta.get(o, meta.ROLE) in roles:
            out.append(o.Geometry.GetBoundingBox(True))
    return out


def slivers(doc, r, min_in=0.25):
    """Head joints thinner than min_in in plan (axis-aligned walls only)."""
    s = units.inch_scale(doc)
    n = 0
    for b in _boxes(doc, r, ("mortar_head",)):
        if min(b.Max.X - b.Min.X, b.Max.Y - b.Min.Y) < min_in * s:
            n += 1
    return n


def overlaps(boxes, shrink):
    """Pairs of world boxes that overlap by more than `shrink` (axis-aligned walls only)."""
    boxes = sorted(boxes, key=lambda b: b.Min.X)
    bad = 0
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if b.Min.X >= a.Max.X - shrink:
                break
            if (min(a.Max.Y, b.Max.Y) - max(a.Min.Y, b.Min.Y) > shrink and
                    min(a.Max.Z, b.Max.Z) - max(a.Min.Z, b.Min.Z) > shrink):
                bad += 1
    return bad


def _check(doc, label, r, expect_ties=True):
    roles = _roles(doc, r)
    bad = [w for w in r.warnings if "could not be added" in w or "failed" in w.lower()]
    assert not bad, "{}: {}".format(label, bad)
    assert roles["brick"] > 0, "{}: no bricks ({})".format(label, roles)
    if expect_ties:
        assert roles["brick_tie"] > 0, "{}: no ties".format(label)
        assert roles["flashing"] >= 1, "{}: no flashing".format(label)
    return roles


def ties_in_bed_joints(doc, r, veneer_layer="Brick Veneer"):
    s = units.inch_scale(doc)
    beds = []
    for o in _parts(doc, r):
        if meta.get(o, meta.ROLE) == "mortar_bed":
            bb = o.Geometry.GetBoundingBox(True)
            beds.append((bb.Min.Z, bb.Max.Z))
    n = 0
    for o in _parts(doc, r):
        if meta.get(o, meta.ROLE) == "brick_tie":
            z = o.InstanceXform.M23
            assert any(z0 + 0.05 * s < z < z1 - 0.05 * s for z0, z1 in beds), "tie at z={} not in a bed joint".format(z / s)
            n += 1
    return n


def _section_plane(doc, origin, normal, size):
    vids = [v.ActiveViewportID for v in doc.Views]
    plane = G.Plane(origin, normal)
    return doc.Objects.AddClippingPlane(plane, size, size, vids)


def run(doc, clear=True, real=False, captures=True):
    if clear:
        for o in list(doc.Objects):
            doc.Objects.Delete(o, True)
        docutil.purge_unused_blocks(doc)
    engine.setup_document(doc)
    lib = library.get(True)
    f = lambda v: _ft(doc, v)
    s = units.inch_scale(doc)
    steel = _test_assembly(lib, STEEL)
    shelf = _test_assembly(lib, SHELF)
    results = {}

    # 1. straight 20' x 10' wall, running bond, ledge base: count + timing
    line = G.LineCurve(G.Point3d(f(20), 0, 0), G.Point3d(0, 0, 0))   # exterior faces -Y (Front view)
    t0 = time.time()
    r = engine.create(doc, _add(doc, line), steel, {"height": "10'"}, lib=lib)
    dt = time.time() - t0
    roles = _check(doc, "straight", r)
    eq = brick_equivalents(doc, r)
    per_ft2 = eq / 200.0
    print("straight 20x10 detail: {} parts in {:.2f}s; {:.1f} brick equivalents = {:.2f}/ft2; {}".format(
        len(r.part_ids), dt, eq, per_ft2, dict(roles)))
    assert 6.4 < per_ft2 < 7.1, "modular running bond should be ~6.75 bricks/ft2, got {:.2f}".format(per_ft2)
    assert roles["weep"] >= 8, "expected ~10 weeps on 20', got {}".format(roles["weep"])
    assert overlaps(_boxes(doc, r, BRICK_ROLES + ("mortar_head", "weep")), 0.01 * s) == 0, "bricks/joints overlap"
    assert slivers(doc, r) == 0, "straight: mortar slivers"
    nt = ties_in_bed_joints(doc, r)
    print("  ties: {} (all in bed joints)".format(nt))
    results["straight"] = (r, dt)
    if dt > 3.0:
        print("  WARNING: slower than the 3 s target")

    # design LOD: no mortar
    r = engine.create(doc, _add(doc, G.LineCurve(G.Point3d(f(20), f(-30), 0), G.Point3d(0, f(-30), 0))),
                      steel, {"lod": "design"}, lib=lib)
    roles = _roles(doc, r)
    assert roles["mortar_head"] == 0 and roles["brick_tie"] == 0 and roles["brick"] > 1000, roles
    r = engine.create(doc, _add(doc, G.LineCurve(G.Point3d(f(20), f(-36), 0), G.Point3d(0, f(-36), 0))),
                      steel, {"lod": "schematic"}, lib=lib)
    assert _roles(doc, r)["masonry"] == 1

    # 2. polyline with a left and a right turn (outside + inside corner)
    pl = G.PolylineCurve([G.Point3d(f(30), 0, 0), G.Point3d(f(46), 0, 0), G.Point3d(f(46), f(12), 0),
                          G.Point3d(f(58), f(12), 0)])
    t0 = time.time()
    r = engine.create(doc, _add(doc, pl), steel, {"height": "6'"}, lib=lib)
    print("corners: {} parts in {:.2f}s {}".format(len(r.part_ids), time.time() - t0, r.warnings))
    _check(doc, "corners", r)
    nov = overlaps(_boxes(doc, r, BRICK_ROLES + ("mortar_head", "weep")), 0.01 * s)
    assert slivers(doc, r) == 0, "corner: mortar slivers"
    assert nov == 0, "corner: {} overlapping bricks/joints".format(nov)
    eq = brick_equivalents(doc, r)
    face = (16 + 12 + 12) * 6.0
    print("  corner wall: {:.0f} brick eq. for ~{:.0f} ft2 face = {:.2f}/ft2".format(eq, face, eq / face))
    assert 6.2 < eq / face < 7.3
    ties_in_bed_joints(doc, r)
    results["corners"] = r

    # 3. arc
    arc = G.ArcCurve(G.Arc(G.Point3d(f(64), 0, 0), G.Point3d(f(74), f(-6), 0), G.Point3d(f(84), 0, 0)))
    t0 = time.time()
    r = engine.create(doc, _add(doc, arc), steel, {"height": "6'"}, lib=lib)
    print("arc: {} parts in {:.2f}s {}".format(len(r.part_ids), time.time() - t0, r.warnings))
    _check(doc, "arc", r)
    ties_in_bed_joints(doc, r)
    results["arc"] = r

    # 4. closed rectangle drawn counter-clockwise, and a closed circle
    rect = G.Rectangle3d(G.Plane.WorldXY, G.Interval(f(90), f(110)), G.Interval(0, f(16))).ToNurbsCurve()
    t0 = time.time()
    r = engine.create(doc, _add(doc, rect), steel, {"height": "4'"}, lib=lib)
    print("closed rect: {} parts in {:.2f}s {}".format(len(r.part_ids), time.time() - t0, r.warnings))
    _check(doc, "rect", r)
    assert overlaps(_boxes(doc, r, BRICK_ROLES + ("mortar_head", "weep")), 0.01 * s) == 0, "rect corners overlap"
    assert slivers(doc, r) == 0, "rect: mortar slivers at corners"
    eq = brick_equivalents(doc, r)
    face = 2 * (20 + 16 + 2 * 0.69) * 4.0
    print("  rect: {:.0f} brick eq = {:.2f}/ft2".format(eq, eq / face))
    assert 6.3 < eq / face < 7.2
    results["rect"] = r
    circ = G.ArcCurve(G.Circle(G.Point3d(f(130), f(8), 0), f(8)))
    r = engine.create(doc, _add(doc, circ), steel, {"height": "3'"}, lib=lib)
    print("circle: {} parts {}".format(len(r.part_ids), r.warnings))
    _check(doc, "circle", r)

    # 5. 45-degree (mitered) corner
    pl45 = G.PolylineCurve([G.Point3d(f(140), 0, 0), G.Point3d(f(150), 0, 0), G.Point3d(f(157), f(7), 0)])
    r = engine.create(doc, _add(doc, pl45), steel, {"height": "3'"}, lib=lib)
    print("45 deg corner: {} parts {}".format(len(r.part_ids), r.warnings))
    _check(doc, "45", r)
    results["miter"] = r

    # 6. every bond, 8' x 4' walls side by side (exterior toward -Y)
    for i, bond in enumerate(BONDS):
        x0 = f(-10 - 10 * i)
        name = _variant(lib, steel, "[{}]".format(bond), veneer={"bond": bond})
        crv = G.LineCurve(G.Point3d(x0 + f(8), f(-60), 0), G.Point3d(x0, f(-60), 0))
        t0 = time.time()
        r = engine.create(doc, _add(doc, crv), name, {"height": "4'"}, lib=lib)
        roles = _check(doc, bond, r)
        eq = brick_equivalents(doc, r)
        print("bond {:<8} {:5d} parts {:.2f}s  {:.2f} brick eq/ft2 {}".format(
            bond, len(r.part_ids), time.time() - t0, eq / 32.0,
            dict((k, v) for k, v in roles.items() if k.startswith("brick"))))
        assert overlaps(_boxes(doc, r, BRICK_ROLES + ("mortar_head", "weep")), 0.01 * s) == 0, bond
        assert slivers(doc, r) == 0, "{}: mortar slivers".format(bond)
        results["bond_" + bond] = r

    # 7. shelf angle + soft joint, soldier course at top, rowlock at bottom, 3 courses below the base
    name = _variant(lib, shelf, "[specials]", veneer={"extend_bottom": 8,
                                                      "courses": [{"type": "soldier", "at": "top"},
                                                                  {"type": "rowlock", "at": "bottom"}]})
    crv = G.LineCurve(G.Point3d(f(8), f(-90), 0), G.Point3d(0, f(-90), 0))
    r = engine.create(doc, _add(doc, crv), name, {"height": "8'"}, lib=lib)
    roles = _check(doc, "shelf", r)
    print("shelf angle: {} parts {} {}".format(len(r.part_ids), dict(roles), r.warnings))
    assert roles["shelf_angle"] == 2 and roles["brick_soldier"] > 0 and roles["brick_rowlock"] > 0
    assert roles["sealant"] == 1 and roles["backer_rod"] == 1
    ties_in_bed_joints(doc, r)
    results["shelf"] = r

    # 8. ledge base, king brick, stack bond, rounded coursing
    name = _variant(lib, steel, "[king]", veneer={"brick": "king", "bond": "stack", "top_course": "round"},
                    brick_layer={"thickness": 3})
    crv = G.LineCurve(G.Point3d(f(20), f(-90), 0), G.Point3d(f(12), f(-90), 0))
    r = engine.create(doc, _add(doc, crv), name, {"height": "7'-1\""}, lib=lib)
    _check(doc, "king", r)
    print("king/stack: {} parts {}".format(len(r.part_ids), r.warnings))

    # 9. accessories as assembly extras instead of layer options (no duplicates)
    name = _variant(lib, steel, "[extras]", veneer={"ties": False, "base": False},
                    extras=[{"name": "Ties", "component": "brick_ties", "material": "Brick Tie"},
                            {"name": "Base", "component": "veneer_base", "material": "Flashing",
                             "options": {"support": "shelf_angle"}}])
    crv = G.LineCurve(G.Point3d(f(32), f(-90), 0), G.Point3d(f(24), f(-90), 0))
    r = engine.create(doc, _add(doc, crv), name, {"height": "4'"}, lib=lib)
    roles = _check(doc, "extras", r)
    assert roles["flashing"] == 1 and roles["shelf_angle"] == 1, roles
    print("extras: {} ties, {} flashing".format(roles["brick_tie"], roles["flashing"]))

    # 10. two-sided brick wall: per-wall stack with the gypsum replaced by air space + brick
    results["two_sided"] = two_sided(doc, lib, steel, f(-110))

    if real:
        run_real(doc, lib)
    if captures:
        capture_all(doc, results)
    doc.Views.Redraw()
    print("PHASE 2 OK")
    return results


def two_sided(doc, lib, assembly, y):
    """Brick on both faces: the interior gypsum is replaced by a 1" air space + brick (per-wall stack)."""
    f = lambda v: _ft(doc, v)
    s = units.inch_scale(doc)
    layers = copy.deepcopy(lib.assembly(assembly)["layers"])
    gyp = [i for i, l in enumerate(layers) if l["name"] == "Gypsum"][0]
    inner = copy.deepcopy(layers[0])
    inner["name"] = "Brick Veneer (2)"
    inner["material"] = "Brick - Buff"
    layers[gyp:gyp + 1] = [{"name": "Air Space (2)", "component": "void", "thickness": 1}, inner]
    crv = G.LineCurve(G.Point3d(f(20), y, 0), G.Point3d(0, y, 0))      # exterior toward -Y
    r = engine.create(doc, _add(doc, crv), assembly, {"height": "8'"}, lib=lib)
    drv = doc.Objects.FindId(r.driver_id)
    t0 = time.time()
    r = engine.update_params(doc, drv, {"layers": layers}, lib=lib)
    dt = time.time() - t0
    by_layer = {}
    for o in _parts(doc, r):
        key = (meta.get(o, meta.LAYER), meta.get(o, meta.ROLE))
        by_layer.setdefault(key, []).append(o)
    count = lambda layer, role: len(by_layer.get((layer, role), []))
    print("two-sided: {} parts in {:.2f}s {}".format(len(r.part_ids), dt, r.warnings))
    for layer in ("Brick Veneer", "Brick Veneer (2)"):
        print("  {}: bricks {} ties {} weeps {} flashing {}".format(
            layer, count(layer, "brick"), count(layer, "brick_tie"), count(layer, "weep"), count(layer, "flashing")))
    assert count("Brick Veneer (2)", "brick") > 500, "interior brick missing"
    assert count("Brick Veneer (2)", "brick_tie") > 0, "interior brick has no ties"
    assert count("Brick Veneer (2)", "weep") == 0 and count("Brick Veneer (2)", "flashing") == 0
    assert count("Brick Veneer", "flashing") == 1 and count("Brick Veneer", "weep") > 0
    bb = G.BoundingBox.Empty
    for o in by_layer[("Brick Veneer (2)", "brick")]:
        bb.Union(o.Geometry.GetBoundingBox(True))
    # core_exterior reference: framing 0..6" toward +Y, 1" air, brick 7 .. 10-5/8"
    assert abs((bb.Min.Y - y) / s - 7.0) < 0.05 and abs((bb.Max.Y - y) / s - 10.625) < 0.05, \
        "interior brick at {:.3f}..{:.3f}".format((bb.Min.Y - y) / s, (bb.Max.Y - y) / s)
    tb = G.BoundingBox.Empty
    for o in by_layer[("Brick Veneer (2)", "brick_tie")]:
        tb.Union(o.Geometry.GetBoundingBox(True))
    assert (tb.Min.Y - y) / s > 5.0 and (tb.Max.Y - y) / s < 10.625 - 0.5, \
        "interior ties at {:.3f}..{:.3f}".format((tb.Min.Y - y) / s, (tb.Max.Y - y) / s)
    assert overlaps(_boxes(doc, r, BRICK_ROLES + ("mortar_head", "weep")), 0.01 * s) == 0
    assert slivers(doc, r) == 0, "two-sided: mortar slivers"
    ties_in_bed_joints(doc, r)
    return r


def run_real(doc, lib=None):
    """Build the library assemblies (needs components/framing.py)."""
    lib = lib or library.get()
    f = lambda v: _ft(doc, v)
    out = []
    for i, name in enumerate(REAL):
        crv = G.LineCurve(G.Point3d(f(20), f(-130 - 10 * i), 0), G.Point3d(0, f(-130 - 10 * i), 0))
        t0 = time.time()
        r = engine.create(doc, _add(doc, crv), name, {}, lib=lib)
        roles = _roles(doc, r)
        print("REAL {}: {} parts in {:.2f}s, studs {} ties {} {}".format(
            name, len(r.part_ids), time.time() - t0,
            sum(v for k, v in roles.items() if "stud" in k), roles["brick_tie"], r.warnings))
        assert roles["brick_tie"] > 0
        out.append(r)
    out.append(two_sided(doc, lib, STEEL, f(-180)))
    return out


def _box(doc, x0, y0, z0, x1, y1, z1):
    f = lambda v: _ft(doc, v)
    return G.BoundingBox(G.Point3d(f(x0), f(y0), f(z0)), G.Point3d(f(x1), f(y1), f(z1)))


def _persp(doc, cam, target, lens=50):
    v = doc.Views.Find("Perspective", False)
    vp = v.ActiveViewport
    f = lambda p: G.Point3d(*[_ft(doc, c) for c in p])
    vp.SetCameraLocations(f(target), f(cam))
    vp.Camera35mmLensLength = lens
    return v


def _cap(doc, name, **kw):
    doc.Views.Redraw()
    CAPTURE(doc, name, **kw)          # first pass builds render meshes
    return CAPTURE(doc, name, **kw)


def capture_all(doc, results):
    for i, bond in enumerate(BONDS):
        x0 = -10 - 10 * i
        _cap(doc, "phase2_bond_" + bond, view="Front", mode="Shaded",
             box=_box(doc, x0 - 0.3, -61, -0.5, x0 + 8.3, -59, 4.3), width=900, height=520)
    _persp(doc, (38.5, 19.5, 8), (46.5, 11.5, 2.5), 35)
    _cap(doc, "phase2_corner", view="Perspective", mode="Shaded", zoom_extents=False)
    _persp(doc, (39, 7, 6), (46.5, -0.5, 2), 35)
    _cap(doc, "phase2_inside_corner", view="Perspective", mode="Shaded", zoom_extents=False)
    _persp(doc, (74, 9, 8), (74, -4, 2), 35)
    _cap(doc, "phase2_arc", view="Perspective", mode="Shaded", zoom_extents=False)
    _persp(doc, (130, -13, 7), (130, 4, 1), 35)
    _cap(doc, "phase2_circle", view="Perspective", mode="Shaded", zoom_extents=False)
    _persp(doc, (122, -14, 14), (100, 8, 0), 35)
    _cap(doc, "phase2_rect", view="Perspective", mode="Shaded", zoom_extents=False)
    _persp(doc, (113.5, -3.5, 3.0), (110.3, -0.3, 1.5), 50)
    _cap(doc, "phase2_rect_corner", view="Perspective", mode="Shaded", zoom_extents=False)
    _persp(doc, (148.5, 5.5, 4.5), (150.5, 0.5, 1.2), 40)
    _cap(doc, "phase2_miter", view="Perspective", mode="Shaded", zoom_extents=False)

    # base close-up of the shelf-angle wall, cut by a section plane at x = 2'
    s = units.inch_scale(doc)
    cp = _section_plane(doc, G.Point3d(_ft(doc, 2.2), _ft(doc, -90), 0), G.Vector3d(-1, 0, 0), _ft(doc, 30))
    _persp(doc, (4.4, -92.6, 1.4), (2.0, -89.5, -0.2), 50)
    _cap(doc, "phase2_base", view="Perspective", mode="Shaded", zoom_extents=False)
    _cap(doc, "phase2_section_shelf", view="Right", mode="Shaded",
         box=_box(doc, 0, -91.1, -1.05, 8, -89.2, 0.75), width=800, height=700)
    _cap(doc, "phase2_section_shelf_top", view="Right", mode="Shaded",
         box=_box(doc, 0, -91.1, 7.0, 8, -89.2, 8.5), width=800, height=700)
    doc.Objects.Delete(cp, True)
    # section through a tie column on the straight wall (find the first tie)
    r = results["straight"][0]
    tie = [o for o in _parts(doc, r) if meta.get(o, meta.ROLE) == "brick_tie"][0]
    xt = tie.InstanceXform.M03
    cp = _section_plane(doc, G.Point3d(xt, 0, 0), G.Vector3d(-1, 0, 0), _ft(doc, 30))
    _cap(doc, "phase2_section_ties", view="Right", mode="Shaded",
         box=_box(doc, 0, -1.0, -0.4, 20, 0.6, 3.4), width=600, height=1000)
    _cap(doc, "phase2_section_base", view="Right", mode="Shaded",
         box=_box(doc, 0, -0.95, -0.3, 20, 0.6, 1.0), width=900, height=750)
    _persp(doc, (xt / s / 12 + 2.5, -3.0, 2.2), (xt / s / 12 - 0.3, 0.0, 0.6), 50)
    _cap(doc, "phase2_ties_persp", view="Perspective", mode="Shaded", zoom_extents=False)
    doc.Objects.Delete(cp, True)
    # two-sided brick wall, cut through an interior tie
    r = results.get("two_sided")
    if r is not None:
        ties = [o for o in _parts(doc, r) if meta.get(o, meta.ROLE) == "brick_tie"
                and meta.get(o, meta.LAYER) == "Brick Veneer (2)"]
        xt = ties[0].InstanceXform.M03
        cp = _section_plane(doc, G.Point3d(xt, 0, 0), G.Vector3d(-1, 0, 0), _ft(doc, 30))
        _cap(doc, "phase2_two_sided", view="Right", mode="Shaded",
             box=_box(doc, 0, -111.0, -0.3, 20, -109.0, 2.6), width=800, height=1000)
        doc.Objects.Delete(cp, True)
