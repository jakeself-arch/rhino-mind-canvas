"""MCUpdate: rebuild assemblies (after editing driver curves or library files).
Selecting a window / door rebuilds its wall."""

from .. import engine, library
from . import ui


def run():
    doc = ui.doc()
    drivers = ui.select_drivers("Select assemblies to rebuild", allow_all=True)
    if not drivers:
        return ui.Result.Cancel
    lib = library.get()
    results = engine.build_many(doc, drivers, lib)
    total = sum(len(r.part_ids) for r in results)
    secs = sum(r.seconds for r in results)
    for r in results:
        for w in r.warnings:
            ui.say("  warning: " + w)
    ui.say("Rebuilt {} assemblies, {} parts in {:.2f}s.".format(len(results), total, secs))
    doc.Views.Redraw()
    return ui.Result.Success
