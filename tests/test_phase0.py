"""Phase 0 smoke test: solid-layer walls on open, closed and curved drivers.

Run inside Rhino (e.g. via the MCP run_python tool):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_phase0.py")["run"](__rhino_doc__)
"""

import Rhino

from mindcanvas import engine, meta, units

G = Rhino.Geometry
ASSEMBLY = "Basic - Solid Layers (test)"


def _ft(doc, feet):
    return units.to_model(doc, feet * 12.0)


def _add_curve(doc, curve):
    return doc.Objects.FindId(doc.Objects.AddCurve(curve))


def run(doc, clear=True):
    if clear:
        for o in list(doc.Objects):
            doc.Objects.Delete(o, True)
    engine.setup_document(doc)
    f = lambda v: _ft(doc, v)
    results = []

    # open L-shaped polyline (exterior on the left of travel)
    pl = G.PolylineCurve([G.Point3d(0, 0, 0), G.Point3d(f(20), 0, 0), G.Point3d(f(20), f(14), 0)])
    results.append(("open L", engine.create(doc, _add_curve(doc, pl), ASSEMBLY, {"height": "10'"})))

    # closed rectangle drawn counter-clockwise (must still put exterior outside)
    rect = G.Rectangle3d(G.Plane.WorldXY, G.Interval(f(30), f(50)), G.Interval(0, f(16))).ToNurbsCurve()
    results.append(("closed rect", engine.create(doc, _add_curve(doc, rect), ASSEMBLY,
                                                 {"reference": "exterior_face"})))

    # arc, centerline reference, raised base
    arc = G.ArcCurve(G.Arc(G.Point3d(f(60), 0, 0), G.Point3d(f(70), f(8), 0), G.Point3d(f(80), 0, 0)))
    results.append(("arc", engine.create(doc, _add_curve(doc, arc), ASSEMBLY,
                                         {"reference": "center", "base_offset": "1'"})))

    for label, r in results:
        print(label, r, r.warnings)
        assert len(r.part_ids) == 5, "{}: expected 5 parts (void makes none), got {}".format(label, len(r.part_ids))

    # closed rect, exterior face reference: outer siding face must be ON the driver
    drv = doc.Objects.FindId(results[1][1].driver_id)
    siding = [o for o in meta.parts_of(doc, drv.Id) if meta.get(o, meta.LAYER) == "Siding"][0]
    bb = siding.Geometry.GetBoundingBox(True)
    assert abs(bb.Min.X - f(30)) < 1e-6 and abs(bb.Max.X - f(50)) < 1e-6, "siding not on driver: {}".format(bb)

    # rebuild must replace, not duplicate
    r2 = engine.build(doc, drv.Id)
    assert len(meta.parts_of(doc, drv.Id)) == 5
    # param change: flip puts exterior inside
    r3 = engine.update_params(doc, drv, {"flip": True})
    # exterior face stays on the driver but now faces inward, so the wall
    # grows outward: gypsum becomes the outermost layer
    by_layer = dict((meta.get(o, meta.LAYER), o.Geometry.GetBoundingBox(True)) for o in meta.parts_of(doc, drv.Id))
    assert by_layer["Gypsum"].Min.X < by_layer["Siding"].Min.X, "flip did not mirror the stack"
    assert abs(by_layer["Siding"].Max.X - f(30)) > 0 and by_layer["Siding"].Min.X < f(30), "siding should sit outside the line"
    engine.update_params(doc, drv, {"flip": None})

    print("units:", units.parse_length("3-5/8"), units.parse_length("1'-6\""), units.format_inches(30.5))
    doc.Views.Redraw()
    print("PHASE 0 OK")
    return results
