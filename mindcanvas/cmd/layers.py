"""MCLayers: edit the layer stack of selected walls.

Replace / Insert / Remove / Thickness / ToExterior / ToInterior / Mirror /
Reset / SaveAs. Every edit rebuilds the walls immediately; Esc restores the
walls as they were. SaveAs turns the edited stack into a new named assembly
in library/assemblies/zz_user_assemblies.json.
"""

import copy

import Rhino

from .. import engine, library, meta, stack, units
from ..kinds import wall as wallkind
from . import ui

RI = Rhino.Input
CUSTOM_SOLID = "Custom solid... (any material, any thickness)"
CUSTOM_VOID = "Air space... (any thickness)"


def _get_index(prompt, count, default=1):
    gi = RI.Custom.GetInteger()
    gi.SetCommandPrompt(prompt)
    gi.SetLowerLimit(1, False)
    gi.SetUpperLimit(count, False)
    gi.SetDefaultInteger(default)
    if gi.Get() != RI.GetResult.Number:
        return None
    return gi.Number() - 1


def _get_text(prompt, default=""):
    gs = RI.Custom.GetString()
    gs.SetCommandPrompt(prompt)
    if default:
        gs.SetDefaultString(default)
    gs.AcceptNothing(True)
    res = gs.Get()
    if res == RI.GetResult.String:
        return gs.StringResult().strip()
    if res == RI.GetResult.Nothing and default:
        return default
    return None


def _choose_layer(lib):
    entries = stack.catalog(lib)
    labels = [CUSTOM_SOLID, CUSTOM_VOID] + [label for label, _ in entries]
    choice = ui.pick_from_list("Mind Canvas - Layer", "Choose the new layer", labels)
    if choice is None:
        return None
    if choice in (CUSTOM_SOLID, CUSTOM_VOID):
        spec = {"component": "void", "name": "Air Space"}
        if choice == CUSTOM_SOLID:
            mat = ui.pick_from_list("Mind Canvas - Material", "Material", sorted(lib.data["materials"]))
            if not mat:
                return None
            spec = {"component": "solid", "name": mat, "material": mat}
        t = _get_text('Thickness (inches, e.g. 5/8, 3-5/8, 1\'-0")', "1")
        if not t:
            return None
        spec["thickness"] = units.format_inches(units.parse_length(t), 64)
        return spec
    return dict(entries)[choice] if choice in dict(entries) else None


def _show(lib, layers, title):
    ui.say("{} (exterior -> interior):".format(title))
    for i, spec in enumerate(layers):
        ui.say("  " + stack.describe(lib.resolve_layer(spec), i))
    full = [lib.resolve_layer(s) for s in layers]
    ui.say("  total {}".format(units.format_inches(wallkind.total_thickness(full), 64)))


def run():
    doc = ui.doc()
    lib = library.get()
    drivers = ui.select_drivers("Select walls to edit layers", kind="wall")
    if not drivers:
        return ui.Result.Cancel
    asm_name = meta.get(drivers[0], meta.ASSEMBLY)
    layers = stack.current(lib, drivers[0])
    originals = [(d.Id, meta.params(d).get("layers"), meta.get(d, meta.ASSEMBLY)) for d in drivers]

    def apply(new_layers):
        for d in drivers:
            r = engine.set_layers(doc, doc.Objects.FindId(d.Id), new_layers, lib)
            for w in r.warnings:
                ui.say("  warning: " + w)
        doc.Views.Redraw()

    go = RI.Custom.GetOption()
    go.AcceptNothing(True)
    while True:
        _show(lib, layers, asm_name)
        go.SetCommandPrompt("Edit layers (Enter = done)")
        go.ClearCommandOptions()
        ops = ["Replace", "Insert", "Remove", "Thickness", "ToExterior", "ToInterior", "Mirror", "Reset", "SaveAs"]
        idx = dict((go.AddOption(op), op) for op in ops)
        res = go.Get()
        if res == RI.GetResult.Nothing:
            break
        if res != RI.GetResult.Option:
            # Esc: put every wall back the way it was
            for did, old_layers, old_asm in originals:
                d = doc.Objects.FindId(did)
                if meta.get(d, meta.ASSEMBLY) != old_asm:
                    engine.set_assembly(doc, d, old_asm, lib)
                engine.set_layers(doc, doc.Objects.FindId(did), old_layers, lib)
            doc.Views.Redraw()
            return ui.Result.Cancel
        op = idx.get(go.OptionIndex())
        n = len(layers)
        try:
            if op == "Replace":
                i = _get_index("Layer number to replace", n, n)
                spec = _choose_layer(lib) if i is not None else None
                if spec:
                    layers = stack.replace(layers, i, spec)
            elif op == "Insert":
                i = _get_index("Insert before layer number ({} = interior side)".format(n + 1), n + 1, n + 1)
                spec = _choose_layer(lib) if i is not None else None
                if spec:
                    layers = stack.insert(layers, i, spec)
            elif op == "Remove":
                i = _get_index("Layer number to remove", n, n)
                if i is not None:
                    layers = stack.remove(layers, i)
            elif op == "Thickness":
                i = _get_index("Layer number", n, 1)
                if i is not None:
                    cur = units.format_inches(units.parse_length(lib.resolve_layer(layers[i]).get("thickness", 0)))
                    t = _get_text("New thickness", cur.strip('"'))
                    if t:
                        layers = stack.set_thickness(layers, i, t)
            elif op in ("ToExterior", "ToInterior"):
                i = _get_index("Layer number to move", n, 1)
                if i is not None:
                    layers = stack.move(layers, i, -1 if op == "ToExterior" else 1)
            elif op == "Mirror":
                layers = stack.mirror(layers)
            elif op == "Reset":
                layers = copy.deepcopy(lib.assembly(asm_name)["layers"])
                apply(None)
                continue
            elif op == "SaveAs":
                name = _get_text("Name for the new assembly", asm_name + " (custom)")
                if not name:
                    continue
                if name in lib.data["assemblies"] and lib.data["assemblies"][name].get("based_on") is None:
                    ui.say("'{}' is a library assembly; choose another name.".format(name))
                    continue
                path = lib.save_assembly(name, stack.as_assembly(lib, asm_name, layers))
                for d in drivers:
                    ui.report(engine.set_assembly(doc, doc.Objects.FindId(d.Id), name, lib), "Retyped:")
                ui.say("Saved assembly '{}' to {}".format(name, path))
                asm_name = name
                layers = stack.current(lib, doc.Objects.FindId(drivers[0].Id))
                originals = [(d.Id, None, name) for d in drivers]
                doc.Views.Redraw()
                continue
            else:
                continue
        except Exception as ex:
            ui.say("Could not apply {}: {}".format(op, ex))
            continue
        apply(layers)
    return ui.Result.Success
