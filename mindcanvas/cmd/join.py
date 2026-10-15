"""MCJoin: show and set how walls join (L / T joins between wall drivers, walls under floors and
roofs). Pick walls, then set the style of each end and the join priority:

    Start / End  Auto (wrap at an L, core at a T) | Wrap | Miter | Butt | None (never join)
    Priority     at an L the wall with the higher priority runs through (default 0)
    Report       list the joins of the selected walls
"""

import Rhino

from .. import engine, library, meta
from ..kinds import wall as wallkind
from . import ui

RI = Rhino.Input
STYLE_OPTIONS = ["Auto", "Wrap", "Miter", "Butt", "None"]
KEEP = "Keep"


def _report(doc, lib, drivers):
    from ..joins import find
    for d in drivers:
        ctx = wallkind.make_context(doc, lib, d, meta.get(d, meta.ASSEMBLY), meta.params(d))
        notes = find.describe(ctx)
        ui.say("Wall {} ({}):".format(str(d.Id)[:8], meta.get(d, meta.ASSEMBLY)))
        for n in notes or ["no joins"]:
            ui.say("  " + n)
        for w in ctx.warnings:
            ui.say("  warning: " + w)


def run():
    doc = ui.doc()
    lib = library.get()
    drivers = ui.select_drivers("Select walls to join", kind="wall")
    if not drivers:
        return ui.Result.Cancel
    p = meta.params(drivers[0])
    cur = p.get("joins") or {}
    pick = lambda v: STYLE_OPTIONS.index(str(v).capitalize()) if str(v).capitalize() in STYLE_OPTIONS else 0
    opts = [KEEP] + STYLE_OPTIONS
    start_i = pick(cur.get("start", "auto")) + 1 if len(drivers) == 1 else 0
    end_i = pick(cur.get("end", "auto")) + 1 if len(drivers) == 1 else 0
    opt_pri = RI.Custom.OptionInteger(int(float(p.get("join_priority", 0) or 0)), -100, 100)

    gg = RI.Custom.GetOption()
    gg.SetCommandPrompt("Wall joins (Enter to apply)")
    gg.AcceptNothing(True)
    while True:
        gg.ClearCommandOptions()
        i_s = ui.add_option_list(gg, "Start", opts, start_i)
        i_e = ui.add_option_list(gg, "End", opts, end_i)
        ui._idx(gg.AddOptionInteger("Priority", opt_pri))
        i_r = ui._idx(gg.AddOption("Report"))
        res = gg.Get()
        if res == RI.GetResult.Option:
            if gg.OptionIndex() == i_s:
                start_i = gg.Option().CurrentListOptionIndex
            elif gg.OptionIndex() == i_e:
                end_i = gg.Option().CurrentListOptionIndex
            elif gg.OptionIndex() == i_r:
                _report(doc, lib, drivers)
            continue
        if res == RI.GetResult.Nothing:
            break
        return ui.Result.Cancel

    for d in drivers:
        prm = meta.params(d)
        joins = dict(prm.get("joins") or {})
        for key, i in (("start", start_i), ("end", end_i)):
            if opts[i] != KEEP:
                joins[key] = opts[i].lower()
        joins = {k: v for k, v in joins.items() if v != "auto"}
        changes = {"joins": joins or None, "join_priority": opt_pri.CurrentValue or None}
        ui.report(engine.update_params(doc, d, changes, lib), "Joined:")
    doc.Views.Redraw()
    return ui.Result.Success
