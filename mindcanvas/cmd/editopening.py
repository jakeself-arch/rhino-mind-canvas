"""MCEditOpening: change the type, size, sill, swing / hinge or head course of windows and doors
(select their line or any of their parts), or Remove them."""

import Rhino

from .. import engine, library, meta
from ..openings import core
from . import ui
from .opening import Settings

RI = Rhino.Input


def select_openings(doc, prompt):
    go = RI.Custom.GetObject()
    go.SetCommandPrompt(prompt)
    go.SubObjectSelect = False
    go.GroupSelect = False
    go.EnablePreSelect(True, True)

    def _ok(rh_obj, geom, ci):
        return core.opening_of(doc, rh_obj) is not None

    go.SetCustomGeometryFilter(RI.Custom.GetObjectGeometryFilter(_ok))
    go.GetMultiple(1, 0)
    if go.CommandResult() != ui.Result.Success:
        return []
    out, seen = [], set()
    for i in range(go.ObjectCount):
        op = core.opening_of(doc, go.Object(i).Object())
        if op is not None and op.Id not in seen:
            seen.add(op.Id)
            out.append(op)
    doc.Objects.UnselectAll()
    return out


def run():
    doc = ui.doc()
    lib = library.get()
    ops = select_openings(doc, "Select windows / doors to edit")
    if not ops:
        return ui.Result.Cancel
    first = ops[0]
    s = Settings(doc, lib, meta.get(first, meta.ASSEMBLY), meta.params(first))
    type_changed = False
    gg = RI.Custom.GetOption()
    gg.AcceptNothing(True)
    while True:
        gg.SetCommandPrompt("{} opening(s) [{}] (Enter to apply)".format(len(ops), s.type_name))
        gg.ClearCommandOptions()
        handlers = s.add_options(gg)
        i_remove = gg.AddOption("Remove")
        res = gg.Get()
        if res == RI.GetResult.Option:
            if gg.OptionIndex() == i_remove:
                hosts = [core.host_of(doc, o) for o in ops]
                with engine._quiet():
                    for o in ops:
                        doc.Objects.Delete(o, True)
                for h in dict((str(h.Id), h) for h in hosts if h is not None).values():
                    ui.report(engine.build(doc, h.Id, lib), "Rebuilt wall:")
                doc.Views.Redraw()
                return ui.Result.Success
            before = s.type_name
            s.handle(gg, handlers)
            type_changed = type_changed or s.type_name != before
            continue
        if res == RI.GetResult.Nothing:
            break
        return ui.Result.Cancel
    params = s.params()
    hosts = {}
    with engine._quiet():
        for o in ops:
            if type_changed:
                core.set_type(doc, o, s.type_name)
                o = doc.Objects.FindId(o.Id)
            core.update(doc, o, params)
            h = core.host_of(doc, o)
            if h is not None:
                hosts[str(h.Id)] = h
    for h in hosts.values():
        ui.report(engine.build(doc, h.Id, lib), "Updated:")
    doc.Views.Redraw()
    return ui.Result.Success
