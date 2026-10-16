"""Joins between assemblies (Phase 7).

    plan.py   pure 2D rules: where each layer of a wall end stops at an L or T join
    find.py   detection in the document: walls meeting walls (L / T), walls under / over floors,
              walls under roofs; fills ctx.joins (walls), ctx.join_insets (floors), roof wall
              dimensions; ctx.join_partners = ids of the assemblies to rebuild with this one
    geom.py   geometry: joined layer outlines and solids, T notches, roof infill over walls

Joins are found from the drivers alone (curves, stacks, params), never from generated parts, so
any build order gives the same result. engine.build rebuilds the partners of a driver after it.
"""


def attach_wall(ctx, driver_obj):
    from . import find
    find.attach_wall(ctx, driver_obj)


def attach_floor(ctx, driver_obj):
    from . import find
    find.attach_floor(ctx, driver_obj)


def attach_roof(ctx, driver_obj):
    from . import find
    find.attach_roof(ctx, driver_obj)
