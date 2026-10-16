"""MCPanel: open the Mind Canvas panel (a floating window with every tool; see eto/panel.py)."""

from . import ui


def run():
    from ..eto import panel
    panel.open_panel(ui.doc())
    return ui.Result.Success
