"""Offline checks of the entourage generators (mindcanvas/entourage/shapes.py; no Rhino needed).

    %USERPROFILE%\\.rhinocode\\py39-rh8\\python.exe tests/offline/test_entourage_shapes.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [os.path.join(HERE, "fake"), ROOT]

from mindcanvas import units  # noqa: E402
from mindcanvas.entourage import shapes  # noqa: E402


def entries():
    out = {}
    folder = os.path.join(ROOT, "library", "entourage")
    for name in sorted(os.listdir(folder)):
        if name.endswith(".json") and not name.startswith("zz_"):
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                out.update((k, v) for k, v in json.load(f).items() if not k.startswith("_"))
    return out


def run():
    es = entries()
    assert len(es) >= 12, len(es)
    for name, d in es.items():
        layers = shapes.build(d)
        c = shapes.count(layers)
        x0, y0, x1, y1 = shapes.bounds(layers)
        H = units.parse_length(d["height"])
        assert c["loops"] >= 1 and abs(y0) < 1.0, (name, c, y0)
        if d["generator"] == "person":
            assert abs(y1 - H) < 2.0 and x1 - x0 < H * 0.6, (name, y1, x1 - x0)
        elif d["generator"] == "tree":
            assert abs(y1 - H) / H < 0.08, (name, y1, H)
        depths = [ly.depth for ly in layers]
        assert depths == sorted(depths, reverse=True), (name, depths)       # far to near
        print("{:<28} {} {:.0f} x {:.0f} in".format(name, c, x1 - x0, y1 - y0))
    # same seed -> same tree, other seed -> another; overrides; custom; unknown generator
    t = es["Tree - Bare, 18 ft"]
    key = lambda L: [(ly.depth, ly.loops, ly.lines) for ly in L]
    assert key(shapes.build(t, 3)) == key(shapes.build(t, 3)) != key(shapes.build(t, 4))
    assert abs(shapes.bounds(shapes.build(es["Person - Child"], height=40))[3] - 40) < 2.0
    left = shapes.build(es["Person - Walking, Suit"], facing="left")
    right = shapes.build(es["Person - Walking, Suit"])
    assert abs(shapes.bounds(left)[0] + shapes.bounds(right)[2]) < 1e-6
    cu = shapes.build({"generator": "custom", "loops": [[[0, 0], [10, 0], [5, 20]]], "lines": [[[2, 5], [8, 5]]]})
    assert shapes.count(cu) == {"layers": 1, "loops": 1, "lines": 1}
    try:
        shapes.build({"generator": "nope"})
        raise AssertionError("unknown generator accepted")
    except ValueError:
        pass
    print("ENTOURAGE SHAPES OK")


if __name__ == "__main__":
    run()
