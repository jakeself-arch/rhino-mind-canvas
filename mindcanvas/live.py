"""Live mode: rebuild an assembly when its driver curve is edited, delete its
parts when the driver is deleted.

Events only queue work; the rebuild happens on the next Idle so Rhino has
finished the user's command. Nothing is queued while Undo/Redo is running,
because undo restores the old parts itself.

Openings: editing or deleting an opening's line rebuilds its host; deleting a host deletes
its openings. Joins: building an assembly rebuilds the ones joined to it (engine.build); deleting
one rebuilds the assemblies it was joined to (user text mc.joined).
"""

import sys

import System

import scriptcontext
import Rhino

STICKY_KEY = "mindcanvas.live"


def is_on():
    return STICKY_KEY in scriptcontext.sticky


def _state():
    return scriptcontext.sticky.get(STICKY_KEY)


def _undoing(doc):
    return doc is None or doc.UndoActive or getattr(doc, "RedoActive", False)


def enable():
    if is_on():
        return
    state = {"queue": [], "busy": False, "handlers": None}

    def _meta():
        return sys.modules.get("mindcanvas.meta") or __import__("mindcanvas.meta", fromlist=["x"])

    def on_replace(sender, e):
        try:
            if state["busy"] or _undoing(e.Document):
                return
            if _meta().is_driver(e.NewRhinoObject):
                state["queue"].append((e.Document.RuntimeSerialNumber, e.ObjectId))
        except Exception as ex:
            print("Mind Canvas live (replace): {}".format(ex))

    def on_delete(sender, e):
        try:
            # a deleted object may no longer report its document
            doc = e.TheObject.Document or Rhino.RhinoDoc.ActiveDoc
            if state["busy"] or _undoing(doc):
                return
            if _meta().is_driver(e.TheObject):
                # a Replace also fires Delete for the old object; Idle sorts it out
                sn = doc.RuntimeSerialNumber
                state["queue"].append((sn, e.ObjectId))
                host = e.TheObject.Attributes.GetUserString("mc.host")
                if host:   # an opening: its host rebuilds without it
                    state["queue"].append((sn, System.Guid(host)))
                joined = e.TheObject.Attributes.GetUserString("mc.joined")
                for pid in (joined or "").split(","):
                    if pid:   # walls / floors / roofs joined to it rebuild without it
                        state["queue"].append((sn, System.Guid(pid)))
        except Exception as ex:
            print("Mind Canvas live (delete): {}".format(ex))

    def on_idle(sender, e):
        if not state["queue"] or state["busy"]:
            return
        state["busy"] = True
        items, state["queue"] = state["queue"], []
        try:
            engine = __import__("mindcanvas.engine", fromlist=["x"])
            seen = set()
            for sn, oid in items:
                if (sn, oid) in seen:
                    continue
                seen.add((sn, oid))
                doc = Rhino.RhinoDoc.FromRuntimeSerialNumber(sn)
                if doc is None:
                    continue
                undo = doc.BeginUndoRecord("Mind Canvas update")
                try:
                    obj = doc.Objects.FindId(oid)
                    if obj is None or obj.IsDeleted:
                        engine.delete_parts(doc, oid)
                        engine.delete_openings(doc, oid)   # a deleted wall takes its openings along
                    elif _meta().is_driver(obj):
                        r = engine.build(doc, oid)
                        seen.add((sn, r.driver_id))     # an opening built its host
                        for j in r.joined:              # joined assemblies were rebuilt with it
                            seen.add((sn, j.driver_id))
                        for w in r.warnings:
                            print("Mind Canvas: " + w)
                except Exception as ex:
                    print("Mind Canvas live update failed: {}".format(ex))
                finally:
                    doc.EndUndoRecord(undo)
                doc.Views.Redraw()
        finally:
            state["busy"] = False

    state["handlers"] = (on_replace, on_delete, on_idle)
    Rhino.RhinoDoc.ReplaceRhinoObject += on_replace
    Rhino.RhinoDoc.DeleteRhinoObject += on_delete
    Rhino.RhinoApp.Idle += on_idle
    scriptcontext.sticky[STICKY_KEY] = state


class quiet(object):
    """Context manager: changes made inside (e.g. moving an opening's line during a host
    build) do not queue live rebuilds."""

    def __enter__(self):
        self.state = _state()
        if self.state is not None:
            self.prev = self.state["busy"]
            self.state["busy"] = True
        return self

    def __exit__(self, *exc):
        if self.state is not None:
            self.state["busy"] = self.prev
        return False


def disable():
    state = _state()
    if state is None:
        return
    on_replace, on_delete, on_idle = state["handlers"]
    Rhino.RhinoDoc.ReplaceRhinoObject -= on_replace
    Rhino.RhinoDoc.DeleteRhinoObject -= on_delete
    Rhino.RhinoApp.Idle -= on_idle
    del scriptcontext.sticky[STICKY_KEY]


def toggle():
    if is_on():
        disable()
    else:
        enable()
    return is_on()
