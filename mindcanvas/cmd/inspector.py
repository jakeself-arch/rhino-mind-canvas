"""MCInspector: open the inspector, a floating window that follows the selection (see
eto/inspector.py), and turn on double-click editing of assemblies."""

from . import ui


def run():
    from ..eto import inspector
    inspector.enable_double_click()
    inspector.open_inspector()
    return ui.Result.Success
