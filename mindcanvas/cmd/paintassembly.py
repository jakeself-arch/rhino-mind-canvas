"""MCPaintAssembly: click assemblies (their curve or any part) to give them one assembly / window
type, like a paint bucket. Started by the palette's Paint... button with the chosen tile; run on
its own it asks for the kind and the assembly. Option Assembly changes it; Enter finishes."""

import Rhino
import scriptcontext

from .. import library, meta, props
from ..eto import palette
from . import ui

RI = Rhino.Input


def _choose(lib, kind=None):
    if kind is None:
        labels = [t for _, t in palette.TABS]
        lbl = ui.pick_from_list("Mind Canvas - Paint", "What do you want to paint?", labels)
        if not lbl:
            return None, None
        kind = palette.TABS[labels.index(lbl)][0]
    name = ui.pick_from_list("Mind Canvas - Paint", "Paint with", palette.names(lib, kind),
                             palette.current(lib, kind))
    return kind, name


def run():
    doc = ui.doc()
    lib = library.get()
    kind, name = scriptcontext.sticky.pop(palette.PAINT_KEY, (None, None))
    if not name:
        kind, name = _choose(lib)
        if not name:
            return ui.Result.Cancel

    def _ok(rh_obj, geom, ci):
        d = props.assembly_of(doc, rh_obj)
        return d is not None and meta.get(d, meta.TYPE) == kind

    painted = 0
    doc.Objects.UnselectAll()
    while True:
        go = RI.Custom.GetObject()
        go.SubObjectSelect = False
        go.GroupSelect = False
        go.EnablePreSelect(False, True)
        go.AcceptNothing(True)
        go.SetCustomGeometryFilter(RI.Custom.GetObjectGeometryFilter(_ok))
        go.SetCommandPrompt("Click {} to make them '{}' (Enter to finish)".format(props.kind_name(kind, 2), name))
        i_asm = go.AddOption("Assembly")
        res = go.Get()
        if res == RI.GetResult.Option:
            if go.OptionIndex() == i_asm:
                k, n = _choose(lib, kind)
                if n:
                    name = n
            continue
        if res != RI.GetResult.Object:
            break
        d = props.assembly_of(doc, go.Object(0).Object())
        doc.Objects.UnselectAll()
        if d is None:
            continue
        if meta.get(d, meta.ASSEMBLY) == name:
            ui.say("Already '{}'.".format(name))
            continue
        for r in palette.apply_to(doc, lib, [d], name):
            ui.report(r, "{}:".format(name))
        painted += 1
        doc.Views.Redraw()
    palette.set_current(lib, kind, name, doc)
    ui.say("Painted {} {}.".format(painted, props.kind_name(kind, painted)))
    return ui.Result.Success if painted else ui.Result.Cancel
