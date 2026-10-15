#! python3
"""Register every commands/MC*.py script as a Rhino command alias.

Run once in Rhino: _RunPythonScript, pick this file (or drag it onto Rhino).
Afterwards type MCWall, MCEdit, ... like any Rhino command. Re-run after
adding new command scripts.
"""

import os

import Rhino

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMANDS = os.path.join(ROOT, "commands")


def install():
    aliases = Rhino.ApplicationSettings.CommandAliasList
    added = []
    for name in sorted(os.listdir(COMMANDS)):
        if not (name.startswith("MC") and name.endswith(".py")):
            continue
        alias = name[:-3]
        macro = '! _-RunPythonScript "{}"'.format(os.path.join(COMMANDS, name))
        if aliases.IsAlias(alias):
            aliases.SetMacro(alias, macro)
        else:
            aliases.Add(alias, macro)
        added.append(alias)
    Rhino.RhinoApp.WriteLine("Mind Canvas commands installed: " + ", ".join(added))
    return added


if __name__ == "__main__":
    install()
