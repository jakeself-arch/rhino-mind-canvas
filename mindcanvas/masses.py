"""Mass drivers: closed solids, pushed and pulled with the gumball, that control the existing
drivers (the kinds are not rewritten: a mass only writes their params).

A mass carries user text
    mc.kind = mass      mc.type = opening | wall      mc.assembly = <opening type / wall assembly>
    mc.params = JSON: snap (SnapHead: head on the brick coursing), swing, hinge, head
and sits on MindCanvas::_Masses (translucent, tagged `exclude`: never drawn, never printed).
Wall masses (mc.type = wall, Phase 10) are in mindcanvas/wallmasses.py; sync() and release()
dispatch to it.

Opening masses (Phase 9): a solid crossing a wall. Where it cuts the wall's mid surface, the
bounding rectangle of the cut (along the wall x up) is the ROUGH OPENING; the mass's depth is
ignored. Every wall it crosses gets an opening driver (user text mc.mass = mass id) whose params
come from that rectangle (inches; shim from the opening type):
    window: width = RO width - 2 shim, sill = RO bottom + shim, height = RO height - 2 shim
    door:   width = RO width - 2 shim, sill = RO bottom,        height = RO height - shim
plus params["ro"] = {"width", "bottom", "top"} (bottom / top above the host base): the rectangle
as drawn. SnapHead moves the unit to the brick coursing but "ro" keeps the mass where it was put.
A cut across a wall corner or past a wall end is rejected with a warning (no corner windows).

Two-way:
    sync(doc, mass)   mass -> openings (create / update / delete) -> host builds. Live mode runs
                      it on every gumball edit. Only the geometry params are written to existing
                      openings; type, swing, hinge and head stay as edited (MCEditOpening).
    follow(doc, ctx)  called by engine.build after every host build: a mass with ONE opening is
                      moved with the opening's frame (stored on the opening as mc.mass.frame: the
                      host curve moved, e.g. its wall mass was moved; a frame that only turned
                      around while the box still fits, a flipped wall, leaves it) and resized to
                      its rough opening ("ro", else derived from
                      the unit size: numeric edits, the opening line moved). Masses with several
                      openings only follow their own edits.
"""

import json

import System
import Rhino

from . import docutil, geo, library, meta, units

G = Rhino.Geometry
MASS = "mc.mass"                 # opening driver -> its mass id
FRAME = "mc.mass.frame"          # opening driver -> [ox, oy, oz, xx, xy] of its plane at the last build
LAYER = docutil.MASS_LAYER
COLOR = (110, 190, 255)
TRANSPARENCY = 0.7
MARGIN_IN = 6.0                  # new boxes stick out of the wall faces by this much
EDGE_IN = 0.25                   # a cut closer than this to a wall end / corner is rejected
MIN_IN = 1.0                     # smallest rough opening

_STATE = {"driving": 0}


class _driving(object):
    """Inside: host builds come from a mass edit (follow() stores frames but moves no mass)."""

    def __enter__(self):
        _STATE["driving"] += 1
        return self

    def __exit__(self, *exc):
        _STATE["driving"] -= 1
        return False


def _quiet():
    from . import live
    return live.quiet()


# -- objects -----------------------------------------------------------------------------
def is_mass(obj):
    return meta.is_mass(obj)


def all_masses(doc):
    found = doc.Objects.FindByUserString(meta.KIND, meta.MASS_KIND, True) or []
    return [o for o in found if not o.IsDeleted]


def openings_of(doc, mass_id):
    from .openings import core
    found = doc.Objects.FindByUserString(MASS, str(mass_id), True) or []
    return [o for o in found if not o.IsDeleted and core.is_opening(o)]


def mass_of(doc, op_obj):
    mid = meta.get(op_obj, MASS) if op_obj is not None else None
    if not mid:
        return None
    try:
        m = doc.Objects.FindId(System.Guid(mid))
    except Exception:
        return None
    return m if (m is not None and not m.IsDeleted and is_mass(m)) else None


def to_brep(geom):
    if isinstance(geom, G.Brep):
        return geom.DuplicateBrep()
    if isinstance(geom, G.Extrusion):
        return geom.ToBrep()
    return None


def is_solid_candidate(obj):
    """A closed Brep / Extrusion that is not a Mind Canvas part, driver or mass already."""
    if obj is None or meta.get(obj, meta.KIND):
        return False
    b = to_brep(obj.Geometry)
    return b is not None and b.IsSolid


def ensure_layer(doc):
    """MindCanvas::_Masses: light blue, translucent render material, never printed or drawn."""
    from .drawing import tags
    idx = docutil.ensure_layer(doc, LAYER, COLOR)
    layer = doc.Layers[idx]
    changed = False
    if layer.PlotWeight != -1:
        layer.PlotWeight = -1
        changed = True
    if (layer.GetUserString(tags.KEY) or "") != "exclude":
        layer.SetUserString(tags.KEY, "exclude")
        changed = True
    if layer.RenderMaterialIndex < 0:
        mat = Rhino.DocObjects.Material()
        mat.Name = "MC Mass"
        mat.DiffuseColor = System.Drawing.Color.FromArgb(*COLOR)
        mat.Transparency = TRANSPARENCY
        layer.RenderMaterialIndex = doc.Materials.Add(mat)
        changed = True
    if changed:
        doc.Layers.Modify(layer, idx, True)
    return idx


def set_visible(doc, on):
    idx = ensure_layer(doc)
    layer = doc.Layers[idx]
    if layer.IsVisible != bool(on):
        layer.IsVisible = bool(on)
        doc.Layers.Modify(layer, idx, True)
    return layer.IsVisible


def is_visible(doc):
    idx = doc.Layers.FindByFullPath(LAYER, -1)
    return idx < 0 or doc.Layers[idx].IsVisible


def write(doc, obj, type_name, prm, kind="opening"):
    attrs = obj.Attributes.Duplicate()
    attrs.SetUserString(meta.KIND, meta.MASS_KIND)
    attrs.SetUserString(meta.TYPE, kind)
    attrs.SetUserString(meta.ASSEMBLY, type_name)
    attrs.SetUserString(meta.PARAMS, json.dumps(prm, sort_keys=True))
    attrs.LayerIndex = ensure_layer(doc)
    attrs.MaterialSource = Rhino.DocObjects.ObjectMaterialSource.MaterialFromLayer
    attrs.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromLayer
    with _quiet():
        doc.Objects.ModifyAttributes(obj, attrs, True)
    return doc.Objects.FindId(obj.Id)


def mass_params(params):
    """The params a mass keeps for the openings it creates."""
    return dict((k, params[k]) for k in ("snap", "swing", "hinge", "head") if k in (params or {}))


def link(doc, op_obj, mass_id):
    attrs = op_obj.Attributes.Duplicate()
    attrs.SetUserString(MASS, str(mass_id))
    with _quiet():
        doc.Objects.ModifyAttributes(op_obj, attrs, True)


def set_type(doc, op_obj, type_name):
    """An opening's type changed (MCEditOpening): its mass creates that type from now on."""
    m = mass_of(doc, op_obj)
    if m is not None and meta.get(m, meta.ASSEMBLY) != type_name:
        write(doc, m, type_name, meta.params(m))


# -- walls -------------------------------------------------------------------------------
class WallInfo(object):
    """What a mass needs from a wall without building it: the oriented curve, base, height and
    the stack's face offsets (model units)."""

    def __init__(self, doc, lib, obj):
        from .kinds import wall
        prm = meta.params(obj)
        assembly = lib.assembly(meta.get(obj, meta.ASSEMBLY))
        s = units.inch_scale(doc)
        self.obj = obj
        self.raw = obj.Geometry
        crv = geo.orient_driver(self.raw)
        if prm.get("flip"):
            crv.Reverse()
        self.curve = crv
        self.base_z = crv.PointAtStart.Z + units.parse_length(prm.get("base_offset", 0)) * s
        self.height = units.parse_length(prm.get("height", assembly.get("default_height", "10'"))) * s
        offs = wall.stack_offsets(lib, assembly, prm, s)
        self.y_ext = max(o[1] for o in offs)
        self.y_int = min(o[2] for o in offs)


def mid_surface(doc, curve, y_ext, y_int, z0, z1):
    """Vertical Brep through the middle of a wall's stack between z0 and z1."""
    tol = doc.ModelAbsoluteTolerance
    mid = geo.offset(curve, 0.5 * (y_ext + y_int), tol)
    mid.Translate(G.Vector3d(0, 0, z0 - mid.PointAtStart.Z))
    srf = G.Surface.CreateExtrusion(mid, G.Vector3d(0, 0, z1 - z0))
    return G.Brep.CreateFromSurface(srf) if srf is not None else None


def cut_points(doc, brep, surface):
    """Points along the cut of a mass through a wall's mid surface ([] if it does not cross)."""
    if brep is None or surface is None:
        return []
    tol = doc.ModelAbsoluteTolerance
    ok, curves, pts = Rhino.Geometry.Intersect.Intersection.BrepBrep(brep, surface, tol)
    if not ok or not curves:
        return []
    out = []
    for c in curves:
        ok, pl = c.TryGetPolyline()
        if ok:
            out.extend(pl)
            continue
        out.extend(c.PointAt(t) for t in (c.DivideByCount(32, True) or []))
        out.extend([c.PointAtStart, c.PointAtEnd])
    return out


def _station(raw, p):
    from .openings import core
    return core.station_of(raw, p)


def crossings(doc, lib, brep, warnings):
    """[(wall object, ro)] for every wall the mass crosses; ro (inches) = {"station" (center,
    along the driver as drawn), "width", "bottom", "top" (above the wall base)}."""
    from .openings import core
    tol = doc.ModelAbsoluteTolerance
    s = units.inch_scale(doc)
    bb = brep.GetBoundingBox(True)
    out = []
    for w in meta.all_drivers(doc, "wall"):
        if w.IsDeleted:
            continue
        wb = w.Geometry.GetBoundingBox(True)
        wb.Inflate(units.to_model(doc, 48))
        if bb.Max.X < wb.Min.X or bb.Min.X > wb.Max.X or bb.Max.Y < wb.Min.Y or bb.Min.Y > wb.Max.Y:
            continue
        try:
            info = WallInfo(doc, lib, w)
        except Exception as ex:
            warnings.append("Wall {} skipped: {}".format(str(w.Id)[:8], ex))
            continue
        if bb.Max.Z < info.base_z or bb.Min.Z > info.base_z + info.height:
            continue
        pad = units.to_model(doc, 24)
        srf = mid_surface(doc, info.curve, info.y_ext, info.y_int, min(bb.Min.Z, info.base_z) - pad,
                          max(bb.Max.Z, info.base_z + info.height) + pad)
        pts = cut_points(doc, brep, srf)
        if not pts:
            continue
        raw = info.raw
        L = raw.GetLength()
        st = [_station(raw, p) for p in pts]
        s0, s1 = min(st), max(st)
        z0, z1 = min(p.Z for p in pts), max(p.Z for p in pts)
        if (s1 - s0) < MIN_IN * s or (z1 - z0) < MIN_IN * s:
            continue
        edge = EDGE_IN * s
        kinks = [raw.GetLength(G.Interval(raw.Domain.T0, k)) for k in geo.kink_parameters(raw)]
        if any(s0 + edge < k < s1 - edge for k in kinks):
            warnings.append("A mass crosses a wall corner; corner openings are not supported (skipped).")
            continue
        if not raw.IsClosed and (s0 < edge or s1 > L - edge):
            warnings.append("A mass runs past a wall end; corner openings are not supported (skipped).")
            continue
        # width square to the wall at the middle of the cut (curved walls: the chord)
        sm = 0.5 * (s0 + s1)
        ok, t = raw.LengthParameter(sm)
        P = raw.PointAt(t)
        T = raw.TangentAt(t)
        T = G.Vector3d(T.X, T.Y, 0)
        T.Unitize()
        xs = [(G.Point3d(p.X, p.Y, P.Z) - P) * T for p in pts]
        x0, x1 = min(xs), max(xs)
        if not _rectangular(st, [p.Z for p in pts], s0, s1, z0, z1, units.to_model(doc, 0.125)):
            warnings.append("A mass is not a box square to its wall; its bounding rectangle is used.")
        ro = {"station": round((sm + 0.5 * (x0 + x1)) / s, 4), "width": round((x1 - x0) / s, 4),
              "bottom": round((z0 - info.base_z) / s, 4), "top": round((z1 - info.base_z) / s, 4)}
        out.append((w, ro))
    return out


def _rectangular(st, zs, s0, s1, z0, z1, tol):
    for cs, cz in ((s0, z0), (s1, z0), (s0, z1), (s1, z1)):
        if not any(abs(a - cs) < tol and abs(b - cz) < tol for a, b in zip(st, zs)):
            return False
    return True


# -- rough opening <-> unit ---------------------------------------------------------------------
def unit_params(t, ro):
    """Unit width / height / sill (inches) of an opening type for a rough opening."""
    shim = units.parse_length(t["shim"])
    door = t.get("category") == "door"
    width = ro["width"] - 2 * shim
    if door:
        sill = max(ro["bottom"], 0.0)
        height = ro["top"] - shim - sill
    else:
        sill = ro["bottom"] + shim
        height = ro["top"] - ro["bottom"] - 2 * shim
    return {"width": round(width, 4), "height": round(height, 4), "sill": round(sill, 4),
            "station": ro["station"],
            "ro": {"width": ro["width"], "bottom": ro["bottom"], "top": ro["top"]}}


def rough_opening(t, params):
    """{"width", "bottom", "top"} (inches) of an opening: params["ro"] (as its mass drew it),
    else from the unit size."""
    ro = params.get("ro")
    if ro:
        return ro
    shim = units.parse_length(t["shim"])
    door = t.get("category") == "door"
    W = units.parse_length(params.get("width", t["width"]))
    H = units.parse_length(params.get("height", t["height"]))
    sill = units.parse_length(params.get("sill", t["sill"]))
    return {"width": W + 2 * shim, "bottom": sill if door else sill - shim, "top": sill + H + shim}


# -- mass -> openings -----------------------------------------------------------------------------
class SyncResult(object):
    def __init__(self):
        self.results = []          # engine BuildResults of the hosts
        self.warnings = []
        self.openings = []         # opening ids now driven by the mass
        self.walls = []            # wall ids driven by the wall masses synced (wallmasses)
        self.removed = 0
        self.seconds = 0.0

    def __repr__(self):
        return "<SyncResult {} openings, {} hosts, {:.2f}s>".format(
            len(self.openings), len(self.results), self.seconds)


def sync(doc, mass_obj, lib=None):
    """Re-derive the mass's openings from its geometry and rebuild the hosts that changed."""
    import time
    from . import engine
    from .openings import core
    t0 = time.time()
    if meta.get(mass_obj, meta.TYPE) == "wall":
        from . import wallmasses
        return wallmasses.sync(doc, mass_obj, lib)
    lib = lib or library.get()
    out = SyncResult()
    brep = to_brep(mass_obj.Geometry)
    if brep is None or not brep.IsSolid:
        out.warnings.append("A mass must be a closed solid; nothing changed.")
        return out
    type_name = meta.get(mass_obj, meta.ASSEMBLY)
    mprm = meta.params(mass_obj)
    try:
        t = core.merged_type(lib, type_name)
    except KeyError as ex:
        out.warnings.append(str(ex))
        return out
    hits = crossings(doc, lib, brep, out.warnings)
    by_host = {}
    for o in openings_of(doc, mass_obj.Id):
        by_host.setdefault(meta.get(o, core.HOST) or "", []).append(o)
    hosts = {}
    with _driving():
        with _quiet():
            for w, ro in hits:
                prm = unit_params(t, ro)
                if prm["width"] <= 0 or prm["height"] <= 0:
                    out.warnings.append("A mass is smaller than the unit's shims; skipped.")
                    continue
                if mprm.get("snap"):
                    full = dict(mprm, **prm)
                    snapped, delta = engine.snap_to_coursing(doc, w, type_name, full, lib)
                    prm.update(dict((k, snapped[k]) for k in ("width", "height", "sill")))
                ops = by_host.pop(str(w.Id), [])
                if ops:
                    o = ops[0]
                    core.update(doc, o, prm)
                    for extra in ops[1:]:
                        doc.Objects.Delete(extra, True)
                        out.removed += 1
                else:
                    create = dict((k, mprm[k]) for k in ("swing", "hinge", "head") if k in mprm)
                    create.update(prm)
                    o = core.create(doc, w, type_name, create, lib=lib)
                    link(doc, o, mass_obj.Id)
                out.openings.append(o.Id)
                hosts[str(w.Id)] = w
            for hid, ops in by_host.items():
                for o in ops:
                    h = core.host_of(doc, o)
                    doc.Objects.Delete(o, True)
                    out.removed += 1
                    if h is not None:
                        hosts[str(h.Id)] = h
        for h in hosts.values():
            try:
                r = engine.build(doc, h.Id, lib)
            except Exception as ex:
                out.warnings.append("Wall {} could not be rebuilt: {}".format(str(h.Id)[:8], ex))
                continue
            out.results.append(r)
    out.seconds = time.time() - t0
    return out


def release(doc, mass_id, lib=None):
    """A mass was deleted: delete its openings and rebuild their hosts. Returns the BuildResults.
    Wall masses: a deleted wall mass deletes its wall, a deleted wall its mass (wallmasses)."""
    from . import engine, wallmasses
    from .openings import core
    out = wallmasses.release(doc, mass_id, lib)
    ops = openings_of(doc, mass_id)
    if not ops:
        return out
    hosts = {}
    with _quiet():
        for o in ops:
            h = core.host_of(doc, o)
            if h is not None:
                hosts[str(h.Id)] = h
            doc.Objects.Delete(o, True)
    return out + [engine.build(doc, h.Id, lib) for h in hosts.values()]


def delete_unused(doc, mass_ids):
    """Delete the masses (of deleted openings) that have no openings left."""
    n = 0
    with _quiet():
        for mid in set(mass_ids):
            try:
                m = doc.Objects.FindId(System.Guid(mid))
            except Exception:
                continue
            if (m is not None and not m.IsDeleted and is_mass(m) and meta.get(m, meta.TYPE) != "wall"
                    and not openings_of(doc, m.Id)):
                if doc.Objects.Delete(m, True):
                    n += 1
    return n


# -- openings -> mass -------------------------------------------------------------------------------
def _frame_data(plane):
    o, x = plane.Origin, plane.XAxis
    return [round(o.X, 6), round(o.Y, 6), round(o.Z, 6), round(x.X, 6), round(x.Y, 6)]


def _frame_plane(data):
    o = G.Point3d(data[0], data[1], data[2])
    x = G.Vector3d(data[3], data[4], 0)
    x.Unitize()
    return G.Plane(o, x, G.Vector3d.CrossProduct(G.Vector3d.ZAxis, x))


def _ctx_mid(ctx, op):
    key = (round(op.y_ext, 6), round(op.y_int, 6))
    cache = ctx.__dict__.setdefault("_mass_mid", {})
    if key not in cache:
        pad = ctx.u(48)
        cache[key] = mid_surface(ctx.doc, ctx.curve, op.y_ext, op.y_int, ctx.base_z - pad,
                                 ctx.base_z + ctx.height + pad)
    return cache[key]


def rect_local(ctx, op, brep):
    """(x0, x1, z0, z1) of the mass's cut through the wall in the opening's frame, else None."""
    pts = cut_points(ctx.doc, brep, _ctx_mid(ctx, op))
    if not pts:
        return None
    xs = [op.local(p)[0] for p in pts]
    zs = [p.Z for p in pts]
    return min(xs), max(xs), min(zs), max(zs)


def target_local(ctx, op):
    """(x0, x1, z0, z1) of the opening's rough opening in its frame, centered on its station
    (not where the host may have shifted the unit to clear a corner)."""
    ro = rough_opening(op.t, op.params)
    raw = getattr(ctx, "raw_curve", None)
    xc = 0.0
    if raw is not None:
        ok, t = raw.LengthParameter(min(max(ctx.u(op.params.get("station", 0.0)), 0.0), raw.GetLength()))
        if ok:
            xc = op.local(raw.PointAt(t))[0]
    hw = 0.5 * ctx.u(ro["width"])
    return xc - hw, xc + hw, ctx.base_z + ctx.u(ro["bottom"]), ctx.base_z + ctx.u(ro["top"])


def _close(a, b, tol):
    return all(abs(p - q) < tol for p, q in zip(a, b))


def _bbox_local(op, brep):
    bb = brep.GetBoundingBox(op.plane)     # in plane coordinates (x, y, z - plane z)
    return bb.Min.X, bb.Max.X, op.plane.Origin.Z + bb.Min.Z, op.plane.Origin.Z + bb.Max.Z


def _transformed(geom, xf):
    g = geom.Duplicate()
    if g.Transform(xf):
        return g
    b = to_brep(geom)
    return b if (b is not None and b.Transform(xf)) else None


def follow(doc, ctx):
    """After a host build: masses with one opening follow it (see the module doc); every
    mass-driven opening remembers its frame."""
    ops = [op for op in (getattr(ctx, "openings", None) or []) if meta.get(op.obj, MASS)]
    if not ops:
        return
    tol = ctx.u(1.0 / 32)
    for op in ops:
        o = doc.Objects.FindId(op.id)
        m = mass_of(doc, o)
        if m is None:
            continue
        frame = _frame_data(op.plane)
        if not _STATE["driving"] and len(openings_of(doc, m.Id)) == 1:
            try:
                _fit(doc, ctx, op, o, m, tol)
            except Exception as ex:
                ctx.warn("A mass could not follow its opening: {}".format(ex))
        if meta.get(o, FRAME) != json.dumps(frame):
            attrs = o.Attributes.Duplicate()
            attrs.SetUserString(FRAME, json.dumps(frame))
            with _quiet():
                doc.Objects.ModifyAttributes(o, attrs, True)


def _fit(doc, ctx, op, o, m, tol):
    geom = m.Geometry
    target = target_local(ctx, op)
    cur = rect_local(ctx, op, to_brep(geom))
    fits = cur is not None and _close(cur, target, tol)
    moved = None
    raw = meta.get(o, FRAME)
    if raw:
        old = _frame_plane(json.loads(raw))
        changed = old.Origin.DistanceTo(op.plane.Origin) > tol or old.XAxis.IsParallelTo(op.plane.XAxis, 1e-6) != 1
        # the wall moved: the box rides along (unless it still fits a wall whose line only turned
        # around, e.g. a wall mass flipped to its other face)
        if changed and not (fits and old.XAxis * op.plane.XAxis < 0):
            moved = _transformed(geom, G.Transform.PlaneToPlane(old, op.plane))
            if moved is not None:
                cur = rect_local(ctx, op, to_brep(moved))
    if moved is None and fits:
        return
    base = moved if moved is not None else geom
    if cur is None:
        cur = _bbox_local(op, to_brep(base))
    if not _close(cur, target, tol):
        w0, w1 = cur[1] - cur[0], cur[3] - cur[2]
        if w0 <= ctx.tol or w1 <= ctx.tol:
            return
        sx = (target[1] - target[0]) / w0
        sz = (target[3] - target[2]) / w1
        cx, cz = 0.5 * (cur[0] + cur[1]), 0.5 * (cur[2] + cur[3])
        tx, tz = 0.5 * (target[0] + target[1]), 0.5 * (target[2] + target[3])
        X, Y = op.plane.XAxis, op.plane.YAxis
        pc = G.Plane(op.pt(cx, 0, cz), X, Y)
        xf = G.Transform.Translation(X * (tx - cx) + G.Vector3d.ZAxis * (tz - cz)) * G.Transform.Scale(pc, sx, 1.0, sz)
        fitted = _transformed(base, xf)
        if fitted is None:
            ctx.warn("A mass could not be resized to its opening.")
            return
        base = fitted
    if base is geom:
        return
    with _quiet():
        doc.Objects.Replace(m.Id, base)


# -- creating masses ------------------------------------------------------------------------------
def from_opening(doc, op_obj, lib=None, snap=False):
    """A box mass around an existing opening's rough opening (sticking out of the wall faces by
    MARGIN_IN); the opening is linked to it. Returns the mass object (or the existing one)."""
    from .kinds import wall
    from .openings import core
    existing = mass_of(doc, op_obj)
    if existing is not None:
        return existing
    lib = lib or library.get()
    host = core.host_of(doc, op_obj)
    if host is None or meta.get(host, meta.TYPE) != "wall":
        raise ValueError("Only openings in walls can get a mass.")
    ctx = wall.make_context(doc, lib, host, meta.get(host, meta.ASSEMBLY), meta.params(host))
    rec = [op for op in ctx.openings if op.id == op_obj.Id]
    if not rec:
        raise ValueError("The opening is not placed in its wall (see the wall's warnings).")
    op = rec[0]
    x0, x1, z0, z1 = target_local(ctx, op)
    m = ctx.u(MARGIN_IN)
    box = op.box(x0, x1, op.y_int - op.sag - m, op.y_ext + op.sag + m, z0, z1)
    prm = mass_params(dict(meta.params(op_obj), snap=bool(snap)))
    with _quiet():
        mid = doc.Objects.AddBrep(box)
    mass = write(doc, doc.Objects.FindId(mid), meta.get(op_obj, meta.ASSEMBLY), prm)
    link(doc, doc.Objects.FindId(op_obj.Id), mass.Id)
    o = doc.Objects.FindId(op_obj.Id)
    attrs = o.Attributes.Duplicate()
    attrs.SetUserString(FRAME, json.dumps(_frame_data(op.plane)))
    with _quiet():
        doc.Objects.ModifyAttributes(o, attrs, True)
    return doc.Objects.FindId(mass.Id)


def make(doc, solid_obj, type_name, params=None, lib=None):
    """Turn a closed solid into an opening mass and sync it. Returns (mass object, SyncResult)."""
    from .openings import core
    lib = lib or library.get()
    core.type_def(lib, type_name)
    mass = write(doc, solid_obj, type_name, mass_params(params))
    return mass, sync(doc, mass, lib)
