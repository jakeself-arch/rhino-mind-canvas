"""MCSetup: prepare the document for assembly-level detail."""

from .. import engine, live
from . import ui


def run():
    doc = ui.doc()
    engine.setup_document(doc)
    ui.say("Mind Canvas: absolute tolerance set to {:.6g} {} (= 0.001\").".format(
        doc.ModelAbsoluteTolerance, doc.ModelUnitSystem))
    if not live.is_on():
        live.enable()
        ui.say("Live update is ON (MCLive toggles it).")
    try:
        from ..eto import inspector
        inspector.enable_double_click()
        ui.say("Double-click an assembly to edit it (MCInspector opens the inspector).")
    except Exception as ex:
        ui.say("Double-click editing skipped: {}".format(ex))
    try:
        from ..viewport import overlay
        if not overlay.is_on():
            overlay.enable(True, True)
        ui.say("Drag the arrows on a selected assembly; rest the mouse on one for its label (MCHandles).")
    except Exception as ex:
        ui.say("Viewport handles skipped: {}".format(ex))
    try:
        from ..drawing import displaymode, patterns
        patterns.ensure(doc)
        displaymode.ensure()
        ui.say("Hatch patterns and the '{}' display mode are ready (MCDisplaySetup).".format(displaymode.NAME))
    except Exception as ex:
        ui.say("Drawing setup skipped: {}".format(ex))
    return ui.Result.Success
