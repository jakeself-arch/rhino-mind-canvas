"""Curtain wall <-> visual grid editor model (curtainwall/gridedit.py).

load(doc, lib, driver) reads the BUILT grid of a curtain wall (whatever its grid mode) into a
GridModel in inches: grid lines from the grid's vertices (wall ends, corners and kinks locked),
transoms per bay, every cell's infill, and its doors (hosted openings of category door; windows
in bays are left alone). apply(...) writes the model back: params grid = custom (verticals,
transoms with "at" stations for partial ones, infill), the doors as opening drivers (created,
updated or deleted), then ONE rebuild of the curtain wall.
"""

from .. import engine, library, live, meta, units
from ..kinds import curtainwall as cwkind
from ..openings import core
from . import gridedit as ge


class Session(object):
    """One curtain wall being edited: its context (for stations and the preview) + the model."""

    def __init__(self, doc, driver, lib=None):
        self.doc = doc
        self.lib = lib or library.get()
        self.id = driver.Id
        self.reload()

    @property
    def driver(self):
        return self.doc.Objects.FindId(self.id)

    def reload(self):
        drv = self.driver
        if drv is None or drv.IsDeleted:
            raise ValueError("The curtain wall is gone.")
        self.ctx = cwkind.make_context(self.doc, self.lib, drv, meta.get(drv, meta.ASSEMBLY), meta.params(drv))
        self.model = read(self.ctx)
        return self.model

    # -- u (inches along the grid curve) <-> world ---------------------------------------------------
    def station_of_u(self, u):
        g, s = self.ctx.grid, self.ctx.s
        return g.station_of(g.point_at_u(u * s))

    def point(self, u, z, y=None):
        """World point at (u, z) inches on the glass face (y = signed offset, model units)."""
        g, s = self.ctx.grid, self.ctx.s
        G = cwkind.geo.G
        bi = min(range(len(g.bays)), key=lambda i: _dist_u(g, i, u * s))
        b = g.bays[bi]
        P = g.point_at_u(u * s)
        uu, _ = b.local(P)
        return b.world(uu, self.ctx.yG if y is None else y, g.base_z + z * s)

    def door_types(self):
        return door_types(self.lib)

    def door_info(self, name):
        return door_info(self.lib, name, self.model.wh)

    # -- write back -------------------------------------------------------------------------------
    def apply(self, model=None):
        model = model or self.model
        r = apply(self.doc, self.lib, self.driver, model, self.station_of_u)
        self.reload()
        return r


def _dist_u(g, i, u):
    a, b = g.vertices[i].u, (g.vertices[i + 1].u if i + 1 < len(g.vertices) else g.length)
    return 0.0 if a - 1e-9 <= u <= b + 1e-9 else min(abs(u - a), abs(u - b))


def read(ctx):
    g, S, s = ctx.grid, ctx.dims, ctx.s
    m = ge.GridModel(g.length / s, ctx.height / s, S.mp["w"], S.tp["w"], g.closed, g.row_types)
    verts = []
    for v in g.vertices:
        locked = v.kind in ("start", "end", "corner") or v.kink or (g.closed and v.index == 0)
        verts.append(ge.Vert(v.u / s, locked, v.kind if v.kind != "inline" or not v.kink else "kink"))
    if g.closed:
        verts.append(ge.Vert(g.length / s, True, "seam"))
    m.verts = verts
    lines = {}
    for b, hs in g.bay_hs.items():
        for h in hs[1:-1]:
            key = (h.kind, round((h.z - g.base_z) / s, 4))
            lines.setdefault(key, set()).add(b)
    m.hlines = [ge.HLine(z, bays, kind) for (kind, z), bays in sorted(lines.items(), key=lambda kv: kv[0][1])]
    m.has_stack = S.style == "unitized"
    m.materialize(lambda b, r: g.infill(b, r))
    for op in ctx.openings or []:
        if not op.door:
            continue
        hit = g.cell_at(op.plane.Origin)
        if hit is None or hit[0] in m.doors:
            continue
        head = (op.rz1 - g.base_z) / s + 0.5 * S.tp["w"]
        m.doors[hit[0]] = ge.Door(op.name, head, op.swing, op.hinge, int(op.t["leaf"].get("leaves", 1) or 1),
                                  op.shim / s, str(op.id))
    return m


def door_types(lib):
    """Door type names, curtain-wall doors (aluminum entrance doors) first."""
    names = core.type_names(lib, "door")
    cw = [n for n in names if "Aluminum" in n]
    return cw + [n for n in names if n not in cw]


def door_info(lib, name, transom_w):
    """leaves, shim and the default head line (inches above the base) of a door type."""
    t = core.merged_type(lib, name)
    shim = units.parse_length(t.get("shim", "1/2"))
    return {"leaves": int((t.get("leaf") or {}).get("leaves", 1) or 1), "shim": shim,
            "head": units.parse_length(t.get("height", 84)) + shim + 0.5 * transom_w}


def apply(doc, lib, drv, model, station_of_u):
    """Write a GridModel to a curtain wall and its doors, then rebuild it once."""
    upd = model.export(station_of_u)
    keep = set()
    with live.quiet():
        for bay, d in sorted(model.doors.items()):
            prm = model.door_params(bay, station_of_u)
            obj = doc.Objects.FindId(_guid(d.id)) if d.id else None
            if obj is not None and not obj.IsDeleted and core.host_of(doc, obj) is not None:
                if meta.get(obj, meta.ASSEMBLY) != d.type:
                    core.set_type(doc, obj, d.type)
                    obj = doc.Objects.FindId(obj.Id)
                core.update(doc, obj, prm)
            else:
                obj = core.create(doc, drv, d.type, prm, lib=lib)
                d.id = str(obj.Id)
            keep.add(str(obj.Id))
        for o in core.hosted(doc, drv.Id):
            cat = core.merged_type(lib, meta.get(o, meta.ASSEMBLY)).get("category")
            if cat == "door" and str(o.Id) not in keep:
                doc.Objects.Delete(o, True)
    return engine.update_params(doc, doc.Objects.FindId(drv.Id), upd, lib)


def _guid(text):
    import System
    try:
        return System.Guid(str(text))
    except Exception:
        return System.Guid.Empty
