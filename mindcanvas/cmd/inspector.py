"""MCInspector: open the inspector, a floating window that follows the selection (see
eto/inspector.py), and turn on double-click editing of assemblies and the viewport handles /
hover labels (unless MCHandles turned them off in this session)."""

from . import ui


def run():
    from ..eto import inspector
    from ..viewport import overlay
    inspector.enable_double_click()
    if overlay.state()["hooks"] is None and not overlay.state().get("off"):
        overlay.enable(True, True)
    inspector.open_inspector()
    return ui.Result.Success
