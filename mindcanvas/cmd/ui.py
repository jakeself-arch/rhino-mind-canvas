"""Shared command-line / dialog helpers for commands."""

import System
import Rhino
import scriptcontext

from .. import meta, units

RI = Rhino.Input
Result = Rhino.Commands.Result


def doc():
    return Rhino.RhinoDoc.ActiveDoc


def say(msg):
    Rhino.RhinoApp.WriteLine(msg)


def report(result, label="Built"):
    say("{} {} parts in {:.2f}s.".format(label, len(result.part_ids), result.seconds))
    for w in result.warnings:
        say("  warning: " + w)


def _idx(ret):
    """pythonnet returns (index, ref-arg) tuples for AddOption* calls."""
    return ret[0] if isinstance(ret, tuple) else ret


def pick_from_list(title, message, items, default=None):
    if not items:
        say("Nothing to choose from.")
        return None
    arr = System.Array[System.Object](list(items))
    choice = Rhino.UI.Dialogs.ShowListBox(title, message, arr, default if default in items else items[0])
    return str(choice) if choice is not None else None


LAST_ASSEMBLY = "mindcanvas.last_assembly."


def pick_assembly(lib, kind, title="Mind Canvas"):
    names = lib.assemblies(kind)
    key = LAST_ASSEMBLY + kind
    choice = pick_from_list(title, "Choose a {} assembly".format(kind), names, scriptcontext.sticky.get(key))
    if choice:
        scriptcontext.sticky[key] = choice
    return choice


def select_drivers(prompt, kind=None, allow_all=False):
    """Select assemblies by clicking their driver curve OR any of their parts.
    Returns a list of driver objects. With allow_all, Enter = every driver."""
    d = doc()
    go = RI.Custom.GetObject()
    go.SetCommandPrompt(prompt + (" (Enter for all)" if allow_all else ""))
    go.SubObjectSelect = False
    go.GroupSelect = False
    go.EnablePreSelect(True, True)
    go.AcceptNothing(allow_all)

    def _ok(rh_obj, geom, ci):
        drv = meta.driver_of(d, rh_obj)
        return drv is not None and (kind is None or meta.get(drv, meta.TYPE) == kind)

    go.SetCustomGeometryFilter(RI.Custom.GetObjectGeometryFilter(_ok))
    res = go.GetMultiple(1, 0)
    if res == RI.GetResult.Nothing and allow_all:
        return meta.all_drivers(d, kind)
    if go.CommandResult() != Result.Success:
        return []
    out, seen = [], set()
    for i in range(go.ObjectCount):
        drv = meta.driver_of(d, go.Object(i).Object())
        if drv is not None and drv.Id not in seen:
            seen.add(drv.Id)
            out.append(drv)
    d.Objects.UnselectAll()
    return out


def length_option(value_inches, doc_):
    """OptionDouble in model units for an inch value."""
    return RI.Custom.OptionDouble(units.to_model(doc_, value_inches))


def add_option_double(getter, name, opt):
    return _idx(getter.AddOptionDouble(name, opt))


def add_option_toggle(getter, name, opt):
    return _idx(getter.AddOptionToggle(name, opt))


def add_option_list(getter, name, values, current):
    return _idx(getter.AddOptionList(name, System.Array[System.String](list(values)), current))
