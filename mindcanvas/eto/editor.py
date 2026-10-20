"""Assembly editor dialog (MCAssemblyEditor, also opened from MCPanel).

Left: the assembly picker (by kind) and its layers, exterior / top first, with Add / Duplicate /
Remove / Up / Down / Mirror. Right: the selected layer (name, component, material, thickness,
core, options JSON) and the assembly's other settings as JSON. Bottom: Save As (to
library/assemblies/zz_user_assemblies.json) and Apply to the assemblies selected in the model
(the window is modeless).
All edits go through asmedit.AssemblyModel.
"""

import Eto.Drawing as drawing
import Eto.Forms as forms

from .. import asmedit, library, meta, units
from . import widgets as w

KINDS = ["wall", "floor", "roof", "curtain_wall"]
_OPEN = []          # keeps open editors alive after the command's script ends


class AssemblyEditor(object):
    def __init__(self, doc, lib=None, name=None, kind=None, drivers=None):
        self.doc = doc
        self.lib = lib or library.get()
        self.drivers = list(drivers or [])
        if name is None and self.drivers:
            name = meta.get(self.drivers[0], meta.ASSEMBLY)
        if kind is None:
            kind = self.lib.assembly(name).get("kind", "wall") if name else "wall"
        names = self.lib.assemblies(kind)
        name = name if name in names else (names[0] if names else None)
        if name is None:
            raise asmedit.EditError("No {} assemblies in the library.".format(kind))
        self.model = asmedit.AssemblyModel(self.lib, name)
        self.index = 0 if self.model.layers else -1
        self._quiet = False
        self._build(kind)
        self.refresh()

    # -- layout ------------------------------------------------------------------------------
    def _build(self, kind):
        m = self.model
        self.dd_kind = w.dropdown(KINDS, KINDS.index(kind), self.on_kind)
        self.dd_asm = w.dropdown(self.lib.assemblies(kind), self.lib.assemblies(kind).index(m.source), self.on_assembly)
        self.lb_layers = w.listbox([], 220, self.on_layer)
        self.tb_name = w.textbox("", self.on_fields)
        self.dd_comp = w.dropdown(m.components(), 0)
        self.dd_comp.SelectedIndexChanged += lambda s, e: self.on_fields()
        self.cb_mat = w.combobox(m.materials())
        self.cb_mat.LostFocus += lambda s, e: self.on_fields()
        self.cb_mat.SelectedIndexChanged += lambda s, e: self.on_fields()
        self.tb_thick = w.textbox("", self.on_fields, 90)
        self.ck_core = w.checkbox("Core (location line reference)", False, self.on_fields)
        self.ta_opts = w.textarea("", 90)
        self.ta_opts.LostFocus += lambda s, e: self.on_fields()
        self.ta_settings = w.textarea("", 150)
        self.lb_total = w.label("")
        self.tb_save = w.textbox("", None, 260)
        self.lb_status = w.label("", wrap=True)
        layer_buttons = w.rows((w.button("Add", self.on_add), w.button("Duplicate", self.on_duplicate),
                                w.button("Remove", self.on_remove)),
                               (w.button("Up", lambda: self.on_move(-1)), w.button("Down", lambda: self.on_move(1)),
                                w.button("Mirror", self.on_mirror)), padding=0)
        left = w.rows((w.label("Kind"), self.dd_kind), (w.label("Assembly"), self.dd_asm),
                      w.label("Layers (exterior / top first)", bold=True), self.lb_layers, self.lb_total, layer_buttons)
        right = w.rows(w.label("Selected layer", bold=True), (w.label("Name"), self.tb_name),
                       (w.label("Component"), self.dd_comp), (w.label("Material"), self.cb_mat),
                       (w.label("Thickness"), self.tb_thick), self.ck_core, w.label("Options (JSON)"), self.ta_opts,
                       w.label("Other settings (JSON)", bold=True), self.ta_settings,
                       w.button("Apply settings JSON", self.on_settings))
        bottom = w.rows((w.label("Save as"), self.tb_save, w.button("Save", self.on_save),
                         w.button("Apply to selected", self.on_apply), w.button("Close", self.close)),
                        self.lb_status)
        split = forms.TableLayout()
        split.Spacing = drawing.Size(8, 8)
        split.Rows.Add(forms.TableRow(forms.TableCell(left, False), forms.TableCell(right, True)))
        root = forms.DynamicLayout()
        root.AddRow(split)
        root.AddRow(bottom)
        self.form = forms.Form()
        self.form.Title = "Mind Canvas - Assembly Editor"
        self.form.Resizable = True
        self.form.MinimumSize = drawing.Size(860, 620)
        self.form.Content = root

    # -- state -> controls -------------------------------------------------------------------
    def refresh(self):
        m = self.model
        self._quiet = True
        try:
            rows = m.rows() if m.has_layers else ["(no layer stack: edit the settings below)"]
            self.lb_layers.DataStore = rows
            if m.has_layers and m.layers:
                self.index = max(0, min(self.index, len(m.layers) - 1))
                self.lb_layers.SelectedIndex = self.index
            else:
                self.index = -1
            self.lb_total.Text = "Total {}".format(units.format_inches(m.total(), 64)) if m.has_layers else ""
            enabled = self.index >= 0
            for c in (self.tb_name, self.dd_comp, self.cb_mat, self.tb_thick, self.ck_core, self.ta_opts):
                c.Enabled = enabled
            if enabled:
                i = self.index
                self.tb_name.Text = m.field(i, "name")
                w.set_items(self.dd_comp, m.components(), m.field(i, "component") or "solid")
                self.cb_mat.Text = m.field(i, "material")
                self.tb_thick.Text = m.field(i, "thickness")
                self.ck_core.Checked = m.field(i, "core")
                self.ta_opts.Text = m.field(i, "options")
            self.ta_settings.Text = m.settings_json()
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

    # -- handlers ----------------------------------------------------------------------------
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
        self.index = 0
        self.tb_save.Text = ""
        self.refresh()

    def on_layer(self):
        if self._quiet:
            return
        self.on_fields()
        self.index = self.lb_layers.SelectedIndex
        self.refresh()

    def on_fields(self):
        """Write the field controls back to the selected layer (only what changed)."""
        if self._quiet or self.index < 0 or not self.model.has_layers:
            return
        m, i = self.model, self.index
        vals = {"name": self.tb_name.Text.strip(), "component": w.selected(self.dd_comp) or "solid",
                "material": (self.cb_mat.Text or "").strip(), "thickness": self.tb_thick.Text.strip(),
                "core": bool(self.ck_core.Checked), "options": self.ta_opts.Text}
        changed = False
        for k, v in vals.items():
            cur = m.field(i, k)
            same = (v == cur) if k != "options" else (_norm(v) == _norm(cur))
            if not same:
                if not self._guard(lambda: m.set_field(i, k, v)):
                    return
                changed = True
        if changed:
            self.refresh()

    def on_add(self):
        self.on_fields()
        if self.model.has_layers:
            self.index = self.model.add(self.index + 1 if self.index >= 0 else None)
            self.refresh()

    def on_duplicate(self):
        if self.index >= 0:
            self.index = self.model.duplicate(self.index)
            self.refresh()

    def on_remove(self):
        if self.index >= 0 and self._guard(lambda: self.model.remove(self.index)):
            self.refresh()

    def on_move(self, step):
        if self.index >= 0:
            self.on_fields()
            self.index = self.model.move(self.index, step)
            self.refresh()

    def on_mirror(self):
        if self.model.has_layers:
            self.model.mirror()
            self.refresh()

    def on_settings(self):
        if self._guard(lambda: self.model.set_settings_json(self.ta_settings.Text)):
            self.refresh()

    def on_save(self):
        self.on_fields()
        name = self.tb_save.Text.strip()
        path = [None]

        def go():
            path[0] = self.model.save_as(name)
        if self._guard(go):
            kind = self.model.kind
            self._quiet = True
            w.set_items(self.dd_asm, self.lib.assemblies(kind), name)
            self._quiet = False
            self.refresh()
            self.status("Saved '{}' to {}".format(name, path[0]))

    def on_apply(self):
        out = [None]
        drivers = selected_drivers(self.doc) or self.drivers

        def go():
            out[0] = self.model.apply(self.doc, drivers)
        if self._guard(go):
            n = len(out[0])
            warn = sum(len(r.warnings) for r in out[0])
            self.doc.Views.Redraw()
            self.status("Applied '{}' to {} assembl{}{}.".format(
                self.model.source, n, "y" if n == 1 else "ies", " ({} warnings)".format(warn) if warn else ""))

    def close(self):
        self.form.Close()

    def show(self):
        self.form.Owner = w.owner()
        _OPEN.append(self)
        self.form.Closed += lambda s, e: _OPEN.remove(self) if self in _OPEN else None
        self.form.Show()


def selected_drivers(doc):
    """Drivers of the selected objects (a part selects its assembly, a wall mass its wall), in
    selection order."""
    from .. import wallmasses
    out, seen = [], set()
    for o in doc.Objects.GetSelectedObjects(False, False) or []:
        d = meta.driver_of(doc, o)
        if d is None and wallmasses.is_wall_mass(o):
            d = wallmasses.wall_of(doc, o)
        if d is not None and d.Id not in seen:
            seen.add(d.Id)
            out.append(d)
    return out


def _norm(text):
    import json
    try:
        return json.dumps(json.loads(text or "{}"), sort_keys=True)
    except ValueError:
        return text
