"""Junction lines where solids of different materials interpenetrate (a slab run
into a wall). The HLD only draws each object's own edges, so these are missing
otherwise. Off by default: assemblies should not overlap, and the BrepBrep
pass is the most expensive step (style "junction": {"on": true, "max_pairs"}).
"""

import Rhino
from Rhino.Geometry.Intersect import Intersection

G = Rhino.Geometry


def lines(scene, items, tol, max_pairs=3000, cancel=None):
    """World polylines [(pts, item)] of intersections between non-block parts."""
    cands = [it for it in items if not it.block and not it.small and not it.ground]
    cands.sort(key=lambda it: it.bbox.Min.X)
    out, pairs = [], 0
    for i, a in enumerate(cands):
        if cancel is not None:
            cancel.check()
        for b in cands[i + 1:]:
            if b.bbox.Min.X > a.bbox.Max.X + tol:
                break
            if a.material == b.material:
                continue
            ix = G.BoundingBox.Intersection(a.bbox, b.bbox)
            if not ix.IsValid:
                continue
            pairs += 1
            if pairs > max_pairs:
                return out, pairs
            ba, bb = scene.world_brep(a), scene.world_brep(b)
            if ba is None or bb is None:
                continue
            rc, crvs, pts = Intersection.BrepBrep(ba, bb, tol)
            for c in (crvs or []) if rc else []:
                pc = c.ToPolyline(tol, 0.05, 0.0, 0.0)
                if pc is not None:
                    out.append((list(pc.ToPolyline()), a))
    return out, pairs
