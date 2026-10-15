"""Openings (windows, doors) hosted by assemblies.

    core.py     opening drivers, params, placement in a host (Opening records), cutters
    geom.py     section sweeps and mitered frame members shared by units and components
    units.py    window / door unit geometry, trim, sill pan, head drip (built with the host)

A host kind (walls today; curtain walls, floors and roofs later) resolves its openings into
`ctx.openings` while building its context. Components cut themselves with
`core.cut(ctx, breps, band)` or read the Opening records directly (framing, masonry).
"""

from .core import (DEFAULTS, Opening, create, cut, hosted, is_opening, merged_type, resolve,  # noqa: F401
                   sync_from_geometry, type_names)
