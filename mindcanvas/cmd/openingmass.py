"""MCOpeningMass: windows and doors driven by masses (boxes you push and pull with the gumball).

Click a wall: a window / door of the current type goes there with a box around its rough opening.
Select closed solids (boxes you drew): each becomes a mass; every wall it crosses gets an opening
the size of the cut (the rough opening; the box's depth does not matter).
Options: Type, unit Width / Height / Sill (for clicked walls), Swing / Hinge (doors), HeadCourse,
SnapHead, Convert (give existing windows / doors a box), Show (masses on / off).
With MCLive on, scaling or moving a box with the gumball rebuilds its walls when you let go.
"""

import scriptcontext
import Rhino

from .. import engine, library, live, masses, meta
from ..openings import core
from . import ui
from .opening import STICKY, Settings, pick_type
from .editopening import select_openings

RI = Rhino.Input


def _filter(doc):
    def _ok(rh_obj, geom, ci):
        drv = meta.driver_of(doc, rh_obj)
        if drv is not None:
            return meta.get(drv, meta.TYPE) == "wall"
        return masses.is_solid_candidate(rh_obj)
    return RI.Custom.GetObjectGeometryFilter(_ok)


def _report(sr):
    ui.say("Mass: {} opening(s), {} wall(s) rebuilt in {:.2f}s.".format(
        len(sr.openings), len(sr.results), sr.seconds))
    for w in sr.warnings:
        ui.say("  warning: " + w)
    for r in sr.results:
        for w in r.warnings:
            ui.say("  warning: " + w)


def convert(doc, lib, snap):
    ops = select_openings(doc, "Select windows / doors to give a mass")
    n = 0
    for o in ops:
        if masses.mass_of(doc, o) is not None:
            continue
        try:
            masses.from_opening(doc, o, lib, snap)
            n += 1
        except ValueError as ex:
            ui.say("  skipped: {}".format(ex))
    ui.say("Gave {} opening(s) a mass.".format(n))


def run():
    doc = ui.doc()
    lib = library.get()
    names = core.type_names(lib)
    if not names:
        ui.say("No opening types in library/openings.")
        return ui.Result.Cancel
    st = scriptcontext.sticky.get(STICKY, {})
    tname = st.get("type") if st.get("type") in names else pick_type(lib)
    if not tname:
        return ui.Result.Cancel
    s = Settings(doc, lib, tname, st.get("params"), st.get("snap", True))
    masses.ensure_layer(doc)
    made = 0
    while True:
        go = RI.Custom.GetObject()
        go.SubObjectSelect = False
        go.GroupSelect = False
        go.EnablePreSelect(True, True)
        go.AcceptNothing(True)
        go.SetCustomGeometryFilter(_filter(doc))
        go.SetCommandPrompt("Click a wall for a {} mass, or select boxes to use as masses [{}] (Enter to finish)".format(
            "door" if s.door else "window", s.type_name))
        handlers = s.add_options(go)
        i_convert = go.AddOption("Convert")
        show = RI.Custom.OptionToggle(masses.is_visible(doc), "Off", "On")
        i_show = ui.add_option_toggle(go, "Show", show)
        res = go.GetMultiple(1, 0)
        if res == RI.GetResult.Option:
            if go.OptionIndex() == i_convert:
                convert(doc, lib, s.snap.CurrentValue)
            elif go.OptionIndex() == i_show:
                masses.set_visible(doc, show.CurrentValue)
            else:
                s.handle(go, handlers)
            doc.Views.Redraw()
            continue
        if res != RI.GetResult.Object:
            break
        prm = dict(s.params(), snap=s.snap.CurrentValue)
        picked = [go.Object(i) for i in range(go.ObjectCount)]
        doc.Objects.UnselectAll()
        for ref in picked:
            obj = ref.Object()
            drv = meta.driver_of(doc, obj)
            if drv is not None:
                pt = ref.SelectionPoint()
                if not pt.IsValid:
                    pt = obj.Geometry.GetBoundingBox(True).Center
                op, r = engine.add_opening(doc, drv, s.type_name, s.snapped(drv, s.params()), pt, lib)
                ui.report(r, "{}:".format(s.type_name))
                try:
                    masses.from_opening(doc, op, lib, s.snap.CurrentValue)
                except ValueError as ex:
                    ui.say("  no mass: {}".format(ex))
                    continue
            else:
                mass, sr = masses.make(doc, obj, s.type_name, prm, lib)
                _report(sr)
            made += 1
        scriptcontext.sticky[STICKY] = {"type": s.type_name, "params": s.params(), "snap": s.snap.CurrentValue}
        doc.Views.Redraw()
    if made and not live.is_on():
        ui.say("Turn MCLive on to rebuild the walls while you push and pull the masses.")
    ui.say("Made {} opening mass(es).".format(made))
    return ui.Result.Success if made else ui.Result.Cancel
