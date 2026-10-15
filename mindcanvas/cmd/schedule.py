"""MCSchedule: material quantity takeoff, window / door counts and the curtain-wall panel schedule
(panels per infill type + glass area), printed and optionally saved as CSV (the opening and panel
schedules go next to it as <name>_Openings.csv / <name>_CurtainWalls.csv)."""

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
    cws = schedule.curtain_walls(doc, ids)
    if cws:
        ui.say("")
        ui.say(schedule.format_curtain_walls(cws))
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
        if cws:
            path = os.path.splitext(dlg.FileName)[0] + "_CurtainWalls.csv"
            schedule.write_curtain_walls_csv(cws, path)
            ui.say("Saved " + path)
    return ui.Result.Success
