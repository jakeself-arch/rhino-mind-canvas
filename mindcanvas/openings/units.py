"""Window and door units, built with their host (parts belong to the host driver).

Window: mitered frame (glazing pocket when fixed, exterior stop when operable), optional
mullions / transoms, sashes (casement, awning, double hung, sliding), insulated glass
(two lites + spacer at detail). Door: three-sided mitered frame with a stop, leaf (optional
glass lite), threshold, and the swing (arc + open leaf line at the floor, for plans).
Both: interior jamb liners + stool (windows), sill pan and, on walls without brick, a head
drip cap (detail).

LOD: schematic = plain frame ring + one glass slab / leaf; design = profiles, sashes, glass
as one slab; detail = everything.

Frame profiles are (p, q): p inward from the frame's outer edge, q from the frame's exterior
face toward the interior. The frame's exterior face is op.y_fe (see core.Opening).
"""

import math

import Rhino

from .. import units
from ..components.base import Part
from . import geom

G = Rhino.Geometry
CLR = 1.0 / 16


def glazed_profile(F, D, igu, bite, g, ext, bead):
    """Frame/sash section with a glazing pocket. Returns (points, (q_glass0, q_glass1), depth)."""
    Fb = max(F - bite - g, 0.25 * F)
    qg0 = ext + g
    qg1 = qg0 + igu
    qb0 = qg1 + g
    qb1 = qb0 + bead
    D = max(D, qb1 + g)
    pts = [(0, 0), (F, 0), (F, ext), (Fb, ext), (Fb, qb0), (F, qb0), (F, qb1), (Fb, qb1), (Fb, D), (0, D)]
    return pts, (qg0, qg1), D


def stop_profile(F, D, stop, q0, q1):
    """Frame section with a stop leg (p from F - stop to F) between q0 and q1."""
    Fs = F - stop
    if q0 <= 1e-9:
        return [(0, 0), (F, 0), (F, q1), (Fs, q1), (Fs, D), (0, D)]
    if q1 >= D - 1e-9:
        return [(0, 0), (Fs, 0), (Fs, q0), (F, q0), (F, D), (0, D)]
    return [(0, 0), (Fs, 0), (Fs, q0), (F, q0), (F, q1), (Fs, q1), (Fs, D), (0, D)]


class _B(object):
    """Collects parts of one opening."""

    def __init__(self, ctx, op):
        self.ctx, self.op = ctx, op
        self.parts = []
        self.u = ctx.u
        self.tol = ctx.tol

    def add(self, geom_, material, role, **extra):
        if geom_ is None:
            return
        self.parts.append(Part(geom_, material, role=role, extra=extra))

    def box(self, x0, x1, y0, y1, z0, z1, material, role, **extra):
        if abs(x1 - x0) > self.tol and abs(y1 - y0) > self.tol and abs(z1 - z0) > self.tol:
            self.add(self.op.box(x0, x1, y0, y1, z0, z1), material, role, **extra)

    def ring(self, x0, x1, z0, z1, profile, y_face, material, role, sides=("head", "sill", "left", "right")):
        for side, b in sorted(geom.frame_ring(self.op, x0, x1, z0, z1, profile, y_face, self.tol, sides).items()):
            self.add(b, material, role, side=side)

    def igu(self, x0, x1, z0, z1, y_ext, gz, detail):
        u = self.u
        lites = max(1, int(gz.get("lites", 2)))
        tg, sp = u(gz.get("glass", "1/4")), u(gz.get("space", "1/2"))
        mat = gz.get("material", "Glass")
        total = lites * tg + (lites - 1) * sp
        if not detail or lites == 1:
            self.box(x0, x1, y_ext - total, y_ext, z0, z1, mat, "glass", lites=lites)
            return total
        y = y_ext
        sw, inset = u("3/8"), u("1/16")
        smat = gz.get("spacer", "Aluminum")
        for i in range(lites):
            self.box(x0, x1, y - tg, y, z0, z1, mat, "glass", lite=i + 1)
            y -= tg
            if i < lites - 1:
                a, b = y - sp, y
                xa, xb, za, zb = x0 + inset, x1 - inset, z0 + inset, z1 - inset
                self.box(xa, xb, a, b, zb - sw, zb, smat, "spacer")
                self.box(xa, xb, a, b, za, za + sw, smat, "spacer")
                self.box(xa, xa + sw, a, b, za + sw, zb - sw, smat, "spacer")
                self.box(xb - sw, xb, a, b, za + sw, zb - sw, smat, "spacer")
                y -= sp
        return total


def _igu_thickness(ctx, gz):
    lites = max(1, int(gz.get("lites", 2)))
    return lites * ctx.u(gz.get("glass", "1/4")) + (lites - 1) * ctx.u(gz.get("space", "1/2"))


# -- windows -------------------------------------------------------------------------
def _cells(x0, x1, z0, z1, nx, nz, M):
    """Sightline rectangles between mullions, and the mullion rectangles (vertical first)."""
    cw = (x1 - x0 - nx * M) / float(nx + 1)
    ch = (z1 - z0 - nz * M) / float(nz + 1)
    cells, vm, hm = [], [], []
    for i in range(nx + 1):
        a = x0 + i * (cw + M)
        if i < nx:
            vm.append((a + cw, a + cw + M))
        for k in range(nz + 1):
            b = z0 + k * (ch + M)
            cells.append((a, a + cw, b, b + ch))
            if k < nz:
                hm.append((a, a + cw, b + ch, b + ch + M))
    return cells, vm, hm


def _mullion_section(M, D, fixed, igu_q, g, ext, bead, stop):
    h = 0.5 * M
    if fixed:
        lw = min(h - 0.1 * M, 0.5 * h)
        hb = h - lw
        qg0, qg1 = igu_q
        qb0, qb1 = qg1 + g, qg1 + g + bead
        right = [(h, 0), (h, ext), (hb, ext), (hb, qb0), (h, qb0), (h, qb1), (hb, qb1), (hb, D)]
    else:
        hb = h - stop
        right = [(h, 0), (h, ext), (hb, ext), (hb, D)]
    left = [(-u, q) for u, q in reversed(right)]
    return right + left


def _window(b, detail, design):
    ctx, op, u = b.ctx, b.op, b.u
    t = op.t
    fr, gz = t["frame"], t["glazing"]
    mat = fr.get("material", "Aluminum")
    F = u(fr.get("face", "1-3/4"))
    yF = op.y_fe
    Df = op.y_fe - op.y_fi
    x0, x1, z0, z1 = -0.5 * op.W, 0.5 * op.W, op.z0, op.z1
    igu = _igu_thickness(ctx, gz)
    if not design:   # schematic
        b.ring(x0, x1, z0, z1, [(0, 0), (F, 0), (F, Df), (0, Df)], yF, mat, "frame")
        yg = yF - 0.5 * (Df - igu)
        b.box(x0 + F, x1 - F, yg - igu, yg, z0 + F, z1 - F, gz.get("material", "Glass"), "glass")
        return
    g, ext, bead, stop = u("1/8"), u("3/8"), u("1/2"), u("3/8")
    bite = u(gz.get("bite", "1/2"))
    oper = str(t.get("operation", "fixed")).lower()
    fixed = oper == "fixed"
    if fixed:
        prof, igu_q, Dn = glazed_profile(F, Df, igu, bite, g, ext, bead)
    else:
        prof, igu_q, Dn = stop_profile(F, Df, stop, 0.0, ext), None, Df
    if Dn > Df + ctx.tol:
        ctx.warn("Window '{}': frame depth {} is less than its glazing needs ({}).".format(
            op.name, units.format_inches(Df / ctx.s), units.format_inches(Dn / ctx.s)))
    b.ring(x0, x1, z0, z1, prof, yF, mat, "frame")
    mu = t.get("mullions") or {}
    nx, nz = int(mu.get("vertical", 0) or 0), int(mu.get("horizontal", 0) or 0)
    M = u(mu.get("face", fr.get("face", "1-3/4")))
    cells, vm, hm = _cells(x0 + F, x1 - F, z0 + F, z1 - F, nx, nz, M)
    sec = _mullion_section(M, Df, fixed, igu_q, g, ext, bead, stop)
    for a, c in vm:
        xc = 0.5 * (a + c)
        poly = [(xc + s, yF - q) for s, q in sec]
        b.add(geom.prism_z(op, poly, z0 + F - bite, z1 - F + bite, b.tol), mat, "mullion")
    for a, c, za, zc in hm:
        zm = 0.5 * (za + zc)
        poly = [(yF - q, zm + s) for s, q in sec]
        b.add(geom.prism_x(op, poly, a - bite, c + bite, b.tol), mat, "mullion")
    if fixed:
        for cx0, cx1, cz0, cz1 in cells:
            b.igu(cx0 - bite, cx1 + bite, cz0 - bite, cz1 + bite, yF - igu_q[0], gz, detail)
        return
    sh = t.get("sash") or {}
    smat = sh.get("material", mat)
    Fs = u(sh.get("face", "2"))
    Ds = u(sh.get("depth", "1-3/4"))
    sprof, sq, Ds = glazed_profile(Fs, Ds, igu, bite, g, u("1/4"), u("3/8"))
    ov = stop - CLR * ctx.s
    q0 = ext + CLR * ctx.s
    q1 = q0 + Ds + CLR * ctx.s
    if oper in ("double_hung", "sliding") and q1 + Ds > Df + ctx.tol:
        ctx.warn("Window '{}': frame too shallow for two sashes.".format(op.name))

    def sash(sx0, sx1, sz0, sz1, q):
        y = yF - q
        b.ring(sx0, sx1, sz0, sz1, sprof, y, smat, "sash")
        b.igu(sx0 + Fs - bite, sx1 - Fs + bite, sz0 + Fs - bite, sz1 - Fs + bite, y - sq[0], gz, detail)

    for cx0, cx1, cz0, cz1 in cells:
        X0, X1, Z0, Z1 = cx0 - ov, cx1 + ov, cz0 - ov, cz1 + ov
        if oper == "double_hung":
            zm = 0.5 * (Z0 + Z1)
            sash(X0, X1, zm - 0.5 * Fs, Z1, q0)
            sash(X0, X1, Z0, zm + 0.5 * Fs, q1)
        elif oper == "sliding":
            xm = 0.5 * (X0 + X1)
            sash(X0, xm + 0.5 * Fs, Z0, Z1, q0)
            sash(xm - 0.5 * Fs, X1, Z0, Z1, q1)
        else:   # casement, awning, hopper, single sash
            sash(X0, X1, Z0, Z1, q0)


# -- doors ---------------------------------------------------------------------------
def _door(b, detail, design):
    ctx, op, u = b.ctx, b.op, b.u
    t = op.t
    fr, lf = t["frame"], t["leaf"]
    mat = fr.get("material", "Hollow Metal")
    F = u(fr.get("face", "2"))
    stop = u(fr.get("stop", "5/8"))
    yF = op.y_fe
    Df = op.y_fe - op.y_fi
    T = u(lf.get("thickness", "1-3/4"))
    clr = u(lf.get("clearance", "1/8"))
    x0, x1, z0, z1 = -0.5 * op.W, 0.5 * op.W, op.z0, op.z1
    inswing = op.swing != "out"
    rab = min(T + CLR * ctx.s, Df)
    if inswing:
        lq0, lq1 = Df - rab, Df - rab + T
        sq0, sq1 = max(0.0, lq0 - u("1-1/2")), lq0
    else:
        lq0, lq1 = rab - T, rab
        sq0, sq1 = lq1, min(Df, lq1 + u("1-1/2"))
    sides = ("head", "left", "right")
    if design:
        prof = stop_profile(F + stop, Df, stop, sq0, sq1)
    else:
        prof = [(0, 0), (F, 0), (F, Df), (0, Df)]
    b.ring(x0, x1, z0, z1, prof, yF, mat, "frame", sides)
    # leaf
    lx0, lx1 = x0 + F + clr, x1 - F - clr
    lz0, lz1 = z0 + u(lf.get("undercut", "3/4")), z1 - F - clr
    ly1, ly0 = yF - lq0, yF - lq1
    lmat = lf.get("material", "Hollow Metal Door")
    lite = lf.get("lite") if design else None
    leaf = op.box(lx0, lx1, ly0, ly1, lz0, lz1)
    if lite:
        if lite.get("width"):
            hw = 0.5 * u(lite["width"])
            gx0, gx1 = 0.5 * (lx0 + lx1) - hw, 0.5 * (lx0 + lx1) + hw
        else:
            gx0, gx1 = lx0 + u(lite.get("stile", 5)), lx1 - u(lite.get("stile", 5))
        gz0, gz1 = lz0 + u(lite.get("bottom", 10)), lz1 - u(lite.get("top", 5))
        if gx1 - gx0 > u(2) and gz1 - gz0 > u(2):
            hole = op.box(gx0, gx1, ly0 - u(1), ly1 + u(1), gz0, gz1)
            res = G.Brep.CreateBooleanDifference([leaf], [hole], ctx.tol)
            if res:
                leaf = res[0]
            gz_ = dict(t["glazing"])
            gz_.update(lite.get("glazing", {}))
            igu = _igu_thickness(ctx, gz_)
            if igu > T - u("1/8"):
                gz_ = {"lites": 1, "glass": lite.get("glass", "1/4"), "material": gz_.get("material", "Glass")}
                igu = _igu_thickness(ctx, gz_)
            yc = 0.5 * (ly0 + ly1)
            bite = u("1/2")
            b.igu(gx0 - bite, gx1 + bite, gz0 - bite, gz1 + bite, yc + 0.5 * igu, gz_, detail)
            if detail:   # glazing stops both faces
                st = u("5/8")
                sp = [(0, 0), (st, 0), (st, st), (0, st)]
                b.ring(gx0 - st, gx1 + st, gz0 - st, gz1 + st, sp, ly1 + st, lmat, "glazing_stop")
                b.ring(gx0 - st, gx1 + st, gz0 - st, gz1 + st, sp, ly0, lmat, "glazing_stop")
    b.add(leaf, lmat, "leaf")
    # threshold
    th = t.get("threshold")
    if design and th:
        tw, tht = u(th.get("width", 5)), u(th.get("height", "1/2"))
        yc = 0.5 * (ly0 + ly1)
        tw = min(tw, Df + u(1))
        poly = [(yc + 0.5 * tw, z0), (yc + 0.5 * tw - 0.35 * tw, z0 + tht), (yc - 0.5 * tw + 0.35 * tw, z0 + tht),
                (yc - 0.5 * tw, z0)]
        b.add(geom.prism_x(op, poly, x0 + F, x1 - F, b.tol), th.get("material", "Aluminum"), "threshold")
    # swing (plan symbol at the floor). Hinge "left" = left as seen from the exterior (+X here).
    W_leaf = lx1 - lx0
    hx = lx1 if op.hinge == "left" else lx0
    lx = lx0 if op.hinge == "left" else lx1
    side = -1.0 if inswing else 1.0
    yh = ly0 if inswing else ly1
    zf = op.z0
    P = op.pt(hx, yh, zf)
    closed = op.pt(lx, yh, zf)
    opened = op.pt(hx, yh + side * W_leaf, zf)
    try:
        arc = G.Arc(G.Plane(P, closed - P, opened - P), W_leaf, math.pi / 2)
        b.add(G.ArcCurve(arc), "Door Swing", "swing")
    except Exception:
        pass
    b.add(G.LineCurve(P, opened), "Door Swing", "swing")


# -- trim, sill pan, head drip ------------------------------------------------------------------
def _trim(b):
    ctx, op, u = b.ctx, b.op, b.u
    tr = op.t.get("trim") or {}
    tl = u(tr.get("liner") or 0)
    mat = tr.get("material", "Wood Trim")
    ya, yb = op.y_int, op.y_fi
    if tl <= 0 or yb - ya < u("1/8"):
        return
    st = u(tr["stool"]) if (not op.door and tr.get("stool")) else 0.0
    rx, rz0, rz1 = op.rx, op.rz0, op.rz1
    if st:
        proj = u(tr.get("stool_projection", "3/4"))
        b.box(-rx, rx, ya - proj, yb, rz0, rz0 + st, mat, "stool")
    zb = rz0 + st
    b.box(-rx, -rx + tl, ya, yb, zb, rz1 - tl, mat, "liner", side="left")
    b.box(rx - tl, rx, ya, yb, zb, rz1 - tl, mat, "liner", side="right")
    b.box(-rx, rx, ya, yb, rz1 - tl, rz1, mat, "liner", side="head")


def _pan(b):
    ctx, op, u = b.ctx, b.op, b.u
    sp = op.t.get("sill_pan") or {}
    if op.door or not sp:
        return
    tp = u(sp.get("thickness", "1/32"))
    drip = u("3/8")
    if op.masonry_ext is not None and op.behind_brick:
        # on the rough sill, lapping 3/4" out over the back of the rowlock
        zp = op.rz0 + tp
        yf = op.y_fe + u("3/4")
        hx = 0.5 * op.W + op.joint
        drip = u("1/4")
    elif op.masonry_ext is not None:
        zp = op.z0
        yf = op.y_fe + u("1/2")
        hx = 0.5 * op.W + op.joint
    else:
        zp = op.rz0 + tp
        yf = max(op.y_ext, op.y_fe) + u(sp.get("drip", "3/8"))
        hx = op.rx
    path = [(yf, zp - drip), (yf, zp), (op.y_fi, zp), (op.y_fi, zp + u(sp.get("back_dam", 1)))]
    poly = geom.thicken(path, tp)
    b.add(geom.prism_x(op, poly, -hx, hx, b.tol), sp.get("material", "Flashing - Membrane"), "sill_pan")


def _drip(b):
    ctx, op, u = b.ctx, b.op, b.u
    hf = op.t.get("head_flashing") or {}
    if op.masonry_ext is not None or not hf or op.y_fe > op.y_ext - u("1/8"):
        return
    tf = u(hf.get("thickness", "1/32"))
    zd = op.z1 + tf
    yd = op.y_ext + u(hf.get("drip", "3/8"))
    path = [(yd, zd - u("3/8")), (yd, zd), (op.y_fe + tf, zd), (op.y_fe + tf, zd + u(hf.get("upturn", 2)))]
    poly = geom.thicken(path, tf)
    hx = 0.5 * op.W + op.joint
    b.add(geom.prism_x(op, poly, -hx, hx, b.tol), hf.get("material", "Flashing"), "head_flashing")


def build(ctx, op):
    """Parts of one opening's unit + trim (tagged with the opening id)."""
    b = _B(ctx, op)
    design = ctx.lod != "schematic"
    detail = ctx.lod == "detail"
    try:
        (_door if op.door else _window)(b, detail, design)
        if design:
            _trim(b)
        if detail:
            _pan(b)
            _drip(b)
    except Exception as ex:
        ctx.warn("Opening '{}': unit geometry failed ({}).".format(op.name, ex))
    for p in b.parts:
        p.extra["opening"] = str(op.id)
        p.extra["type"] = op.name
        p.layer_name = "Opening"
    return b.parts
