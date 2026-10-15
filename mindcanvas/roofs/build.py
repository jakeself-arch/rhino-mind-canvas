"""Roof builder. Everything is built per face in the face's local frame (x = uphill, y = ridge
direction, z = world z) as section polygons in (x, z) extruded along y, then placed with the face
frame. Repeated members (rafters, ceiling joists, blocking, shingle courses) are block instances
whose names carry a hash of their section. Footprints that are not rectangles in the face frame
(L-shapes, irregular boundaries) get their layers intersected with the footprint prism.

Roles: rafter (flat: roof_joist), barge_rafter, ridge, lookout, bird_block, ceiling_joist,
insulation, fascia, subfascia, soffit, soffit_vent, soffit_nailer, drip_edge, gutter,
rake_board, shingle_course, ridge_cap, solid / membrane / framing (schematic) / eave_membrane.
"""

import math

import Rhino

from .. import geo, hgeo, profiles, units
from ..components.base import Part
from ..floors import joists as jmod
from . import shape as rshape

G = Rhino.Geometry


def rafter_member(lib, ctx, band):
    """(system name, system, profile name, profile, warning) of the rafter layer."""
    o = ctx.options(band)
    sname, sysd = jmod.system(lib, o.get("system"))
    gauge = o.get("gauge")
    name, prof, msg = jmod.select_member(lib, sysd, o.get("rafter") or o.get("joist"), band.thickness / ctx.s,
                                         gauge=int(gauge) if gauge else None)
    return sname, sysd, name, prof, msg


def layer_thickness(lib, spec, opts):
    """Inches a rafter / ceiling joist layer should be (member depth), or None to keep it."""
    if opts.get("fit", "joist") != "joist":
        return None
    _, sysd = jmod.system(lib, opts.get("system"))
    T = units.parse_length(spec.get("thickness", 0))
    gauge = opts.get("gauge")
    _, p, _ = jmod.select_member(lib, sysd, opts.get("rafter") or opts.get("joist"), T,
                                 gauge=int(gauge) if gauge else None)
    d = units.parse_length(p.get("depth", 0))
    return d if abs(d - T) > 1e-6 else None


def _sign(v):
    return 1.0 if v > 0 else -1.0


class Builder(object):
    def __init__(self, ctx):
        self.ctx = ctx
        self.lib = ctx.lib
        self.st = ctx.st
        self.T = ctx.st["trim"]
        self.s = ctx.s
        self.u = ctx.u
        self.tol = ctx.tol
        self.parts = []
        rb = ctx.structure
        self.rb = rb
        self.layer = rb.name
        self.sys_name, self.sys, self.prof_name, self.prof, msg = rafter_member(self.lib, ctx, rb)
        if msg:
            ctx.warn(msg)
        self.metal = self.sys.get("type") == "metal"
        o = ctx.options(rb)
        self.material = o.get("rafter_material") or self.prof.get("material") or self.sys.get("material") \
            or rb.material
        w_in, d_in = profiles.size(self.prof)
        self.b, self.D = w_in * ctx.s, d_in * ctx.s
        self.spacing = ctx.u(o.get("spacing", self.sys.get("rafter_spacing", 24)))
        if self.spacing < 2 * self.b:
            self.spacing = 4 * self.b
            ctx.warn("Rafter spacing too small; using {}.".format(units.format_inches(self.spacing / ctx.s)))
        st = self.st
        self.wd, self.we, self.wi = ctx.u(st["wall_depth"]), ctx.u(st["wall_ext"]), ctx.u(st["wall_int"])
        T = self.T
        self.ft = ctx.u(T["fascia_t"]) if T.get("fascia") else 0.0
        self.sft = ctx.u(T["subfascia_t"]) if T.get("subfascia") else 0.0
        self.flat = st["shape"] == "flat"
        self.gable = st["shape"] == "gable"
        self.faces = ctx.faces
        self.p = self.faces[0].p
        self.rt = 0.0
        if self.gable:
            plumb = self.D * math.sqrt(1 + self.p * self.p) / ctx.s
            self.ridge_name, self.ridge_prof = jmod.deeper(self.lib, self.sys.get("ridge_family", self.sys.get("family")),
                                                           plumb + (0.0 if self.metal else 0.5))
            if self.ridge_prof is None:
                self.ridge_name, self.ridge_prof = self.prof_name, self.prof
            rw, rd = profiles.size(self.ridge_prof)
            self.rt, self.rD = rw * ctx.s, rd * ctx.s
        self.loops = profiles.build(self.prof, ctx.s)
        self._positions()

    # -- helpers ----------------------------------------------------------------------------------
    def name(self, role, profile=None):
        return jmod.label(self.sys, role, profile or self.prof_name)

    def block(self, kind, poly, y0, y1, material):
        """Block index of a section polygon extruded y0..y1 (local; name = hash of the section)."""
        key = (kind, tuple((round(x / self.s, 4), round(z / self.s, 4)) for x, z in poly), round((y1 - y0) / self.s, 4))
        bname = "MC Roof {} {} #{}".format(kind, units.format_inches((y1 - y0) / self.s).replace('"', "in"),
                                         hgeo.tag(key, material))
        cache = self.ctx.__dict__.setdefault("_mc_roof_blocks", {})
        if bname not in cache:
            g = hgeo.prism_xz(poly, y0, y1, self.tol)
            if g is None:
                return None
            cache[bname] = self.ctx.block(bname, [g], material)
        return cache[bname]

    def add_block(self, face, kind, poly, y0, y1, material, role, extra, dy=0.0, dx=0.0, dz=0.0):
        idx = self.block(kind, poly, 0.0, y1 - y0, material)
        if idx is None:
            return
        xf = face.frame.placed(dy + y0, dx) * G.Transform.Translation(0, 0, dz)
        self.parts.append(Part(material=material, role=role, block=idx, xform=xf, extra=extra, layer_name=self.layer))

    def add(self, face, breps, material, role, extra=None):
        for b in breps or []:
            if b is None:
                continue
            g = b.DuplicateBrep()
            g.Transform(face.frame.xform)
            self.parts.append(Part(g, material, role=role, extra=dict(extra or {}), layer_name=self.layer))

    def region_slab(self, region, below=(), above=(), x_lo=None, x_hi=None):
        """Solid over a local plan polygon (irregular footprints): its vertical prism kept under
        every line in `below` and over every line in `above` (lines z = a + b x), optionally
        clipped to x_lo <= x <= x_hi in plan. Built from planar faces (hgeo.slab_between): Booleans
        with the footprint's coplanar end faces and Brep.Trim by a plane are not reliable."""
        poly = list(region)
        if x_lo is not None:
            poly = hgeo.clip_halfplane(poly, lambda q: q[0] - x_lo)
        if x_hi is not None and poly:
            poly = hgeo.clip_halfplane(poly, lambda q: x_hi - q[0])
        if len(poly) < 3 or abs(hgeo.area(poly)) < self.u(0.5) ** 2:
            return []
        return hgeo.slab_between(poly, below, above, self.tol)

    def section_or_region(self, face, sec, y0, y1, region, rect, below=(), above=(), x_lo=None, x_hi=None):
        if rect:
            b = hgeo.prism_xz(sec, y0, y1, self.tol)
            return [b] if b is not None else []
        return self.region_slab(region, below, above, x_lo, x_hi)

    def interior(self, face):
        """Interior plan polygon (inside the wall finishes) of a face, local, clipped at the ridge."""
        d = self.wd + self.wi
        ip = hgeo.offset_edges(face.plate, [-d] * len(face.plate))
        if face.v_ridge is not None:
            vr = face.v_ridge
            ip = hgeo.clip_halfplane(ip, lambda q: vr - q[0])
        return ip

    def ys(self, face):
        return self.rafter_ys if face.index == 0 else [-y for y in self.rafter_ys]

    def barge_ys(self, face):
        return self.barges if face.index == 0 else [-y for y in self.barges]

    # -- rafter layout ----------------------------------------------------------------------------
    def _positions(self):
        f = self.faces[0]
        plate = f.plate
        b, sp = self.b, self.spacing
        x0, ymin, x1, ymax = f.plate_bbox
        fixed = []
        n = len(plate)
        eps = self.u(0.5)
        for i in range(n):
            a, c = plate[i], plate[(i + 1) % n]
            if rshape.edge_kind(a, c, self.tol) != "rake":
                continue
            ye = 0.5 * (a[1] + c[1])
            xm = 0.5 * (a[0] + c[0])
            side = 1.0 if hgeo.inside(plate, (xm, ye + eps)) else -1.0
            fixed.append(ye + side * 0.5 * b)
        ys = list(fixed)
        k = 1
        while ymin + k * sp < ymax - 0.5 * b:
            y = ymin + k * sp
            k += 1
            if all(abs(y - q) >= b for q in fixed):
                ys.append(y)
        ys.sort()
        out = []
        for y in ys:
            if not out or y - out[-1] > self.tol * 10:
                out.append(y)
        self.rafter_ys = out
        self.barges = []
        if self.T.get("barge"):
            for e in f.edges():
                if e.kind != "rake":
                    continue
                oy = _sign(e.out[1])
                yb = e.y - oy * (self.ft + 0.5 * b)
                inner = [y for y in out if (y - yb) * oy < 0]
                nearest = min((abs(y - yb) for y in inner), default=1e9)
                if nearest > 1.5 * b + self.u(1):
                    self.barges.append(yb)

    # -- rafters ------------------------------------------------------------------------------------
    def rafter_poly(self, face, xa, xb, bearings):
        zb, zt = face.zb, face.zt
        pts = [(xa, zb(xa))]
        if face.p > 1e-9 and not self.metal:
            for kind, bx in sorted(bearings, key=lambda q: q[1]):
                if kind == "low":
                    o, i = bx, bx + self.wd
                    if o <= xa + self.tol or i >= xb - self.tol:
                        continue
                    zs = zb(i)
                    pts += [(o, zb(o)), (o, zs), (i, zs)]
                else:
                    o, i = bx, bx - self.wd
                    if i <= xa + self.tol or o >= xb - self.tol:
                        continue
                    zs = zb(o)
                    pts += [(i, zb(i)), (i, zs), (o, zs)]
        pts += [(xb, zb(xb)), (xb, zt(xb)), (xa, zt(xa))]
        return pts

    def metal_member(self, face, xa, xb):
        """C member along the slope between plumb cuts at xa and xb (local geometry at y = 0)."""
        p = face.p
        c, sn = 1.0 / math.sqrt(1 + p * p), p / math.sqrt(1 + p * p)
        zc = face.zb.up(0.5 * self.D)
        m = self.u(2)
        x0 = xa - m
        plane = G.Plane(G.Point3d(x0, 0, zc(x0)), G.Vector3d(0, 1, 0), G.Vector3d(-sn, 0, c))
        L = (xb - x0 + m) / c
        brep = geo.extrude_profile(self.loops[0], plane, L)
        res = []
        for piece in hgeo.keep_below(brep, G.Point3d(xa, 0, 0), G.Vector3d(-1, 0, 0), self.tol):
            res += hgeo.keep_below(piece, G.Point3d(xb, 0, 0), G.Vector3d(1, 0, 0), self.tol)
        return res

    def add_member(self, face, kind, role, member, xa, xb, y, bearings, length_in):
        extra = {"length": round(length_in, 4), "member": member}
        if self.metal:
            key = (kind, round((xb - xa) / self.s, 4), round(xa / self.s, 4), round(face.zb.a / self.s, 4),
                   round(face.p, 6), self.prof_name)
            bname = "MC Roof {} {} #{}".format(kind, self.prof_name.replace('"', "in"), hgeo.tag(key))
            cache = self.ctx.__dict__.setdefault("_mc_roof_blocks", {})
            if bname not in cache:
                geoms = self.metal_member(face, xa, xb)
                if not geoms:
                    return
                cache[bname] = self.ctx.block(bname, geoms, self.material)
            xf = face.frame.placed(y)
            self.parts.append(Part(material=self.material, role=role, block=cache[bname], xform=xf, extra=extra,
                                   layer_name=self.layer))
            return
        poly = self.rafter_poly(face, xa, xb, bearings)
        self.add_block(face, kind, poly, -0.5 * self.b, 0.5 * self.b, self.material, role, extra, dy=y)

    def rafters(self, face):
        ft, sft = self.ft, self.sft
        role = "roof_joist" if self.flat else "rafter"
        label = self.name("joist" if self.flat else "rafter")
        cos = face.cos
        for y in self.ys(face):
            for x0, x1 in hgeo.chords(face.poly, y):
                xa = x0 + ft + sft
                ridge = face.is_ridge_end(x1)
                xb = x1 - (0.5 * self.rt if ridge else ft + sft)
                if xb - xa < self.u(12):
                    continue
                bearings = []
                for b0, b1 in hgeo.chords(face.plate, y):
                    if x0 - self.tol <= b0 < xb:
                        bearings.append(("low", b0))
                    if xa < b1 < xb - self.tol:
                        bearings.append(("high", b1))
                self.add_member(face, "Rafter", role, label, xa, xb, y, bearings, (xb - xa) / cos / self.s)
                self.n_rafters += 1
        for y in self.barge_ys(face):
            for x0, x1 in hgeo.chords(face.poly, y):
                xa = x0 + ft + sft
                ridge = face.is_ridge_end(x1)
                xb = x1 - (0.5 * self.rt if ridge else ft + sft)
                if xb - xa < self.u(12):
                    continue
                self.add_member(face, "Barge", "barge_rafter", self.name("barge"), xa, xb, y, [], (xb - xa) / cos / self.s)

    def ridge(self):
        if not self.gable:
            return
        f = self.faces[0]
        vr = f.v_ridge
        top = f.zt(vr - 0.5 * self.rt)
        if self.metal:
            loop = profiles.build(self.ridge_prof, self.s)[0]
            pts = [loop.Point(i) for i in range(loop.PointCount)]
            poly = [(vr + p.X, top - 0.5 * self.rD + p.Y) for p in pts[:-1]]
        else:
            poly = [(vr - 0.5 * self.rt, top - self.rD), (vr + 0.5 * self.rt, top - self.rD),
                    (vr + 0.5 * self.rt, top), (vr - 0.5 * self.rt, top)]
        inset = self.ft if self.T.get("rake_board") else 0.0
        for y0, y1 in hgeo.chords(f.poly, vr - self.u(0.25), axis=0):
            y0, y1 = y0 + inset, y1 - inset
            self.add(f, [hgeo.prism_xz(poly, y0, y1, self.tol)], self.material, "ridge",
                     {"length": round((y1 - y0) / self.s, 4), "member": self.name("ridge", self.ridge_name)})

    def lookouts(self, face, e):
        """Flat 2x blocks between the barge rafter and the end rafter, tops flush with the rafters."""
        if self.metal or not self.T.get("lookout"):
            return
        prof = self.lib.profile(self.T["lookout"])
        lw_in, ld_in = profiles.size(prof)
        lw, lt = self.u(ld_in), self.u(lw_in)       # flat: wide face along the slope
        oy = _sign(e.out[1])
        yb = e.y - oy * (self.ft + 0.5 * self.b)
        if not any(abs(yb - q) < self.tol * 10 for q in self.barge_ys(face)):
            return
        inner = [y for y in self.ys(face) if (y - yb) * oy < 0]
        if not inner:
            return
        ye = min(inner, key=lambda y: abs(y - yb))
        ya, yz = sorted((yb - oy * 0.5 * self.b, ye + oy * 0.5 * self.b))
        if yz - ya < self.u(2):
            return
        p = face.p
        c, sn = face.cos, p * face.cos
        xs = [b0 for b0, b1 in hgeo.chords(face.plate, ye)]
        if not xs:
            return
        x0 = min(xs) + self.wd + self.u(6)
        xr0, xr1 = e.xrange
        x_end = xr1 - (0.5 * self.rt if face.is_ridge_end(xr1) else self.ft + self.sft) - self.u(6)
        step = self.u(self.T.get("lookout_spacing", 24)) * c
        zt = face.zt
        x = x0
        member = self.name("lookout", self.T["lookout"])
        while x < x_end:
            h = 0.5 * lw * c
            a, b = (x - h, zt(x - h)), (x + h, zt(x + h))
            poly = [a, b, (b[0] + lt * sn, b[1] - lt * c), (a[0] + lt * sn, a[1] - lt * c)]
            rel = [(px - x, pz - zt(x)) for px, pz in poly]
            self.add_block(face, "Lookout", rel, ya, yz, self.material, "lookout",
                           {"length": round((yz - ya) / self.s, 4), "member": member}, dx=x, dz=zt(x))
            x += step

    def bird_blocks(self, face):
        if self.metal or not self.T.get("bird_block") or self.ctx.lod != "detail":
            return
        vent = self.u(self.T.get("vent_gap", 1.5))
        bw = self.u(1.5)
        ys = sorted(self.ys(face))
        zb, zt = face.zb, face.zt
        member = self.name("bird_block")
        for ya, yb in zip(ys, ys[1:]):
            if yb - ya > 1.5 * self.spacing:
                continue
            ym = 0.5 * (ya + yb)
            for b0, b1 in hgeo.chords(face.plate, ym):
                cands = [("low", b0)]
                if not face.is_ridge_end(b1) and (face.v_ridge is None or b1 < face.v_ridge):
                    cands.append(("high", b1))
                for kind, bx in cands:
                    if kind == "low":
                        xa, xz, zs = bx, bx + bw, zb(bx + self.wd)
                    else:
                        xa, xz, zs = bx - bw, bx, zb(bx)
                    poly = [(xa, zs), (xz, zs), (xz, zt(xz) - vent), (xa, zt(xa) - vent)]
                    if zt(xa) - vent - zs < self.u(1):
                        continue
                    y0, y1 = ya + 0.5 * self.b, yb - 0.5 * self.b
                    rel = [(x - xa, z - zs) for x, z in poly]
                    self.add_block(face, "Bird Block", rel, y0, y1, self.material, "bird_block",
                                   {"length": round((y1 - y0) / self.s, 4), "member": member}, dx=xa, dz=zs)

    def rafter_fill(self, face):
        o = self.ctx.options(self.rb)
        fill = o.get("cavity_fill")
        if not fill or self.ctx.lod != "detail":
            return
        depth = min(self.u(o.get("fill_depth") or 1e6), self.D)
        ip = self.interior(face)
        ys = sorted(self.ys(face))
        zb = face.zb
        zf = zb.up(depth)
        for ya, yb in zip(ys, ys[1:]):
            if yb - ya > 1.5 * self.spacing:
                continue
            for x0, x1 in hgeo.chords(ip, 0.5 * (ya + yb)):
                if face.v_ridge is not None:
                    x1 = min(x1, face.v_ridge - 0.5 * self.rt)
                if x1 - x0 < self.u(4):
                    continue
                poly = [(x0, zb(x0)), (x1, zb(x1)), (x1, zf(x1)), (x0, zf(x0))]
                y0, y1 = ya + 0.5 * self.b, yb - 0.5 * self.b
                rel = [(x - x0, z - zb(x0)) for x, z in poly]
                area = (x1 - x0) / face.cos * (y1 - y0) / (self.s * self.s)
                self.add_block(face, "Fill", rel, y0, y1, fill, "insulation", {"area": round(area, 2)},
                               dx=x0, dz=zb(x0))

    # -- roof-plane layers --------------------------------------------------------------------------
    def plane_layers(self, face):
        ctx = self.ctx
        try:
            self._plane_layers(face)
        finally:
            self.layer = self.rb.name

    def _plane_layers(self, face):
        ctx = self.ctx
        for band in ctx.bands:
            if band is self.rb:
                self.layer = band.name
                if ctx.lod == "schematic":
                    self._slab(face, band, "overhang", self.material, "framing")
                continue
            self.layer = band.name
            if band.component == "void" or band.thickness <= self.tol:
                continue
            region = ctx.option(band, "region", "overhang" if band.index < self.rb.index else "interior")
            if band.component == "shingles" and ctx.lod == "detail" and face.p > 0.02:
                self._shingles(face, band)
                continue
            em = ctx.option(band, "eave_membrane")
            if em and ctx.lod == "detail" and region == "overhang":
                x_split = face.plate_bbox[0] + self.wd + self.u(em.get("width", 24))
                self._slab(face, band, region, em.get("material", "Ice and Water Shield"), "eave_membrane",
                           x_hi=x_split)
                self._slab(face, band, region, band.material, band.component, x_lo=x_split)
                continue
            role = "roofing" if band.component == "shingles" else ("membrane" if band.component == "membrane" else "solid")
            self._slab(face, band, region, band.material, role)

    def _region(self, face, region):
        if region == "interior":
            poly = self.interior(face)
        else:
            poly = face.poly
        return poly, hgeo.is_rect(poly, self.tol)

    def _slab(self, face, band, region, material, role, x_lo=None, x_hi=None):
        bot, top = face.lines[band.index]
        poly, rect = self._region(face, region)
        if len(poly) < 3:
            return
        x0, y0, x1, y1 = hgeo.bbox(poly)
        nw = self.nailer_width(face)
        if nw > 0 and region == "overhang" and 0 < band.index < self.rb.index - 1:
            # low-slope edge: the insulation stops at the perimeter nailers
            x0, x1, y0, y1 = x0 + nw, x1 - nw, y0 + nw, y1 - nw
        if x_lo is not None:
            x0 = max(x0, x_lo)
        if x_hi is not None:
            x1 = min(x1, x_hi)
        if x1 - x0 < self.u(0.5):
            return
        sec = [(x0, bot(x0)), (x1, bot(x1)), (x1, top(x1)), (x0, top(x0))]
        breps = self.section_or_region(face, sec, y0, y1, poly, rect, below=[top], above=[bot], x_lo=x_lo, x_hi=x_hi)
        area = (x1 - x0) / face.cos * (y1 - y0) / (self.s * self.s)
        self.add(face, breps, material, role, {"area": round(area, 2)} if rect else None)

    def nailer_width(self, face):
        """Width of the stacked wood nailers at the edge of a low-slope (flat) roof, or 0."""
        nailer = self.T.get("edge_nailer")
        if not (self.flat and nailer and face.rect and self.rb.index >= 3 and self.ctx.lod != "schematic"):
            return 0.0
        return self.u(profiles.size(self.lib.profile(nailer))[1])

    def edge_nailers(self, face):
        """Stacked flat 2x nailers around a low-slope roof, from the deck up to the membrane."""
        nw = self.nailer_width(face)
        if nw <= 0:
            return
        c = self.rb.index
        zd = face.lines[c - 1][1](face.bbox[0])           # deck top (level)
        top = face.lines[0][0]                            # membrane bottom (follows the taper)
        ply = self.u(profiles.size(self.lib.profile(self.T["edge_nailer"]))[0])
        x0, y0, x1, y1 = face.bbox
        strips = [[(x0, y0), (x0 + nw, y0), (x0 + nw, y1), (x0, y1)], [(x1 - nw, y0), (x1, y0), (x1, y1), (x1 - nw, y1)],
                  [(x0 + nw, y0), (x1 - nw, y0), (x1 - nw, y0 + nw), (x0 + nw, y0 + nw)],
                  [(x0 + nw, y1 - nw), (x1 - nw, y1 - nw), (x1 - nw, y1), (x0 + nw, y1)]]
        member = "{} Edge Nailer".format(self.T["edge_nailer"])
        zmax = max(top(x0), top(x1))
        for strip in strips:
            L = max(strip[1][0] - strip[0][0], strip[2][1] - strip[1][1])
            k = 0
            while zd + k * ply < zmax - self.u(0.25):
                lo, hi = hgeo.Line(zd + k * ply, 0.0), hgeo.Line(zd + (k + 1) * ply, 0.0)
                pieces = self.region_slab(strip, below=[hi, top], above=[lo])
                self.add(face, pieces, "Wood Framing", "edge_nailer", {"length": round(L / self.s, 4), "member": member})
                k += 1

    def _shingles(self, face, band):
        o = self.ctx.options(band)
        bot, top = face.lines[band.index]
        T = band.thickness
        tip = min(self.u(o.get("tip", 0.125)), 0.5 * T)
        e = self.u(o.get("exposure", 5))
        c = face.cos
        sec = 1.0 / c
        eh = e * c
        over = self.u(0.375)
        poly = face.poly
        rect = face.rect
        x0, y0, x1, y1 = face.bbox
        xs = x0 - over
        xe = face.v_ridge if face.v_ridge is not None else x1 + over
        ya, yz = y0 - over, y1 + over
        member = "{} Course, {} exposure".format(band.material, units.format_inches(e / self.s))
        x = xs
        loose = []
        while x < xe - self.u(0.25):
            xz = min(x + eh, xe)
            sh = [(x, bot(x)), (xz, bot(xz)), (xz, bot(xz) + tip * sec), (x, bot(x) + T * sec)]
            extra = {"length": round((yz - ya) / self.s, 4), "member": member}
            if rect:
                rel = [(px - x, pz - bot(x)) for px, pz in sh]
                self.add_block(face, "Shingle Course", rel, ya, yz, band.material, "shingle_course", extra,
                               dx=x, dz=bot(x))
            else:
                bt = hgeo.Line(0.0, ((bot(xz) + tip * sec) - (bot(x) + T * sec)) / (xz - x))
                bt.a = bot(x) + T * sec - bt.b * x
                loose += self.region_slab(poly, below=[bt], above=[bot], x_lo=x, x_hi=xz)
            x = xz
        if loose:
            self.add(face, loose, band.material, "shingle_course", {"member": member})

    def ridge_cap(self):
        if not (self.gable and self.T.get("ridge_cap") and self.ctx.lod == "detail"):
            return
        f = self.faces[0]
        band = self.ctx.bands[0]
        top = f.lines[band.index][1]
        vr = f.v_ridge
        w = self.u(self.T.get("ridge_cap_width", 6))
        tc = self.u(self.T.get("ridge_cap_t", 0.25))
        za, zr = top(vr - w), top(vr)
        poly = [(vr - w, za), (vr, zr), (vr + w, za), (vr + w, za + tc), (vr, zr + tc), (vr - w, za + tc)]
        for y0, y1 in hgeo.chords(f.poly, vr - self.u(0.25), axis=0):
            self.add(f, [hgeo.prism_xz(poly, y0 - self.u(0.375), y1 + self.u(0.375), self.tol)], band.material,
                     "ridge_cap", {"length": round((y1 - y0) / self.s, 4)})

    # -- eave + rake trim -------------------------------------------------------------------------------
    def lines_of(self, face):
        c = self.rb.index
        zs = face.lines[c - 1][1] if c > 0 else face.zt
        return face.zb, face.zt, zs

    def eave(self, face, e):
        ctx, T, u = self.ctx, self.T, self.u
        so = _sign(e.out[0])                          # -1: the roof rises inward (a low eave)
        xe = e.x
        X = lambda a: xe - so * a
        zb, zt, zs = self.lines_of(face)
        za = lambda line: (lambda a: line(X(a)))
        zb_a, zt_a, zs_a = za(zb), za(zt), za(zs)
        ya, yb = e.yrange
        ym = 0.5 * (ya + yb)
        walls = [q for ch in hgeo.chords(face.plate, ym) for q in ch]
        if face.v_ridge is not None:
            walls = [q for q in walls if q < face.v_ridge]
        bwall = min(walls, key=lambda q: abs(q - xe)) if walls else None
        ft, sft = self.ft, self.sft
        a_tail = ft + sft
        a_wall = abs(bwall - xe) - self.we if bwall is not None else a_tail
        soffit = T.get("soffit") and a_wall > a_tail + u(1)
        z_sb = min(zb_a(a_tail), zb_a(max(a_wall, a_tail)))
        ts = u(T["soffit_t"]) if soffit else 0.0
        z_fb = z_sb - ts - u(T.get("fascia_drop", 0.75))
        rb = ft if T.get("rake_board") else 0.0
        L = lambda y0, y1: {"length": round((y1 - y0) / self.s, 4)}
        out = []          # (poly (a, z), y0, y1, material, role, member)
        if ft > 0:
            out.append(([(0, z_fb), (ft, z_fb), (ft, zt_a(ft)), (0, zt_a(0))], ya, yb, T["fascia_material"],
                        "fascia", "1x Fascia"))
        if sft > 0:
            if self.metal:
                t = u(self.prof.get("t", 0.0566))
                leg = u(1.25)
                a0 = ft
                poly = [(a0, min(z_sb, zb_a(a0)) - t), (a0 + leg, min(z_sb, zb_a(a0)) - t),
                        (a0 + leg, min(z_sb, zb_a(a0))), (a0 + t, min(z_sb, zb_a(a0)))] + \
                       [(a0 + t, zt_a(a0 + t)), (a0 + leg, zt_a(a0 + leg)), (a0 + leg, zt_a(a0 + leg) + t), (a0, zt_a(a0) + t)]
                out.append((poly, ya + rb, yb - rb, self.material, "subfascia", self.name("subfascia")))
            else:
                out.append(([(ft, z_sb), (ft + sft, z_sb), (ft + sft, zt_a(ft + sft)), (ft, zt_a(ft))], ya + rb, yb - rb,
                            self.material, "subfascia", self.name("subfascia", "2x")))
        if soffit:
            z0, z1 = z_sb - ts, z_sb
            vw = u(T.get("soffit_vent", 0) or 0) if ctx.lod == "detail" else 0.0
            if vw > 0 and a_wall - a_tail > vw + u(3):
                am = 0.5 * (a_tail + a_wall)
                segs = [(ft, am - 0.5 * vw, T["soffit_material"], "soffit"),
                        (am - 0.5 * vw, am + 0.5 * vw, T["vent_material"], "soffit_vent"),
                        (am + 0.5 * vw, a_wall, T["soffit_material"], "soffit")]
            else:
                segs = [(ft, a_wall, T["soffit_material"], "soffit")]
            pys = [q for ch in hgeo.chords(face.plate, xe - so * (a_wall + self.we + self.u(1)), axis=0) for q in ch]
            sy0 = max(ya + rb, min(pys) - self.we) if pys else ya + rb
            sy1 = min(yb - rb, max(pys) + self.we) if pys else yb - rb
            for a0, a1, mat, role in segs:
                out.append(([(a0, z0), (a1, z0), (a1, z1), (a0, z1)], sy0, sy1, mat, role, "Soffit"))
            nailer = T.get("soffit_nailer")
            if nailer and ctx.lod == "detail":
                nw, nh = [u(v) for v in profiles.size(self.lib.profile(nailer))]
                a1 = a_wall
                if zb_a(a1 - nw) >= z1 + nh + self.tol and zb_a(a1) >= z1 + nh + self.tol:
                    out.append(([(a1 - nw, z1), (a1, z1), (a1, z1 + nh), (a1 - nw, z1 + nh)], sy0, sy1,
                                "Wood Framing", "soffit_nailer", "{} Soffit Nailer".format(nailer)))
        if ctx.lod == "detail" and T.get("drip_edge"):
            dt = u(T["drip_t"])
            if self.nailer_width(face) > 0:      # low slope: edge metal over the membrane, down the nailers
                zr_a = za(face.lines[0][1])
                path = [(u(3.5), zr_a(u(3.5))), (0.0, zr_a(0.0)), (0.0, zt_a(0.0) - u(1.5)), (-u(0.5), zt_a(0.0) - u(2.0))]
                member = "Edge Metal"
            else:
                path = [(u(2.5), zs_a(u(2.5))), (0.0, zs_a(0.0)), (0.0, zs_a(0.0) - u(1.5)), (-u(0.5), zs_a(0.0) - u(2.0))]
                member = "Drip Edge"
            out.append((hgeo.thicken(path, dt, -1), ya, yb, T["drip_material"], "drip_edge", member))
            if T.get("gutter") and so < 0:
                S = u(T.get("gutter_size", 5))
                zg = zs_a(0.0) - u(1.0)
                g = [(0.0, zg), (0.0, zg - 0.8 * S), (-0.6 * S, zg - 0.8 * S), (-0.75 * S, zg - 0.6 * S),
                     (-0.7 * S, zg - 0.4 * S), (-0.9 * S, zg - 0.25 * S), (-0.95 * S, zg), (-0.85 * S, zg)]
                out.append((hgeo.thicken(g, u(T["gutter_t"]), -1), ya, yb, T["gutter_material"], "gutter",
                            "{} K-Style Gutter".format(units.format_inches(S / self.s))))
        for poly, y0, y1, mat, role, member in out:
            if y1 - y0 < self.u(1):
                continue
            sec = [(X(a), z) for a, z in poly]
            ex = L(y0, y1)
            ex["member"] = member
            self.add(face, [hgeo.prism_xz(sec, y0, y1, self.tol)], mat, role, ex)

    def rake(self, face, e):
        T, u = self.T, self.u
        oy = _sign(e.out[1])
        ye = e.y
        Y = lambda d: ye - oy * d
        zb, zt, zs = self.lines_of(face)
        xr0, xr1 = e.xrange
        ft, sft = self.ft, self.sft
        ridge = face.is_ridge_end(xr1)
        xa = xr0 + ft
        xb = xr1 if ridge else xr1 - ft
        drop = u(T.get("fascia_drop", 0.75))
        out = []
        if T.get("rake_board") and ft > 0:
            poly = [(xa, zb(xa) - drop), (xb, zb(xb) - drop), (xb, zt(xb)), (xa, zt(xa))]
            out.append((poly, Y(ft), Y(0), T["fascia_material"], "rake_board", "1x Rake Board",
                        (xb - xa) / face.cos))
        if self.ctx.lod == "detail" and T.get("drip_edge"):
            dt = u(T["drip_t"])
            x0, x1 = xr0, xr1
            ztop, zlow = (face.lines[0][1], zt.up(-u(1.5))) if self.nailer_width(face) > 0 else (zs, zs.up(-u(1.5)))
            flange = [(x0, ztop(x0)), (x1, ztop(x1)), (x1, ztop(x1) + dt), (x0, ztop(x0) + dt)]
            leg = [(x0, zlow(x0)), (x1, zlow(x1)), (x1, ztop(x1)), (x0, ztop(x0))]
            out.append((flange, Y(u(2.5)), Y(0), T["drip_material"], "drip_edge", "Drip Edge", (x1 - x0) / face.cos))
            out.append((leg, Y(0), Y(-dt), T["drip_material"], "drip_edge", "Drip Edge", (x1 - x0) / face.cos))
        for poly, y0, y1, mat, role, member, L in out:
            y0, y1 = min(y0, y1), max(y0, y1)
            self.add(face, [hgeo.prism_xz(poly, y0, y1, self.tol)], mat, role,
                     {"length": round(L / self.s, 4), "member": member})
        if self.ctx.lod == "detail":
            self.lookouts(face, e)

    def oblique(self, face, e):
        """Fascia band along an edge that is neither an eave nor a rake (irregular boundaries)."""
        if not self.T.get("fascia") or self.ft <= 0:
            return
        ox, oy = e.out
        ft = self.ft
        a, b = e.a, e.b
        strip = [a, b, (b[0] - ox * ft, b[1] - oy * ft), (a[0] - ox * ft, a[1] - oy * ft)]
        zb, zt, zs = self.lines_of(face)
        depth = self.D * math.sqrt(1 + face.p * face.p) + self.u(2)
        res = hgeo.slab_between(hgeo.ccw(strip), [zt], [hgeo.Line(zt.a - depth, zt.b)], self.tol)
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        self.add(face, res, self.T["fascia_material"], "fascia", {"length": round(L / self.s, 4), "member": "1x Fascia"})

    # -- ceiling stack ------------------------------------------------------------------------------------
    def ceiling(self):
        ctx = self.ctx
        bands = ctx.ceiling_bands
        if not bands:
            return
        cj = [b for b in bands if b.component in ("joists", "framing")]
        cj = cj[0] if cj else None
        for band in bands:
            if band is cj or band.component == "void" or band.thickness <= self.tol:
                continue
            if band.d_int >= (cj.d_ext - self.tol if cj else ctx.base_z):
                for f in self.faces:
                    self._ceiling_blanket(f, band)
            else:
                crv = geo.offset(ctx.curve, -(self.wd + self.wi), self.tol)
                for r in G.Brep.CreatePlanarBreps(crv, self.tol) or []:
                    amp = G.AreaMassProperties.Compute(crv)
                    self.parts.append(Part(geo.extrude_region(r, band.d_int, band.thickness, self.tol), band.material,
                                           role="solid", extra={"area": round(amp.Area / (self.s * self.s), 2) if amp else 0},
                                           layer_name=band.name))
        if cj is not None:
            if ctx.lod == "schematic":
                for f in self.faces:
                    self._ceiling_blanket(f, cj, role="framing", baffle=0.0, region="plate")
            else:
                for f in self.faces:
                    self._ceiling_joists(f, cj)

    def _ceiling_blanket(self, face, band, role="solid", baffle=None, region="interior"):
        poly = self.interior(face) if region == "interior" else face.plate
        if face.v_ridge is not None and region != "interior":
            vr = face.v_ridge
            poly = hgeo.clip_halfplane(poly, lambda q: vr - q[0])
        if len(poly) < 3:
            return
        rect = hgeo.is_rect(poly, self.tol)
        x0, y0, x1, y1 = hgeo.bbox(poly)
        gap = self.u(self.T.get("baffle_gap", 1.5)) if baffle is None else baffle
        zb = face.zb
        sec = [(x0, band.d_int), (x1, band.d_int), (x1, band.d_ext), (x0, band.d_ext)]
        sec = hgeo.clip_halfplane(sec, lambda q: zb(q[0]) - gap - q[1])
        if len(sec) < 3:
            return
        under = hgeo.Line(zb.a - gap, zb.b)
        breps = self.section_or_region(face, sec, y0, y1, poly, rect,
                                       below=[hgeo.Line(band.d_ext, 0.0), under], above=[hgeo.Line(band.d_int, 0.0)])
        for b in breps:
            b.Transform(face.frame.xform)
            self.parts.append(Part(b, band.material, role=role, layer_name=band.name))

    def _ceiling_joists(self, face, band):
        ctx = self.ctx
        o = ctx.options(band)
        sname, sysd = jmod.system(self.lib, o.get("system") or self.sys_name.replace("_joists", ""))
        metal = sysd.get("type") == "metal"
        gauge = o.get("gauge")
        name, prof, msg = jmod.select_member(self.lib, sysd, o.get("joist"), band.thickness / self.s,
                                             gauge=int(gauge) if gauge else None)
        if msg:
            ctx.warn(msg)
        material = o.get("joist_material") or prof.get("material") or sysd.get("material")
        w_in, d_in = profiles.size(prof)
        bw, D = w_in * self.s, d_in * self.s
        z0 = band.d_int
        member = jmod.label(sysd, "ceiling_joist", name)
        zt = face.zt
        x0p, ymin, x1p, ymax = face.plate_bbox
        cys = []
        for y in self.ys(face):
            side = 1.0
            off = 0.5 * (self.b + bw)
            if not hgeo.inside(face.plate, (0.5 * (x0p + x1p), y + off + 0.5 * bw)):
                side = -1.0
            cys.append(y + side * off)
        cys.sort()
        loops = profiles.build(prof, self.s)
        for yc in cys:
            for b0, b1 in hgeo.chords(face.plate, yc):
                xs, xe = b0, b1
                if face.v_ridge is not None:
                    if xs >= face.v_ridge:
                        continue
                    xe = min(xe, face.v_ridge)
                if xe - xs < self.u(6):
                    continue
                extra = {"length": round((xe - xs) / self.s, 4), "member": member}
                if metal:
                    plane = G.Plane(G.Point3d(xs, 0, z0 + 0.5 * D), G.Vector3d(0, 1, 0), G.Vector3d(0, 0, 1))
                    brep = geo.extrude_profile(loops[0], plane, xe - xs)
                    geoms = hgeo.keep_below(brep, G.Point3d(0, 0, zt.a), G.Vector3d(-zt.b, 0, 1), self.tol)
                    key = (round(xs / self.s, 4), round(xe / self.s, 4), round(z0 / self.s, 4), round(zt.a / self.s, 4),
                           round(zt.b, 6), name)
                    bname = "MC Roof Ceiling Joist {} #{}".format(name.replace('"', "in"), hgeo.tag(key))
                    cache = ctx.__dict__.setdefault("_mc_roof_blocks", {})
                    if bname not in cache:
                        cache[bname] = ctx.block(bname, geoms, material)
                    self.parts.append(Part(material=material, role="ceiling_joist", block=cache[bname],
                                           xform=face.frame.placed(yc), extra=extra, layer_name=band.name))
                    continue
                sec = [(xs, z0), (xe, z0), (xe, z0 + D), (xs, z0 + D)]
                sec = hgeo.clip_halfplane(sec, lambda q: zt(q[0]) - q[1])
                if len(sec) < 3:
                    continue
                rel = [(x - xs, z - z0) for x, z in sec]
                idx = self.block("Ceiling Joist", rel, 0.0, bw, material)
                if idx is not None:
                    xf = face.frame.placed(yc - 0.5 * bw, xs) * G.Transform.Translation(0, 0, z0)
                    self.parts.append(Part(material=material, role="ceiling_joist", block=idx, xform=xf, extra=extra,
                                           layer_name=band.name))
        fill = o.get("cavity_fill")
        if fill and ctx.lod == "detail":
            depth = min(self.u(o.get("fill_depth") or 1e6), D)
            gap = self.u(self.T.get("baffle_gap", 1.5))
            ip = self.interior(face)
            zb = face.zb
            for ya, yb in zip(cys, cys[1:]):
                if yb - ya > 1.5 * self.spacing:
                    continue
                for x0, x1 in hgeo.chords(ip, 0.5 * (ya + yb)):
                    sec = [(x0, z0), (x1, z0), (x1, z0 + depth), (x0, z0 + depth)]
                    sec = hgeo.clip_halfplane(sec, lambda q: zb(q[0]) - gap - q[1])
                    if len(sec) < 3:
                        continue
                    y0, y1 = ya + 0.5 * bw, yb - 0.5 * bw
                    rel = [(x - x0, z - z0) for x, z in sec]
                    area = (x1 - x0) * (y1 - y0) / (self.s * self.s)
                    idx = self.block("Ceiling Fill", rel, 0.0, y1 - y0, fill)
                    if idx is not None:
                        xf = face.frame.placed(y0, x0) * G.Transform.Translation(0, 0, z0)
                        self.parts.append(Part(material=fill, role="insulation", block=idx, xform=xf,
                                               extra={"area": round(area, 2)}, layer_name=band.name))

    # -- run ----------------------------------------------------------------------------------------------
    def run(self):
        ctx = self.ctx
        self.n_rafters = 0
        for f in self.faces:
            self.plane_layers(f)
        if ctx.lod != "schematic":
            for f in self.faces:
                self.rafters(f)
                self.bird_blocks(f)
                self.rafter_fill(f)
            self.ridge()
            self.layer = "Trim"
            for f in self.faces:
                for e in f.edges():
                    if e.kind == "eave":
                        self.eave(f, e)
                    elif e.kind == "rake":
                        self.rake(f, e)
                    else:
                        self.oblique(f, e)
            self.layer = self.rb.name
            for f in self.faces:
                self.edge_nailers(f)
            self.ridge_cap()
        self.ceiling()
        for p in self.parts:
            p.layer_name = p.layer_name or self.rb.name
        return self.parts
