#! python3
"""Register every commands/MC*.py script as a Rhino command alias, plus the short aliases in
tools/aliases.json (I = MCInspector, MT = MCMatch, WA = MCWall, ...).

Run once in Rhino: _RunPythonScript, pick this file (or drag it onto Rhino).
Afterwards type MCWall, MCEdit, ... like any Rhino command. Re-run after
adding new command scripts or editing aliases.json. A short alias that already
runs something else (yours or Rhino's) is left alone and reported.
"""

import json
import os

import Rhino

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMANDS = os.path.join(ROOT, "commands")
SHORT = os.path.join(ROOT, "tools", "aliases.json")


def _set(aliases, alias, macro):
    if aliases.IsAlias(alias):
        aliases.SetMacro(alias, macro)
    else:
        aliases.Add(alias, macro)


def _macro(command):
    return '! _-RunPythonScript "{}"'.format(os.path.join(COMMANDS, command + ".py"))


def install_short(aliases, commands):
    """Short aliases -> the same macro as their MC command. Returns (added, skipped [(alias,
    existing macro)])."""
    try:
        with open(SHORT) as f:
            short = json.load(f)
    except (IOError, ValueError) as ex:
        Rhino.RhinoApp.WriteLine("Mind Canvas: could not read {}: {}".format(SHORT, ex))
        return [], []
    added, skipped = [], []
    for alias, command in sorted(short.items()):
        if alias.startswith("_") or command not in commands:
            continue
        macro = _macro(command)
        if aliases.IsAlias(alias):
            old = aliases.GetMacro(alias) or ""
            if "RunPythonScript" not in old or os.path.join("commands", "MC") not in old:
                skipped.append((alias, old))
                continue
        _set(aliases, alias, macro)
        added.append("{}={}".format(alias, command))
    return added, skipped


def install():
    aliases = Rhino.ApplicationSettings.CommandAliasList
    added = []
    for name in sorted(os.listdir(COMMANDS)):
        if not (name.startswith("MC") and name.endswith(".py")):
            continue
        alias = name[:-3]
        _set(aliases, alias, _macro(alias))
        added.append(alias)
    Rhino.RhinoApp.WriteLine("Mind Canvas commands installed: " + ", ".join(added))
    short, skipped = install_short(aliases, added)
    if short:
        Rhino.RhinoApp.WriteLine("Mind Canvas short aliases: " + ", ".join(short))
    for alias, old in skipped:
        Rhino.RhinoApp.WriteLine("  {} was left alone (it runs '{}'); change tools/aliases.json to use another name.".format(alias, old))
    return added


if __name__ == "__main__":
    install()
