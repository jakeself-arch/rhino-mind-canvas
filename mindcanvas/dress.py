"""Dress a massing solid (MCDress): one closed solid = one story.

A dressed solid is a PERIMETER wall mass (wallmasses.py: one closed wall along its outline, the
finished exterior face on the solid's faces, growing inward) whose params carry

    dress = {"floor": <floor assembly> | "none", "ground": bool}
    top_cut = inches its wall stops below the solid's top (set here)

Floors (sync): where a dressed solid's bottom sits on another's top (within GAP_IN, outlines
overlapping) the upper story gets a floor of its dress["floor"] assembly:

    top        = the shared face (the massing line is the finished floor; reference "top")
    boundary   = the LOWER solid's outline set in to the lower wall's core exterior (the rim sits on
                 the framing, as in tests/test_phase7.floor_joins), so the Phase 7 joins run the
                 sheathing over the rim
    lower wall stops at the floor framing's bottom: its mass gets top_cut = the floor's depth from
                 its top down through the joist layer

ground = True also gives a story with nothing under it a floor at its bottom (its own outline).
Floor drivers carry user text mc.dress = "<lower mass id>|<upper mass id>" (ground: "|<upper>").
sync() makes / moves / removes them and resets top_cut when a story above goes away; live mode runs
it after a dressed mass is edited or deleted. No roofs: a sloped top is reported (roofs from
masses = the unbuilt Phase 11); put an MCRoof on top.
"""

import Rhino

from . import engine, geo, library, meta, units, wallmasses

G = Rhino.Geometry
DRESS = "dress"
FLOOR_OF = "mc.dress"
GAP_IN = 0.5


def is_dressed(obj):
    return obj is not None and wallmasses.is_wall_mass(obj) and isinstance(meta.params(obj).get(DRESS), dict)


def dressed(doc):
    return [m for m in wallmasses.all_wall_masses(doc) if is_dressed(m)]


def dress_floors(doc):
    return [o for o in meta.all_drivers(doc, "floor") if not o.IsDeleted and meta.get(o, FLOOR_OF)]


def sloped_top(brep, tol):
    """True when a solid's top is not one level face (a gable / shed / dome top)."""
    flip = -1.0 if brep.SolidOrientation == G.BrepSolidOrientation.Inward else 1.0
    for f in brep.Faces:
        n = f.NormalAt(f.Domain(0).Mid, f.Domain(1).Mid)
        if f.OrientationIsReversed:
            n = -n
        nz = n.Z * flip
        if 0.02 < nz < 0.999:
            return True
    return False


class Story(object):
    """A dressed solid read for sync: its id, bottom / top z and plan outline (clockwise, at z0)."""

    def __init__(self, doc, obj):
        from . import masses
        tol = doc.ModelAbsoluteTolerance
        self.obj, self.id = obj, str(obj.Id)
        brep = masses.to_brep(obj.Geometry)
        bb = brep.GetBoundingBox(True)
        face, z0 = wallmasses._bottom_face(brep, tol)
        outer = [lp for lp in face.Loops if lp.LoopType == G.BrepLoopType.Outer][0]
        self.outline = geo.orient_driver(wallmasses._flat(outer.To3dCurve(), z0))
        self.z0, self.z1 = z0, bb.Max.Z
        self.settings = dict(meta.params(obj).get(DRESS) or {})
        self.bbox = self.outline.GetBoundingBox(True)

    @property
    def floor(self):
        f = self.settings.get("floor")
        return None if not f or str(f).lower() == "none" else f

    def on(self, below, doc):
        """True when this story sits on `below` (bottom on its top, outlines overlapping)."""
        if abs(self.z0 - below.z1) > units.to_model(doc, GAP_IN):
            return False
        a, b = self.bbox, below.bbox
        if a.Max.X <= b.Min.X or b.Max.X <= a.Min.X or a.Max.Y <= b.Min.Y or b.Max.Y <= a.Min.Y:
            return False
        tol = doc.ModelAbsoluteTolerance
        plane = G.Plane(G.Point3d(0, 0, self.z0), G.Vector3d.ZAxis)
        lower = wallmasses._flat(below.outline, self.z0)
        rel = G.Curve.PlanarClosedCurveRelationship(self.outline, lower, plane, tol)
        return rel != G.RegionContainment.Disjoint


def wall_inset(doc, lib, story):
    """Model distance from a story's outline (the wall's exterior face) in to its core exterior."""
    from .kinds import wall as wallkind
    w = wallmasses.wall_of(doc, story.obj)
    name = meta.get(w if w is not None else story.obj, meta.ASSEMBLY)
    prm = meta.params(w) if w is not None else dict(meta.params(story.obj).get("wall") or {})
    prm = dict(prm)
    prm.setdefault("reference", wallmasses.DEFAULT_REFERENCE)
    s = units.inch_scale(doc)
    offs = wallkind.stack_offsets(lib, lib.assembly(name), prm, s)
    ext = max(o[1] for o in offs)
    core = [o for o in offs if o[0].get("core")] or [o for o in offs if o[0].get("component") == "framing"]
    return max(0.0, ext - core[0][1]) if core else 0.0


def floor_depth(lib, name):
    """Inches from a floor assembly's top down to its framing bottom (through the joist layer)."""
    from .kinds import floor as floorkind
    from .kinds import wall as wallkind
    asm = lib.assembly(name)
    layers = [floorkind.fitted_layer(lib, spec, i, {}) for i, spec in enumerate(wallkind.layer_specs(lib, asm, {}))]
    core = [i for i, l in enumerate(layers) if l.get("core") or l.get("component") in ("joists", "framing")]
    c = core[0] if core else len(layers) - 1
    return sum(units.parse_length(l.get("thickness", 0)) for l in layers[:c + 1])


def boundary(doc, lib, base, z):
    """A floor's boundary: base's outline set in to its wall's core exterior, at z."""
    tol = doc.ModelAbsoluteTolerance
    d = wall_inset(doc, lib, base)
    crv = geo.offset(base.outline, -d, tol) if d > tol else base.outline.DuplicateCurve()   # clockwise: - = in
    return wallmasses._flat(crv, z)


def plan(doc, stories):
    """{key: (lower Story | None, upper Story)} of the floors there should be."""
    want = {}
    for up in stories:
        if up.floor is None:
            continue
        below = [lo for lo in stories if lo is not up and up.on(lo, doc)]
        for lo in below:
            want["{}|{}".format(lo.id, up.id)] = (lo, up)
        if not below and up.settings.get("ground"):
            want["|{}".format(up.id)] = (None, up)
    return want


def _tag(doc, obj, key):
    attrs = obj.Attributes.Duplicate()
    attrs.SetUserString(FLOOR_OF, key)
    doc.Objects.ModifyAttributes(obj, attrs, True)


class SyncResult(object):
    def __init__(self):
        self.created, self.moved, self.removed, self.cut = 0, 0, 0, 0
        self.results = []
        self.warnings = []

    def __repr__(self):
        return "<dress: +{} floors, {} moved, -{}, {} top cuts>".format(self.created, self.moved, self.removed, self.cut)


def sync(doc, lib=None):
    """Make the floors between dressed stories match the solids (and the lower walls' top cuts)."""
    lib = lib or library.get()
    out = SyncResult()
    stories = []
    for m in dressed(doc):
        try:
            stories.append(Story(doc, m))
        except Exception as ex:
            out.warnings.append("A dressed solid could not be read: {}".format(ex))
    want = plan(doc, stories)
    existing = {}
    for f in dress_floors(doc):
        existing.setdefault(meta.get(f, FLOOR_OF), f)
    tol = doc.ModelAbsoluteTolerance * 10
    # 1. lower walls stop under the floor framing above them
    cuts = {}
    for key, (lo, up) in want.items():
        if lo is not None:
            cuts[lo.id] = max(cuts.get(lo.id, 0.0), round(floor_depth(lib, up.floor), 4))
    resync = []
    for st in stories:
        c = cuts.get(st.id, 0.0)
        if abs(wallmasses.top_cut(st.obj) - c) > 1e-6:
            prm = meta.params(st.obj)
            if c:
                prm["top_cut"] = c
            else:
                prm.pop("top_cut", None)
            st.obj = wallmasses.write_params(doc, st.obj, prm)
            resync.append(st.obj)
            out.cut += 1
    if resync:
        sr = wallmasses.sync_many(doc, resync, lib)
        out.results.extend(sr.results)
        out.warnings.extend(sr.warnings)
    # 2. floors
    with engine._quiet():
        for key, (lo, up) in sorted(want.items()):
            try:
                crv = boundary(doc, lib, lo or up, up.z0)
            except Exception as ex:
                out.warnings.append("No floor over a dressed solid: {}".format(ex))
                continue
            lod = (meta.params(up.obj).get("wall") or {}).get("lod")
            prm = {"reference": "top", "base_offset": 0}
            if lod:
                prm["lod"] = lod
            f = existing.pop(key, None)
            if f is None:
                obj = doc.Objects.FindId(doc.Objects.AddCurve(crv))
                _tag(doc, obj, key)
                out.results.append(engine.create(doc, doc.Objects.FindId(obj.Id), up.floor, prm, lib))
                out.created += 1
                continue
            same = wallmasses._same_curve(f.Geometry, crv, tol)
            fp = meta.params(f)
            if same and meta.get(f, meta.ASSEMBLY) == up.floor and all(fp.get(k) == v for k, v in prm.items()):
                continue
            if not same:
                doc.Objects.Replace(f.Id, crv)
            f = doc.Objects.FindId(f.Id)
            fp.update(prm)
            meta.write_driver(doc, f, "floor", up.floor, fp)
            out.results.append(engine.build(doc, f.Id, lib))
            out.moved += 1
        for key, f in existing.items():
            engine.delete_parts(doc, f.Id)
            doc.Objects.Delete(f, True)
            out.removed += 1
    return out


def sync_if_dressed(doc, lib=None):
    """sync() when the model has dressed solids or their floors (live mode, after mass edits)."""
    if not dressed(doc) and not dress_floors(doc):
        return None
    return sync(doc, lib)


def make(doc, solids, wall_assembly, floor_assembly=None, ground=False, lib=None):
    """Dress closed solids (each one story) and sync. Returns (mass objects, SyncResult, notes)."""
    from . import masses
    lib = lib or library.get()
    notes = []
    tol = doc.ModelAbsoluteTolerance
    new, old = [], []
    for s in solids:
        if is_dressed(s) or wallmasses.is_wall_mass(s):
            old.append(s)
        else:
            new.append(s)
        b = masses.to_brep(s.Geometry)
        if b is not None and sloped_top(b, tol):
            notes.append("A solid has a sloped top: its walls go to its highest point and it gets no roof "
                         "(roofs from masses are not built yet; put an MCRoof on top).")
    objs = []
    if new:
        made, sr = wallmasses.make_many(doc, new, wall_assembly, {"mode": "perimeter"}, lib)
        objs.extend(made)
        notes.extend(sr.warnings)
    for m in old:
        objs.append(doc.Objects.FindId(m.Id))
    settings = {"floor": floor_assembly or "none", "ground": bool(ground)}
    for i, m in enumerate(objs):
        prm = meta.params(m)
        prm[DRESS] = dict(settings)
        prm["mode"] = "perimeter"
        objs[i] = wallmasses.write_params(doc, m, prm)
    if old:
        for m in old:
            w = wallmasses.wall_of(doc, doc.Objects.FindId(m.Id))
            if w is not None and meta.get(w, meta.ASSEMBLY) != wall_assembly:
                engine.set_assembly(doc, w, wall_assembly, lib)
        wallmasses.sync_many(doc, [doc.Objects.FindId(m.Id) for m in old], lib)
    sr = sync(doc, lib)
    return [doc.Objects.FindId(o.Id) for o in objs], sr, notes
