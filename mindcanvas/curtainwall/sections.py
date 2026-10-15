"""2D member sections of a curtain wall, in inches.

Coordinates (a, q): a = across the member (plan at a vertical: along the wall; section at a
horizontal: up), centred on the grid line; q = depth behind the exterior face of the glass
(q > 0 toward the interior, q < 0 in front of the glass). The glass occupies q in [0, T].

A Section lists Members (role, material, loops: first = outline, the rest = holes) and:
    edge_neg, edge_pos   a of the glass edge on each side (None = no glass on that side)
    struct_half          crossing members (transoms between verticals) stop at +-struct_half
    cover_half           crossing covers (pressure plates, caps) stop at +-cover_half
    setting              a where setting blocks start under the glass above (horizontals)

Joint styles:
    captured  tube + screw spline, thermal isolator, pressure plate, snap cap, EPDM gaskets
    ssg       tube, structural silicone + spacer tape at each glass edge, weather seal +
              backer rod in the joint, no cap
    butt      no member: silicone + backer rod between the glass edges (optional glass fin)
    split     unitized split mullion / stack joint: female + male halves with integral
              exterior lips, interlocking legs, weather and air seal gaskets
    unit      unitized intermediate horizontal: tube + web + integral lip
"""

import math

BLOCK_LT = 0.125      # interlock leg thickness


class Member(object):
    __slots__ = ("role", "material", "loops", "cover", "detail")

    def __init__(self, role, material, loops, cover=False, detail=False):
        self.role = role
        self.material = material
        self.loops = loops
        self.cover = cover          # pressure plate / cap: ends at the crossing cover line
        self.detail = detail        # only at detail LOD

    def __repr__(self):
        return "<Member {} {}>".format(self.role, self.material)


class Section(object):
    def __init__(self):
        self.members = []
        self.edge_neg = None
        self.edge_pos = None
        self.struct_half = 0.0
        self.cover_half = 0.0
        self.setting = None

    def add(self, role, material, loops, cover=False, detail=False):
        if loops and isinstance(loops[0], tuple):
            loops = [loops]
        self.members.append(Member(role, material, loops, cover, detail))

    def for_lod(self, lod):
        return [m for m in self.members if lod == "detail" or not m.detail]


def rect(a0, a1, q0, q1):
    a0, a1 = min(a0, a1), max(a0, a1)
    q0, q1 = min(q0, q1), max(q0, q1)
    return [(a0, q0), (a1, q0), (a1, q1), (a0, q1)]


def circle(ca, cq, r, n=16):
    return [(ca + r * math.cos(2 * math.pi * i / n), cq + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def mirror(pts):
    return [(-a, q) for a, q in reversed(pts)]


def sides(side):
    return {"both": (-1, 1), "neg": (-1,), "pos": (1,), "none": ()}[side]


def _gaskets(S, sec, sgn, e, w):
    """Exterior + interior glazing gaskets at a glass edge e (abs) on side sgn."""
    a0, a1 = sgn * (e + 1.0 / 16), sgn * (w / 2 - 3.0 / 16)
    sec.add("gasket", S.gasket_mat, rect(a0, a1, -S.g, 0.0), detail=True)
    sec.add("gasket", S.gasket_mat, rect(a0, a1, S.T, S.T + S.g), detail=True)


def schematic(S, style, prof, side):
    """Plain box from the system's front to the back of the member."""
    sec = Section()
    w, D = prof["w"], prof["D"]
    if style == "butt":
        e = S.jb / 2
        sec.edge_neg, sec.edge_pos = -e, e
        return sec
    qt = S.q_tube(style, prof)
    front = {"captured": -S.cap_P, "split": -(S.g + S.lip), "unit": -(S.g + S.lip)}.get(style, qt)
    sec.add("mullion", prof["material"], rect(-w / 2, w / 2, front, qt + D))
    e = (S.j / 2 if side == "both" else -(w / 2 - 0.25)) if style == "ssg" else w / 2 - S.bite
    _edges(sec, side, e)
    sec.struct_half = sec.cover_half = w / 2
    return sec


def _edges(sec, side, e):
    sg = sides(side)
    if -1 in sg:
        sec.edge_neg = -e
    if 1 in sg:
        sec.edge_pos = e


def captured(S, prof, side):
    sec = Section()
    w, D, t = prof["w"], prof["D"], prof["t"]
    qt = S.q_tube("captured", prof)
    l = S.l
    if prof["solid"]:
        sec.add("mullion", prof["material"], rect(-w / 2, w / 2, qt, qt + D))
        ad = prof["adaptor"]
        wb = w / 2 - 0.125
        sec.add("glazing_adaptor", S.material("pressure_plate"),
                [(-l / 2, 0.0), (l / 2, 0.0), (l / 2, qt - ad), (wb, qt - ad), (wb, qt), (-wb, qt),
                 (-wb, qt - ad), (-l / 2, qt - ad)])
    else:
        outer = [(-l / 2, 0.0), (l / 2, 0.0), (l / 2, qt), (w / 2, qt), (w / 2, qt + D), (-w / 2, qt + D),
                 (-w / 2, qt), (-l / 2, qt)]
        hole = rect(-w / 2 + t, w / 2 - t, qt + t, qt + D - t)
        sec.add("mullion", prof["material"], [outer, hole])
    sec.add("isolator", S.iso_mat, rect(-l / 2, l / 2, -S.g, 0.0), detail=True)
    hp = w / 2 - S.cap_t - 1.0 / 32
    sec.add("pressure_plate", S.material("pressure_plate"), rect(-hp, hp, -S.g - S.ppt, -S.g), cover=True)
    P = max(S.cap_P, S.g + S.ppt + S.cap_t + 1.0 / 16)
    ct, end = S.cap_t, -0.125
    cap = [(-w / 2, end), (-w / 2, -P), (w / 2, -P), (w / 2, end), (w / 2 - ct, end), (w / 2 - ct, -P + ct),
           (-w / 2 + ct, -P + ct), (-w / 2 + ct, end)]
    sec.add("cap", S.material("cap"), cap, cover=True)
    e = w / 2 - S.bite
    for sgn in sides(side):
        _gaskets(S, sec, sgn, e, w)
    _edges(sec, side, e)
    sec.struct_half = sec.cover_half = w / 2
    sec.setting = l / 2
    return sec


def ssg(S, prof, side):
    sec = Section()
    w, D, t = prof["w"], prof["D"], prof["t"]
    qt = S.q_tube("ssg", prof)
    loops = [rect(-w / 2, w / 2, qt, qt + D)]
    if not prof["solid"]:
        loops.append(rect(-w / 2 + t, w / 2 - t, qt + t, qt + D - t))
    sec.add("mullion", prof["material"], loops)
    E = S.j / 2 if side == "both" else -(w / 2 - 0.25)
    for sgn in sides(side):
        a0 = sgn * E
        sec.add("structural_silicone", S.silicone, rect(a0, a0 + sgn * S.sb, S.T, qt), detail=True)
        sec.add("spacer_tape", S.tape_mat, rect(a0 + sgn * S.sb, a0 + sgn * (S.sb + 0.25), S.T, qt),
                detail=True)
    if side == "both":
        sec.add("weather_seal", S.sealant, rect(-S.j / 2, S.j / 2, 0.0, S.seal), detail=True)
        r = 0.48 * S.j
        sec.add("backer_rod", S.backer, circle(0.0, S.seal + r, r), detail=True)
    _edges(sec, side, E)
    sec.struct_half = w / 2
    sec.cover_half = 0.0
    return sec


def butt(S, side="both"):
    sec = Section()
    jb, T = S.jb, S.T
    sec.add("butt_seal", S.sealant, rect(-jb / 2, jb / 2, 0.0, 0.25), detail=True)
    sec.add("butt_seal", S.sealant, rect(-jb / 2, jb / 2, T - 0.25, T), detail=True)
    sec.add("backer_rod", S.backer, circle(0.0, T / 2, 0.48 * jb), detail=True)
    if S.backup == "fin":
        ft = S.fin_t
        sec.add("structural_silicone", S.silicone, rect(-ft / 2, ft / 2, T, T + 0.25), detail=True)
        sec.add("glass_fin", S.glass_mat, rect(-ft / 2, ft / 2, T + 0.25, T + 0.25 + S.fin_d))
    _edges(sec, side, jb / 2)
    return sec


def _half(S, prof, female):
    """Left half (a < 0) of a split member: tube + web + exterior lip + interlock legs."""
    w, D, t = prof["w"], prof["D"], prof["t"]
    qt = S.q_tube("split", prof)
    s2 = S.split / 2
    web = 0.25
    lt = BLOCK_LT
    qi = qt + 0.35 * D
    ax = 0.5 * s2
    pts = [(-w / 2, qt), (-w / 2, qt + D), (-s2, qt + D)]
    if female:
        pts += [(-s2, qi + 2.5 * lt), (ax, qi + 2.5 * lt), (ax, qi + 1.5 * lt), (-s2, qi + 1.5 * lt),
                (-s2, qi - 1.5 * lt), (ax, qi - 1.5 * lt), (ax, qi - 2.5 * lt), (-s2, qi - 2.5 * lt)]
    else:
        pts += [(-s2, qi + 0.5 * lt), (ax, qi + 0.5 * lt), (ax, qi - 0.5 * lt), (-s2, qi - 0.5 * lt)]
    pts += [(-s2, -S.g - S.lip), (-w / 2, -S.g - S.lip), (-w / 2, -S.g), (-s2 - web, -S.g), (-s2 - web, qt)]
    loops = [pts]
    if not prof["solid"]:
        loops.append(rect(-w / 2 + t, -s2 - t, qt + t, qt + D - t))
    return loops, s2 + web


def split(S, prof, side, neg_female=True, neg_role="mullion_female", pos_role="mullion_male"):
    """Split member: the neg half (a < 0) and the pos half (a > 0)."""
    sec = Section()
    w, D = prof["w"], prof["D"]
    qt = S.q_tube("split", prof)
    neg, sa = _half(S, prof, neg_female)
    pos, _ = _half(S, prof, not neg_female)
    pos = [mirror(lp) for lp in pos]
    sec.add(neg_role, prof["material"], neg)
    sec.add(pos_role, prof["material"], pos)
    s2 = S.split / 2
    sec.add("weather_gasket", S.gasket_mat, rect(-s2, s2, -S.g - S.lip, -S.g), detail=True)
    sec.add("air_seal", S.gasket_mat, rect(-s2, s2, qt + D - 0.375, qt + D - 0.125), detail=True)
    e = w / 2 - S.bite
    for sgn in sides(side):
        _gaskets(S, sec, sgn, e, w)
    _edges(sec, side, e)
    sec.struct_half = sec.cover_half = w / 2
    sec.setting = sa
    return sec


def unit(S, prof, side):
    """Intermediate horizontal of a unitized frame: I-shape with an integral exterior lip."""
    sec = Section()
    w, D, t = prof["w"], prof["D"], prof["t"]
    qt = S.q_tube("unit", prof)
    wb = 0.125
    f = -S.g - S.lip
    pts = [(-w / 2, qt), (-w / 2, qt + D), (w / 2, qt + D), (w / 2, qt), (wb, qt), (wb, -S.g), (w / 2, -S.g),
           (w / 2, f), (-w / 2, f), (-w / 2, -S.g), (-wb, -S.g), (-wb, qt)]
    loops = [pts]
    if not prof["solid"]:
        loops.append(rect(-w / 2 + t, w / 2 - t, qt + t, qt + D - t))
    sec.add("transom", prof["material"], loops)
    e = w / 2 - S.bite
    for sgn in sides(side):
        _gaskets(S, sec, sgn, e, w)
    _edges(sec, side, e)
    sec.struct_half = sec.cover_half = w / 2
    sec.setting = wb
    return sec


def vertical(S, kind, lod):
    """Plan section of a vertical at a vertex of kind inline / start / end."""
    side = {"inline": "both", "start": "pos", "end": "neg"}[kind]
    style = S.v_style
    if style == "butt" and kind != "inline":
        style = "captured"
    if lod == "schematic":
        return schematic(S, style, S.mp, side)
    if style == "captured":
        return captured(S, S.mp, side)
    if style == "ssg":
        return ssg(S, S.mp, side)
    if style == "butt":
        return butt(S, side)
    return split(S, S.mp, side, neg_female=True)


def horizontal(S, kind, lod):
    """Section of a horizontal (sill / transom / stack / head); a = up."""
    side = {"sill": "pos", "head": "neg", "transom": "both", "stack": "both"}[kind]
    style = S.h_style
    if style == "unit" and kind != "transom":
        style = "split"
    if lod == "schematic":
        sec = schematic(S, style, S.tp, side)
        for m in sec.members:
            m.role = "sill" if kind == "sill" else ("head" if kind == "head" else "transom")
        return sec
    if style == "captured":
        sec = captured(S, S.tp, side)
    elif style == "ssg":
        sec = ssg(S, S.tp, side)
    elif style == "unit":
        sec = unit(S, S.tp, side)
    else:
        # lower half = male, upper half = female: the upper unit's channel sits over the lower
        # unit's leg. Sill: starter sill + the unit's bottom rail; head: top rail + receptor.
        neg_role, pos_role = {"sill": ("starter_sill", "sill"), "head": ("head", "head_receptor")}.get(
            kind, ("stack_male", "stack_female"))
        sec = split(S, S.tp, side, neg_female=False, neg_role=neg_role, pos_role=pos_role)
    for m in sec.members:
        if m.role == "mullion":
            m.role = {"sill": "sill", "head": "head"}.get(kind, "transom")
    return sec
