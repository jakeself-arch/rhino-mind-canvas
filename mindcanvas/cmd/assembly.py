"""MCSetAssembly: swap the assembly type of existing walls."""

from .. import engine, library, meta
from . import ui


def run():
    doc = ui.doc()
    drivers = ui.select_drivers("Select walls to retype")
    if not drivers:
        return ui.Result.Cancel
    kind = meta.get(drivers[0], meta.TYPE)
    name = ui.pick_assembly(library.get(), kind, "Mind Canvas - Set Assembly")
    if not name:
        return ui.Result.Cancel
    for d in drivers:
        ui.report(engine.set_assembly(doc, d, name), "Retyped:")
    doc.Views.Redraw()
    return ui.Result.Success
