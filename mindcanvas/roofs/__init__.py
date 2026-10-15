"""Roofs (phase 6): a closed horizontal boundary (the plate line = outside face of the wall framing)
+ a shape (flat / shed / gable) + a layer stack on the roof plane + an optional ceiling stack.

    shape.py   settings (DEFAULTS <- assembly <- params), faces: per roof plane a local frame
               (x = uphill slope direction, y = ridge direction), the overhang footprint, the
               rafter bottom line and the layer lines
    build.py   Builder: rafters (birdsmouth), ridge, barge rafters, lookouts, ceiling joists,
               layers (shingle courses, ice shield, tapered insulation), eave + rake trim
               (fascia, sub-fascia, soffit + vent, drip edge, gutter, rake board, bird blocks)

The kind lives in mindcanvas/kinds/roof.py.
"""
