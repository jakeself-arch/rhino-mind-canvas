"""MCUpdate: rebuild assemblies (after editing driver curves or library files)."""

from .. import engine, library
from . import ui


def run():
    doc = ui.doc()
    drivers = ui.select_drivers("Select assemblies to rebuild", allow_all=True)
    if not drivers:
        return ui.Result.Cancel
    lib = library.get()
    total, secs = 0, 0.0
    for d in drivers:
        r = engine.build(doc, d.Id, lib)
        total += len(r.part_ids)
        secs += r.seconds
        for w in r.warnings:
            ui.say("  warning: " + w)
    ui.say("Rebuilt {} assemblies, {} parts in {:.2f}s.".format(len(drivers), total, secs))
    doc.Views.Redraw()
    return ui.Result.Success
