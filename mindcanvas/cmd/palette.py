"""MCPalette: the assembly palette, a floating window of drawn tiles (eto/palette.py). Click a tile:
it is what the next wall / floor / window ... will be, and the selected assemblies of its kind take
it; double-click: the visual assembly editor; Paint...: click assemblies to give them the tile."""

from . import ui


def run():
    from ..eto import palette
    palette.open_palette()
    return ui.Result.Success
