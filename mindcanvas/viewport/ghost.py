"""Ghost previews for the placing commands.

    OpeningPreview   MCOpening: the window / door follows the mouse along the wall under it: its
                     rough opening on both wall faces (head on the brick coursing with SnapHead) and
                     a tag with type, size and sill. Walls are found by the mouse ray against each
                     wall's mid surface, else (plan views, or past a wall's end) the wall curve
                     nearest on screen (within NEAR_PX).
    WallBand         MCWall Draw: while you pick the points, the wall's thickness shows as a band
                     (exterior face heavier, ticks on the exterior side) with a tag; in 3D views
                     its top at the wall height.
"""

import Rhino
import System

from .. import geo, meta, units
from . import shapes

G = Rhino.Geometry
NEAR_PX = 14
GHOST = (255, 120, 0)
FILL = (255, 170, 60)
INK = (30, 30, 30)


def _c(rgb, a=255):
    return System.Drawing.Color.FromArgb(a, rgb[0], rgb[1], rgb[2])


def _tag(disp, vp, lines, xy):
    from . import overlay
    overlay._tag(disp, lines, xy[0] + 18, xy[1] + 14, vp)


# -- walls under the mouse -----------------------------------------------------------------------
class Target(object):
    """A wall or curtain wall the mouse can point at: its driver, its curve as drawn (raw), the
    curve the faces offset from, base / top z and the mid surface (model units)."""

    def __init__(self, doc, lib, driver):
        from .. import masses, props
        self.driver = driver
        self.kind = meta.get(driver, meta.TYPE)
        self.raw = driver.Geometry
        tol = doc.ModelAbsoluteTolerance
        if self.kind == "wall":
            info = masses.WallInfo(doc, lib, driver)
            self.curve, self.z0, self.z1 = info.curve, info.base_z, info.base_z + info.height
            mid = 0.5 * (info.y_ext + info.y_int)
        else:
            st = props.settings(lib, driver)
            s = units.inch_scale(doc)
            self.curve = geo.orient_driver(self.raw)
            self.z0 = self.raw.PointAtStart.Z + units.parse_length(st.get("base_offset", 0)) * s
            self.z1 = self.z0 + units.parse_length(st.get("height", 120)) * s
            mid = 0.0
        c = geo.offset(self.curve, mid, tol) if abs(mid) > tol else self.curve.DuplicateCurve()
        c.Translate(G.Vector3d(0, 0, self.z0 - c.PointAtStart.Z))
        srf = G.Surface.CreateExtrusion(c, G.Vector3d(0, 0, self.z1 - self.z0))
        self.brep = G.Brep.CreateFromSurface(srf) if srf is not None else None
        self.plan = shapes.pts(self.raw)


def targets(doc, lib, kinds=("wall", "curtain_wall")):
    out = []
    for k in kinds:
        for d in meta.all_drivers(doc, k):
            if d.IsDeleted or not d.Visible:
                continue
            try:
                out.append(Target(doc, lib, d))
            except Exception:
                pass
    return out


def _seg_dist(p, a, b):
    ax, ay = b[0] - a[0], b[1] - a[1]
    L2 = ax * ax + ay * ay
    t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / L2))
    q = (a[0] + t * ax, a[1] + t * ay)
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5


def hit(doc, tgts, vp, xy):
    """(Target, point on its mid surface / curve) under the screen point, or None."""
    ok, ray = vp.GetFrustumLine(float(xy[0]), float(xy[1]))
    if not ok:
        return None
    tol = doc.ModelAbsoluteTolerance
    cam = vp.CameraLocation
    rc = G.LineCurve(ray)
    best = None
    for t in tgts:
        if t.brep is None:
            continue
        res = Rhino.Geometry.Intersect.Intersection.CurveBrep(rc, t.brep, tol)
        pts = list(res[2]) if res and res[0] and len(res) > 2 and res[2] else []
        for p in pts:
            d = cam.DistanceTo(p)
            if best is None or d < best[0]:
                best = (d, t, p)
    if best is not None:
        return best[1], best[2]
    # plan views / past the faces: the nearest wall curve on screen
    near = None
    for t in tgts:
        scr = [vp.WorldToClient(p) for p in t.plan]
        for a, b in zip(scr, scr[1:]):
            dd = _seg_dist(xy, (a.X, a.Y), (b.X, b.Y))
            if dd <= NEAR_PX and (near is None or dd < near[0]):
                near = (dd, t)
    if near is None:
        return None
    t = near[1]
    # the point of the curve nearest to the mouse on screen
    best_p, best_d = None, None
    for i in range(0, 201):
        q = t.raw.PointAtNormalizedLength(i / 200.0)
        s = vp.WorldToClient(q)
        dd = (s.X - xy[0]) ** 2 + (s.Y - xy[1]) ** 2
        if best_d is None or dd < best_d:
            best_p, best_d = q, dd
    return t, best_p


# -- MCOpening ------------------------------------------------------------------------------------
class OpeningPreview(object):
    """Ghost of the opening MCOpening is about to place. `settings` is cmd.opening.Settings."""

    def __init__(self, doc, lib, settings):
        self.doc, self.lib, self.s = doc, lib, settings
        self.tgts = targets(doc, lib)
        self.current = None        # (Target, point)
        self.xy = None
        self._snap_cache = {}

    def refresh_targets(self):
        self.tgts = targets(self.doc, self.lib)

    def on_mouse_move(self, sender, e):
        try:
            p = e.WindowPoint
            self.xy = (p.X, p.Y)
            self.current = hit(self.doc, self.tgts, e.Viewport, self.xy)
        except Exception as ex:
            self.current = None
            print("Mind Canvas opening preview: {}".format(ex))

    def pick(self, view, xy):
        """Target and point under a click (the mouse position at the click)."""
        return hit(self.doc, self.tgts, view.ActiveViewport, xy)

    def params(self, host):
        prm = self.s.params()
        if host.kind != "wall" or not self.s.snap.CurrentValue:
            return prm
        key = (str(host.driver.Id), self.s.type_name, prm["width"], prm["height"], prm["sill"])
        if key not in self._snap_cache:
            from .. import engine
            try:
                self._snap_cache[key] = engine.snap_to_coursing(self.doc, host.driver, self.s.type_name, prm, self.lib)[0]
            except Exception:
                self._snap_cache[key] = prm
        out = dict(prm)
        out.update(self._snap_cache[key])
        return out

    def ghost(self):
        """(polylines, tag lines) of the opening at the current mouse position; ([], []) if none."""
        if self.current is None:
            return [], []
        from ..openings import core
        tg, p = self.current
        prm = self.params(tg)
        t = core.merged_type(self.lib, self.s.type_name, prm)
        door = t.get("category") == "door"
        what = "Door" if door else "Window"
        if tg.kind != "wall":
            line = [G.Point3d(p.X, p.Y, tg.z0), G.Point3d(p.X, p.Y, tg.z1)]
            return [line], ["{}: fills the curtain-wall bay".format(self.s.type_name)]
        station = units.to_inches(self.doc, core.station_of(tg.raw, p))
        of = shapes.OpeningFrame(self.doc, self.lib, tg.driver, station)
        half, zb, zt = shapes.opening_box(t, prm["width"], prm["height"], prm["sill"])
        name = self.s.type_name
        lines = [name if name.lower().startswith(what.lower()) else "{}: {}".format(what, name),
                 "{} x {}, sill {}".format(shapes.fmt(prm["width"]), shapes.fmt(prm["height"]), shapes.fmt(prm["sill"]))]
        if abs(prm["sill"] - self.s.params()["sill"]) > 1e-6 or abs(prm["height"] - self.s.params()["height"]) > 1e-6:
            lines.append("head on the brick coursing")
        return of.rect(-half, half, zb, zt), lines

    def on_draw(self, sender, e):
        try:
            polys, lines = self.ghost()
            col = _c(GHOST)
            for pl in polys:
                e.Display.DrawPolyline(pl, col, 2)
            if lines and self.xy is not None:
                _tag(e.Display, e.Viewport, lines, self.xy)
        except Exception as ex:
            print("Mind Canvas opening preview: {}".format(ex))


# -- MCWall Draw -------------------------------------------------------------------------------------
class WallBand(object):
    """The band of the wall being drawn: points so far + the mouse point."""

    def __init__(self, doc, lib, assembly, params):
        from ..kinds import wall as wallkind
        self.doc, self.lib = doc, lib
        self.assembly = assembly
        self.params = dict(params)
        s = units.inch_scale(doc)
        offs = wallkind.stack_offsets(lib, lib.assembly(assembly), self.params, s)
        self.y_ext = max(o[1] for o in offs)
        self.y_int = min(o[2] for o in offs)
        self.height = units.parse_length(self.params.get("height", 120)) * s
        self.s = s
        self.points = []
        self.xy = None

    def side(self):
        return -1.0 if self.params.get("flip") else 1.0

    def faces(self, pts):
        """(exterior polyline, interior polyline) of an open polyline through pts."""
        tol = self.doc.ModelAbsoluteTolerance
        clean = [pts[0]]
        for p in pts[1:]:
            if p.DistanceTo(clean[-1]) > tol * 10:
                clean.append(p)
        if len(clean) < 2:
            return None
        crv = G.PolylineCurve(clean)
        out = []
        for d in (self.y_ext, self.y_int):
            try:
                out.append(shapes.pts(geo.offset(crv, self.side() * d, tol)))
            except Exception:
                return None
        return out

    def ticks(self, ext, itr):
        """Short strokes from the exterior face outward, one per segment (where the exterior is)."""
        out = []
        L = max(abs(self.y_ext - self.y_int), self.s * 4)
        for a, b in zip(ext, ext[1:]):
            m = G.Point3d(0.5 * (a.X + b.X), 0.5 * (a.Y + b.Y), a.Z)
            t = b - a
            t.Z = 0
            if t.Length < 1e-9:
                continue
            n = G.Vector3d.CrossProduct(G.Vector3d.ZAxis, t)
            n = n * (self.side() / n.Length)
            out.append([m, m + n * L])
        return out

    def label(self):
        s = self.s
        T = (self.y_ext - self.y_int) / s
        ref = props_label(self.params.get("reference", "center"))
        return [self.assembly, "{} thick, {} high, location {}".format(shapes.fmt(T), shapes.fmt(self.height / s), ref)]

    def on_mouse_move(self, sender, e):
        p = e.WindowPoint
        self.xy = (p.X, p.Y)

    def on_draw(self, sender, e):
        try:
            pts = list(self.points) + [e.CurrentPoint]
            if self.points:
                z = self.points[0].Z
                pts = [G.Point3d(p.X, p.Y, z) for p in pts]
            disp = e.Display
            if len(pts) >= 2:
                f = self.faces(pts)
                if f is not None:
                    ext, itr = f
                    if len(ext) == len(itr):      # one quad per segment (a concave ring fills wrong)
                        for i in range(len(ext) - 1):
                            disp.DrawPolygon([ext[i], ext[i + 1], itr[i + 1], itr[i]], _c(FILL, 70), True)
                    disp.DrawPolyline(ext, _c(GHOST), 3)
                    disp.DrawPolyline(itr, _c(GHOST), 1)
                    for tk in self.ticks(ext, itr):
                        disp.DrawLine(tk[0], tk[1], _c(GHOST), 1)
                    up = G.Vector3d(0, 0, self.height)
                    for face in (ext, itr):
                        disp.DrawPolyline([p + up for p in face], _c(GHOST, 140), 1)
                    for p in (ext[0], itr[0], ext[-1], itr[-1]):
                        disp.DrawLine(p, p + up, _c(GHOST, 140), 1)
            if self.xy is not None:
                _tag(disp, e.Viewport, self.label(), self.xy)
        except Exception as ex:
            print("Mind Canvas wall preview: {}".format(ex))


def props_label(v):
    from .. import props
    return props.label(v)
