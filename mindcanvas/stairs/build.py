"""Stair geometry: the side curve -> plan samples (inches) -> stair.plan.Layout -> closed solids.

Each piece of a layout (the whole stair, or one plate per tread for open stairs) is built as ONE
watertight mesh over its cuts - tread tops, risers, the underside, both sides, the start and end
faces - and turned into a Brep with its coplanar faces merged, so a straight flight has one
sawtooth face per side and cuts cleanly in sections. Vertical edges are split at every height used
on that vertical line, so faces always meet edge to edge (no T-junctions).

Curved stairs: the piece is built a little WIDER than the stair, on the cuts that matter only
(treads, landings, a sample every 20 degrees: Layout.coarse / extended), and intersected with the
true band between the curve and its offset (band()), so the sides and the plan edges of the treads
are the real curves (one smooth face per side) instead of facets.

Closed curves (a stair wrapping an elevator): path_pieces() starts at the curve's seam and walks it
`laps` times (fractions allowed); the plan overlaps itself, each lap higher.
"""

import math

import Rhino

from . import plan

G = Rhino.Geometry
SMOOTH_DEG = 15.0         # corners of the stair line sharper than this get a landing
FACET_IN = 6.0            # curved flights: one sample per 6" of side line (8 at least)


def _unit(v):
    v = G.Vector3d(v.X, v.Y, 0.0)
    v.Unitize()
    return v


def _angle(a, b):
    return math.degrees(G.Vector3d.VectorAngle(_unit(a), _unit(b)))


def _pieces(curve):
    """The curve split at its G1 kinks."""
    from .. import geo
    ts = geo.kink_parameters(curve)
    if not ts:
        return [curve]
    # Trim between the kinks (Split merges the pieces on both sides of a closed curve's seam)
    ps = [curve.Domain.T0] + sorted(ts) + [curve.Domain.T1]
    out = [curve.Trim(a, b) for a, b in zip(ps, ps[1:]) if b - a > 1e-9]
    return [p for p in out if p is not None] or [curve]


def _samples(piece, s, tol):
    if piece.IsLinear(tol):
        ts = [piece.Domain.T0, piece.Domain.T1]
    else:
        n = max(8, int(math.ceil(piece.GetLength() / (FACET_IN * s))))
        ts = list(piece.DivideByCount(n, True))
        if abs(ts[-1] - piece.Domain.T1) > 1e-12:     # closed curves leave out their end (= start)
            ts.append(piece.Domain.T1)
    out = []
    for t in ts:
        p, d = piece.PointAt(t), _unit(piece.TangentAt(t))
        out.append((p.X / s, p.Y / s, d.X, d.Y))
    return out


def path_pieces(curve, laps=1.0):
    """The curve split at its kinks; a closed curve repeated `laps` times (the last lap partial)."""
    pieces = _pieces(curve)
    if not curve.IsClosed:
        return pieces
    laps = max(float(laps or 1.0), 1e-3)
    out = []
    whole = int(math.floor(laps + 1e-9))
    for _ in range(whole):
        out += [p.DuplicateCurve() for p in pieces]
    rest = (laps - whole) * curve.GetLength()
    for p in pieces:
        if rest <= 1e-9:
            break
        L = p.GetLength()
        if L <= rest + 1e-9:
            out.append(p.DuplicateCurve())
            rest -= L
            continue
        ok, t = p.LengthParameter(rest)
        out.append(p.Trim(p.Domain.T0, t))
        break
    return out


def segments(curve, s, tol, laps=1.0):
    """[[(x, y, dx, dy), ...]] in inches along the path, split where it turns more than SMOOTH_DEG."""
    segs = []
    prev = None
    for piece in path_pieces(curve, laps):
        smp = _samples(piece, s, tol)
        if prev is not None and _angle(prev.TangentAtEnd, piece.TangentAtStart) < SMOOTH_DEG:
            x, y, dx0, dy0 = segs[-1][-1]
            dx, dy = dx0 + smp[0][2], dy0 + smp[0][3]
            L = math.hypot(dx, dy)
            segs[-1][-1] = (x, y, dx / L, dy / L)
            segs[-1].extend(smp[1:])
        else:
            segs.append(smp)
        prev = piece
    return segs


def is_curved(curve, tol):
    return any(not p.IsLinear(tol) for p in _pieces(curve))


class _Mesher(object):
    """Vertices are identified by (point id, height): the point id is a cut end ("c" / "o", the
    first of the consecutive cuts sharing that point), so flights that touch (a U stair without a
    gap) keep their own vertices."""

    def __init__(self, s, base_z, origin):
        self.s, self.base_z, self.origin = s, base_z, origin
        self.keys = {}
        self.pts = []
        self.faces = []
        self.zs = {}            # point id -> heights used on its vertical line

    def v(self, p, z):
        pid, xy = p
        k = (pid, round(z, 5))
        i = self.keys.get(k)
        if i is None:
            i = self.keys[k] = len(self.pts)
            self.pts.append((xy[0], xy[1], z))
            self.zs.setdefault(pid, set()).add(round(z, 5))
        return i

    def poly(self, idx):
        out = []
        for i in idx:
            if i not in out:
                out.append(i)
        if len(out) >= 3:
            self.faces.append(out)

    def ladders(self, todo):
        """Vertical faces between two vertical edges (pa, za0..za1), (pb, zb0..zb1); call after
        every other face so each edge is split at all heights on its line."""
        for pa, za0, za1, pb, zb0, zb1 in todo:
            if pa[0] == pb[0]:
                continue
            A = [z for z in sorted(self.zs.get(pa[0], ())) if za0 - 1e-5 <= z <= za1 + 1e-5]
            B = [z for z in sorted(self.zs.get(pb[0], ())) if zb0 - 1e-5 <= z <= zb1 + 1e-5]
            if not A or not B or (len(A) < 2 and len(B) < 2):
                continue
            i = j = 0
            while i < len(A) - 1 or j < len(B) - 1:
                if i < len(A) - 1 and (j == len(B) - 1 or A[i + 1] <= B[j + 1]):
                    self.poly([self.v(pa, A[i]), self.v(pb, B[j]), self.v(pa, A[i + 1])])
                    i += 1
                else:
                    self.poly([self.v(pa, A[i]), self.v(pb, B[j]), self.v(pb, B[j + 1])])
                    j += 1

    def mesh(self):
        m = G.Mesh()
        s, o = self.s, self.origin
        for x, y, z in self.pts:
            m.Vertices.Add(o.X + x * s, o.Y + y * s, self.base_z + z * s)
        for f in self.faces:
            if len(f) == 3:
                m.Faces.AddFace(f[0], f[1], f[2])
            elif len(f) == 4:
                m.Faces.AddFace(f[0], f[1], f[2], f[3])
            else:
                for k in range(1, len(f) - 1):
                    m.Faces.AddFace(f[0], f[k], f[k + 1])
        return m


def _point_ids(lay, js, side, pts=None):
    """(id, xy) per cut j in js of one side; consecutive cuts at the same point share an id."""
    out = []
    for j in js:
        p = pts[j][0 if side == "c" else 1] if pts else getattr(lay.cuts[j], side)
        if out and plan._same(out[-1][1], p):
            out.append(out[-1])
        else:
            out.append(((side, j), p))
    return out


def piece_mesh(lay, js, bottoms, s, base_z, pts=None, origin=None):
    """Closed mesh of the cells between the cuts js (bottoms: {cut index: z above the base},
    inches; pts: {cut index: (c, o)} in place of the cuts' own ends)."""
    return piece_faces(lay, js, bottoms, pts, s, base_z, origin or G.Point3d(0, 0, 0)).mesh()


def piece_faces(lay, js, bottoms, pts=None, s=1.0, base_z=0.0, origin=None):
    """The _Mesher (vertices in inches + faces) of piece_mesh; no Rhino geometry is made."""
    M = _Mesher(s, base_z, origin)
    C, O = _point_ids(lay, js, "c", pts), _point_ids(lay, js, "o", pts)
    top = lambda k: lay.top(js[k])            # cell k: between js[k] and js[k + 1]
    bot = lambda k: bottoms[js[k]]
    todo = []
    n = len(js) - 1
    for k in range(n):
        t = top(k)
        C0, C1, O0, O1 = C[k], C[k + 1], O[k], O[k + 1]
        M.poly([M.v(C0, t), M.v(C1, t), M.v(O1, t), M.v(O0, t)])
        M.poly([M.v(C0, bot(k)), M.v(O0, bot(k)), M.v(O1, bot(k + 1)), M.v(C1, bot(k + 1))])
        todo.append((C0, bot(k), t, C1, bot(k + 1), t))
        todo.append((O0, bot(k), t, O1, bot(k + 1), t))
        if k > 0 and abs(top(k - 1) - t) > 1e-9:
            lo, hi = sorted((top(k - 1), t))
            M.v(C0, lo), M.v(O0, lo)
            todo.append((C0, lo, hi, O0, lo, hi))
    todo.append((C[0], bot(0), top(0), O[0], bot(0), top(0)))
    todo.append((C[-1], bot(n), top(n - 1), O[-1], bot(n), top(n - 1)))
    M.ladders(todo)
    return M


def band(curve, sigma, width_model, z0, z1, tol):
    """The true stair band: the region between the path curve (one lap) and its offset by the width
    toward the stair, extruded from z0 to z1 (open curves extended at both ends so the stair's own
    start / end faces make the ends)."""
    from .. import geo
    c = curve.DuplicateCurve()
    if not c.IsClosed:
        e = c.Extend(G.CurveEnd.Both, width_model, G.CurveExtensionStyle.Line)
        c = e or c
    return geo.band_solids(c, 0.0, sigma * width_model, z0, z1 - z0, tol)


def trimmed(brep, bands, tol):
    """brep intersected with the band solid(s); None when the Boolean fails."""
    try:
        res = G.Brep.CreateBooleanIntersection([brep], list(bands), tol)
    except Exception:
        return None
    if not res or not all(r.IsSolid for r in res):
        return None
    out = []
    for r in res:
        r.MergeCoplanarFaces(tol)
        if r.SolidOrientation == G.BrepSolidOrientation.Inward:
            r.Flip()
        out.append(r)
    return out


def solid(mesh, tol):
    """Brep of a closed mesh with its coplanar faces merged (the mesh itself if that fails)."""
    mesh.Normals.ComputeNormals()
    mesh.UnifyNormals()
    if not mesh.IsClosed:
        return mesh, False
    vmp = G.VolumeMassProperties.Compute(mesh)
    if vmp is not None and vmp.Volume < 0:
        mesh.Flip(True, True, True)
    brep = G.Brep.CreateFromMesh(mesh, True)
    if brep is None:
        return mesh, False
    brep.MergeCoplanarFaces(tol)
    if not brep.IsSolid:
        return mesh, False
    if brep.SolidOrientation == G.BrepSolidOrientation.Inward:
        brep.Flip()
    return brep, True
