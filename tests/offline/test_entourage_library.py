"""Offline checks of the entourage model library (library/entourage; no Rhino needed).

    %USERPROFILE%\\.rhinocode\\py39-rh8\\python.exe tests/offline/test_entourage_library.py

Every catalog entry: its OBJ + MTL + thumbnail exist, the OBJ reads, is normalised (base on the
ground, footprint centred on the origin), matches the catalog size and triangle count, and the
license is CC0. Categories hold enough models; people are 4'-7' tall (standing ones), trees are
taller than 12'. catalog.add_model / remove_model round trip in a temporary library copy.
"""

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from mindcanvas import library  # noqa: E402
from mindcanvas.entourage import catalog, objfile  # noqa: E402

MIN = {"People": 20, "Trees": 50, "Plants": 30, "Vehicles": 18, "Furniture": 70, "Kitchen & Bath": 25,
       "Lighting": 20, "Site": 15}


def check_entries(lib):
    folder = catalog.folder(lib)
    names = catalog.names(lib)
    assert len(names) >= 250, len(names)
    for c, n in MIN.items():
        assert len(catalog.names(lib, c)) >= n, (c, len(catalog.names(lib, c)))
    for n in names:
        d = catalog.entry(lib, n)
        p = catalog.model_path(lib, n)
        assert os.path.isfile(p), (n, p)
        assert os.path.isfile(os.path.splitext(p)[0] + ".mtl"), n
        assert os.path.isfile(catalog.thumb_path(lib, n)), n
        assert d["license"] == "CC0 1.0", (n, d["license"])
        m = objfile.read(p)
        assert m.triangle_count() == d["triangles"], (n, m.triangle_count(), d["triangles"])
        (x0, y0, z0), (x1, y1, z1) = m.bbox()
        tol = 0.15
        if d.get("mount") == "ceiling":
            assert abs(z1) < tol, (n, z1)
        else:
            assert abs(z0) < tol, (n, z0)
        assert abs(x0 + x1) < 2 * tol and abs(y0 + y1) < 2 * tol, (n, x0, x1, y0, y1)
        for a, b in zip(d["size"], (x1 - x0, y1 - y0, z1 - z0)):
            assert abs(a - b) < 0.2, (n, d["size"])
        assert m.header().get("license") == "CC0 1.0", n
        rel = os.path.relpath(p, folder).replace(os.sep, "/")
        assert rel == d["file"], (n, rel)
    for n in catalog.names(lib, "People", "Standing"):
        h = catalog.height(lib, n)
        assert 48 < h < 84, (n, h)
    for n in catalog.names(lib, "Trees"):
        assert catalog.height(lib, n) > 144, n
    for n in catalog.names(lib, "Vehicles", "Cars"):
        x, y, z = catalog.entry(lib, n)["size"]
        assert x > y and 150 < x < 220, (n, x, y)       # cars run along X
    assert catalog.categories(lib)[:3] == ["People", "Trees", "Plants"], catalog.categories(lib)
    assert catalog.search(lib, "pine tree")
    print("  {} models in {} categories, all files normalised".format(len(names), len(catalog.categories(lib))))


def check_add_model():
    tmp = tempfile.mkdtemp()
    try:
        for section in library.SECTIONS:
            os.makedirs(os.path.join(tmp, section))
        src = os.path.join(tmp, "box.obj")
        with open(src, "w") as f:      # a 2 m x 1 m x 0.5 m box, Y up, off the origin
            f.write("mtllib box.mtl\n")
            for x in (3, 5):
                for y in (1, 1.5):
                    for z in (0, 1):
                        f.write("v {} {} {}\n".format(x, y, z))
            f.write("usemtl Red\nf 1 2 4 3\nf 5 7 8 6\nf 1 5 6 2\nf 3 4 8 7\nf 1 3 7 5\nf 2 6 8 4\n")
        with open(os.path.join(tmp, "box.mtl"), "w") as f:
            f.write("newmtl Red\nKd 1 0 0\n")
        lib = library.Library(tmp)
        d = catalog.add_model(lib, src, "Test Box", units="meters", up="y")
        assert d["category"] == catalog.USER_CATEGORY
        w, dp, h = d["size"]
        assert abs(w - 78.74) < 0.1 and abs(dp - 39.37) < 0.1 and abs(h - 19.69) < 0.1, d["size"]
        assert "Test Box" in catalog.names(lib, catalog.USER_CATEGORY)
        m = objfile.read(catalog.model_path(lib, "Test Box"))
        assert m.colors.get("Red") == (255, 0, 0), m.colors
        assert os.path.isfile(catalog.thumb_path(lib, "Test Box"))
        d2 = catalog.add_model(lib, src, "Test Box", units="meters", up="y", height=30)
        assert abs(d2["size"][2] - 30) < 0.01, d2
        catalog.remove_model(lib, "Test Box")
        assert "Test Box" not in catalog.names(lib)
        assert not os.path.exists(os.path.join(tmp, "entourage", catalog.USER_FILE))
        print("  add_model / remove_model OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_recipe():
    r = json.load(open(os.path.join(ROOT, "tools", "entourage", "recipe.json"), encoding="utf-8"))
    for sid, s in r["sources"].items():
        assert s["license"] == "CC0 1.0", sid
    names = [i["name"] for c in r["categories"] for i in c["items"]]
    assert len(names) == len(set(names)), "duplicate names in recipe.json"
    print("  recipe: {} sources, {} models".format(len(r["sources"]), len(names)))


if __name__ == "__main__":
    check_entries(library.Library())
    check_add_model()
    check_recipe()
    print("ENTOURAGE LIBRARY OK")
