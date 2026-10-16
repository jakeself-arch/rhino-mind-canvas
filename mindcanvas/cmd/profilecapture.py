"""MCProfileCapture: turn closed curves drawn in Rhino into a library profile.

Draw the profile in any view (X across, Y up of the active construction plane), run the command,
select the curves (the largest closed one is the outline, the others holes), click the base point
(for trims: the point on the wall face at the trim's height), name it. The profile goes to
library/profiles/zz_user_profiles.json; family 'trim' lists it in MCTrim.
"""

import scriptcontext
import Rhino

from .. import capture, library
from . import ui

RI = Rhino.Input
STICKY = "mindcanvas.profilecapture.settings"
FAMILIES = ["Trim", "None"]


def get_curves(prompt, closed_only=False):
    go = RI.Custom.GetObject()
    go.SetCommandPrompt(prompt)
    go.GeometryFilter = Rhino.DocObjects.ObjectType.Curve
    if closed_only:
        go.GeometryAttributeFilter = RI.Custom.GeometryAttributeFilter.ClosedCurve
    go.SubObjectSelect = False
    go.EnablePreSelect(True, True)
    if go.GetMultiple(1, 0) != RI.GetResult.Object:
        return []
    out = [go.Object(i).Curve() for i in range(go.ObjectCount)]
    ui.doc().Objects.UnselectAll()
    return [c for c in out if c is not None]


def get_base(prompt, curves, plane):
    bb = Rhino.Geometry.BoundingBox.Empty
    for c in curves:
        bb.Union(c.GetBoundingBox(plane))
    corner = plane.PointAt(bb.Min.X, bb.Min.Y)
    gp = RI.Custom.GetPoint()
    gp.SetCommandPrompt(prompt + " (Enter = lower-left corner)")
    gp.AcceptNothing(True)
    res = gp.Get()
    if res == RI.GetResult.Point:
        return gp.Point()
    if res == RI.GetResult.Nothing:
        return corner
    return None


def get_name(prompt, default):
    rc, txt = RI.RhinoGet.GetString(prompt, False, default)
    return txt.strip() if rc == Rhino.Commands.Result.Success and txt and txt.strip() else None


def run():
    doc = ui.doc()
    lib = library.get()
    plane = doc.Views.ActiveView.ActiveViewport.ConstructionPlane()
    curves = get_curves("Select the closed curves of the profile", closed_only=True)
    if not curves:
        return ui.Result.Cancel
    if not all(c.IsPlanar(doc.ModelAbsoluteTolerance) for c in curves):
        ui.say("Profile curves must be planar.")
        return ui.Result.Failure
    base = get_base("Base point (on the wall face, at the trim height)", curves, plane)
    if base is None:
        return ui.Result.Cancel
    st = scriptcontext.sticky.get(STICKY, {})
    fam_i = FAMILIES.index(st.get("family", "Trim"))
    go = RI.Custom.GetOption()
    go.AcceptNothing(True)
    while True:
        go.SetCommandPrompt("Profile family (Enter to continue)")
        go.ClearCommandOptions()
        i_f = ui.add_option_list(go, "Family", FAMILIES, fam_i)
        res = go.Get()
        if res == RI.GetResult.Option:
            fam_i = go.Option().CurrentListOptionIndex
            continue
        if res == RI.GetResult.Nothing:
            break
        return ui.Result.Cancel
    material = ui.pick_from_list("Mind Canvas - Profile", "Material", sorted(lib.data["materials"]),
                                 st.get("material", "Wood Trim"))
    name = get_name("Profile name", st.get("name", "Trim - My Profile"))
    if not name:
        return ui.Result.Cancel
    if name in lib.data["profiles"] and not lib.is_user_entry("profiles", name):
        ui.say("'{}' is a library profile; choose another name.".format(name))
        return ui.Result.Failure
    try:
        defn = capture.profile_definition(doc, curves, plane, base,
                                          family="trim" if FAMILIES[fam_i] == "Trim" else None, material=material)
    except ValueError as ex:
        ui.say(str(ex))
        return ui.Result.Failure
    path = lib.save_entry("profiles", name, defn)
    scriptcontext.sticky[STICKY] = {"family": FAMILIES[fam_i], "material": material, "name": name}
    n = len(defn.get("loops") or [defn["points"]])
    ui.say("Saved profile '{}' ({} loop(s)) to {}. Use MCTrim to put it on walls.".format(name, n, path))
    return ui.Result.Success
