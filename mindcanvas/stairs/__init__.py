"""Stairs: one side of the plan boundary + the floor-to-floor height.

    plan.py    pure-Python layout: flights, corner landings, risers from the height, treads fitted
               to the curve, levels per cell, undersides per style (testable without Rhino)
    build.py   the curve -> plan samples, layout pieces -> watertight meshes -> closed Breps

The kind lives in mindcanvas/kinds/stair.py.
"""
