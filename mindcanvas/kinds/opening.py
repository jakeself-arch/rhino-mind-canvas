"""Openings (windows, doors) as a driver kind.

An opening driver has no parts of its own: its unit, trim and every cut belong to the host
assembly, so engine.build(opening) re-reads the opening's line (moved / scaled by the user) and
rebuilds the host. See mindcanvas/openings/core.py for the params.
"""

from ..openings import core

HOSTED = True
DEFAULTS = {}


def host_of(doc, obj):
    return core.host_of(doc, obj)


def sync(doc, obj, host):
    return core.sync_from_geometry(doc, obj, host)


def make_context(doc, lib, driver_obj, assembly_name, params):
    raise TypeError("Openings are built with their host.")


def build(ctx):
    raise TypeError("Openings are built with their host.")
