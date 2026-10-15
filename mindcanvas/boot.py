"""Entry point used by the scripts in commands/.

    import mindcanvas.boot as b; b.run("wall")

Reloads the package first in dev mode (a `.dev` file in the project root),
then runs mindcanvas.cmd.<name>.run() and reports errors on the command line.
"""

import importlib
import traceback

import Rhino


def run(name):
    from mindcanvas import dev
    dev.maybe_reload()
    try:
        mod = importlib.import_module("mindcanvas.cmd." + name)
        return mod.run()
    except Exception as ex:
        Rhino.RhinoApp.WriteLine("Mind Canvas error: {}".format(ex))
        print(traceback.format_exc())
        return Rhino.Commands.Result.Failure
