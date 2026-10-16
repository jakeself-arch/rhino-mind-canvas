"""MCEntourage: place line-drawn people, trees and shrubs (library/entourage), turn them to face
the view, give them new random variations, or capture your own figure from curves.

Click points to place figures (Enter to finish); each one faces the active view's camera.
Options: Type, HeightInches (0 = the library height), Random (a new variation per figure),
Mirror, and the actions FaceView (turn figures to the current view), Reseed (new variations of
selected figures) and Capture (curves drawn in a Front-like view -> a new library entry).
"""

import random

import scriptcontext
import Rhino

from .. import capture, library
from ..entourage import place
from . import profilecapture, ui

RI = Rhino.Input
STICKY = "mindcanvas.entourage.settings"


def _select_figures(prompt, allow_all=True):
    doc = ui.doc()
    go = RI.Custom.GetObject()
    go.SetCommandPrompt(prompt + (" (Enter for all)" if allow_all else ""))
    go.SubObjectSelect = False
    go.EnablePreSelect(True, True)
    go.AcceptNothing(allow_all)
    go.SetCustomGeometryFilter(RI.Custom.GetObjectGeometryFilter(lambda o, g, ci: place.is_entourage(o)))
    res = go.GetMultiple(1, 0)
    if res == RI.GetResult.Nothing and allow_all:
        return place.all_figures(doc)
    if res != RI.GetResult.Object:
        return []
    out = [go.Object(i).Object() for i in range(go.ObjectCount)]
    doc.Objects.UnselectAll()
    return out


def face_view():
    doc = ui.doc()
    figs = _select_figures("Figures to turn toward the current view")
    n = place.face_view(doc, figs, doc.Views.ActiveView.ActiveViewport)
    ui.say("Turned {} figure(s) to face '{}'.".format(n, doc.Views.ActiveView.ActiveViewport.Name))
    doc.Views.Redraw()


def reseed(lib):
    doc = ui.doc()
    figs = _select_figures("Figures to vary", allow_all=False)
    for f in figs:
        place.rebuild(doc, lib, f, seed=random.randint(1, 99999))
    ui.say("New variations of {} figure(s).".format(len(figs)))
    doc.Views.Redraw()


def capture_figure(lib):
    doc = ui.doc()
    plane = doc.Views.ActiveView.ActiveViewport.ConstructionPlane()
    curves = profilecapture.get_curves("Select the curves of the figure (closed = outline, open = lines)")
    if not curves:
        return None
    base = profilecapture.get_base("Base point (where the figure stands)", curves, plane)
    if base is None:
        return None
    name = profilecapture.get_name("Name of the figure", "Entourage - My Figure")
    if not name:
        return None
    if name in lib.data["entourage"] and not lib.is_user_entry("entourage", name):
        ui.say("'{}' is a library figure; choose another name.".format(name))
        return None
    defn = capture.entourage_definition(doc, curves, plane, base)
    path = lib.save_entry("entourage", name, defn)
    ui.say("Saved '{}' ({} outline(s), {} line(s)) to {}.".format(name, len(defn["loops"]), len(defn["lines"]), path))
    return name


def run():
    doc = ui.doc()
    lib = library.get()
    names = place.names(lib)
    if not names:
        ui.say("No figures in library/entourage.")
        return ui.Result.Failure
    st = scriptcontext.sticky.get(STICKY, {})
    current = st.get("name") if st.get("name") in names else names[0]
    o_h = RI.Custom.OptionDouble(float(st.get("height", 0.0)), 0.0, 2400.0)
    o_rand = RI.Custom.OptionToggle(st.get("random", True), "No", "Yes")
    o_mirror = RI.Custom.OptionToggle(st.get("mirror", False), "No", "Yes")
    placed = 0
    gp = RI.Custom.GetPoint()
    gp.AcceptNothing(True)
    while True:
        gp.SetCommandPrompt("Place '{}' (Enter to finish)".format(current))
        gp.ClearCommandOptions()
        i_type = ui._idx(gp.AddOption("Type"))
        ui.add_option_double(gp, "HeightInches", o_h)
        ui.add_option_toggle(gp, "Random", o_rand)
        ui.add_option_toggle(gp, "Mirror", o_mirror)
        i_face = ui._idx(gp.AddOption("FaceView"))
        i_seed = ui._idx(gp.AddOption("Reseed"))
        i_cap = ui._idx(gp.AddOption("Capture"))
        res = gp.Get()
        if res == RI.GetResult.Option:
            idx = gp.OptionIndex()
            if idx == i_type:
                pick = ui.pick_from_list("Mind Canvas - Entourage", "Figure", names, current)
                current = pick or current
            elif idx == i_face:
                face_view()
            elif idx == i_seed:
                reseed(lib)
            elif idx == i_cap:
                new = capture_figure(lib)
                if new:
                    names = place.names(lib)
                    current = new
            continue
        if res == RI.GetResult.Point:
            pt = gp.Point()
            seed = random.randint(1, 99999) if o_rand.CurrentValue else None
            h = o_h.CurrentValue or None
            obj = place.place(doc, lib, current, pt, 0.0, o_mirror.CurrentValue, seed, height=h)
            place.face_view(doc, [obj], gp.View().ActiveViewport if gp.View() else doc.Views.ActiveView.ActiveViewport)
            placed += 1
            doc.Views.Redraw()
            continue
        break
    scriptcontext.sticky[STICKY] = {"name": current, "height": o_h.CurrentValue, "random": o_rand.CurrentValue,
                                    "mirror": o_mirror.CurrentValue}
    if placed:
        ui.say("Placed {} figure(s).".format(placed))
    return ui.Result.Success
