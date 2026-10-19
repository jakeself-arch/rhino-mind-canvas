"""The visual curtain-grid editor window (MCCurtainGrid; MCEditCurtainWall > Editor; the panel).

Top: the tools (Select / Grid line / Transom / Delete / Paint / Door), the paint infill, the door
type + swing + hinge, snapping, "whole width" for new transoms, exterior / interior view.
Middle: the drawn elevation (eto/cwgridview.py over curtainwall/gridedit.py); right: the
selection (typed positions: a grid line from the previous / to the next, a transom's height,
a door's height), Divide bay, Equalize run, Delete.
Bottom: Undo / Redo, Revert, Apply (rebuild the curtain wall), Auto apply (on: rebuild after
every finished edit, ~0.1 s for a 30' wall at detail), 3D preview (the edited grid drawn on the wall in the Rhino viewports, orange; the
selection in blue), Reload, Close.

Applying writes params grid = custom + the doors (curtainwall/gridio.py); MCEditCurtainWall's
Grid option turns a wall back to Equal / Fixed / List.
"""

import time

import Eto.Drawing as drawing
import Eto.Forms as forms
import Rhino
import System

from .. import units
from ..curtainwall import gridedit as ge
from ..curtainwall import gridio
from . import cwgridview
from . import widgets as w

TOOL_LABELS = [("select", "Select"), ("vertical", "Grid line"), ("horizontal", "Transom"),
               ("delete", "Delete"), ("paint", "Paint"), ("door", "Door")]
PAINTS = [(ge.VISION, "Vision"), (ge.SPANDREL, "Spandrel"), (ge.SHADOW, "Shadow box")]
SNAPS = [("1/16\"", 0.0625), ("1/8\"", 0.125), ("1/4\"", 0.25), ("1/2\"", 0.5), ("1\"", 1.0),
         ("2\"", 2.0), ("6\"", 6.0), ("1'", 12.0), ("off", 0.0)]
AUTO_DELAY_MS = 350
PREVIEW_EVERY_S = 0.12
_OPEN = []
ORANGE = System.Drawing.Color.FromArgb(240, 128, 0)
BLUE = System.Drawing.Color.FromArgb(0, 122, 230)


class CurtainGridEditor(object):
    def __init__(self, doc, driver, lib=None, width=980, height=560):
        self.doc = doc
        self.session = gridio.Session(doc, driver, lib)
        self.ctl = ge.GridController(self.session.model, width, height, self.session.door_info)
        types = self.session.door_types()
        self.ctl.door_type = types[0] if types else None
        self.door_types = types
        self.applied = self.ctl.version
        self.start_state = self.ctl.m.state()
        self.preview_on = True
        self.auto = True
        self._quiet = False
        self._timer = None
        self._last_redraw = 0.0
        self._handler = None
        self._closed = False
        self._build(width, height)
        self.refresh()
        self._hook_preview()

    # -- layout -----------------------------------------------------------------------------------
    def _build(self, width, height):
        c = self.ctl
        self.rb_tool = forms.RadioButtonList()
        self.rb_tool.DataStore = [t[1] for t in TOOL_LABELS]
        self.rb_tool.Orientation = forms.Orientation.Horizontal
        self.rb_tool.SelectedIndex = 0
        self.rb_tool.SelectedIndexChanged += lambda s, e: self.on_tool()
        self.dd_paint = w.dropdown([p[1] for p in PAINTS], 1, self.on_paint)
        self.dd_door = w.dropdown(self.door_types or ["(no door types)"], 0, self.on_door_type, 250)
        self.dd_swing = w.dropdown(["In", "Out"], 0, self.on_door_props)
        self.dd_hinge = w.dropdown(["Left", "Right"], 0, self.on_door_props)
        self.dd_snap = w.dropdown([s[0] for s in SNAPS], 4, self.on_snap)
        self.ck_whole = w.checkbox("Whole width", False, self.on_whole)
        self.dd_view = w.dropdown(["From exterior", "From interior"], 0, self.on_view)
        self.view = cwgridview.GridView(c, self.on_change, width, height)
        self.lb_title = w.label("", bold=True)
        self.info_box = forms.Panel()
        self.tb_div = w.textbox("2", None, 40)
        side = w.rows(self.lb_title, self.info_box,
                      w.label("Grid", bold=True),
                      (w.button("Divide bay into", self.on_divide), self.tb_div),
                      w.button("Equalize run", self.on_equalize),
                      w.button("Delete selected", self.on_delete),
                      w.label("Keys: S select, V grid line, H transom, X delete, P paint, D door, "
                              "Del delete, Ctrl+Z / Ctrl+Y. Ctrl-drag a transom: only its bay. "
                              "Shift-click with Transom: across every bay (or the reverse with "
                              "Whole width). Alt: no snapping.", wrap=True),
                      None, padding=6)
        side.Width = 250
        self.ck_auto = w.checkbox("Auto apply", True, self.on_auto)
        self.ck_prev = w.checkbox("3D preview", True, self.on_preview)
        self.lb_status = w.label("", wrap=True)
        bottom = w.rows((w.button("Undo", self.on_undo), w.button("Redo", self.on_redo),
                         w.button("Revert", self.on_revert), w.button("Reload", self.on_reload), None,
                         self.ck_prev, self.ck_auto, w.button("Apply", self.on_apply),
                         w.button("Close", self.close)),
                        self.lb_status)
        tools = w.rows((self.rb_tool, None, w.label("Snap"), self.dd_snap, self.dd_view),
                       (w.label("Paint"), self.dd_paint, w.label("Door"), self.dd_door, self.dd_swing,
                        self.dd_hinge, self.ck_whole, None))
        mid = forms.TableLayout()
        mid.Spacing = drawing.Size(6, 6)
        mid.Rows.Add(forms.TableRow(forms.TableCell(self.view.control, True), forms.TableCell(side, False)))
        mid.Rows[0].ScaleHeight = True
        root = forms.TableLayout()
        root.Rows.Add(forms.TableRow(forms.TableCell(tools, True)))
        root.Rows.Add(forms.TableRow(forms.TableCell(mid, True)))
        root.Rows[1].ScaleHeight = True
        root.Rows.Add(forms.TableRow(forms.TableCell(bottom, True)))
        self.form = forms.Form()
        self.form.Title = "Mind Canvas - Curtain Grid: {}".format(self.session.ctx.assembly_name)
        self.form.Resizable = True
        self.form.MinimumSize = drawing.Size(900, 560)
        self.form.Size = drawing.Size(width + 300, height + 190)
        self.form.Content = root
        self.form.Closing += self._closing
        self.form.Closed += self._closed_evt

    # -- state -> controls ----------------------------------------------------------------------------
    def refresh(self):
        c = self.ctl
        self._quiet = True
        try:
            title, fields = c.info()
            self.lb_title.Text = title
            self._fields(fields)
            s = c.sel
            if s and s[0] in ("door", "door_head") and s[1] in c.m.doors:
                d = c.m.doors[s[1]]
                self.dd_swing.SelectedIndex = 1 if d.swing == "out" else 0
                self.dd_hinge.SelectedIndex = 1 if d.hinge == "right" else 0
                if d.type in self.door_types:
                    self.dd_door.SelectedIndex = self.door_types.index(d.type)
            dirty = c.version != self.applied
            self.lb_status.Text = ("* not applied. " if dirty else "") + (c.status or "")
            self.rb_tool.SelectedIndex = [t[0] for t in TOOL_LABELS].index(c.tool)
        finally:
            self._quiet = False
        self.view.invalidate()

    def _fields(self, fields):
        lay = forms.DynamicLayout()
        lay.Spacing = drawing.Size(4, 4)
        for key, label, value, editable in fields:
            if isinstance(value, float):
                txt = units.format_inches(value, 16)
            else:
                txt = str(value)
            if editable:
                tb = w.textbox(txt, None, 110)
                tb.KeyDown += self._enter_handler(key, tb)
                tb.LostFocus += self._commit_handler(key, tb, txt)
                lay.AddRow(w.label(label), tb)
            else:
                lay.AddRow(w.label(label), w.label(txt))
        self.info_box.Content = lay

    def _enter_handler(self, key, tb):
        def h(sender, e):
            if e.Key == forms.Keys.Enter:
                self._commit(key, tb.Text)
                e.Handled = True
        return h

    def _commit_handler(self, key, tb, original):
        def h(sender, e):
            if not self._quiet and tb.Text != original:
                self._commit(key, tb.Text)
        return h

    def _commit(self, key, text):
        try:
            v = units.parse_length(text)
        except Exception:
            self.ctl.status = "Not a length: '{}'".format(text)
            self.refresh()
            return
        if self.ctl.set_value(key, v):
            self.on_change(True)
        else:
            self.refresh()

    # -- handlers -------------------------------------------------------------------------------------
    def on_change(self, edited):
        """From the view: edited True = a finished model edit, None = a drag in progress."""
        if self._closed:
            return
        if edited is None:
            self._redraw_rhino(throttle=True)
            return
        self.refresh()
        self._redraw_rhino()
        if edited and self.auto:
            self._schedule_apply()

    def on_tool(self):
        if not self._quiet:
            self.ctl.set_tool(TOOL_LABELS[self.rb_tool.SelectedIndex][0])
            self.refresh()
            self.view.control.Focus()

    def on_paint(self):
        self.ctl.paint = PAINTS[self.dd_paint.SelectedIndex][0]
        if not self._quiet:
            self.ctl.set_tool("paint")
            self.refresh()

    def on_door_type(self):
        if self._quiet or not self.door_types:
            return
        name = self.door_types[self.dd_door.SelectedIndex]
        self.ctl.door_type = name
        if not self.ctl.set_door_props(type_name=name, info=self.session.door_info(name)):
            self.ctl.set_tool("door")
        self.on_change(True)

    def on_door_props(self):
        swing = ["in", "out"][self.dd_swing.SelectedIndex]
        hinge = ["left", "right"][self.dd_hinge.SelectedIndex]
        self.ctl.door_swing, self.ctl.door_hinge = swing, hinge
        if not self._quiet and self.ctl.set_door_props(swing=swing, hinge=hinge):
            self.on_change(True)

    def on_snap(self):
        self.ctl.snap = SNAPS[self.dd_snap.SelectedIndex][1]

    def on_whole(self):
        self.ctl.whole = bool(self.ck_whole.Checked)

    def on_view(self):
        self.ctl.view = "exterior" if self.dd_view.SelectedIndex == 0 else "interior"
        self.ctl.layout()
        self.view.invalidate()

    def on_divide(self):
        bay = self.ctl.selected_bay()
        if bay is None:
            self.ctl.status = "Select a bay (a panel or a line) first."
            return self.refresh()
        try:
            n = int(self.tb_div.Text.strip())
        except ValueError:
            n = 2
        m = self.ctl.m
        if self.ctl.edit(lambda: m.divide_bay(bay, n), "Bay {} divided into {}.".format(bay + 1, n)) is not None:
            self.ctl.sel = None
            self.on_change(True)
        else:
            self.refresh()

    def on_equalize(self):
        bay = self.ctl.selected_bay()
        bay = 0 if bay is None else bay
        m = self.ctl.m
        if self.ctl.edit(lambda: m.equalize(bay), "Grid lines spread evenly.") is not None:
            self.on_change(True)
        else:
            self.refresh()

    def on_delete(self):
        v0 = self.ctl.version
        self.ctl.delete()
        self.on_change(self.ctl.version != v0)

    def on_undo(self):
        if self.ctl.undo():
            self.on_change(True)
        else:
            self.refresh()

    def on_redo(self):
        if self.ctl.redo():
            self.on_change(True)
        else:
            self.refresh()

    def on_revert(self):
        self.ctl.edit(lambda: self.ctl.m.restore(self.start_state), "Back to the grid at the start.")
        self.ctl.sel = None
        self.on_change(True)

    def on_reload(self):
        self.reload()
        self.ctl.status = "Reloaded from the model."
        self.refresh()

    def on_auto(self):
        self.auto = bool(self.ck_auto.Checked)
        if self.auto and self.ctl.version != self.applied:
            self._schedule_apply()

    def on_preview(self):
        self.preview_on = bool(self.ck_prev.Checked)
        self._redraw_rhino()

    def on_apply(self):
        self.apply()

    # -- apply / reload ---------------------------------------------------------------------------------
    def apply(self):
        self._cancel_timer()
        c = self.ctl
        t0 = time.time()
        try:
            r = self.session.apply(c.m)
        except Exception as ex:
            c.status = "Apply failed: {}".format(ex)
            self.refresh()
            return None
        sel = c.sel
        self._adopt(self.session.model)
        c.sel = sel if self._valid(sel) else None
        warn = [x for x in r.warnings if "skipped" in x or "too" in x]
        c.status = "Applied in {:.1f} s.{}".format(time.time() - t0, (" " + warn[0]) if warn else "")
        self.applied = c.version
        self.doc.Views.Redraw()
        self.refresh()
        return r

    def _adopt(self, model):
        """The rebuilt wall's model replaces the edited one (same grid; ids of new doors)."""
        c = self.ctl
        c.m = model
        c.layout()
        c.version += 1

    def _valid(self, sel):
        m = self.ctl.m
        if not sel:
            return False
        if sel[0] == "vertical":
            return sel[1] < len(m.verts)
        if sel[0] == "hline":
            return sel[1] is not None and sel[1] < len(m.hlines) and sel[2] < m.nbays
        if sel[0] in ("door", "door_head"):
            return sel[1] in m.doors
        return sel[1] < m.nbays and sel[2] < len(m.rows(sel[1]))

    def reload(self):
        self._adopt(self.session.reload())
        self.ctl.sel = None
        self.ctl.undo_stack, self.ctl.redo_stack = [], []
        self.applied = self.ctl.version
        self.start_state = self.ctl.m.state()

    def _schedule_apply(self):
        self._cancel_timer()
        t = forms.UITimer()
        t.Interval = AUTO_DELAY_MS / 1000.0
        t.Elapsed += lambda s, e: self._timer_fired()
        self._timer = t
        t.Start()

    def _timer_fired(self):
        self._cancel_timer()
        if not self._closed and self.ctl.drag is None and self.ctl.version != self.applied:
            self.apply()

    def _cancel_timer(self):
        if self._timer is not None:
            try:
                self._timer.Stop()
            except Exception:
                pass
            self._timer = None

    # -- 3D preview ---------------------------------------------------------------------------------
    def _hook_preview(self):
        def draw(sender, e):
            try:
                if self._closed or not self.preview_on or e.RhinoDoc is None:
                    return
                if e.RhinoDoc.RuntimeSerialNumber != self.doc.RuntimeSerialNumber:
                    return
                for a, b, sel in preview_lines(self.session, self.ctl):
                    e.Display.DrawLine(a, b, BLUE if sel else ORANGE, 4 if sel else 2)
            except Exception:
                pass
        self._handler = draw
        Rhino.Display.DisplayPipeline.DrawForeground += draw
        self._redraw_rhino()

    def _unhook_preview(self):
        if self._handler is not None:
            Rhino.Display.DisplayPipeline.DrawForeground -= self._handler
            self._handler = None
            self.doc.Views.Redraw()

    def _redraw_rhino(self, throttle=False):
        now = time.time()
        if throttle and now - self._last_redraw < PREVIEW_EVERY_S:
            return
        self._last_redraw = now
        try:
            self.doc.Views.Redraw()
        except Exception:
            pass

    # -- window ---------------------------------------------------------------------------------------
    def _closing(self, sender, e):
        if self._closed or self.ctl.version == self.applied:
            return
        res = forms.MessageBox.Show(self.form, "Apply the grid changes to the curtain wall?",
                                    "Mind Canvas - Curtain Grid", forms.MessageBoxButtons.YesNoCancel)
        if res == forms.DialogResult.Cancel:
            e.Cancel = True
        elif res == forms.DialogResult.Yes:
            self.apply()

    def _closed_evt(self, sender, e):
        self._closed = True
        self._cancel_timer()
        self._unhook_preview()
        if self in _OPEN:
            _OPEN.remove(self)

    def close(self):
        self.form.Close()

    def show(self):
        self.form.Owner = w.owner()
        _OPEN.append(self)
        self.form.Show()
        self.view.control.Focus()


def preview_lines(session, ctl):
    """[(a, b, selected)] world lines of the edited grid on the wall's glass face."""
    m = ctl.m
    pt = session.point
    out = []
    sel = ctl.sel
    for k, v in enumerate(m.verts):
        out.append((pt(v.u, 0.0), pt(v.u, m.H), sel == ("vertical", k)))
    for b in range(m.nbays):
        u0, u1 = m.span(b)
        for li in m.lines_in(b):
            if m.hidden(b, li):
                continue
            z = m.hlines[li].z
            s_ = bool(sel and sel[0] == "hline" and sel[1] == li)
            out.append((pt(u0, z), pt(u1, z), s_))
        d = m.doors.get(b)
        if d is not None:
            a0, a1 = u0 + 0.5 * m.wv, u1 - 0.5 * m.wv
            s_ = bool(sel and sel[0] in ("door", "door_head") and sel[1] == b)
            out.append((pt(u0, d.head), pt(u1, d.head), s_))
            zt = d.head - 0.5 * m.wh
            if d.leaves >= 2:
                um = 0.5 * (a0 + a1)
                out.append((pt(um, 0.0), pt(um, zt), s_))
            hinge = a1 if d.hinge == "left" else a0
            latch = a0 if d.hinge == "left" else a1
            if d.leaves >= 2:
                for h_, l_ in ((a0, 0.5 * (a0 + a1)), (a1, 0.5 * (a0 + a1))):
                    out.append((pt(l_, zt), pt(h_, 0.5 * zt), s_))
                    out.append((pt(l_, 0.0), pt(h_, 0.5 * zt), s_))
            else:
                out.append((pt(latch, zt), pt(hinge, 0.5 * zt), s_))
                out.append((pt(latch, 0.0), pt(hinge, 0.5 * zt), s_))
    return out


def open_editor(doc, driver, lib=None):
    for ed in list(_OPEN):
        if ed.session.id == driver.Id and not ed._closed:
            ed.form.BringToFront()
            return ed
    ed = CurtainGridEditor(doc, driver, lib)
    ed.show()
    return ed
