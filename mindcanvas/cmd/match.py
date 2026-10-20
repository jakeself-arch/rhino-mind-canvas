"""MCMatch: click an assembly, then click others of the same kind: each one takes its assembly
and settings at once (like Rhino's MatchProperties). Enter when done.
Option Match = All (assembly + settings) | AssemblyOnly. See mindcanvas/match.py for what is
never copied."""

import scriptcontext
import Rhino

from .. import library, match, meta, props
from . import ui

RI = Rhino.Input
WHAT = ["All", "AssemblyOnly"]
STICKY = "mindcanvas.match.what"


def _getter(doc, prompt, ok):
    go = RI.Custom.GetObject()
    go.SetCommandPrompt(prompt)
    go.SubObjectSelect = False
    go.GroupSelect = False

    def _filter(rh_obj, geom, ci):
        d = props.assembly_of(doc, rh_obj)
        return d is not None and ok(d)

    go.SetCustomGeometryFilter(RI.Custom.GetObjectGeometryFilter(_filter))
    return go


def run():
    doc = ui.doc()
    lib = library.get()
    what_i = scriptcontext.sticky.get(STICKY, 0)

    go = _getter(doc, "Assembly to match", lambda d: True)
    go.EnablePreSelect(True, True)
    if go.Get() != RI.GetResult.Object:
        return ui.Result.Cancel
    src = props.assembly_of(doc, go.Object(0).Object())
    kind = meta.get(src, meta.TYPE)
    name = meta.get(src, meta.ASSEMBLY)
    doc.Objects.UnselectAll()
    doc.Views.Redraw()

    n = 0
    while True:
        gt = _getter(doc, "Click {} to match '{}' (Enter when done)".format(props.kind_name(kind, 2), name),
                     lambda d: meta.get(d, meta.TYPE) == kind and d.Id != src.Id)
        gt.EnablePreSelect(False, True)
        gt.AcceptNothing(True)
        i_what = ui.add_option_list(gt, "Match", WHAT, what_i)
        res = gt.Get()
        if res == RI.GetResult.Option:
            if gt.OptionIndex() == i_what:
                what_i = gt.Option().CurrentListOptionIndex
                scriptcontext.sticky[STICKY] = what_i
            continue
        if res != RI.GetResult.Object:
            break
        dst = props.assembly_of(doc, gt.Object(0).Object())
        src = doc.Objects.FindId(src.Id)
        try:
            r = match.match(doc, lib, src, dst, assembly_only=WHAT[what_i] == "AssemblyOnly")
        except Exception as ex:
            ui.say("Mind Canvas: {}".format(ex))
            continue
        ui.report(r, "Matched:")
        n += 1
        doc.Objects.UnselectAll()
        doc.Views.Redraw()
    ui.say("Matched {}.".format(props.kind_label(kind, n)))
    return ui.Result.Success
