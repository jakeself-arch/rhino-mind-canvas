"""MCWallMass: walls driven by masses (boxes / extruded strips you push and pull with the gumball).

Select closed solids (a box, an extruded L / polyline / curved strip, a ring, a whole block): each
becomes a wall mass of the current assembly. Mode: Auto reads a thin solid as one wall (a strip) and
a block (a cube, an L-shaped or round building) as one closed wall around its whole outline
(Perimeter); Strip / Perimeter force either reading. SetMode applies the current Mode to masses
already made. The wall's finished exterior face sits on the mass's outer face and
the wall grows inward by the assembly's thickness (the mass's thickness does not matter); base and
height come from the mass. Masses that touch form a group: a closed ring puts the exterior outside,
an open group the face away from its center, a lone mass the face toward the camera. A blue arrow
shows the exterior side.
Options: Assembly, Mode, SetMode, Flip (pick masses: exterior to the other face; perimeters keep it
outside), Convert (give existing walls a mass), Show (masses on / off).
With MCLive on, moving, scaling or face-dragging a mass rebuilds its walls when you let go.
"""

import scriptcontext
import Rhino

from .. import library, live, masses, meta, wallmasses
from . import ui

RI = Rhino.Input
STICKY = "mindcanvas.wallmass.settings"
MODE_OPTIONS = ["Auto", "Strip", "Perimeter"]


def _solids(doc):
    def _ok(rh_obj, geom, ci):
        return masses.is_solid_candidate(rh_obj)
    return RI.Custom.GetObjectGeometryFilter(_ok)


def _report(sr, label="Wall masses:"):
    ui.say("{} {} wall(s), {} rebuilt in {:.2f}s.".format(label, len(sr.walls), len(sr.results), sr.seconds))
    for w in sr.warnings:
        ui.say("  warning: " + w)
    for r in sr.results:
        for w in r.warnings:
            ui.say("  warning: " + w)


def pick_wall_masses(doc, prompt):
    """Wall masses picked as the mass, its wall driver or a part of its wall."""
    go = RI.Custom.GetObject()
    go.SetCommandPrompt(prompt)
    go.SubObjectSelect = False
    go.GroupSelect = False
    go.EnablePreSelect(False, True)
    go.SetCustomGeometryFilter(RI.Custom.GetObjectGeometryFilter(
        lambda o, g, ci: wallmasses.pick_mass(doc, o) is not None))
    if go.GetMultiple(1, 0) != RI.GetResult.Object:
        return []
    out, seen = [], set()
    for i in range(go.ObjectCount):
        m = wallmasses.pick_mass(doc, go.Object(i).Object())
        if m is not None and m.Id not in seen:
            seen.add(m.Id)
            out.append(m)
    doc.Objects.UnselectAll()
    return out


def run():
    doc = ui.doc()
    lib = library.get()
    names = lib.assemblies("wall")
    st = scriptcontext.sticky.get(STICKY, {})
    name = st.get("assembly") if st.get("assembly") in names else ui.current_assembly(lib, "wall", doc)
    if not name:
        ui.say("No wall assemblies in library/assemblies.")
        return ui.Result.Cancel
    mode_i = MODE_OPTIONS.index(st.get("mode", "Auto")) if st.get("mode") in MODE_OPTIONS else 0
    masses.ensure_layer(doc)
    wallmasses.show_arrows(True)
    made = 0
    while True:
        go = RI.Custom.GetObject()
        go.SubObjectSelect = False
        go.GroupSelect = False
        go.EnablePreSelect(True, True)
        go.AcceptNothing(True)
        go.SetCustomGeometryFilter(_solids(doc))
        go.SetCommandPrompt("Select solids to use as wall masses [{}, {}] (Enter to finish)".format(
            name, MODE_OPTIONS[mode_i]))
        i_asm = go.AddOption("Assembly")
        i_mode = ui.add_option_list(go, "Mode", MODE_OPTIONS, mode_i)
        i_setmode = go.AddOption("SetMode")
        i_flip = go.AddOption("Flip")
        i_convert = go.AddOption("Convert")
        show = RI.Custom.OptionToggle(masses.is_visible(doc), "Off", "On")
        i_show = ui.add_option_toggle(go, "Show", show)
        res = go.GetMultiple(1, 0)
        if res == RI.GetResult.Option:
            oi = go.OptionIndex()
            if oi == i_asm:
                picked = ui.pick_assembly(lib, "wall", "Mind Canvas - Wall mass")
                if picked:
                    name = picked
            elif oi == i_mode:
                mode_i = go.Option().CurrentListOptionIndex
            elif oi == i_setmode:
                ms = pick_wall_masses(doc, "Select wall masses (or their walls) to read as {}".format(MODE_OPTIONS[mode_i]))
                if ms:
                    _report(wallmasses.set_mode(doc, ms, MODE_OPTIONS[mode_i].lower(), lib),
                            "Mode {}:".format(MODE_OPTIONS[mode_i]))
            elif oi == i_flip:
                ms = pick_wall_masses(doc, "Select wall masses (or their walls) to flip")
                if ms:
                    _report(wallmasses.flip(doc, ms, lib), "Flipped:")
            elif oi == i_convert:
                walls = [w for w in ui.select_drivers("Select walls to give a mass", kind="wall")
                         if wallmasses.mass_of(doc, w) is None]
                if walls:
                    ms, sr, skipped = wallmasses.convert(doc, walls, lib)
                    _report(sr, "Converted {}:".format(len(ms)))
                    for msg in skipped:
                        ui.say("  skipped " + msg)
            elif oi == i_show:
                on = masses.set_visible(doc, show.CurrentValue)
                wallmasses.show_arrows(on)
            doc.Views.Redraw()
            continue
        if res != RI.GetResult.Object:
            break
        solids = [go.Object(i).Object() for i in range(go.ObjectCount)]
        doc.Objects.UnselectAll()
        objs, sr = wallmasses.make_many(doc, solids, name, {"mode": MODE_OPTIONS[mode_i].lower()}, lib)
        _report(sr)
        made += len(objs)
        scriptcontext.sticky[STICKY] = {"assembly": name, "mode": MODE_OPTIONS[mode_i]}
        doc.Views.Redraw()
    if made and not live.is_on():
        ui.say("Turn MCLive on to rebuild the walls while you push and pull the masses.")
    ui.say("Made {} wall mass(es).".format(made))
    return ui.Result.Success if made else ui.Result.Cancel
