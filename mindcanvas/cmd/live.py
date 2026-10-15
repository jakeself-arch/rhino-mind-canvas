"""MCLive: toggle automatic rebuilding when driver curves are edited."""

from .. import live
from . import ui


def run():
    on = live.toggle()
    ui.say("Mind Canvas live update is {}.".format("ON" if on else "OFF"))
    return ui.Result.Success
