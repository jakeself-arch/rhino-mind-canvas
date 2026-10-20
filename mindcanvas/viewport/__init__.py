"""Editing in the viewport: drag handles on the selected assemblies, hover labels, ghost previews.

    shapes.py    what an assembly looks like to the viewport tools (outline, handles, label): pure
                 geometry from the drivers, no drawing, no events (testable without clicks)
    overlay.py   the display conduit (handles, drag ghost + dimension tag, hover outline + label) and
                 the mouse callback (hover pick, handle hit test, drag, apply on release)
    ghost.py     previews for the placing commands (MCOpening's rough opening, MCWall's band)
"""
