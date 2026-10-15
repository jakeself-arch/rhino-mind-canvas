"""MCSchedule: material quantity takeoff and window / door counts, printed and optionally saved
as CSV (the opening schedule goes next to it as <name>_Openings.csv)."""

import os

import Rhino

from .. import schedule
from . import ui


def run():
    doc = ui.doc()
    drivers = ui.select_drivers("Select assemblies for takeoff", allow_all=True)
    if not drivers:
        return ui.Result.Cancel
    ids = [d.Id for d in drivers]
    rows = schedule.takeoff(doc, ids)
    ui.say(schedule.format_table(rows))
    ops = schedule.openings(doc, ids)
    if ops:
        ui.say("")
        ui.say(schedule.format_openings(ops))
    dlg = Rhino.UI.SaveFileDialog()
    dlg.Filter = "CSV (*.csv)|*.csv"
    dlg.FileName = "MindCanvas_Takeoff.csv"
    dlg.Title = "Save takeoff as CSV (Cancel to skip)"
    if dlg.ShowSaveDialog():
        schedule.write_csv(rows, dlg.FileName)
        ui.say("Saved " + dlg.FileName)
        if ops:
            path = os.path.splitext(dlg.FileName)[0] + "_Openings.csv"
            schedule.write_openings_csv(ops, path)
            ui.say("Saved " + path)
    return ui.Result.Success
