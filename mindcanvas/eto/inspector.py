"""The inspector (MCInspector): a floating window that follows the Rhino selection.

Select walls, curtain walls, floors, roofs, stairs or windows / doors (their curve or any of their parts)
and the inspector shows their settings, one section per kind (props.FIELDS). A change applies at
once to every selected assembly of that kind: press Enter or leave a box, pick from a list, tick
a box. Values that differ show "(varies)" / an empty box until you set them. Buttons under each
section run the full edit commands on the selection (layers, framing, joins, grid editor, ...).

With nothing selected it shows the current assembly of each kind (what the next MCWall / MCFloor
/ ... builds, saved with the model: ui.current_assembly) and buttons to draw one.

Double-clicking an assembly in a viewport (enable_double_click) opens the curtain-grid editor for
a curtain wall and the inspector for anything else.
"""

import Eto.Drawing as drawing
import Eto.Forms as forms
import Rhino
import scriptcontext

from .. import library, meta, props, units
from . import widgets as w

STATE_KEY = "mindcanvas.inspector"
MOUSE_KEY = "mindcanvas.dblclick"
VARIES = "(varies)"
CREATE = [("wall", "Wall", "MCWall"), ("curtain_wall", "Curtain wall", "MCCurtainWall"),
          ("floor", "Floor", "MCFloor"), ("roof", "Roof", "MCRoof"), ("stair", "Stair", "MCStair")]
EDITABLE_ASSEMBLIES = ("wall", "floor", "roof", "curtain_wall")   # the assembly editor's kinds
FIELD_WIDTH = 170    # fixed, so long assembly names don't widen the window
TEXT_WIDTH = 290     # wrapping labels: a width to wrap at (the scrollable would let them run on)


def _buttons(*pairs):
    """One row of equal-width buttons in its own layout (the outer layout's columns belong to the
    grids)."""
    row = forms.TableRow()
    for lbl, fn in pairs:
        row.Cells.Add(forms.TableCell(w.button(lbl, fn), True))
    lay = forms.TableLayout()
    lay.Spacing = drawing.Size(4, 4)
    lay.Rows.Add(row)
    return lay


def _note(text):
    lb = w.label(text, wrap=True)
    lb.Width = TEXT_WIDTH
    return lb


def run_command(name):
    return Rhino.RhinoApp.RunScript("_" + name, False)


def later(fn):
    """Run fn on the next Idle (outside mouse / selection events, where commands cannot start)."""
    def _once(sender, e):
        Rhino.RhinoApp.Idle -= _once
        try:
            fn()
        except Exception as ex:
            print("Mind Canvas: {}".format(ex))
    Rhino.RhinoApp.Idle += _once


class _Row(object):
    """One setting of the selected assemblies of one kind."""

    def __init__(self, owner, kind, field, ids):
        self.owner, self.kind, self.field, self.ids = owner, kind, field, ids
        self.loaded, self.mixed, self.values = None, False, []
        t = field.type
        if t in ("assembly", "choice"):
            self.control = w.dropdown([], 0, width=FIELD_WIDTH)
            self.control.SelectedIndexChanged += lambda s, e: self._picked()
        elif t == "bool":
            self.control = w.checkbox("", False)
            self.control.CheckedChanged += lambda s, e: self.commit(self.control.Checked)
        else:
            self.control = w.textbox("", None, FIELD_WIDTH)
            self.control.KeyDown += self._key
            self.control.LostFocus += lambda s, e: self._typed()

    def drivers(self):
        return self.owner.objects(self.ids)

    def choices(self):
        lib = self.owner.lib
        if self.field.type != "assembly":
            return list(self.field.choices)
        if self.kind == "opening":
            from ..openings import core
            return core.type_names(lib)
        return lib.assemblies(self.kind)

    def load(self):
        ds = self.drivers()
        if not ds:
            return
        self.loaded, self.mixed = props.common(self.owner.lib, ds, self.field)
        c, t = self.control, self.field.type
        if t in ("assembly", "choice"):
            vals = self.choices()
            if self.loaded is not None and self.loaded not in vals:
                vals.append(self.loaded)
            self.values = ([None] if self.mixed else []) + vals
            shown = [VARIES if v is None else (v if t == "assembly" else props.label(v)) for v in self.values]
            c.DataStore = shown
            c.SelectedIndex = 0 if self.mixed else (self.values.index(self.loaded) if self.loaded in self.values else -1)
        elif t == "bool":
            c.ThreeState = self.mixed
            c.Checked = None if self.mixed else bool(self.loaded)
        else:
            c.PlaceholderText = VARIES if self.mixed else ""
            c.Text = "" if (self.mixed or self.loaded is None) else self._fmt(self.loaded)

    def _fmt(self, v):
        if self.field.type == "length":
            return units.format_inches(v)
        return "{:g}".format(v)

    def _picked(self):
        i = self.control.SelectedIndex
        if 0 <= i < len(self.values):
            self.commit(self.values[i])

    def _key(self, sender, e):
        if e.Key == forms.Keys.Enter:
            e.Handled = True
            self._typed()

    def _typed(self):
        text = self.control.Text.strip()
        if not text:
            return
        if not self.mixed and self.loaded is not None and text == self._fmt(self.loaded):
            return
        try:
            v = units.parse_length(text) if self.field.type == "length" else float(text)
        except ValueError:
            self.owner.say("'{}' is not a {}.".format(text, "length" if self.field.type == "length" else "number"))
            return
        self.commit(round(v, 4))

    def commit(self, v):
        if self.owner.loading or v is None:
            return
        if self.field.type == "bool":
            v = bool(v)
        if not self.mixed and v == self.loaded:
            return
        self.owner.apply(self, v)


class Inspector(object):
    def __init__(self):
        self.lib = library.get()
        self.ids = []
        self.layout_key = None
        self.rows = []
        self.loading = False
        self.busy = False
        self.dirty = False
        self.snap = True
        self.status = _note("")
        self.form = forms.Form()
        self.form.Title = "Mind Canvas inspector"
        self.form.Resizable = True
        self.form.MinimumSize = drawing.Size(320, 240)
        self.form.Size = drawing.Size(340, 520)
        self._handlers = None
        self.form.Closed += lambda s, e: self._closed()
        self.refresh(force=True)

    # -- Rhino events ---------------------------------------------------------------------
    def hook(self):
        if self._handlers:
            return
        mark = lambda s, e: self.mark()
        idle = lambda s, e: self._idle()
        self._handlers = (mark, idle)
        Rhino.RhinoDoc.SelectObjects += mark
        Rhino.RhinoDoc.DeselectObjects += mark
        Rhino.RhinoDoc.DeselectAllObjects += mark
        Rhino.Commands.Command.EndCommand += mark
        Rhino.RhinoApp.Idle += idle

    def unhook(self):
        if not self._handlers:
            return
        mark, idle = self._handlers
        Rhino.RhinoDoc.SelectObjects -= mark
        Rhino.RhinoDoc.DeselectObjects -= mark
        Rhino.RhinoDoc.DeselectAllObjects -= mark
        Rhino.Commands.Command.EndCommand -= mark
        Rhino.RhinoApp.Idle -= idle
        self._handlers = None

    def mark(self):
        if not self.busy:
            self.dirty = True

    def _idle(self):
        if self.dirty and not self.busy:
            self.dirty = False
            try:
                self.refresh()
            except Exception as ex:
                print("Mind Canvas inspector: {}".format(ex))

    def _closed(self):
        self.unhook()
        scriptcontext.sticky["mindcanvas.inspector.location"] = (self.form.Location.X, self.form.Location.Y)
        if scriptcontext.sticky.get(STATE_KEY) is self:
            del scriptcontext.sticky[STATE_KEY]

    # -- helpers ----------------------------------------------------------------------------
    @property
    def doc(self):
        return Rhino.RhinoDoc.ActiveDoc

    def objects(self, ids):
        out = []
        for i in ids:
            o = self.doc.Objects.FindId(i)
            if o is not None and not o.IsDeleted:
                out.append(o)
        return out

    def say(self, msg):
        self.status.Text = msg
        Rhino.RhinoApp.WriteLine("Mind Canvas: " + msg)

    def reselect(self, ids):
        """Select the assemblies' curves so the selection (and the inspector) stays on them."""
        doc = self.doc
        self.busy = True
        try:
            for i in ids:
                doc.Objects.Select(i, True)
        finally:
            self.busy = False
        doc.Views.Redraw()

    # -- content ----------------------------------------------------------------------------
    def refresh(self, force=False):
        doc = self.doc
        if doc is None:
            return
        ds = props.selected(doc)
        groups = props.by_kind(ds)
        key = tuple((k, tuple(str(d.Id) for d in g), k == "opening" and any(props.is_door(self.lib, d) for d in g))
                    for k, g in groups)
        if not force and key == self.layout_key:
            self.reload()
            return
        self.layout_key = key
        self.ids = [d.Id for d in ds]
        self.rows = []
        self.form.Content = self._content(groups)

    def reload(self):
        self.loading = True
        try:
            for r in self.rows:
                r.load()
        finally:
            self.loading = False

    def _content(self, groups):
        lay = forms.DynamicLayout()
        lay.Padding = drawing.Padding(8)
        lay.Spacing = drawing.Size(6, 4)
        if not groups:
            self._empty(lay)
        for kind, ds in groups:
            self._section(lay, kind, ds)
        lay.AddRow(None)
        lay.AddRow(self.status)
        scroll = forms.Scrollable()
        scroll.Content = lay
        self.reload()
        return scroll

    def _section(self, lay, kind, ds):
        names = sorted(set(meta.get(d, meta.ASSEMBLY) or "" for d in ds))
        lay.AddRow(w.label(props.kind_label(kind, len(ds)), bold=True))
        lay.AddRow(_note("; ".join(names)))
        door = kind == "opening" and any(props.is_door(self.lib, d) for d in ds)
        ids = [d.Id for d in ds]
        grid = forms.DynamicLayout()
        grid.Spacing = drawing.Size(6, 4)
        for f in props.fields(kind):
            if f.doors_only and not door:
                continue
            r = _Row(self, kind, f, ids)
            self.rows.append(r)
            grid.AddRow(w.label(f.label), r.control)
        lay.AddRow(grid)
        if kind == "opening":
            ck = w.checkbox("Snap heads to the brick coursing", self.snap)
            ck.CheckedChanged += lambda s, e: setattr(self, "snap", bool(s.Checked))
            lay.AddRow(ck)
        buttons = [(lbl, (lambda c=cmd, i=ids: self.action(c, i))) for lbl, cmd in props.ACTIONS.get(kind, [])]
        if kind in EDITABLE_ASSEMBLIES:
            buttons.append(("Edit assembly...", lambda i=ids: self.edit_assembly(i)))
        for j in range(0, len(buttons), 2):
            lay.AddRow(_buttons(*buttons[j:j + 2]))
        lay.AddRow(None)

    def _empty(self, lay):
        lay.AddRow(w.label("Nothing selected", bold=True))
        lay.AddRow(_note("Select walls, curtain walls, floors, roofs, stairs or windows / doors (their curve "
                         "or any part) to edit them here. Double-click one to open its editor."))
        lay.AddRow(w.label("Next to build", bold=True))
        from ..cmd import ui
        grid = forms.DynamicLayout()
        grid.Spacing = drawing.Size(6, 4)
        for kind, lbl, cmd in CREATE:
            names = self.lib.assemblies(kind)
            if not names:
                continue
            cur = ui.current_assembly(self.lib, kind, self.doc)
            dd = w.dropdown(names, names.index(cur) if cur in names else 0, width=FIELD_WIDTH)
            dd.SelectedIndexChanged += (lambda s, e, k=kind: ui.set_current_assembly(k, w.selected(s), self.doc))
            grid.AddRow(w.label(lbl), dd, w.button("Draw", (lambda c=cmd: self.action(c, [])), 56))
        lay.AddRow(grid)
        lay.AddRow(_buttons(("Window / door", lambda: self.action("MCOpening", [])),
                            ("Match...", lambda: self.action("MCMatch", []))))
        lay.AddRow(_buttons(("Palette (pick by sight)...", self.open_palette)))
        lay.AddRow(None)

    # -- actions ----------------------------------------------------------------------------
    def apply(self, row, value):
        doc = self.doc
        ds = row.drivers()
        if not ds:
            return
        self.busy = True
        try:
            results = props.apply(doc, self.lib, ds, row.field, value, self.snap)
        except Exception as ex:
            self.say("{} failed: {}".format(row.field.label, ex))
            return
        finally:
            self.busy = False
        doc.Views.Redraw()
        warns = [m for r in results for m in r.warnings]
        secs = sum(r.seconds for r in results)
        self.say("{}: rebuilt {} in {:.2f}s{}".format(row.field.label, props.kind_label(row.kind, len(results)), secs,
                                                     " ({} warnings, see the command line)".format(len(warns)) if warns else ""))
        for m in warns:
            Rhino.RhinoApp.WriteLine("  warning: " + m)
        if row.field.type == "assembly" or row.field.doors_only:
            self.refresh(force=True)    # the section's name / door fields may change
        else:
            self.reload()
        self.reselect(self.ids)

    def action(self, command, ids):
        ids = list(ids)
        if ids:
            self.reselect(ids)
        ok = run_command(command)
        if not ok:
            self.say("{} did not run (run tools/install.py to register the MC commands).".format(command))
        if ids:
            self.reselect(ids)

    def edit_assembly(self, ids):
        from . import visual
        ds = self.objects(ids)
        if not ds:
            return
        try:
            ed = visual.VisualAssemblyEditor(self.doc, self.lib, name=meta.get(ds[0], meta.ASSEMBLY), drivers=ds)
        except Exception as ex:
            self.say(str(ex))
            return
        ed.show()

    def open_palette(self):
        from . import palette
        palette.open_palette()

    def show(self):
        self.form.Owner = w.owner()
        loc = scriptcontext.sticky.get("mindcanvas.inspector.location")
        if loc:
            self.form.Location = drawing.Point(int(loc[0]), int(loc[1]))
        self.hook()
        self.form.Show()


def current():
    ins = scriptcontext.sticky.get(STATE_KEY)
    try:
        if ins is not None and ins.form.Visible:
            return ins
    except Exception:
        pass
    return None


def open_inspector():
    """Show the inspector (bring the open one to the front instead of opening a second)."""
    ins = current()
    if ins is not None:
        ins.form.BringToFront()
        ins.refresh()
        return ins
    ins = Inspector()
    scriptcontext.sticky[STATE_KEY] = ins
    ins.show()
    return ins


# -- double-click ---------------------------------------------------------------------------
def open_editor_for(doc):
    """What a double-click on an assembly opens: the grid editor for a curtain wall, else the
    inspector. Returns the command / window name."""
    ds = props.selected(doc)
    if not ds:
        return None
    if meta.get(ds[0], meta.TYPE) == "curtain_wall" and len(ds) == 1:
        run_command("MCCurtainGrid")
        return "MCCurtainGrid"
    open_inspector()
    return "inspector"


def enable_double_click():
    """Double-click an assembly (its curve or any part) in a viewport to edit it."""
    if scriptcontext.sticky.get(MOUSE_KEY) is not None:
        return scriptcontext.sticky[MOUSE_KEY]

    class _MindCanvasDoubleClick(Rhino.UI.MouseCallback):
        __namespace__ = "MindCanvas"

        def OnMouseDoubleClick(self, e):
            try:
                if e.MouseButton != Rhino.UI.MouseButton.Left or Rhino.Commands.Command.InCommand():
                    return
                doc = e.View.Document
                if not props.selected(doc):
                    return
                e.Cancel = True          # e.g. no BlockEdit on a stud block
                mod = __import__("mindcanvas.eto.inspector", fromlist=["x"])
                later(lambda: mod.open_editor_for(doc))
            except Exception as ex:
                print("Mind Canvas double-click: {}".format(ex))

    cb = _MindCanvasDoubleClick()
    cb.Enabled = True
    scriptcontext.sticky[MOUSE_KEY] = cb
    return cb


def disable_double_click():
    cb = scriptcontext.sticky.pop(MOUSE_KEY, None)
    if cb is not None:
        cb.Enabled = False
