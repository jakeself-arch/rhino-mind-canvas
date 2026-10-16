"""The Mind Canvas panel (MCPanel): a floating, modeless window with every tool in one place.

Tabs
    Build      buttons for the commands (walls, curtain walls, floors, roofs, openings, opening
               masses, edits, joins, trims, setup, update, live, schedule, purge)
    Selection  the selected assemblies: assembly, height, base offset, detail level -> Apply;
               "Edit assembly" opens the assembly editor on the first one
    Drawing    scale, tone, stipple, SetLOD, output folder -> Draw the active view now; section
               cut, display setup, drawing tags
    Entourage  pick a figure, height, Random / Mirror -> Place; Face view; Capture
    Library    reload, assembly editor, capture a profile, open the folder

Command buttons run the MC commands (Rhino.RhinoApp.RunScript) so they behave exactly as typed.
"""

import os

import Eto.Drawing as drawing
import Eto.Forms as forms
import Rhino
import scriptcontext

from .. import engine, library, meta, units
from ..entourage import place
from . import editor as editor_mod
from . import widgets as w

LODS = ["schematic", "design", "detail"]
BUILD = [("Wall", "MCWall"), ("Curtain wall", "MCCurtainWall"), ("Floor", "MCFloor"), ("Roof", "MCRoof"),
         ("Window / door", "MCOpening"), ("Opening mass", "MCOpeningMass"), ("Edit walls", "MCEdit"),
         ("Layers", "MCLayers"), ("Framing", "MCFraming"), ("Joins", "MCJoin"), ("Trim", "MCTrim"),
         ("Edit opening", "MCEditOpening"),
         ("Edit curtain wall", "MCEditCurtainWall"), ("Edit floor", "MCEditFloor"), ("Edit roof", "MCEditRoof"),
         ("Setup model", "MCSetup"), ("Update", "MCUpdate"), ("Live on / off", "MCLive"),
         ("Schedule", "MCSchedule"), ("Purge", "MCPurge")]
_OPEN = []


def run_command(name):
    """Run an MC command as if typed (aliases are registered by tools/install.py)."""
    return Rhino.RhinoApp.RunScript("_" + name if not name.startswith("_") else name, False)


class MindCanvasPanel(object):
    def __init__(self, doc, lib=None):
        self.doc = doc
        self.lib = lib or library.get()
        self.drivers = []
        self.last_drawing = None
        self._build()
        self.refresh_selection()

    # -- layout ------------------------------------------------------------------------------
    def _page(self, title, content):
        p = forms.TabPage()
        p.Text = title
        p.Content = content
        return p

    def _build(self):
        self.status = w.label("", wrap=True)
        tabs = forms.TabControl()
        for p in (self._page("Build", self._build_tab()), self._page("Selection", self._selection_tab()),
                  self._page("Drawing", self._drawing_tab()), self._page("Entourage", self._entourage_tab()),
                  self._page("Library", self._library_tab())):
            tabs.Pages.Add(p)
        self.tabs = tabs
        root = forms.DynamicLayout()
        root.Padding = drawing.Padding(4)
        root.AddRow(tabs)
        root.AddRow(self.status)
        self.form = forms.Form()
        self.form.Title = "Mind Canvas"
        self.form.Resizable = True
        self.form.Topmost = False
        self.form.MinimumSize = drawing.Size(340, 520)
        self.form.Content = root
        self.form.Closed += lambda s, e: _OPEN.remove(self) if self in _OPEN else None

    def _build_tab(self):
        rows_ = []
        for i in range(0, len(BUILD), 2):
            pair = BUILD[i:i + 2]
            rows_.append(tuple(w.button(lbl, (lambda c=cmd: self.command(c))) for lbl, cmd in pair))
        rows_.append(None)
        return w.rows(*rows_)

    def _selection_tab(self):
        self.lb_sel = w.label("", wrap=True)
        self.dd_asm = w.dropdown([], 0)
        self.tb_height = w.textbox("", None, 110)
        self.tb_base = w.textbox("", None, 110)
        self.dd_lod = w.dropdown(["(keep)"] + LODS, 0)
        return w.rows(w.button("Use the selected assemblies", self.refresh_selection), self.lb_sel,
                      (w.label("Assembly"), self.dd_asm), (w.label("Height"), self.tb_height),
                      (w.label("Base offset"), self.tb_base), (w.label("Detail level"), self.dd_lod),
                      (w.button("Apply", self.apply_selection), w.button("Edit assembly...", self.open_editor)),
                      None)

    def _drawing_tab(self):
        from ..drawing import styles
        self.style_names = styles.names(self.lib)
        st = scriptcontext.sticky.get("mindcanvas.drawing.settings", {})
        opts = [styles.get(n, self.lib).option for n in self.style_names]
        i = opts.index(st["scale"]) if st.get("scale") in opts else (opts.index("Eighth") if "Eighth" in opts else 0)
        self.dd_scale = w.dropdown(self.style_names, i)
        self.ck_tone = w.checkbox("Tone hatching", st.get("tone", True))
        self.ck_stip = w.checkbox("Ground stipple", st.get("stipple", True))
        self.ck_lod = w.checkbox("Set detail level for the scale (rebuilds)", st.get("lod", False))
        from ..cmd import drawing as drawcmd
        self.tb_folder = w.textbox(st.get("folder") or drawcmd.default_folder(self.doc))
        return w.rows((w.label("Scale"), self.dd_scale), self.ck_tone, self.ck_stip, self.ck_lod,
                      (w.label("Folder"), self.tb_folder),
                      w.button("Draw the active view (SVG + PNG)", self.draw_now),
                      (w.button("Section cut", lambda: self.command("MCSectionCut")),
                       w.button("Display setup", lambda: self.command("MCDisplaySetup"))),
                      (w.button("MCDrawing...", lambda: self.command("MCDrawing")),
                       w.button("Drawing tags", lambda: self.command("MCDrawingTag"))),
                      None)

    def _entourage_tab(self):
        st = scriptcontext.sticky.get("mindcanvas.entourage.settings", {})
        names = place.names(self.lib)
        self.lb_ent = w.listbox(names, 200)
        if st.get("name") in names:
            self.lb_ent.SelectedIndex = names.index(st["name"])
        elif names:
            self.lb_ent.SelectedIndex = 0
        self.tb_ent_h = w.textbox(units.format_inches(st.get("height", 0)) if st.get("height") else "", None, 110)
        self.ck_rand = w.checkbox("Random variation", st.get("random", True))
        self.ck_mirror = w.checkbox("Mirror", st.get("mirror", False))
        return w.rows(self.lb_ent, (w.label("Height (blank = library)"), self.tb_ent_h), self.ck_rand, self.ck_mirror,
                      (w.button("Place...", self.place_entourage), w.button("Face the view", self.face_view)),
                      (w.button("Capture from curves...", lambda: self.command("MCEntourage _Capture")),
                       w.button("Reload list", self.reload_entourage)),
                      None)

    def _library_tab(self):
        self.lb_lib = w.label("", wrap=True)
        self.update_library_label()
        return w.rows(self.lb_lib,
                      (w.button("Reload library", self.reload_library), w.button("Open folder", self.open_folder)),
                      (w.button("Assembly editor...", self.open_editor),
                       w.button("Capture profile...", lambda: self.command("MCProfileCapture"))),
                      None)

    # -- actions -----------------------------------------------------------------------------
    def say(self, msg):
        self.status.Text = msg
        Rhino.RhinoApp.WriteLine("Mind Canvas: " + msg)

    def command(self, name):
        ok = run_command(name)
        if not ok:
            self.say("{} did not run (run tools/install.py to register the MC commands).".format(name.split()[0]))
        return ok

    def refresh_selection(self):
        self.drivers = editor_mod.selected_drivers(self.doc)
        ds = self.drivers
        if not ds:
            self.lb_sel.Text = "Nothing selected: select walls, floors, roofs or curtain walls (or any of their parts)."
            w.set_items(self.dd_asm, [])
            self.tb_height.Text = self.tb_base.Text = ""
            return
        kinds_ = sorted(set(meta.get(d, meta.TYPE) for d in ds))
        asms = sorted(set(meta.get(d, meta.ASSEMBLY) for d in ds))
        self.lb_sel.Text = "{} selected ({}): {}".format(len(ds), ", ".join(kinds_), "; ".join(asms))
        if len(kinds_) == 1:
            w.set_items(self.dd_asm, ["(keep)"] + self.lib.assemblies(kinds_[0]), asms[0] if len(asms) == 1 else "(keep)")
        else:
            w.set_items(self.dd_asm, ["(keep)"])
        prm = meta.params(ds[0])
        h = prm.get("height")
        self.tb_height.Text = units.format_inches(float(h)) if h is not None and len(ds) == 1 else ""
        self.tb_height.Enabled = all(meta.get(d, meta.TYPE) in ("wall", "curtain_wall") for d in ds)
        self.tb_base.Text = units.format_inches(float(prm.get("base_offset", 0))) if len(ds) == 1 else ""
        lod = prm.get("lod", "detail")
        w.set_items(self.dd_lod, ["(keep)"] + LODS, lod if len(ds) == 1 else "(keep)")

    def apply_selection(self):
        """Apply the Selection tab to the assemblies it was filled from."""
        if not self.drivers:
            self.say("Nothing selected.")
            return []
        changes = {}
        try:
            if self.tb_height.Enabled and self.tb_height.Text.strip():
                changes["height"] = units.parse_length(self.tb_height.Text)
            if self.tb_base.Text.strip():
                changes["base_offset"] = units.parse_length(self.tb_base.Text)
        except ValueError as ex:
            self.say("Bad length: {}".format(ex))
            return []
        lod = w.selected(self.dd_lod)
        if lod in LODS:
            changes["lod"] = lod
        asm = w.selected(self.dd_asm)
        out = []
        for d in self.drivers:
            d = self.doc.Objects.FindId(d.Id)
            if d is None or d.IsDeleted:
                continue
            prm = meta.params(d)
            diff = dict((k, v) for k, v in changes.items() if prm.get(k) != v)
            if asm and asm != "(keep)" and asm != meta.get(d, meta.ASSEMBLY):
                if diff:
                    engine.update_params(self.doc, d, diff, self.lib)
                    d = self.doc.Objects.FindId(d.Id)
                out.append(engine.set_assembly(self.doc, d, asm, self.lib))
            elif diff:
                out.append(engine.update_params(self.doc, d, diff, self.lib))
        self.doc.Views.Redraw()
        warns = sum(len(r.warnings) for r in out)
        self.say("Rebuilt {} assembl{}{}.".format(len(out), "y" if len(out) == 1 else "ies",
                                                  " ({} warnings, see the command line)".format(warns) if warns else ""))
        for r in out:
            for msg in r.warnings:
                Rhino.RhinoApp.WriteLine("  warning: " + msg)
        self.refresh_selection()
        return out

    def open_editor(self):
        name = meta.get(self.drivers[0], meta.ASSEMBLY) if self.drivers else None
        try:
            from . import visual
            ed = visual.VisualAssemblyEditor(self.doc, self.lib, name=name, drivers=self.drivers)
        except Exception as ex:
            self.say(str(ex))
            return None
        ed.show()
        return ed

    def draw_now(self, view=None):
        """MCDrawing of the active view with the tab's settings; writes SVG + PNG."""
        from ..cmd import drawing as drawcmd
        from ..drawing import pipeline, styles
        style = styles.get(w.selected(self.dd_scale), self.lib)
        view = view or self.doc.Views.ActiveView
        folder = self.tb_folder.Text.strip().strip('"')
        scriptcontext.sticky["mindcanvas.drawing.settings"] = {
            "scale": style.option, "output": "SVG", "tone": bool(self.ck_tone.Checked),
            "stipple": bool(self.ck_stip.Checked), "lod": bool(self.ck_lod.Checked), "folder": folder}
        if self.ck_lod.Checked:
            pipeline.set_lod(self.doc, style)
        try:
            dwg = pipeline.make(self.doc, view, style, bool(self.ck_tone.Checked), bool(self.ck_stip.Checked))
        except Exception as ex:
            self.say("Drawing failed: {}".format(ex))
            return None
        name = "{}_{}_{}".format(drawcmd._slug(os.path.splitext(self.doc.Name or "untitled")[0]),
                                 drawcmd._slug(view.ActiveViewport.Name), style.option)
        paths = pipeline.write(dwg, os.path.join(folder, name))
        self.last_drawing = paths
        self.say("Drew {} lines, {} cut regions -> {}".format(dwg.stats["lines"], dwg.stats["regions"], paths[0]))
        return paths

    def _ent_settings(self):
        names = place.names(self.lib)
        i = self.lb_ent.SelectedIndex
        name = names[i] if 0 <= i < len(names) else (names[0] if names else None)
        try:
            h = units.parse_length(self.tb_ent_h.Text) if self.tb_ent_h.Text.strip() else 0.0
        except ValueError:
            h = 0.0
        return {"name": name, "height": h, "random": bool(self.ck_rand.Checked), "mirror": bool(self.ck_mirror.Checked)}

    def place_entourage(self):
        scriptcontext.sticky["mindcanvas.entourage.settings"] = self._ent_settings()
        return self.command("MCEntourage")

    def face_view(self):
        figs = [o for o in self.doc.Objects.GetSelectedObjects(False, False) or [] if place.is_entourage(o)]
        figs = figs or place.all_figures(self.doc)
        n = place.face_view(self.doc, figs, self.doc.Views.ActiveView.ActiveViewport)
        self.doc.Views.Redraw()
        self.say("Turned {} figure(s) to face '{}'.".format(n, self.doc.Views.ActiveView.ActiveViewport.Name))
        return n

    def reload_entourage(self):
        self.lib.refresh()
        w.set_items(self.lb_ent, place.names(self.lib))

    def reload_library(self):
        self.lib = library.get(force_reload=True)
        self.update_library_label()
        self.reload_entourage()
        self.say("Library reloaded.")

    def update_library_label(self):
        d = self.lib.data
        self.lb_lib.Text = "{} assemblies, {} materials, {} profiles, {} figures{}".format(
            len(d["assemblies"]), len(d["materials"]), len(d["profiles"]), len(d["entourage"]),
            "\nwarning: " + self.lib.warnings[0] if self.lib.warnings else "")

    def open_folder(self):
        import System
        System.Diagnostics.Process.Start("explorer.exe", library.LIBRARY_DIR)

    def show(self):
        self.form.Owner = w.owner()
        _OPEN.append(self)
        self.form.Show()

    def close(self):
        self.form.Close()


def open_panel(doc):
    """Show the panel (bring the open one to the front instead of opening a second)."""
    for p in _OPEN:
        try:
            if p.form.Visible:
                p.form.BringToFront()
                p.refresh_selection()
                return p
        except Exception:
            pass
    p = MindCanvasPanel(doc)
    p.show()
    return p
