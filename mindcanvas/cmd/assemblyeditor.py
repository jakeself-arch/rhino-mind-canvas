"""MCAssemblyEditor: edit library assemblies in a window (Phase 12: the visual editor): a drawn
section of the layer stack (click to select, drag to reorder, drag a boundary to change a
thickness), typed fields for the layer and its options, the assembly's settings, a live preview
sample in the model; save as new assemblies and apply them to the selected walls / floors / roofs /
curtain walls. The window stays open while you work: "Apply to selected" uses the assemblies
selected at that moment. Opens on the assembly of the first selected one. Its "List editor..."
button opens the Phase 8 list editor."""

from .. import library
from . import ui


def run():
    from ..eto import editor, visual
    doc = ui.doc()
    lib = library.get()
    ed = visual.VisualAssemblyEditor(doc, lib, drivers=editor.selected_drivers(doc))
    ed.show()
    return ui.Result.Success
