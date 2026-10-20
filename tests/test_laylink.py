"""Layer = assembly (mindcanvas/laylink.py, MCAssemblyLayers).

Run inside Rhino (e.g. via the MCP run_python tool), in an EMPTY, unsaved document (it is cleared):

    import sys, runpy
    ROOT = r"C:\\Users\\jakob\\Desktop\\BAC\\Rhino Mind Canvas"
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from mindcanvas import dev; dev.reload_all()
    runpy.run_path(ROOT + r"\\tests\\test_laylink.py")["run"](__rhino_doc__)

Covers: a layer per assembly with its kind / assembly in user text and a valid name (inch marks and
slashes in assembly names); its color; a line added on a wall layer becomes that wall (and moves
to the driver layer); a closed curve on a floor / roof layer becomes a floor / roof; an open curve
on a floor layer is left alone; a box on a wall layer becomes a wall mass; a wall moved onto
another wall layer takes that assembly; a wall moved onto a floor layer is put back unchanged; a
wall mass moved onto a layer gives its wall that assembly; nothing is queued while Mind Canvas
builds (live.quiet) or when watching is off. The Idle step is called directly (laylink.process).
"""

import time

import Rhino

from mindcanvas import docutil, engine, laylink, library, live, masses, meta, units, wallmasses

G = Rhino.Geometry
WOOD = "Ext - 2x6 Wood, Fiber Cement"
BRICK = 'Ext - Brick Veneer / 6" Metal Stud'
FLOOR = "Floor - 2x10 Wood Joists, Plywood"
ROOF = "Roof - Low Slope Membrane / 2x10 Joists"
FAILS = []


def say(*a):
    print(" ".join(str(x) for x in a))


def check(cond, label):
    say(("ok   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def _ft(doc, v):
    return units.to_model(doc, v * 12.0)


def _attrs(layer_index):
    a = Rhino.DocObjects.ObjectAttributes()
    a.LayerIndex = layer_index
    return a


def _add_curve(doc, crv, layer_index):
    return doc.Objects.FindId(doc.Objects.AddCurve(crv, _attrs(layer_index)))


def _line(doc, x0, y0, x1, y1):
    f = lambda v: _ft(doc, v)
    return G.LineCurve(G.Point3d(f(x0), f(y0), 0), G.Point3d(f(x1), f(y1), 0))


def _rect(doc, x0, y0, x1, y1, z=0.0):
    f = lambda v: _ft(doc, v)
    return G.PolylineCurve([G.Point3d(f(x), f(y), f(z)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))])


def _move_to_layer(doc, oid, layer_index):
    o = doc.Objects.FindId(oid)
    a = o.Attributes.Duplicate()
    a.LayerIndex = layer_index
    doc.Objects.ModifyAttributes(o, a, True)


def run(doc, lib=None):
    del FAILS[:]
    assert not doc.Path, "run the test in an empty, unsaved document"
    t0 = time.time()
    doc.Objects.Clear()
    engine.setup_document(doc)
    lib = lib or library.get()
    laylink.disable()
    laylink._state()["queue"] = []

    say("-- layers")
    made = laylink.ensure_layers(doc, lib)
    n = sum(len(lib.assemblies(k)) for k, _ in laylink.GROUPS)
    check(len(made) == n, "a layer per wall / curtain wall / floor / roof assembly ({})".format(len(made)))
    bad = [k for k, i in made.items() if laylink.assembly_of_layer(doc, i) != k]
    check(not bad, "each layer knows its kind and assembly ({})".format(bad[:2]))
    names = [doc.Layers[i].Name for i in made.values()]
    check(all(Rhino.DocObjects.Layer.IsValidName(x) for x in names), "all layer names are valid")
    bi = made[("wall", BRICK)]
    check('"' not in doc.Layers[bi].Name and doc.Layers[bi].FullPath.startswith(laylink.ROOT + "::Walls::"),
          "an inch mark in the name becomes in: {}".format(doc.Layers[bi].FullPath))
    c = doc.Layers[bi].Color
    check((c.R, c.G, c.B) == tuple(lib.data["materials"][lib.assembly(BRICK)["layers"][0]["material"]]["color"]),
          "the brick layer has the brick's color")
    check(laylink.ensure_layers(doc, lib) == made, "running it again changes nothing")

    say("-- watching")
    laylink.enable()
    w = _add_curve(doc, _line(doc, 0, 0, 20, 0), made[("wall", WOOD)])
    done = laylink.process()
    w = doc.Objects.FindId(w.Id)
    check(meta.is_driver(w) and meta.get(w, meta.ASSEMBLY) == WOOD, "a line on a wall layer becomes that wall ({})".format(done))
    check(w.Attributes.LayerIndex == docutil.ensure_driver_layer(doc), "... and moves to the driver layer")
    check(len(meta.parts_of(doc, w.Id)) > 0, "... with parts")
    f = _add_curve(doc, _rect(doc, 0, -20, 20, -5, 10), made[("floor", FLOOR)])
    r = _add_curve(doc, _rect(doc, 30, 0, 45, 12, 9), made[("roof", ROOF)])
    o = _add_curve(doc, _line(doc, 0, -30, 10, -30), made[("floor", FLOOR)])
    done = laylink.process()
    check(meta.get(doc.Objects.FindId(f.Id), meta.TYPE) == "floor", "a closed curve on a floor layer becomes a floor")
    check(meta.get(doc.Objects.FindId(r.Id), meta.TYPE) == "roof", "... on a roof layer a roof")
    oo = doc.Objects.FindId(o.Id)
    check(not meta.is_driver(oo) and oo.Attributes.LayerIndex == made[("floor", FLOOR)], "an open curve on a floor layer is left alone")
    box = G.Box(G.Plane.WorldXY, G.Interval(0, _ft(doc, 15)), G.Interval(_ft(doc, 40), _ft(doc, 41)), G.Interval(0, _ft(doc, 9))).ToBrep()
    b = doc.Objects.FindId(doc.Objects.AddBrep(box, _attrs(made[("wall", WOOD)])))
    laylink.process()
    b = doc.Objects.FindId(b.Id)
    check(wallmasses.is_wall_mass(b) and wallmasses.wall_of(doc, b) is not None, "a box on a wall layer becomes a wall mass")
    check(b.Attributes.LayerIndex == masses.ensure_layer(doc), "... on the masses layer")

    say("-- moving onto a layer")
    _move_to_layer(doc, w.Id, made[("wall", BRICK)])
    laylink.process()
    w = doc.Objects.FindId(w.Id)
    check(meta.get(w, meta.ASSEMBLY) == BRICK, "a wall moved onto the brick layer becomes brick")
    check(w.Attributes.LayerIndex == docutil.ensure_driver_layer(doc), "... and goes back to the driver layer")
    _move_to_layer(doc, w.Id, made[("floor", FLOOR)])
    laylink.process()
    w = doc.Objects.FindId(w.Id)
    check(meta.get(w, meta.TYPE) == "wall" and meta.get(w, meta.ASSEMBLY) == BRICK and
          w.Attributes.LayerIndex == docutil.ensure_driver_layer(doc), "a wall moved onto a floor layer is put back unchanged")
    _move_to_layer(doc, b.Id, made[("wall", BRICK)])
    laylink.process()
    b = doc.Objects.FindId(b.Id)
    check(meta.get(wallmasses.wall_of(doc, b), meta.ASSEMBLY) == BRICK, "a wall mass moved onto a layer: its wall takes it")
    check(b.Attributes.LayerIndex == masses.ensure_layer(doc), "... and the mass goes back")

    say("-- quiet")
    with live.quiet():
        if live._state() is None:
            laylink._state()["busy"] = True          # live mode off: stand in for a build
        x = _add_curve(doc, _line(doc, 0, 60, 10, 60), made[("wall", WOOD)])
        laylink._state()["busy"] = False
    check(not laylink._state()["queue"] or not laylink.process(), "nothing queued while Mind Canvas builds")
    laylink.disable()
    y = _add_curve(doc, _line(doc, 0, 70, 10, 70), made[("wall", WOOD)])
    laylink.process()
    check(not meta.is_driver(doc.Objects.FindId(y.Id)), "watching off: a curve stays a curve")
    laylink.enable()
    say("{} checks failed; {:.1f}s".format(len(FAILS), time.time() - t0))
    for f_ in FAILS:
        say("  FAIL " + f_)
    return not FAILS
