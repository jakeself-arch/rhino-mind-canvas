"""MCAssemblyEditor: edit library assemblies in a dialog (layers, materials, thickness, options,
settings), save them as new assemblies and apply them to the selected walls / floors / roofs /
curtain walls. The window stays open while you work: "Apply to selected" uses the assemblies
selected at that moment. Opens on the assembly of the first selected one."""

from .. import library
from . import ui


def run():
    from ..eto import editor
    doc = ui.doc()
    lib = library.get()
    ed = editor.AssemblyEditor(doc, lib, drivers=editor.selected_drivers(doc))
    ed.show()
    return ui.Result.Success
