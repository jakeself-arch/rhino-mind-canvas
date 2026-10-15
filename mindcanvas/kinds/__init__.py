"""Assembly kinds. Each kind module provides:

    DEFAULTS                       default driver params
    make_context(doc, lib, driver_obj, assembly_name, params) -> BuildContext
    build(ctx) -> list[Part]
"""

from . import wall

KINDS = {
    "wall": wall,
}


def get(kind):
    mod = KINDS.get(kind)
    if mod is None:
        raise KeyError("Unknown assembly kind '{}'".format(kind))
    return mod
