"""MCOpening: place windows and doors in walls (and doors in curtain-wall bays: the unit fills the
bay clicked and gets a head transom). Click where the opening's center goes (in plan or 3D);
repeat, Enter to finish."""

import scriptcontext
import Rhino

from .. import engine, library, meta, units
from ..openings import core
from . import ui

RI = Rhino.Input
STICKY = "mindcanvas.opening.settings"
SWING = ["In", "Out"]
HINGE = ["Left", "Right"]
HEADS = ["None", "Soldier", "Sailor"]


def pick_type(lib, current=None):
    names = core.type_names(lib)
    return ui.pick_from_list("Mind Canvas - Opening", "Choose a window or door type", names, current)


def wall_filter(doc):
    def _ok(rh_obj, geom, ci):
        drv = meta.driver_of(doc, rh_obj)
        return drv is not None and meta.get(drv, meta.TYPE) in ("wall", "curtain_wall")
    return RI.Custom.GetObjectGeometryFilter(_ok)


class Settings(object):
    """Command-line options shared by MCOpening and MCEditOpening."""

    def __init__(self, doc, lib, type_name, params=None, snap=True):
        self.doc, self.lib = doc, lib
        self.snap = RI.Custom.OptionToggle(bool(snap), "No", "Yes")
        self.set_type(type_name, params)

    def set_type(self, type_name, params=None):
        self.type_name = type_name
        t = core.merged_type(self.lib, type_name)
        p = dict(t)
        p.update(params or {})
        L = lambda k: units.parse_length(p.get(k, t[k]))
        self.width = ui.length_option(L("width"), self.doc)
        self.height = ui.length_option(L("height"), self.doc)
        self.sill = ui.length_option(L("sill"), self.doc)
        self.door = t.get("category") == "door"
        self.swing = SWING.index(str(p.get("swing", "in")).title()) if str(p.get("swing", "in")).title() in SWING else 0
        self.hinge = HINGE.index(str(p.get("hinge", "left")).title()) if str(p.get("hinge", "left")).title() in HINGE else 0
        head = str(p.get("head", t["masonry"].get("head", "none"))).title()
        self.head = HEADS.index(head) if head in HEADS else 0

    def add_options(self, g):
        """Adds the options; returns {index: handler} for list options and Type."""
        h = {}
        h[g.AddOption("Type")] = "type"
        ui.add_option_double(g, "Width", self.width)
        ui.add_option_double(g, "Height", self.height)
        ui.add_option_double(g, "Sill", self.sill)
        if self.door:
            h[ui.add_option_list(g, "Swing", SWING, self.swing)] = "swing"
            h[ui.add_option_list(g, "Hinge", HINGE, self.hinge)] = "hinge"
        h[ui.add_option_list(g, "HeadCourse", HEADS, self.head)] = "head"
        ui.add_option_toggle(g, "SnapHead", self.snap)
        return h

    def handle(self, g, handlers):
        what = handlers.get(g.OptionIndex())
        if what == "type":
            picked = pick_type(self.lib, self.type_name)
            if picked:
                self.set_type(picked)
        elif what in ("swing", "hinge", "head"):
            setattr(self, what, g.Option().CurrentListOptionIndex)

    def params(self):
        inch = lambda o: round(units.to_inches(self.doc, o.CurrentValue), 4)
        p = {"width": inch(self.width), "height": inch(self.height), "sill": inch(self.sill),
             "head": HEADS[self.head].lower()}
        if self.door:
            p.update(swing=SWING[self.swing].lower(), hinge=HINGE[self.hinge].lower())
        return p

    def snapped(self, host, params):
        """params with the head moved to the host's brick coursing (SnapHead=Yes)."""
        if not self.snap.CurrentValue:
            return params
        out, delta = engine.snap_to_coursing(self.doc, host, self.type_name, params, self.lib)
        if delta:
            what = "height" if (self.door or out.get("height") != params.get("height")) else "sill"
            ui.say("SnapHead: {} {} {} to put the head on the brick coursing.".format(
                what, "raised" if delta > 0 else "lowered", units.format_inches(abs(delta))))
        return out


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
    placed = 0
    while True:
        go = RI.Custom.GetObject()
        go.SubObjectSelect = False
        go.GroupSelect = False
        go.EnablePreSelect(False, True)
        go.AcceptNothing(True)
        go.SetCustomGeometryFilter(wall_filter(doc))
        go.SetCommandPrompt("Click a wall where the {} goes [{}] (Enter to finish)".format(
            "door" if s.door else "window", s.type_name))
        handlers = s.add_options(go)
        res = go.Get()
        if res == RI.GetResult.Option:
            s.handle(go, handlers)
            continue
        if res != RI.GetResult.Object:
            break
        ref = go.Object(0)
        obj = ref.Object()
        pt = ref.SelectionPoint()
        if not pt.IsValid:
            pt = obj.Geometry.GetBoundingBox(True).Center
        drv = meta.driver_of(doc, obj)
        doc.Objects.UnselectAll()
        op, r = engine.add_opening(doc, drv, s.type_name, s.snapped(drv, s.params()), pt, lib)
        placed += 1
        ui.report(r, "{}:".format(s.type_name))
        scriptcontext.sticky[STICKY] = {"type": s.type_name, "params": s.params(), "snap": s.snap.CurrentValue}
        doc.Views.Redraw()
    ui.say("Placed {} opening(s).".format(placed))
    return ui.Result.Success if placed else ui.Result.Cancel
