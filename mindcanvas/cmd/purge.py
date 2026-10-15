"""MCPurge: delete orphaned parts (driver gone), openings whose wall is gone, and unused
Mind Canvas blocks."""

from .. import docutil, engine
from . import ui


def run():
    doc = ui.doc()
    orphans = engine.orphan_parts(doc)
    for o in orphans:
        doc.Objects.Delete(o, True)
    lost = engine.orphan_openings(doc)
    for o in lost:
        doc.Objects.Delete(o, True)
    blocks = docutil.purge_unused_blocks(doc)
    ui.say("Removed {} orphaned parts, {} orphaned openings and {} unused block definitions.".format(
        len(orphans), len(lost), blocks))
    doc.Views.Redraw()
    return ui.Result.Success
