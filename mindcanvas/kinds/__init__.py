"""Assembly kinds. Each kind module provides:

    DEFAULTS                       default driver params
    make_context(doc, lib, driver_obj, assembly_name, params) -> BuildContext
    build(ctx) -> list[Part]

A kind with HOSTED = True (openings) has no parts of its own: building it builds its host
(host_of(doc, obj)).
"""

from . import curtainwall, opening, wall

KINDS = {
    "wall": wall,
    "opening": opening,
    "curtain_wall": curtainwall,
}


def get(kind):
    mod = KINDS.get(kind)
    if mod is None:
        raise KeyError("Unknown assembly kind '{}'".format(kind))
    return mod
