"""Line-drawn entourage: 2D figures (people, trees, shrubs) as layered outlines + detail lines.

Pure Python (no Rhino), so the generators can be tested anywhere. Coordinates are INCHES,
x across the figure (centred on 0), y up from the ground (y = 0).

A figure is a list of `Layer`s. Every layer is one flat card: its closed `loops` are unioned
into the card outline (they hide what is behind the figure in drawings) and its open `lines`
are drawn on it (folds, collars, branches, foliage texture). Layers are stacked in depth by
`depth`: smaller = nearer the viewer (a front arm at -1 is drawn over the torso at 0, a back leg
at +2 is hidden behind it). See entourage/place.py for how a figure becomes Rhino geometry.

Generators are registered in GENERATORS; a library entry (library/entourage/*.json) names one:

    "Person - Walking": {"generator": "person", "pose": "walk", "height": "5'-8\\"", "seed": 3}

Add a generator: a function (params dict, random.Random) -> [Layer], registered with @generator.
"""

import math
import random

GENERATORS = {}


def generator(name):
    def deco(fn):
        GENERATORS[name] = fn
        return fn
    return deco


class Layer(object):
    __slots__ = ("depth", "loops", "lines")

    def __init__(self, depth=0.0, loops=None, lines=None):
        self.depth = float(depth)
        self.loops = loops or []      # closed outlines [[(x, y), ...]] (first point not repeated)
        self.lines = lines or []      # open polylines [[(x, y), ...]]

    def __repr__(self):
        return "<Layer {:+.1f}: {} loops, {} lines>".format(self.depth, len(self.loops), len(self.lines))


def _len(v, default):
    """Inches from a number or an imperial string (units.parse_length, imported lazily)."""
    if v is None:
        return float(default)
    if isinstance(v, (int, float)):
        return float(v)
    from .. import units
    return units.parse_length(v)


# -- primitives ---------------------------------------------------------------------------------
def ellipse(cx, cy, rx, ry, n=20, a0=0.0):
    return [(cx + rx * math.cos(a0 + 2 * math.pi * i / n), cy + ry * math.sin(a0 + 2 * math.pi * i / n))
            for i in range(n)]


def limb(p0, p1, r0, r1, n=6):
    """Tapered capsule from p0 (radius r0) to p1 (radius r1)."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy) or 1e-9
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux
    pts = []
    for i in range(n + 1):       # around p1: +n -> u -> -n
        a = math.pi * i / n
        c, s = math.cos(a), math.sin(a)
        pts.append((p1[0] + r1 * (nx * c + ux * s), p1[1] + r1 * (ny * c + uy * s)))
    for i in range(n + 1):       # around p0: -n -> -u -> +n
        a = math.pi * i / n
        c, s = math.cos(a), math.sin(a)
        pts.append((p0[0] + r0 * (-nx * c - ux * s), p0[1] + r0 * (-ny * c - uy * s)))
    return pts


def chaikin(pts, n=2, closed=True):
    for _ in range(n):
        out = []
        m = len(pts) if closed else len(pts) - 1
        if not closed:
            out.append(pts[0])
        for i in range(m):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            out.append((0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]))
            out.append((0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]))
        if not closed:
            out.append(pts[-1])
        pts = out
    return pts


def mirror_x(pts):
    return [(-x, y) for x, y in pts]


def symmetric(half):
    """Closed outline from its left half (top -> bottom, x <= 0): left half + mirrored right."""
    return list(half) + [(-x, y) for x, y in reversed(half)]


def _rot(p, c, a):
    s, co = math.sin(a), math.cos(a)
    x, y = p[0] - c[0], p[1] - c[1]
    return (c[0] + x * co - y * s, c[1] + x * s + y * co)


def scallops(center, rx, ry, n, bump, rnd, start=0.0, end=2 * math.pi, k=6, jitter=0.08):
    """Cloud outline: n outward bumps along an ellipse arc (start..end angles)."""
    angs = [start + (end - start) * i / float(n) for i in range(n + 1)]
    rad = [1.0 + jitter * (rnd.random() - 0.5) for _ in angs]
    if abs(end - start - 2 * math.pi) < 1e-9:
        rad[-1] = rad[0]
    base = [(center[0] + rx * r * math.cos(a), center[1] + ry * r * math.sin(a)) for a, r in zip(angs, rad)]
    out = []
    for i in range(n):
        a, b = base[i], base[i + 1]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1e-9
        nx, ny = dy / L, -dx / L         # outward for counter-clockwise arcs
        h = bump * L * (0.8 + 0.4 * rnd.random())
        for j in range(k):
            t = j / float(k)
            s = math.sin(math.pi * t)
            out.append((a[0] + dx * t + nx * h * s, a[1] + dy * t + ny * h * s))
    if abs(end - start - 2 * math.pi) > 1e-9:
        out.append(base[-1])
    return out


def inside(pt, poly):
    x, y = pt
    c = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            c = not c
        j = i
    return c


def cup(cx, cy, w, h, a=0.0):
    """Small foliage stroke: a shallow U (3 points + 2), rotated by a."""
    pts = [(-w / 2, h), (-w / 4, 0.15 * h), (0, 0), (w / 4, 0.15 * h), (w / 2, h)]
    return [_rot((cx + x, cy + y), (cx, cy), a) for x, y in pts]


# -- people -------------------------------------------------------------------------------------
@generator("person")
def person(p, rnd):
    """Standing figure seen from the front (pose 'front') or walking in profile (pose 'walk').
    Options: height, dress (suit | coat | dress), bag (bool), arm (down | bent), facing (right |
    left, walk only)."""
    H = _len(p.get("height"), 68)
    child = H < 54
    u = H / (6.2 if child else 7.5)            # head height
    dress = p.get("dress", "suit")
    pose = p.get("pose", "front")
    out = _person_walk(H, u, dress, p, rnd) if pose == "walk" else _person_front(H, u, dress, p, rnd)
    if pose == "walk" and p.get("facing", "right") == "left":
        for ly in out:
            ly.loops = [list(reversed(mirror_x(lp))) for lp in ly.loops]
            ly.lines = [mirror_x(ln) for ln in ly.lines]
    # stand on the lowest point (a stride lifts the ankles)
    y0 = min(y for ly in out for lp in ly.loops for x, y in lp)
    for ly in out:
        ly.loops = [[(x, y - y0) for x, y in lp] for lp in ly.loops]
        ly.lines = [[(x, y - y0) for x, y in ln] for ln in ly.lines]
    return out


def _hem(H, u, dress):
    return {"coat": H - 5.3 * u, "dress": H - 5.0 * u}.get(dress, H - 3.75 * u)


def _person_front(H, u, dress, p, rnd):
    body = Layer(0)
    body.loops.append(ellipse(0, H - 0.5 * u, 0.36 * u, 0.5 * u, 22))
    body.loops.append([(-0.15 * u, H - 1.2 * u), (0.15 * u, H - 1.2 * u), (0.15 * u, H - 0.85 * u),
                       (-0.15 * u, H - 0.85 * u)])
    y_hem = _hem(H, u, dress)
    waist = 0.62 * u if dress == "dress" else 0.78 * u
    flare = {"coat": 0.98 * u, "dress": 1.15 * u}.get(dress, 0.82 * u)
    half = [(-0.22 * u, H - 1.12 * u), (-0.72 * u, H - 1.3 * u), (-0.94 * u, H - 1.55 * u),
            (-0.92 * u, H - 1.95 * u), (-waist, H - 2.9 * u), (-flare, y_hem)]
    body.loops.append(symmetric(chaikin(half, 1, closed=False)))
    # collar and the opening of the jacket / coat
    body.lines.append([(-0.22 * u, H - 1.12 * u), (0, H - 1.75 * u), (0.22 * u, H - 1.12 * u)])
    if dress == "dress":
        body.lines.append([(-waist, H - 2.9 * u), (waist, H - 2.9 * u)])
    else:
        body.lines.append([(0, H - 1.75 * u), (0, y_hem)])
        if dress == "suit":
            body.lines.append([(-0.55 * u, H - 3.05 * u), (-0.3 * u, H - 3.05 * u)])
    # legs behind the hem, shoes in front of the legs
    legs = Layer(1)
    shoes = Layer(0.5)
    top = y_hem + 0.3 * u
    for sx in (-1, 1):
        if dress == "suit":
            leg = [(sx * 0.06 * u, top), (sx * 0.78 * u, top), (sx * 0.52 * u, 0.3 * u), (sx * 0.12 * u, 0.3 * u)]
        else:
            leg = [(sx * 0.12 * u, top), (sx * 0.45 * u, top), (sx * 0.36 * u, 0.3 * u), (sx * 0.16 * u, 0.3 * u)]
        legs.loops.append(leg)
        shoe = [(-0.62, 0.0), (-0.05, 0.0), (-0.05, 0.2), (-0.18, 0.34), (-0.5, 0.34), (-0.66, 0.16)]
        # toes turned slightly out: the left shoe is the outline above, the right one mirrored
        shoes.loops.append([(-sx * (x - 0.08) * u, y * u) for x, y in shoe])
    if dress == "suit":
        legs.lines.append([(0, top), (0, y_hem - 0.35 * u)])
    # arms in front of the body
    arms = Layer(-1)
    bent = p.get("arm", "down") == "bent"
    for sx in (-1, 1):
        sh = (sx * 0.84 * u, H - 1.62 * u)
        if bent and sx > 0:
            el, wr = (sx * 1.18 * u, H - 2.75 * u), (sx * 0.62 * u, H - 3.35 * u)
        else:
            el, wr = (sx * 1.02 * u, H - 2.85 * u), (sx * 1.04 * u, H - 3.85 * u)
        arms.loops.append(limb(sh, el, 0.19 * u, 0.15 * u))
        arms.loops.append(limb(el, wr, 0.15 * u, 0.11 * u))
        hand_c = (wr[0] + (wr[0] - el[0]) * 0.15, wr[1] + (wr[1] - el[1]) * 0.15 - 0.08 * u)
        arms.loops.append(ellipse(hand_c[0], hand_c[1], 0.11 * u, 0.19 * u, 12))
        arms.lines.append([(wr[0] - 0.12 * u, wr[1] + 0.12 * u), (wr[0] + 0.12 * u, wr[1] + 0.12 * u)])
    out = [body, legs, shoes, arms]
    if p.get("bag"):
        hx = 1.04 * u
        bag = Layer(-2)
        bag.loops.append([(hx - 0.55 * u, H - 5.0 * u), (hx + 0.55 * u, H - 5.0 * u),
                          (hx + 0.5 * u, H - 4.05 * u), (hx - 0.5 * u, H - 4.05 * u)])
        bag.lines.append([(hx - 0.2 * u, H - 4.05 * u), (hx - 0.12 * u, H - 3.85 * u),
                          (hx + 0.12 * u, H - 3.85 * u), (hx + 0.2 * u, H - 4.05 * u)])
        out.append(bag)
    return out


def _leg(hip, ang, L, knee_bend, u, toe_lift=0.0):
    """Leg + shoe in profile, facing +x; ang from vertical (+ = forward)."""
    knee = (hip[0] + math.sin(ang) * L * 0.5 + knee_bend * u, hip[1] - math.cos(ang) * L * 0.5)
    ankle = (hip[0] + math.sin(ang) * L, hip[1] - math.cos(ang) * L)
    loops = [limb(hip, knee, 0.34 * u, 0.2 * u), limb(knee, ankle, 0.2 * u, 0.12 * u)]
    foot = [(-0.25, -0.3), (0.95, -0.3), (1.0, -0.12), (0.75, 0.0), (0.1, 0.12), (-0.25, 0.05)]
    a = toe_lift
    loops.append([_rot((ankle[0] + x * u, ankle[1] + y * u + 0.3 * u), (ankle[0] + 0.95 * u, ankle[1] + 0.0), a)
                  for x, y in foot])
    return loops


def _person_walk(H, u, dress, p, rnd):
    stride = math.radians(float(p.get("stride", 20)))
    body = Layer(0)
    body.loops.append(ellipse(0.06 * u, H - 0.5 * u, 0.42 * u, 0.5 * u, 22))
    body.loops.append([(0.42 * u, H - 0.42 * u), (0.55 * u, H - 0.62 * u), (0.42 * u, H - 0.7 * u)])
    body.loops.append([(-0.12 * u, H - 1.2 * u), (0.16 * u, H - 1.2 * u), (0.16 * u, H - 0.85 * u),
                       (-0.12 * u, H - 0.85 * u)])
    y_hem = _hem(H, u, dress)
    back_hem = -0.55 * u if dress in ("coat", "dress") else -0.42 * u
    front_hem = 0.62 * u if dress in ("coat", "dress") else 0.42 * u
    torso = [(-0.3 * u, H - 1.15 * u), (0.22 * u, H - 1.15 * u), (0.42 * u, H - 1.45 * u),
             (0.45 * u, H - 2.2 * u), (0.38 * u, H - 3.0 * u), (front_hem, y_hem), (back_hem, y_hem),
             (-0.42 * u, H - 3.0 * u), (-0.4 * u, H - 1.6 * u)]
    body.loops.append(chaikin(torso, 1))
    body.lines.append([(0.12 * u, H - 1.15 * u), (0.3 * u, H - 1.6 * u)])
    if dress == "suit":
        body.lines.append([(-0.42 * u, H - 3.05 * u), (0.38 * u, H - 3.05 * u)])
    hip = (0.0, H - 3.55 * u)
    L = hip[1] - 0.3 * u
    front_leg = Layer(1, _leg(hip, stride, L, 0.12, u))
    back_leg = Layer(2, _leg(hip, -stride * 0.9, L, 0.25, u, toe_lift=math.radians(18)))
    # arms swing opposite to the legs: the near arm back, the far arm forward
    sh = (-0.02 * u, H - 1.62 * u)

    def arm(ang, depth):
        el = (sh[0] + math.sin(ang) * 1.3 * u, sh[1] - math.cos(ang) * 1.3 * u)
        a2 = ang + math.radians(18)
        wr = (el[0] + math.sin(a2) * 1.05 * u, el[1] - math.cos(a2) * 1.05 * u)
        hand = ellipse(wr[0] + math.sin(a2) * 0.2 * u, wr[1] - math.cos(a2) * 0.2 * u, 0.12 * u, 0.2 * u, 12)
        ly = Layer(depth, [limb(sh, el, 0.2 * u, 0.15 * u), limb(el, wr, 0.15 * u, 0.11 * u), hand])
        ly.lines.append([(wr[0] - 0.13 * u, wr[1] + 0.06 * u), (wr[0] + 0.13 * u, wr[1] - 0.02 * u)])
        return ly
    near_arm = arm(-stride * 1.1, -1)
    far_arm = arm(stride * 1.0, 3)
    out = [body, front_leg, back_leg, near_arm, far_arm]
    if p.get("bag"):
        el = near_arm.loops[1]
        wx = min(x for x, y in el)
        bag = Layer(-2, [[(wx - 0.6 * u, H - 5.05 * u), (wx + 0.5 * u, H - 5.05 * u),
                          (wx + 0.45 * u, H - 4.1 * u), (wx - 0.55 * u, H - 4.1 * u)]])
        out.append(bag)
    return out


# -- trees and plants ---------------------------------------------------------------------------
@generator("tree")
def tree(p, rnd):
    """Deciduous tree. style 'bare' (winter: branching lines), 'canopy' (scalloped crown with
    foliage strokes) or 'conifer'. Options: height, spread (crown width / height), depth
    (branching levels), trunk (diameter)."""
    H = _len(p.get("height"), 300)
    style = p.get("style", "bare")
    if style == "conifer":
        return _conifer(H, p, rnd)
    trunk_d = _len(p.get("trunk"), H / 28.0)
    if style == "canopy":
        return _canopy(H, trunk_d, p, rnd)
    return _bare(H, trunk_d, p, rnd)


def _branch(rnd, p0, ang, length, width, depth, max_depth, card, lines, min_card):
    p1 = (p0[0] + math.sin(ang) * length, p0[1] + math.cos(ang) * length)
    if width >= min_card:
        card.append(limb(p0, p1, width / 2, width * 0.36, 4))
    else:
        mid = ((p0[0] + p1[0]) / 2 + (rnd.random() - 0.5) * 0.08 * length,
               (p0[1] + p1[1]) / 2 + (rnd.random() - 0.5) * 0.08 * length)
        lines.append([p0, mid, p1])
    if depth >= max_depth:
        for k in range(rnd.choice((2, 3))):
            a = ang + (rnd.random() - 0.5) * 1.1
            l2 = length * (0.35 + 0.2 * rnd.random())
            lines.append([p1, (p1[0] + math.sin(a) * l2, p1[1] + math.cos(a) * l2)])
        return
    n = 3 if rnd.random() < 0.25 else 2
    for i in range(n):
        side = -1 if i == 0 else 1
        spread = math.radians(18 + 22 * rnd.random())
        a = ang * 0.82 + side * spread + (math.radians(rnd.uniform(-10, 10)) if i == 2 else 0)
        _branch(rnd, p1, a, length * rnd.uniform(0.66, 0.8), width * 0.66, depth + 1, max_depth,
                card, lines, min_card)


def _bare(H, trunk_d, p, rnd):
    depth = int(p.get("depth", 6))
    h0 = H * float(p.get("clear", 0.32))
    card, lines = [], []
    lean = math.radians(rnd.uniform(-4, 4))
    top = (math.sin(lean) * h0, h0)
    card.append([(-trunk_d * 0.65, 0), (trunk_d * 0.65, 0), (trunk_d * 0.5, trunk_d * 0.6),
                 (top[0] + trunk_d * 0.38, top[1]), (top[0] - trunk_d * 0.38, top[1]), (-trunk_d * 0.5, trunk_d * 0.6)])
    L0 = (H - h0) * 0.3
    bcard, blines = [], []
    for side in (-1, 1):
        a = lean + side * math.radians(rnd.uniform(14, 28))
        _branch(rnd, top, a, L0 * rnd.uniform(0.9, 1.05), trunk_d * 0.72, 1, depth, bcard, blines,
                min_card=trunk_d * 0.22)
    # scale the branching about the fork so the tree is exactly H tall
    y_max = max(y for pl in bcard + blines for x, y in pl)
    k = (H - h0) / max(y_max - h0, 1e-9)
    f = lambda q: (top[0] + (q[0] - top[0]) * k, h0 + (q[1] - h0) * k)
    card += [[f(q) for q in pl] for pl in bcard]
    lines += [[f(q) for q in pl] for pl in blines]
    # bark lines on the trunk
    lines.append([(-trunk_d * 0.1, trunk_d * 0.4), (top[0] - trunk_d * 0.05, h0 * 0.8)])
    return [Layer(0, card, lines)]


def _canopy(H, trunk_d, p, rnd):
    spread = float(p.get("spread", 0.62))
    cy = H * 0.6
    rx, ry = H * spread / 2, H * 0.4
    crown = scallops((0, cy), rx, ry, int(p.get("bumps", 24)), 0.22, rnd)
    texture = []
    n = int(p.get("strokes", 70))
    tries = 0
    while len(texture) < n and tries < n * 20:
        tries += 1
        x = rnd.uniform(-rx, rx)
        y = rnd.uniform(cy - ry, cy + ry)
        # more strokes on the shaded (right, lower) side
        if (x / rx - (y - cy) / ry) < rnd.uniform(-1.6, 1.4):
            continue
        if ((x / rx) ** 2 + ((y - cy) / ry) ** 2) > 0.8:
            continue
        w = H * rnd.uniform(0.035, 0.06)
        texture.append(cup(x, y, w, w * 0.35, rnd.uniform(-0.4, 0.4)))
    crown_ly = Layer(0, [crown], texture)
    trunk = Layer(1, [[(-trunk_d * 0.7, 0), (trunk_d * 0.7, 0), (trunk_d * 0.45, trunk_d),
                       (trunk_d * 0.4, cy), (-trunk_d * 0.4, cy), (-trunk_d * 0.5, trunk_d)]])
    branch_lines = []
    y_b = cy - ry * 0.75
    for side in (-1, 1):
        a = side * math.radians(rnd.uniform(25, 40))
        L = ry * 0.6
        branch_lines.append([(side * trunk_d * 0.3, y_b), (math.sin(a) * L, y_b + math.cos(a) * L)])
    trunk.lines.extend(branch_lines)
    return [crown_ly, trunk]


def _conifer(H, p, rnd):
    W = H * float(p.get("spread", 0.36))
    tiers = int(p.get("tiers", 6))
    trunk_d = H / 30.0
    base = H * 0.12
    pts_l = [(0.0, H)]
    for i in range(tiers):
        f = (i + 1) / float(tiers)
        y = H - (H - base) * f
        w = W / 2 * f
        pts_l.append((-w * 0.62, y + (H - base) / tiers * 0.35))
        pts_l.append((-w * rnd.uniform(0.95, 1.05), y))
    pts_l.append((-trunk_d / 2, base))
    outline = pts_l + [(-x, y) for x, y in reversed(pts_l[1:])]
    lines = []
    for i in range(1, tiers):
        f = (i + 1) / float(tiers)
        y = H - (H - base) * f
        w = W / 2 * f * 0.55
        lines.append([(-w, y + rnd.uniform(0, 3)), (0, y - H * 0.015), (w, y + rnd.uniform(0, 3))])
    trunk = Layer(1, [[(-trunk_d * 0.6, 0), (trunk_d * 0.6, 0), (trunk_d / 2, base + 4), (-trunk_d / 2, base + 4)]])
    return [Layer(0, [outline], lines), trunk]


@generator("shrub")
def shrub(p, rnd):
    """Low scalloped mound. Options: height, width, strokes."""
    h = _len(p.get("height"), 36)
    w = _len(p.get("width"), h * 1.6)
    top = scallops((0, 0), w / 2, h, int(p.get("bumps", 11)), 0.25, rnd, start=0.0, end=math.pi)
    outline = top + [(-w / 2 * 0.92, 0), (w / 2 * 0.92, 0)]
    strokes = []
    n = int(p.get("strokes", 18))
    tries = 0
    while len(strokes) < n and tries < n * 20:
        tries += 1
        x, y = rnd.uniform(-w / 2, w / 2), rnd.uniform(0, h)
        if (x / (w / 2)) ** 2 + (y / h) ** 2 > 0.7 or y < h * 0.1:
            continue
        s = h * rnd.uniform(0.12, 0.2)
        strokes.append(cup(x, y, s, s * 0.35, rnd.uniform(-0.4, 0.4)))
    return [Layer(0, [outline], strokes)]


@generator("custom")
def custom(p, rnd):
    """Captured figure: {"layers": [{"depth": 0, "loops": [[[x, y], ...]], "lines": [...]}]} or
    the short form {"loops": [...], "lines": [...]} (one layer). Inches, y up from the ground."""
    pt = lambda q: (_len(q[0], 0), _len(q[1], 0))
    specs = p.get("layers") or [{"depth": 0, "loops": p.get("loops", []), "lines": p.get("lines", [])}]
    k = float(p.get("scale", 1.0))
    out = []
    for s in specs:
        out.append(Layer(s.get("depth", 0),
                         [[(x * k, y * k) for x, y in map(pt, lp)] for lp in s.get("loops", [])],
                         [[(x * k, y * k) for x, y in map(pt, ln)] for ln in s.get("lines", [])]))
    return out


# -- entry point --------------------------------------------------------------------------------
def build(defn, seed=None, **overrides):
    """Layers of a library entry; `seed` / overrides (height, pose, ...) win over the entry."""
    p = dict(defn)
    p.update(dict((k, v) for k, v in overrides.items() if v is not None))
    fn = GENERATORS.get(p.get("generator", "custom"))
    if fn is None:
        raise ValueError("Unknown entourage generator '{}'. Known: {}".format(
            p.get("generator"), ", ".join(sorted(GENERATORS))))
    rnd = random.Random(int(seed if seed is not None else p.get("seed", 1)))
    layers = [ly for ly in fn(p, rnd) if ly.loops or ly.lines]
    for ly in layers:
        ly.loops = [[(round(x, 3), round(y, 3)) for x, y in lp] for lp in ly.loops if len(lp) >= 3]
        ly.lines = [[(round(x, 3), round(y, 3)) for x, y in ln] for ln in ly.lines if len(ln) >= 2]
    return sorted(layers, key=lambda ly: -ly.depth)       # far to near


def bounds(layers):
    xs = [x for ly in layers for lp in ly.loops + ly.lines for x, y in lp]
    ys = [y for ly in layers for lp in ly.loops + ly.lines for x, y in lp]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)


def count(layers):
    return {"layers": len(layers), "loops": sum(len(ly.loops) for ly in layers),
            "lines": sum(len(ly.lines) for ly in layers)}
