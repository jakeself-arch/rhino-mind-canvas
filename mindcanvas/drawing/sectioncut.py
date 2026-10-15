"""Wall section cuts: a clipping plane perpendicular to a wall at a point, plus a
named view looking at the cut (parallel = the classic wall section; or a
section perspective). An optional second "depth" plane limits how much of the
wall beyond the cut is drawn; it clips but makes no poche (user text mc.clip).
"""

import System
import Rhino

from .. import geo, library, meta, units
from . import displaymode, styles
from .pipeline import CLIP_KEY

G = Rhino.Geometry
D = Rhino.DocObjects
NAME_KEY = "mc.section"


def wall_frame(doc, driver, point, lib=None):
    """(plane at the cut point: X = driver tangent, Y = exterior, Z up; assembly info).
    Works for any kind with bands (walls, curtain walls)."""
    from .. import kinds
    lib = lib or library.get()
    kmod = kinds.get(meta.get(driver, meta.TYPE, "wall"))
    ctx = kmod.make_context(doc, lib, driver, meta.get(driver, meta.ASSEMBLY), meta.params(driver))
    if hasattr(kmod, "section_frame"):      # floors, roofs: their own cut direction and extents
        return kmod.section_frame(ctx, point)
    crv = ctx.curve
    ok, t = crv.ClosestPoint(G.Point3d(point.X, point.Y, crv.PointAtStart.Z))
    frame = geo.frame_at(crv, t, ctx.base_z)
    grid = getattr(ctx, "grid", None)
    if grid is not None:        # curtain wall: the facet (bay chord) under the point
        hit = grid.cell_at(point)
        if hit is not None:
            bay = grid.bays[hit[0]]
            u, y = bay.local(point)
            frame = bay.frame(min(max(u, 0.0), bay.c), ctx.base_z)
    d_ext = max(b.d_ext for b in ctx.bands)
    d_int = min(b.d_int for b in ctx.bands)
    z0 = min(ctx.z_range(b)[0] for b in ctx.bands)
    z1 = max(ctx.z_range(b)[1] for b in ctx.bands)
    return frame, {"d_ext": d_ext, "d_int": d_int, "z0": z0, "z1": z1, "t": t}


def _clear_previous(doc, name):
    for o in doc.Objects.FindByUserString(NAME_KEY, name, True) or []:
        doc.Objects.Delete(o, True)


def make(doc, driver, point, view=None, name=None, depth_in=0.0, perspective=False, style=None,
         margin_in=18.0, lens=35.0):
    """Clipping plane(s) + camera on `view` (default active) + named view.
    Returns dict(name, clip_ids, plane)."""
    view = view or doc.Views.ActiveView
    vp = view.ActiveViewport
    inch = units.inch_scale(doc)
    frame, w = wall_frame(doc, driver, point)
    T = G.Vector3d(frame.XAxis)
    N = G.Vector3d(frame.YAxis)
    Z = G.Vector3d.ZAxis
    zc = 0.5 * (w["z0"] + w["z1"])
    yc = 0.5 * (w["d_ext"] + w["d_int"])
    origin = frame.Origin + N * yc
    origin = G.Point3d(origin.X, origin.Y, zc)
    # plane normal = (N x Z) = T: the display keeps the +T side, the camera looks along +T
    cut_plane = G.Plane(origin, N, Z)
    if cut_plane.Normal * T < 0:
        cut_plane = G.Plane(origin, -N, Z)
    if name is None:
        name = "MC Section {}".format(len(list(doc.Objects.FindByObjectType(D.ObjectType.ClipPlane) or [])) + 1)
    _clear_previous(doc, name)
    half_w = abs(w["d_ext"] - w["d_int"]) * 0.5 + margin_in * inch
    half_h = (w["z1"] - w["z0"]) * 0.5 + margin_in * inch
    ids = []
    a = D.ObjectAttributes()
    a.SetUserString(NAME_KEY, name)
    a.SetUserString(CLIP_KEY, "cut")
    a.Name = name
    cid = doc.Objects.AddClippingPlane(cut_plane, 2 * half_w, 2 * half_h, [vp.Id])
    if cid != System.Guid.Empty:
        doc.Objects.ModifyAttributes(cid, a, True)
        ids.append(cid)
    if depth_in and depth_in > 0:
        back = G.Plane(origin + T * (depth_in * inch), -N, Z)
        if back.Normal * T > 0:
            back = G.Plane(back.Origin, N, Z)
        b = D.ObjectAttributes()
        b.SetUserString(NAME_KEY, name)
        b.SetUserString(CLIP_KEY, "depth")
        b.Name = name + " depth"
        bid = doc.Objects.AddClippingPlane(back, 2 * half_w, 2 * half_h, [vp.Id])
        if bid != System.Guid.Empty:
            doc.Objects.ModifyAttributes(bid, b, True)
            ids.append(bid)
    # camera
    box = G.BoundingBox([origin - N * half_w - Z * half_h, origin + N * half_w + Z * half_h])
    if perspective:
        vp.ChangeToPerspectiveProjection(True, lens)
        dist = max(half_w, half_h) * 2.6
        cam = origin - T * dist + N * (half_w * 0.9) + Z * (half_h * 0.25)
        vp.SetCameraLocations(origin + T * (half_w * 0.6), cam)
        vp.Camera35mmLensLength = lens
    else:
        vp.ChangeToParallelProjection(True)
        cam = origin - T * (60.0 * 12 * inch)
        vp.SetCameraLocations(origin, cam)
        vp.CameraUp = Z
        vp.ZoomBoundingBox(box)
    if style is not None:
        try:
            from . import sectionstyle
            sectionstyle.apply(doc, styles.get(style))
        except Exception:
            pass
    displaymode.assign(view)
    idx = doc.NamedViews.FindByName(name)
    if idx >= 0:
        doc.NamedViews.Delete(idx)
    doc.NamedViews.Add(name, vp.Id)
    view.Redraw()
    return {"name": name, "clip_ids": ids, "plane": cut_plane, "origin": origin, "frame": frame}


def make_plan(doc, driver, point, view=None, name=None, cut_z=None, depth_in=24.0, style=None,
              margin_in=18.0):
    """Plan cut: a horizontal clipping plane at cut_z (default: the picked point's elevation)
    keeping what is below, a "depth" plane depth_in lower, and a top view centred on the
    point (parallel). Returns dict(name, clip_ids, plane, origin, frame)."""
    view = view or doc.Views.ActiveView
    vp = view.ActiveViewport
    inch = units.inch_scale(doc)
    frame, w = wall_frame(doc, driver, point)
    z = point.Z if cut_z is None else cut_z
    origin = G.Point3d(point.X, point.Y, z)
    cut_plane = G.Plane(origin, -G.Vector3d.ZAxis)
    if name is None:
        name = "MC Plan {}".format(len(list(doc.Objects.FindByObjectType(D.ObjectType.ClipPlane) or [])) + 1)
    _clear_previous(doc, name)
    half = abs(w["d_ext"] - w["d_int"]) * 0.5 + margin_in * inch
    ids = []
    for role, pl in (("cut", cut_plane),
                     ("depth", G.Plane(origin - G.Vector3d.ZAxis * (depth_in * inch), G.Vector3d.ZAxis))):
        if role == "depth" and not (depth_in and depth_in > 0):
            continue
        a = D.ObjectAttributes()
        a.SetUserString(NAME_KEY, name)
        a.SetUserString(CLIP_KEY, role)
        a.Name = name if role == "cut" else name + " depth"
        cid = doc.Objects.AddClippingPlane(pl, 4 * half, 4 * half, [vp.Id])
        if cid != System.Guid.Empty:
            doc.Objects.ModifyAttributes(cid, a, True)
            ids.append(cid)
    vp.ChangeToParallelProjection(True)
    vp.SetCameraLocations(origin, origin + G.Vector3d.ZAxis * (60.0 * 12 * inch))
    vp.CameraUp = frame.YAxis
    box = G.BoundingBox([origin - G.Vector3d(half, half, 0), origin + G.Vector3d(half, half, 0)])
    vp.ZoomBoundingBox(box)
    if style is not None:
        try:
            from . import sectionstyle
            sectionstyle.apply(doc, styles.get(style))
        except Exception:
            pass
    displaymode.assign(view)
    idx = doc.NamedViews.FindByName(name)
    if idx >= 0:
        doc.NamedViews.Delete(idx)
    doc.NamedViews.Add(name, vp.Id)
    view.Redraw()
    return {"name": name, "clip_ids": ids, "plane": cut_plane, "origin": origin, "frame": frame}
