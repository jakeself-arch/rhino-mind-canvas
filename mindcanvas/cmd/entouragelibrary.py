"""MCEntourageLibrary: the entourage library window, a picture of every 3D model (people, trees,
vehicles, furniture ...). Click a picture: MCEntourage places it next; double-click: place it now
(eto/entourage.py)."""

from . import ui


def run():
    from ..eto import entourage
    entourage.open_library()
    return ui.Result.Success
