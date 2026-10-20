"""MCWall: turn curves into wall assemblies (or draw a new polyline)."""

import scriptcontext
import Rhino

from .. import engine, library, meta, units
from ..kinds import wall as wallkind
from . import ui

RI = Rhino.Input
G = Rhino.Geometry
REF_OPTIONS = ["ExteriorFace", "InteriorFace", "Center", "CoreExterior", "CoreInterior", "CoreCenter"]
LOD_OPTIONS = ["Schematic", "Design", "Detail"]
STICKY = "mindcanvas.wall.settings"


def _draw_polyline(doc, lib, name, params):
    """Pick the wall's points with its band showing (viewport/ghost.WallBand): Enter finishes,
    Close closes it, Undo drops the last point, Flip / Location change the band on the fly.
    Returns ([curve object], params)."""
    from ..viewport import ghost
    params = dict(params)
    band = ghost.WallBand(doc, lib, name, params)
    closed = False
    while True:
        gp = RI.Custom.GetPoint()
        n = len(band.points)
        gp.SetCommandPrompt("Start of the wall" if n == 0 else "Next point (Enter to finish)")
        gp.AcceptNothing(n >= 2)
        i_undo = gp.AddOption("Undo") if n else -1
        i_close = gp.AddOption("Close") if n >= 2 else -1
        opt_flip = RI.Custom.OptionToggle(bool(params.get("flip")), "No", "Yes")
        ui.add_option_toggle(gp, "Flip", opt_flip)
        ref_i = wallkind.REFERENCES.index(params.get("reference", "center"))
        i_ref = ui.add_option_list(gp, "Location", REF_OPTIONS, ref_i)
        if n:
            gp.SetBasePoint(band.points[-1], True)
            z = band.points[0].Z
            gp.Constrain(G.Plane(G.Point3d(0, 0, z), G.Vector3d.ZAxis), False)
        gp.MouseMove += band.on_mouse_move
        gp.DynamicDraw += band.on_draw
        res = gp.Get()
        if res == RI.GetResult.Option:
            oi = gp.OptionIndex()
            if oi == i_undo and band.points:
                band.points.pop()
            elif oi == i_close:
                closed = True
                break
            elif oi == i_ref:
                params["reference"] = wallkind.REFERENCES[gp.Option().CurrentListOptionIndex]
            if bool(opt_flip.CurrentValue) != bool(params.get("flip")):
                params["flip"] = bool(opt_flip.CurrentValue)
            band = _rebuilt(band, doc, lib, name, params)
            continue
        if res == RI.GetResult.Point:
            p = gp.Point()
            if band.points:
                p = G.Point3d(p.X, p.Y, band.points[0].Z)
            band.points.append(p)
            continue
        if res == RI.GetResult.Nothing and n >= 2:
            break
        return [], params
    pts = list(band.points)
    if closed:
        pts.append(G.Point3d(pts[0]))
    oid = doc.Objects.AddCurve(G.PolylineCurve(pts))
    return [doc.Objects.FindId(oid)], params


def _rebuilt(band, doc, lib, name, params):
    from ..viewport import ghost
    nb = ghost.WallBand(doc, lib, name, params)
    nb.points, nb.xy = band.points, band.xy
    return nb


def run():
    doc = ui.doc()
    lib = library.get()
    if not engine.tolerance_ok(doc):
        ui.say("Mind Canvas: model tolerance is too coarse for assembly detail. Run MCSetup first.")
    name = ui.current_assembly(lib, "wall", doc)   # Assembly option changes it; no dialog
    if not name:
        ui.say("No wall assemblies in library/assemblies.")
        return ui.Result.Cancel
    st = scriptcontext.sticky.get(STICKY, {})

    def _defaults(asm_name):
        asm = lib.assembly(asm_name)
        h = units.parse_length(st.get("height", asm.get("default_height", "10'")))
        r = asm.get("default_reference", st.get("reference", "center"))
        return ui.length_option(h, doc), wallkind.REFERENCES.index(r)

    opt_h, ref_i = _defaults(name)
    opt_flip = RI.Custom.OptionToggle(bool(st.get("flip", False)), "No", "Yes")
    lod_i = wallkind.LODS.index(st.get("lod", "detail"))

    go = RI.Custom.GetObject()
    go.GeometryFilter = Rhino.DocObjects.ObjectType.Curve
    go.EnablePreSelect(True, True)
    curves = []
    while True:
        go.SetCommandPrompt("Select wall curves [{}]".format(name))
        go.ClearCommandOptions()
        i_asm = go.AddOption("Assembly")
        ui.add_option_double(go, "Height", opt_h)
        i_ref = ui.add_option_list(go, "Location", REF_OPTIONS, ref_i)
        i_flip = ui.add_option_toggle(go, "Flip", opt_flip)
        i_lod = ui.add_option_list(go, "Detail", LOD_OPTIONS, lod_i)
        i_draw = go.AddOption("Draw")
        res = go.GetMultiple(1, 0)
        if res == RI.GetResult.Option:
            oi = go.OptionIndex()
            if oi == i_asm:
                picked = ui.pick_assembly(lib, "wall", "Mind Canvas - Wall")
                if picked:
                    name = picked
                    opt_h, ref_i = _defaults(name)
            elif oi == i_ref:
                ref_i = go.Option().CurrentListOptionIndex
            elif oi == i_lod:
                lod_i = go.Option().CurrentListOptionIndex
            elif oi == i_draw:
                drawn = {"height": round(units.to_inches(doc, opt_h.CurrentValue), 4),
                         "reference": wallkind.REFERENCES[ref_i], "flip": bool(opt_flip.CurrentValue)}
                curves, drawn = _draw_polyline(doc, lib, name, drawn)
                ref_i = wallkind.REFERENCES.index(drawn["reference"])
                opt_flip.CurrentValue = bool(drawn["flip"])
                break
            continue
        if res == RI.GetResult.Object:
            curves = [go.Object(i).Object() for i in range(go.ObjectCount)]
            break
        return ui.Result.Cancel
    if not curves:
        return ui.Result.Cancel

    params = {
        "height": round(units.to_inches(doc, opt_h.CurrentValue), 4),
        "reference": wallkind.REFERENCES[ref_i],
        "flip": bool(opt_flip.CurrentValue),
        "lod": wallkind.LODS[lod_i],
    }
    scriptcontext.sticky[STICKY] = params
    for c in curves:
        if meta.is_driver(c) and meta.get(c, meta.TYPE) != "wall":
            ui.say("Skipped a {} line (edit it with MCEditOpening).".format(meta.get(c, meta.TYPE)))
            continue
        if meta.is_driver(c):
            r = engine.set_assembly(doc, c, name)
        else:
            r = engine.create(doc, c, name, params)
        ui.report(r, "Wall:")
    doc.Objects.UnselectAll()
    doc.Views.Redraw()
    return ui.Result.Success
