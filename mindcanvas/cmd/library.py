"""MCLibrary: reload the library, list its contents and open its folder."""

import System

from .. import library
from . import ui


def run():
    lib = library.get(force_reload=True)
    for section in library.SECTIONS:
        ui.say("{:<11} {}".format(section, len(lib.data[section])))
    for kind in sorted(set(a.get("kind", "wall") for a in lib.data["assemblies"].values())):
        ui.say("{} assemblies:".format(kind))
        for n in lib.assemblies(kind):
            ui.say("  " + n)
    for w in lib.warnings:
        ui.say("warning: " + w)
    System.Diagnostics.Process.Start("explorer.exe", library.LIBRARY_DIR)
    return ui.Result.Success
