"""The assembly palette (MCPalette): pick assemblies by sight.

A floating window with a tab per kind (walls, curtain walls, floors, roofs, windows & doors) and a
tile per library entry: its drawn layer section (walls, floors, roofs), a curtain-wall elevation or
a window / door glyph (eto/tiles.py).

    click         the tile becomes what the next MCWall / MCFloor / MCOpening ... builds (blue
                  frame, "NEXT"); selected assemblies of that kind take it at once (one undo step)
    double-click  opens the visual assembly editor on it (walls, floors, roofs, curtain walls)
    Paint...      click assemblies in the viewport to give them the chosen tile (MCPaintAssembly)

The palette follows the selection like the inspector: the tiles of the selected assemblies get an
orange frame and the palette turns to their tab.
"""

import Eto.Drawing as drawing
import Eto.Forms as forms
import Rhino
import scriptcontext

from .. import library, meta, props
from . import sectionview as sv
from . import tiles
from . import widgets as w

STATE_KEY = "mindcanvas.palette"
PAINT_KEY = "mindcanvas.palette.paint"
TABS = [("wall", "Walls"), ("curtain_wall", "Curtain walls"), ("floor", "Floors"), ("roof", "Roofs"),
        ("opening", "Windows & doors")]
TILE_W, TILE_H = 168, 92
COLS = 3
NEXT = (0, 120, 215)
SEL = (255, 120, 0)
HOVER = (150, 150, 150)


def names(lib, kind):
    if kind == "opening":
        from ..openings import core
        return core.type_names(lib)
    return lib.assemblies(kind)


def current(lib, kind, doc=None):
    """What the next assembly of a kind will be (MCOpening: its last type)."""
    if kind == "opening":
        from ..cmd import opening
        t = (scriptcontext.sticky.get(opening.STICKY) or {}).get("type")
        return t if t in names(lib, kind) else None
    from ..cmd import ui
    return ui.current_assembly(lib, kind, doc)


def set_current(lib, kind, name, doc=None):
    if kind == "opening":
        from ..cmd import opening
        st = dict(scriptcontext.sticky.get(opening.STICKY) or {})
        if st.get("type") != name:
            st["type"] = name
            st.pop("params", None)       # the new type's own size
        scriptcontext.sticky[opening.STICKY] = st
        return
    from ..cmd import ui
    ui.set_current_assembly(kind, name, doc)


def assembly_field(kind):
    return [f for f in props.fields(kind) if f.key == "assembly"][0]


def apply_to(doc, lib, drivers, name, snap=True):
    """Give drivers (all of one kind) the assembly / type `name` (one undo step). BuildResults."""
    if not drivers:
        return []
    kind = meta.get(drivers[0], meta.TYPE)
    return props.apply(doc, lib, drivers, assembly_field(kind), name, snap)


class Tile(object):
    def __init__(self, owner, kind, name):
        self.owner, self.kind, self.name = owner, kind, name
        self.hover = False
        d = forms.Drawable()
        d.Size = drawing.Size(TILE_W + 6, TILE_H + 6)
        d.Paint += self._paint
        d.MouseDown += self._down
        d.MouseDoubleClick += self._double
        d.MouseEnter += lambda s, e: self._hover(True)
        d.MouseLeave += lambda s, e: self._hover(False)
        d.ToolTip = name
        self.control = d
        lb = w.label(name, wrap=True)
        lb.Width = TILE_W + 6
        self.label = lb

    def _paint(self, sender, e):
        g = e.Graphics
        try:
            g.DrawImage(tiles.bitmap(self.owner.lib, self.kind, self.name, TILE_W, TILE_H), 3.0, 3.0)
        except Exception as ex:
            p = sv.Painter(g)
            p.text("({})".format(ex)[:40], 6, 6, (160, 0, 0))
        p = sv.Painter(g)
        sel = (self.kind, self.name) in self.owner.selected
        nxt = self.owner.next.get(self.kind) == self.name
        if sel:
            p.frame(sv._pen(SEL, 3.0), 1.5, 1.5, TILE_W + 3, TILE_H + 3)
        elif nxt:
            p.frame(sv._pen(NEXT, 3.0), 1.5, 1.5, TILE_W + 3, TILE_H + 3)
        elif self.hover:
            p.frame(sv._pen(HOVER, 1.5), 1.0, 1.0, TILE_W + 4, TILE_H + 4)
        tags = (["SELECTED"] if sel else []) + (["NEXT"] if nxt else [])
        x = TILE_W + 1
        for t in tags:
            tw = p.measure(t, p.small) + 6
            x -= tw
            p.rect(SEL if t == "SELECTED" else NEXT, x, 4, tw, 12)
            p.text(t, x + 3, 4, (255, 255, 255), p.small)
            x -= 3

    def _hover(self, on):
        self.hover = on
        self.control.Invalidate()

    def _down(self, sender, e):
        if e.Buttons == forms.MouseButtons.Primary:
            self.owner.pick(self.kind, self.name)

    def _double(self, sender, e):
        self.owner.edit(self.kind, self.name)


class Palette(object):
    def __init__(self):
        self.lib = library.get()
        self.selected = set()          # (kind, name) of the selected assemblies
        self.next = {}                 # kind -> current assembly
        self.tiles = []
        self.busy = False
        self.dirty = False
        self._handlers = None
        self.status = w.label("Click a tile: the next one you build; selected ones take it.", wrap=True)
        self.form = forms.Form()
        self.form.Title = "Mind Canvas palette"
        self.form.Resizable = True
        self.form.MinimumSize = drawing.Size(420, 300)
        self.form.Size = drawing.Size(COLS * (TILE_W + 18) + 60, 560)
        self.form.Closed += lambda s, e: self._closed()
        self.tabs = forms.TabControl()
        self.pages = {}
        self.build()

    # -- content ----------------------------------------------------------------------------
    def build(self):
        self.tiles = []
        self.tabs.Pages.Clear()
        self.pages = {}
        for kind, title in TABS:
            grid = forms.TableLayout()
            grid.Spacing = drawing.Size(10, 4)
            grid.Padding = drawing.Padding(6)
            row = None
            ns = names(self.lib, kind)
            for i, n in enumerate(ns):
                t = Tile(self, kind, n)
                self.tiles.append(t)
                if i % COLS == 0:
                    if row is not None:
                        grid.Rows.Add(row)
                    row = forms.TableRow()
                cell = forms.StackLayout()
                cell.Spacing = 2
                cell.Items.Add(forms.StackLayoutItem(t.control))
                cell.Items.Add(forms.StackLayoutItem(t.label))
                row.Cells.Add(forms.TableCell(cell))
            if row is not None:
                grid.Rows.Add(row)
            grid.Rows.Add(forms.TableRow())          # the rest of the height
            sc = forms.Scrollable()
            sc.Content = grid
            page = forms.TabPage()
            page.Text = "{} ({})".format(title, len(ns))
            page.Content = sc
            self.tabs.Pages.Add(page)
            self.pages[kind] = page
        lay = forms.DynamicLayout()
        lay.Padding = drawing.Padding(6)
        lay.Spacing = drawing.Size(6, 6)
        lay.AddRow(self.tabs)
        bar = forms.TableLayout()
        bar.Spacing = drawing.Size(6, 4)
        r = forms.TableRow()
        r.Cells.Add(forms.TableCell(w.button("Paint...", self.paint), False))
        r.Cells.Add(forms.TableCell(w.button("Edit assembly...", lambda: self.edit(*self.focus())), False))
        r.Cells.Add(forms.TableCell(w.button("Reload library", self.reload), False))
        r.Cells.Add(forms.TableCell(None, True))
        bar.Rows.Add(r)
        lay.AddRow(bar)
        lay.AddRow(self.status)
        self.form.Content = lay
        self.refresh()

    def focus(self):
        """(kind, name) the buttons act on: the open tab's NEXT tile."""
        kind = TABS[max(0, self.tabs.SelectedIndex)][0]
        return kind, self.next.get(kind)

    def reload(self):
        self.lib = library.get(force_reload=True)
        tiles._CACHE.clear()
        self.build()
        self.say("Library reloaded.")

    # -- selection following -----------------------------------------------------------------
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
                print("Mind Canvas palette: {}".format(ex))

    def refresh(self):
        doc = Rhino.RhinoDoc.ActiveDoc
        ds = props.selected(doc) if doc is not None else []
        self.selected = set((meta.get(d, meta.TYPE), meta.get(d, meta.ASSEMBLY)) for d in ds)
        self.next = dict((k, current(self.lib, k, doc)) for k, _ in TABS)
        kinds = [meta.get(d, meta.TYPE) for d in ds]
        for i, (k, _) in enumerate(TABS):
            if kinds and kinds[0] == k:
                self.tabs.SelectedIndex = i
                break
        for t in self.tiles:
            t.control.Invalidate()

    def _closed(self):
        self.unhook()
        scriptcontext.sticky[STATE_KEY + ".location"] = (self.form.Location.X, self.form.Location.Y)
        if scriptcontext.sticky.get(STATE_KEY) is self:
            del scriptcontext.sticky[STATE_KEY]

    # -- actions ----------------------------------------------------------------------------
    def say(self, msg):
        self.status.Text = msg
        Rhino.RhinoApp.WriteLine("Mind Canvas: " + msg)

    def pick(self, kind, name):
        """The tile becomes the next of its kind; the selected assemblies of that kind take it."""
        doc = Rhino.RhinoDoc.ActiveDoc
        set_current(self.lib, kind, name, doc)
        ds = [d for d in props.selected(doc) if meta.get(d, meta.TYPE) == kind] if doc is not None else []
        msg = "Next {}: {}".format(props.kind_name(kind), name)
        if ds:
            self.busy = True
            try:
                rs = apply_to(doc, self.lib, ds, name)
            except Exception as ex:
                self.say("Could not apply {}: {}".format(name, ex))
                return
            finally:
                self.busy = False
            for i in [d.Id for d in ds]:
                doc.Objects.Select(i, True)
            doc.Views.Redraw()
            secs = sum(r.seconds for r in rs)
            warns = [m for r in rs for m in r.warnings]
            msg += "; {} took it ({:.2f}s{})".format(props.kind_label(kind, len(ds)), secs,
                                                     ", {} warnings".format(len(warns)) if warns else "")
            for m in warns:
                Rhino.RhinoApp.WriteLine("  warning: " + m)
        self.say(msg)
        self.refresh()

    def paint(self):
        kind, name = self.focus()
        if not name:
            self.say("Click a tile first.")
            return
        scriptcontext.sticky[PAINT_KEY] = (kind, name)
        if not Rhino.RhinoApp.RunScript("_MCPaintAssembly", False):
            self.say("MCPaintAssembly did not run (run tools/install.py to register the MC commands).")

    def edit(self, kind, name):
        if kind == "opening" or not name:
            self.say("Window and door types are edited in library/openings (JSON)." if kind == "opening"
                     else "Click a tile first.")
            return
        from . import editor, visual
        doc = Rhino.RhinoDoc.ActiveDoc
        try:
            ed = visual.VisualAssemblyEditor(doc, self.lib, name=name, drivers=editor.selected_drivers(doc))
        except Exception as ex:
            self.say(str(ex))
            return
        ed.show()

    def show(self):
        self.form.Owner = w.owner()
        loc = scriptcontext.sticky.get(STATE_KEY + ".location")
        if loc:
            self.form.Location = drawing.Point(int(loc[0]), int(loc[1]))
        self.hook()
        self.form.Show()


def current_palette():
    p = scriptcontext.sticky.get(STATE_KEY)
    try:
        if p is not None and p.form.Visible:
            return p
    except Exception:
        pass
    return None


def open_palette():
    p = current_palette()
    if p is not None:
        p.form.BringToFront()
        p.refresh()
        return p
    p = Palette()
    scriptcontext.sticky[STATE_KEY] = p
    p.show()
    return p
