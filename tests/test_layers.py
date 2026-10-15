"""Per-wall layer editing (MCLayers back end): replace, insert, remove,
thickness, mirror, presets, save-as-assembly.

    runpy.run_path(ROOT + r"\\tests\\test_layers.py")["run"](__rhino_doc__)
"""

import json
import os

import Rhino

from mindcanvas import engine, library, meta, stack, units
from mindcanvas.kinds import wall as wallkind

G = Rhino.Geometry
BASE = 'Ext - Brick Veneer / 6" Metal Stud'
TEST_NAME = "zz Test Two-Sided (delete me)"


def _names(lib, drv):
    return [wallkind.layer_name(s, i) for i, s in enumerate(wallkind.effective_layers(lib, drv))]


def _brick_layer(lib):
    for label, spec in stack.catalog(lib):
        if lib.resolve_layer(spec).get("component") == "masonry":
            return spec
    return {"name": "Brick", "component": "solid", "material": "Brick - Red", "thickness": "3-5/8"}


def run(doc, clear=True):
    if clear:
        for o in list(doc.Objects):
            doc.Objects.Delete(o, True)
    engine.setup_document(doc)
    lib = library.get(force_reload=True)
    f = lambda feet: units.to_model(doc, feet * 12)
    cid = doc.Objects.AddCurve(G.LineCurve(G.Point3d(0, 0, 0), G.Point3d(f(12), 0, 0)))
    r = engine.create(doc, doc.Objects.FindId(cid), BASE, {"height": "9'", "lod": "design"})
    drv = doc.Objects.FindId(cid)
    before = _names(lib, drv)
    print("base stack:", before)

    layers = stack.current(lib, drv)
    gyp = len(layers) - 1
    brick = _brick_layer(lib)

    # 1. two-sided brick: interior gypsum -> brick, with an air space behind it
    layers = stack.replace(layers, gyp, brick)
    air = [spec for label, spec in stack.catalog(lib) if label.startswith("Preset:") and spec.get("component") == "void"][0]
    layers = stack.insert(layers, gyp, air)
    r = engine.set_layers(doc, drv, layers)
    drv = doc.Objects.FindId(cid)
    names = _names(lib, drv)
    print("two-sided:", names, r)
    assert names[-1] != "Gypsum", names
    assert len(set(names)) == len(names), "layer names must be unique: {}".format(names)
    mats = set(meta.get(o, meta.MATERIAL) for o in meta.parts_of(doc, cid))
    assert "Gypsum Board" not in mats, mats
    full = wallkind.effective_layers(lib, drv)
    assert sum(1 for s in full if s.get("component") == "masonry") == 2, full
    # detail LOD: both brick faces get ties; weeps / flashing only on the exterior face
    engine.update_params(doc, drv, {"lod": "detail"})
    drv = doc.Objects.FindId(cid)
    by_layer = {}
    for o in meta.parts_of(doc, cid):
        by_layer.setdefault(meta.get(o, meta.LAYER), {}).setdefault(meta.get(o, meta.ROLE), 0)
        by_layer[meta.get(o, meta.LAYER)][meta.get(o, meta.ROLE)] += 1
    ext_name, int_name = [wallkind.layer_name(s, i) for i, s in enumerate(full) if s.get("component") == "masonry"]
    print("exterior brick:", by_layer.get(ext_name))
    print("interior brick:", by_layer.get(int_name))
    assert by_layer[int_name].get("brick_tie", 0) > 0, "interior brick has no ties"
    assert not any(r in by_layer[int_name] for r in ("flashing", "weep", "shelf_angle")), by_layer[int_name]
    engine.update_params(doc, drv, {"lod": "design"})
    drv = doc.Objects.FindId(cid)

    # 2. thickness edit on the framing layer swaps the stud (6" -> 3-5/8")
    fi = [i for i, s in enumerate(full) if s.get("component") == "framing"][0]
    layers = stack.set_thickness(stack.current(lib, drv), fi, "3-5/8")
    engine.set_layers(doc, drv, layers)
    drv = doc.Objects.FindId(cid)
    studs = [o for o in meta.parts_of(doc, cid) if meta.get(o, meta.ROLE) == "stud"]
    assert studs, "no studs after thickness edit"
    member = meta.get(studs[0], meta.EXTRA_PREFIX + "member") or ""
    print("stud after thickness edit:", member)
    assert "3-5/8" in member, member

    # 3. remove + mirror + reset
    layers = stack.remove(stack.current(lib, drv), 0)
    layers = stack.mirror(layers)
    engine.set_layers(doc, drv, layers)
    drv = doc.Objects.FindId(cid)
    assert len(_names(lib, drv)) == len(names) - 1
    engine.set_layers(doc, drv, None)
    drv = doc.Objects.FindId(cid)
    assert _names(lib, drv) == before, "reset failed"

    # 4. save as a new assembly, then retype
    layers = stack.replace(stack.current(lib, drv), gyp, brick)
    path = lib.save_assembly(TEST_NAME, stack.as_assembly(lib, BASE, layers))
    try:
        r = engine.set_assembly(doc, drv, TEST_NAME)
        drv = doc.Objects.FindId(cid)
        assert meta.get(drv, meta.ASSEMBLY) == TEST_NAME
        assert "layers" not in meta.params(drv)
        print("saved + retyped:", r)
    finally:
        with open(path, "r", encoding="utf-8") as fh:
            content = json.load(fh)
        content.pop(TEST_NAME, None)
        if content:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(content, fh, indent=2)
        else:
            os.remove(path)
        engine.set_assembly(doc, doc.Objects.FindId(cid), BASE)

    print("catalog entries:", len(stack.catalog(lib)))
    doc.Views.Redraw()
    print("LAYERS OK")
