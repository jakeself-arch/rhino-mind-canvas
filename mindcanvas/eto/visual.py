"""Visual assembly editor (Phase 12; MCAssemblyEditor and the panel open it).

Left: kind / assembly (/ stack: a roof's layers or its attic ceiling) and the DRAWN SECTION of the
layer stack (eto/sectionview.py over asmview.py): click a layer to select it, drag it to reorder,
drag a boundary to change a thickness (snaps to 1/16", framing to the library's member sizes; Alt =
1/64"); Add / Duplicate / Remove / Up / Down / Mirror; "List editor..." opens the Phase 8 editor.
Right: the selected layer as typed fields (name, component, material, thickness, core, then each
known option of its component: dropdowns, length boxes accepting 3-5/8 or 1'-6", checkboxes) and an
advanced JSON box for nested options; below, the assembly's settings the same way.
Bottom: live preview (a sample of the edited, unsaved assembly built in the model on its own layer,
rebuilt 0.6 s after the last change, removed when the window closes), Save As (user assemblies
only), Apply to the selected assemblies.
All edits go through asmedit.AssemblyModel.
"""

import Eto.Drawing as drawing
import Eto.Forms as forms

from .. import asmedit, asmfields, asmview, library, meta, units
from .. import preview as pv
from . import editor as list_editor
from . import sectionview
from . import widgets as w

KINDS = list_editor.KINDS
DEBOUNCE_S = 0.6
_OPEN = []          # keeps open editors alive after the command's script ends
NONE = asmfields.NONE


class VisualAssemblyEditor(object):
    def __init__(self, doc, lib=None, name=None, kind=None, drivers=None, live_preview=True):
        self.doc = doc
        self.lib = lib or library.get()
        self.drivers = list(drivers or [])
        if name is None and self.drivers:
            name = meta.get(self.drivers[0], meta.ASSEMBLY)
        if kind is None:
            kind = self.lib.assembly(name).get("kind", "wall") if name in self.lib.data["assemblies"] else "wall"
        names = self.lib.assemblies(kind)
        name = name if name in names else (names[0] if names else None)
        if name is None:
            raise asmedit.EditError("No {} assemblies in the library.".format(kind))
        self.model = asmedit.AssemblyModel(self.lib, name)
        self.ctl = asmview.SectionController(self.model, 660, 420)
        self.preview = None
        self.preview_on = bool(live_preview)
        self.last_preview = None
        self.opt_widgets, self.set_widgets = {}, {}
        self._opt_sig = self._set_sig = None
        self._shown = -1            # the layer whose fields are on screen
        self._quiet = False
        self._timer = None
        self._closed = False
        self._build(kind)
        self.refresh(fields=True, settings=True)

    @property
    def index(self):
        return self.ctl.selected

    # -- layout ------------------------------------------------------------------------------
    def _build(self, kind):
        m = self.model
        names = self.lib.assemblies(kind)
        self.dd_kind = w.dropdown(KINDS, KINDS.index(kind), self.on_kind)
        self.dd_asm = w.dropdown(names, names.index(m.source), self.on_assembly)
        self.dd_stack = w.dropdown(["Layers"], 0, self.on_stack)
        self.lb_total = w.label("")
        self.view = sectionview.SectionView(self.ctl, self.on_section, 660, 380)
        self.view.before = self.commit_pending
        buttons = w.rows((w.button("Add", self.on_add), w.button("Duplicate", self.on_duplicate),
                          w.button("Remove", self.on_remove), w.button("Up", lambda: self.on_move(-1)),
                          w.button("Down", lambda: self.on_move(1)), w.button("Mirror", self.on_mirror),
                          w.button("List editor...", self.on_list_editor), None), padding=0)
        hint = w.label("Click a layer to edit it. Drag a layer to reorder. Drag a boundary to change a "
                       "thickness (snaps to 1/16\"; framing snaps to the library's member sizes; hold Alt "
                       "for 1/64\").", wrap=True)
        top = w.rows((w.label("Kind"), self.dd_kind, w.label("Assembly"), self.dd_asm, w.label("Stack"),
                      self.dd_stack, self.lb_total, None), padding=0)
        left = forms.TableLayout()
        left.Spacing = drawing.Size(4, 6)
        for ctl, grow in ((top, False), (self.view.control, True), (buttons, False), (hint, False)):
            row = forms.TableRow(forms.TableCell(ctl, True))
            row.ScaleHeight = grow
            left.Rows.Add(row)

        self.tb_name = w.entry("", self.on_layer_fields, 220)
        self.dd_comp = w.dropdown(m.components(), 0, self.on_layer_fields)
        self.dd_mat = w.dropdown([NONE] + m.materials(), 0, self.on_layer_fields)
        self.tb_thick = w.entry("", self.on_layer_fields, 110)
        self.lb_member = w.label("", wrap=True)
        self.ck_core = w.checkbox("Core (the location line references it)", False, self.on_layer_fields)
        self.pn_opts = forms.Panel()
        self.ta_opts = w.textarea("", 60)
        self.ta_opts.LostFocus += lambda s, e: self.on_advanced_options()
        self.pn_set = forms.Panel()
        self.ta_set = w.textarea("", 60)
        self.ta_set.LostFocus += lambda s, e: self.on_advanced_settings()
        basics = w.rows((w.label("Name"), self.tb_name), (w.label("Component"), self.dd_comp),
                        (w.label("Material"), self.dd_mat), (w.label("Thickness"), self.tb_thick), padding=0)
        right = w.rows(w.label("Selected layer", bold=True), basics, self.lb_member, self.ck_core,
                       w.label("Options", bold=True), self.pn_opts,
                       w.label("Advanced options (JSON, nested settings)"), self.ta_opts,
                       w.label("Assembly settings", bold=True), self.pn_set,
                       w.label("Advanced settings (JSON)"), self.ta_set, None)
        scroll = forms.Scrollable()
        scroll.Content = right
        scroll.ExpandContentWidth = True
        scroll.Size = drawing.Size(440, 300)        # a small preferred height: the row stretches it

        self.ck_preview = w.checkbox("Live preview (a sample in the model, layer MindCanvas::_Preview)",
                                     self.preview_on, self.on_preview_toggle)
        self.lb_preview = w.label("")
        self.tb_save = w.textbox("", None, 260)
        self.lb_status = w.label("", wrap=True)
        bottom = w.rows((self.ck_preview, w.button("Zoom to preview", self.on_zoom), self.lb_preview, None),
                        (w.label("Save as"), self.tb_save, w.button("Save", self.on_save),
                         w.button("Apply to selected", self.on_apply), w.button("Close", self.close), None),
                        self.lb_status)
        split = forms.TableLayout()
        split.Spacing = drawing.Size(8, 8)
        main = forms.TableRow(forms.TableCell(left, True), forms.TableCell(scroll, False))
        main.ScaleHeight = True
        split.Rows.Add(main)
        root = forms.TableLayout()
        root.Padding = drawing.Padding(4)
        root.Spacing = drawing.Size(4, 4)
        for ctl, grow in ((split, True), (bottom, False)):
            row = forms.TableRow(forms.TableCell(ctl, True))
            row.ScaleHeight = grow
            root.Rows.Add(row)
        self.form = forms.Form()
        self.form.Title = "Mind Canvas - Assembly Editor"
        self.form.Resizable = True
        self.form.MinimumSize = drawing.Size(1180, 760)
        self.form.Content = root
        self.form.Closed += lambda s, e: self._cleanup()

    # -- typed field widgets -----------------------------------------------------------------
    @staticmethod
    def _sig(fields):
        return tuple((f.key, f.type, tuple(f.choices) if f.choices else None) for f in fields)

    def _field_layout(self, fields, handler):
        widgets, rows_ = {}, []
        for f in fields:
            if f.type == "bool":
                c = w.checkbox(f.label, bool(f.value), (lambda k=f.key: handler(k)))
                rows_.append(c)
            elif f.choices is not None:
                idx = f.choices.index(f.value) if f.value in f.choices else 0
                c = w.dropdown(f.choices, idx, (lambda k=f.key: handler(k)))
                rows_.append((w.label(f.label), c))
            else:
                c = w.entry(f.value, (lambda k=f.key: handler(k)), 140,
                            ("default " + f.default) if f.default else None)
                rows_.append((w.label(f.label), c))
            if f.default:
                try:
                    c.ToolTip = "Default: " + f.default
                except Exception:
                    pass
            widgets[f.key] = (f, c)
        lay = w.rows(*rows_, padding=0) if rows_ else w.label("(no options for this component)")
        return lay, widgets

    @staticmethod
    def _put(f, c):
        if f.type == "bool":
            c.Checked = bool(f.value)
        elif f.choices is not None:
            c.SelectedIndex = f.choices.index(f.value) if f.value in f.choices else 0
        else:
            c.Text = f.value

    @staticmethod
    def _read(f, c):
        if f.type == "bool":
            return bool(c.Checked)
        if f.choices is not None:
            return w.selected(c)
        return c.Text

    def _show_fields(self, panel, fields, handler, which):
        sig = self._sig(fields)
        if sig == (self._opt_sig if which == "opt" else self._set_sig):
            widgets = self.opt_widgets if which == "opt" else self.set_widgets
            for f in fields:
                self._put(f, widgets[f.key][1])
                widgets[f.key] = (f, widgets[f.key][1])
            return
        lay, widgets = self._field_layout(fields, handler)
        panel.Content = lay
        if which == "opt":
            self.opt_widgets, self._opt_sig = widgets, sig
        else:
            self.set_widgets, self._set_sig = widgets, sig

    # -- state -> controls -------------------------------------------------------------------
    def refresh(self, fields=True, settings=False):
        m = self.model
        self._quiet = True
        try:
            stacks = m.stacks()
            labels = [asmedit.STACK_LABELS.get(s, s) for s in stacks] or ["(none)"]
            w.set_items(self.dd_stack, labels, asmedit.STACK_LABELS.get(m.stack_key, m.stack_key))
            self.dd_stack.Enabled = len(stacks) > 1
            if self.ctl.selected < 0 and m.layers:
                self.ctl.select(0)
            self.ctl.relayout()
            self.view.invalidate()
            self.lb_total.Text = 'Total {}"'.format(asmfields.show_length(self.ctl.layout.total)) if m.layers else ""
            i = self.ctl.selected
            enabled = m.has_layers and 0 <= i < len(m.layers)
            for c in (self.tb_name, self.dd_comp, self.dd_mat, self.tb_thick, self.ck_core, self.ta_opts):
                c.Enabled = enabled
            if fields or i != self._shown:
                if enabled:
                    self.tb_name.Text = m.field(i, "name")
                    w.set_items(self.dd_comp, m.components(), m.field(i, "component") or "solid")
                    w.set_items(self.dd_mat, [NONE] + m.materials(), m.field(i, "material") or NONE)
                    self.tb_thick.Text = asmfields.show_length(m.thickness_in(i))
                    name, prof, metal = m.member(i)
                    self.lb_member.Text = ("Member: {} - the thickness follows it.".format(name) if name else "")
                    self.ck_core.Checked = bool(m.field(i, "core"))
                    self._show_fields(self.pn_opts, m.option_fields(i), self.on_option, "opt")
                    self.ta_opts.Text = m.advanced_options(i)
                    self._shown = i
                else:
                    self.pn_opts.Content = w.label("(no layer selected)")
                    self.opt_widgets, self._opt_sig = {}, None
                    self.lb_member.Text = ""
                    self._shown = -1
            if settings:
                self._show_fields(self.pn_set, m.setting_fields(), self.on_setting, "set")
                self.ta_set.Text = m.advanced_settings()
            if not self.tb_save.Text:
                self.tb_save.Text = m.source if self.lib.is_user_entry("assemblies", m.source) else m.source + " (custom)"
            probs = m.problems()
            self.status(("* unsaved changes. " if m.dirty else "") + (probs[0] if probs else ""))
        finally:
            self._quiet = False

    def status(self, msg):
        self.lb_status.Text = msg

    def _guard(self, fn):
        try:
            fn()
            return True
        except (asmedit.EditError, ValueError) as ex:
            self.status(str(ex))
            return False

    def _changed(self, fields=True, settings=False):
        self.refresh(fields=fields, settings=settings)
        self.schedule_preview()

    # -- section -----------------------------------------------------------------------------
    def on_section(self, result):
        """After a click / drag in the drawn section."""
        if result in ("thickness", "reorder"):
            self._changed(fields=True)
        else:
            self.refresh(fields=True)

    def select_layer(self, i):
        self.commit_pending()
        self.ctl.select(i)
        self.refresh(fields=True)

    def commit_pending(self):
        """Write typed-but-not-committed text fields (a click in the drawing takes no focus)."""
        if self._quiet:
            return
        self.on_layer_fields()
        for key, (f, c) in list(self.opt_widgets.items()):
            if f.type not in ("bool",) and f.choices is None:
                self.on_option(key)
        for key, (f, c) in list(self.set_widgets.items()):
            if f.type not in ("bool",) and f.choices is None:
                self.on_setting(key)

    # -- handlers: kind / assembly / stack -----------------------------------------------------
    def on_kind(self):
        if self._quiet:
            return
        kind = w.selected(self.dd_kind)
        names = self.lib.assemblies(kind)
        if not names:
            self.status("No {} assemblies.".format(kind))
            return
        self._quiet = True
        w.set_items(self.dd_asm, names, names[0])
        self._quiet = False
        self.select_assembly(names[0])

    def on_assembly(self):
        if not self._quiet:
            self.select_assembly(w.selected(self.dd_asm))

    def select_assembly(self, name):
        self.model.load(name)
        self.ctl.select(0)
        self._shown = -1
        self.tb_save.Text = ""
        self.refresh(fields=True, settings=True)
        self.schedule_preview()

    def on_stack(self):
        if self._quiet:
            return
        stacks = self.model.stacks()
        lbl = w.selected(self.dd_stack)
        for s in stacks:
            if asmedit.STACK_LABELS.get(s, s) == lbl and s != self.model.stack_key:
                self.commit_pending()
                self.model.set_stack(s)
                self.ctl.select(0)
                self._shown = -1
                self.refresh(fields=True)

    # -- handlers: the selected layer ---------------------------------------------------------
    def on_layer_fields(self):
        """Write the layer controls back to the shown layer (only what changed)."""
        i = self._shown
        m = self.model
        if self._quiet or i < 0 or i >= len(m.layers) or not m.has_layers:
            return
        changed = []
        name = self.tb_name.Text.strip()
        if name and name != m.field(i, "name"):
            changed.append(("name", name))
        comp = w.selected(self.dd_comp) or "solid"
        if comp != (m.field(i, "component") or "solid"):
            changed.append(("component", comp))
        mat = w.selected(self.dd_mat)
        mat = "" if mat in (None, NONE) else mat
        if mat != m.field(i, "material"):
            changed.append(("material", mat))
        text = self.tb_thick.Text.strip()
        try:
            if text and abs(units.parse_length(text) - m.thickness_in(i)) > 1.0 / 128:     # display precision
                changed.append(("thickness", text))
        except ValueError:
            self.status("Thickness: '{}' is not a length (e.g. 3-5/8, 1'-6\").".format(text))
            return
        if bool(self.ck_core.Checked) != bool(m.field(i, "core")):
            changed.append(("core", bool(self.ck_core.Checked)))
        if not changed:
            return
        for k, v in changed:
            if not self._guard(lambda: m.set_field(i, k, v)):
                return
        self._changed(fields=True)

    def on_option(self, key):
        if self._quiet or key not in self.opt_widgets or not 0 <= self._shown < len(self.model.layers):
            return
        f, c = self.opt_widgets[key]
        out = [False]

        def go():
            out[0] = self.model.set_option(self._shown, key, self._read(f, c), f.type)
        if self._guard(go) and out[0]:
            self._changed(fields=True)

    def on_advanced_options(self):
        if self._quiet or not 0 <= self._shown < len(self.model.layers):
            return
        out = [False]

        def go():
            out[0] = self.model.set_advanced_options(self._shown, self.ta_opts.Text)
        if self._guard(go) and out[0]:
            self._changed(fields=True)

    def on_setting(self, key):
        if self._quiet or key not in self.set_widgets:
            return
        f, c = self.set_widgets[key]
        out = [False]

        def go():
            out[0] = self.model.set_setting(key, self._read(f, c), f.type)
        if self._guard(go) and out[0]:
            self._changed(fields=False, settings=True)

    def on_advanced_settings(self):
        if self._quiet:
            return
        out = [False]

        def go():
            out[0] = self.model.set_advanced_settings(self.ta_set.Text)
        if self._guard(go) and out[0]:
            self._changed(fields=False, settings=True)

    # -- handlers: stack buttons -------------------------------------------------------------
    def on_add(self):
        self.commit_pending()
        m = self.model
        if m.has_layers:
            i = self.ctl.selected
            self.ctl.select(m.add(i + 1 if i >= 0 else None))
            self._changed(fields=True)

    def on_duplicate(self):
        self.commit_pending()
        if self.ctl.selected >= 0:
            self.ctl.select(self.model.duplicate(self.ctl.selected))
            self._changed(fields=True)

    def on_remove(self):
        i = self.ctl.selected
        if i >= 0 and self._guard(lambda: self.model.remove(i)):
            self.ctl.select(min(i, len(self.model.layers) - 1))
            self._shown = -1
            self._changed(fields=True)

    def on_move(self, step):
        self.commit_pending()
        if self.ctl.selected >= 0:
            self.ctl.select(self.model.move(self.ctl.selected, step))
            self._changed(fields=True)

    def on_mirror(self):
        self.commit_pending()
        if self.model.has_layers:
            n = len(self.model.layers)
            self.model.mirror()
            if self.ctl.selected >= 0:
                self.ctl.select(n - 1 - self.ctl.selected)
            self._changed(fields=True)

    def on_list_editor(self):
        """The Phase 8 list editor (fallback), on the saved assembly."""
        try:
            ed = list_editor.AssemblyEditor(self.doc, self.lib, name=self.model.source, drivers=self.drivers)
        except Exception as ex:
            self.status(str(ex))
            return None
        ed.show()
        if self.model.dirty:
            self.status("The list editor shows the saved '{}' (unsaved changes here are not in it).".format(
                self.model.source))
        return ed

    # -- preview -----------------------------------------------------------------------------
    def schedule_preview(self):
        if not self.preview_on or self._closed:
            return
        if self._timer is None:
            t = forms.UITimer()
            t.Interval = DEBOUNCE_S
            t.Elapsed += lambda s, e: self._tick()
            self._timer = t
        self._timer.Stop()
        self._timer.Start()

    def _tick(self):
        if self._timer is not None:
            self._timer.Stop()
        self.rebuild_preview()

    def rebuild_preview(self):
        """Build the sample of the edited assembly now. Returns the BuildResult or None."""
        if not self.preview_on or self._closed:
            return None
        bad = [p for p in self.model.problems() if "not in the library" not in p]
        if bad:
            self.lb_preview.Text = "Preview waits: " + bad[0]
            return None
        if self.preview is None:
            self.preview = pv.Preview(self.doc)
        try:
            res = self.preview.build(self.lib, self.model.data)
        except Exception as ex:
            self.lb_preview.Text = "Preview failed: {}".format(ex)
            self.last_preview = None
            return None
        self.last_preview = res
        warn = len(res.warnings)
        self.lb_preview.Text = "Preview: {} parts, {:.1f} s{}".format(
            len(res.part_ids), self.preview.seconds, ", {} warning{}".format(warn, "" if warn == 1 else "s") if warn else "")
        return res

    def on_preview_toggle(self):
        if self._quiet:
            return
        self.preview_on = bool(self.ck_preview.Checked)
        if self.preview_on:
            self.rebuild_preview()
        elif self.preview is not None:
            self.preview.clear()
            self.doc.Views.Redraw()
            self.lb_preview.Text = ""

    def on_zoom(self):
        if self.preview is None or not self.preview.zoom():
            self.status("No preview in the model yet.")

    # -- save / apply ------------------------------------------------------------------------
    def on_save(self):
        self.commit_pending()
        name = self.tb_save.Text.strip()
        path = [None]

        def go():
            path[0] = self.model.save_as(name)
        if self._guard(go):
            self._quiet = True
            w.set_items(self.dd_asm, self.lib.assemblies(self.model.kind), name)
            self._quiet = False
            self.refresh(fields=False)
            self.status("Saved '{}' to {}".format(name, path[0]))

    def on_apply(self):
        out = [None]
        drivers = list_editor.selected_drivers(self.doc) or self.drivers

        def go():
            out[0] = self.model.apply(self.doc, drivers)
        if self._guard(go):
            n = len(out[0])
            warn = sum(len(r.warnings) for r in out[0])
            self.doc.Views.Redraw()
            self.status("Applied '{}' to {} assembl{}{}.".format(
                self.model.source, n, "y" if n == 1 else "ies", " ({} warnings)".format(warn) if warn else ""))

    # -- picture -----------------------------------------------------------------------------
    def save_png(self, path, width=900, height=520):
        """The drawn section as a PNG (same painting as the window)."""
        ctl = asmview.SectionController(self.model, width, height)
        ctl.select(self.ctl.selected)
        return sectionview.render_png(ctl, path)

    # -- window ------------------------------------------------------------------------------
    def _cleanup(self):
        if self._closed:
            return
        self._closed = True
        if self._timer is not None:
            self._timer.Stop()
        if self.preview is not None:
            self.preview.close()
        if self in _OPEN:
            _OPEN.remove(self)

    def close(self):
        self._cleanup()
        try:
            self.form.Close()
        except Exception:
            pass

    def show(self):
        keep = [e.preview.token for e in _OPEN + [self] if e.preview is not None]
        pv.purge(self.doc, keep)
        self.form.Owner = w.owner()
        _OPEN.append(self)
        self.form.Show()
        self.schedule_preview()
