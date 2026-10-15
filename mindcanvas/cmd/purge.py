"""MCPurge: delete orphaned parts (driver gone) and unused Mind Canvas blocks."""

from .. import docutil, engine
from . import ui


def run():
    doc = ui.doc()
    orphans = engine.orphan_parts(doc)
    for o in orphans:
        doc.Objects.Delete(o, True)
    blocks = docutil.purge_unused_blocks(doc)
    ui.say("Removed {} orphaned parts and {} unused block definitions.".format(len(orphans), blocks))
    doc.Views.Redraw()
    return ui.Result.Success
