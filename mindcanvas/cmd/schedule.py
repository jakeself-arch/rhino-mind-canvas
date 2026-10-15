"""MCSchedule: material quantity takeoff, printed and optionally saved as CSV."""

import Rhino

from .. import schedule
from . import ui


def run():
    doc = ui.doc()
    drivers = ui.select_drivers("Select assemblies for takeoff", allow_all=True)
    if not drivers:
        return ui.Result.Cancel
    rows = schedule.takeoff(doc, [d.Id for d in drivers])
    ui.say(schedule.format_table(rows))
    dlg = Rhino.UI.SaveFileDialog()
    dlg.Filter = "CSV (*.csv)|*.csv"
    dlg.FileName = "MindCanvas_Takeoff.csv"
    dlg.Title = "Save takeoff as CSV (Cancel to skip)"
    if dlg.ShowSaveDialog():
        schedule.write_csv(rows, dlg.FileName)
        ui.say("Saved " + dlg.FileName)
    return ui.Result.Success
