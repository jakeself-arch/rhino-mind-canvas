"""Development helpers: hot-reload the package inside a running Rhino.

Rhino keeps imported modules alive between script runs, so edits to the
package are not seen until the modules are dropped. Commands call
maybe_reload(), which reloads when a `.dev` file exists in the project root.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def dev_mode():
    return os.path.exists(os.path.join(ROOT, ".dev"))


def reload_all():
    """Drop every mindcanvas module so the next import reads fresh code.
    Live mode is switched off and back on so event handlers use new code."""
    ensure_path()
    was_live = False
    live = sys.modules.get("mindcanvas.live")
    if live is not None:
        try:
            was_live = live.is_on()
            live.disable()
        except Exception:
            pass
    for name in list(sys.modules):
        if name == "mindcanvas" or name.startswith("mindcanvas."):
            del sys.modules[name]
    if was_live:
        import mindcanvas.live
        mindcanvas.live.enable()


def maybe_reload():
    if dev_mode():
        reload_all()


def ensure_path():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
