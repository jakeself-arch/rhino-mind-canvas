"""Rhino Mind Canvas - parametric building assemblies for Rhino 8.

Package layout:
    units      - inch <-> model-unit conversion
    library    - assembly definitions loaded from library/*.json
    meta       - user-text metadata linking drivers to generated parts
    docutil    - layers, materials, groups, baking
    geo        - shared geometry helpers (offsets, regions, boxes)
    wall/floor/roof - assembly generators
    engine     - build / rebuild dispatch
    live       - event watcher that rebuilds when a driver curve is edited
    schedule   - material quantity takeoff
"""

__version__ = "0.1.0"
