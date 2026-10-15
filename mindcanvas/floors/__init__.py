"""Floors (phase 6): a closed horizontal boundary + a layer stack (top -> bottom).

    joists.py   joist systems, member selection, JoistLayout (direction, positions, segments)
    build.py    layer builders: solid / membrane / void slabs, joists (rim, joists, blocking,
                bridging, cavity fill), composite metal deck

The kind lives in mindcanvas/kinds/floor.py. Roofs reuse joists.select_member / system and the
ceiling joists of a roof's ceiling stack use JoistLayout-like code in mindcanvas/roofs.
"""
