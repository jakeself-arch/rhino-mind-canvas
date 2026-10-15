"""Curtain walls (phase 5): a horizontal driver curve becomes a faceted grid of mullions,
transoms and infill panels.

    settings.py   defaults <- assembly <- driver params; joint styles; profiles
    grid.py       the layout: runs, grid points (vertices), bays, rows, cells, infill types
    sections.py   2D member sections per joint style (plan at a vertical, section at a
                  horizontal), in (a, q): a across the member, q depth from the glass face
    build.py      3D members (block instances), glass, spandrels, anchors, perimeter seals

The kind module is mindcanvas/kinds/curtainwall.py.
"""
