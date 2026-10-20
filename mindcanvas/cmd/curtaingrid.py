"""MCCurtainGrid: the visual curtain-grid editor. Select a curtain wall (its curve or any part);
a window opens with its elevation: drag grid lines and transoms, add / delete them (a transom can
cross only some bays), paint panels vision / spandrel / shadow box, put doors (single or pair) in
bays and drag their head. The edited grid shows on the wall in the viewports; Apply (or Auto
apply) rebuilds it. The window stays open while you work in Rhino."""

from .. import library
from ..kinds import curtainwall as cwkind
from . import ui


def run():
    doc = ui.doc()
    drivers = ui.select_drivers("Select a curtain wall to edit its grid", kind=cwkind.KIND)
    if not drivers:
        return ui.Result.Cancel
    from ..eto import cwgrid
    cwgrid.open_editor(doc, drivers[0], library.get())
    if len(drivers) > 1:
        ui.say("The grid editor works on one curtain wall at a time; opened the first one.")
    return ui.Result.Success
