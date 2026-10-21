"""The entourage library window (MCEntourageLibrary): pick 3D entourage by sight.

A floating window with a category list, a group filter, a search box and a picture per model
(the PNG thumbnails next to the OBJ files, library/entourage/thumbs).

    click         the model becomes the current one (what MCEntourage places next; blue frame)
    double-click  place it: runs MCEntourage (click points in the viewport, Enter to finish)
    Place         the same for the current model
    Swap selected the selected entourage becomes the current model (same place, same turn)
    Face view     turns the selected entourage (or all, when none is selected) to the view
    Add OBJ...    your own OBJ file into the library ("My Models"; MCEntourage Import)

Models of the selection get an orange frame.
"""

import os

import Eto.Drawing as drawing
import Eto.Forms as forms
import Rhino
import scriptcontext

from .. import library
from ..cmd import entourage as cmd
from ..entourage import catalog, place
from . import sectionview as sv
from . import widgets as w

STATE_KEY = "mindcanvas.entourage.window"
TILE = 116
COLS = 4
NEXT = (0, 120, 215)
SEL = (255, 120, 0)
HOVER = (150, 150, 150)
ALL = "All"
_BITMAPS = {}


def bitmap(path):
    if not path or not os.path.isfile(path):
        return None
    key = (path, os.path.getmtime(path))
    bmp = _BITMAPS.get(key)
    if bmp is None:
        bmp = _BITMAPS[key] = drawing.Bitmap(path)
    return bmp


def fmt_size(size):
    def fi(x):
        ft, inch = divmod(int(round(x)), 12)
        return "{}'-{}\"".format(ft, inch) if ft else "{}\"".format(inch)
    return " x ".join(fi(x) for x in size) if size else ""


class Tile(object):
    def __init__(self, owner, name):
        self.owner, self.name = owner, name
        self.hover = False
        d = forms.Drawable()
        d.Size = drawing.Size(TILE + 6, TILE + 6)
        d.Paint += self._paint
        d.MouseDown += self._down
        d.MouseDoubleClick += lambda s, e: self.owner.place(self.name)
        d.MouseEnter += lambda s, e: self._hover(True)
        d.MouseLeave += lambda s, e: self._hover(False)
        e = catalog.entry(owner.lib, name)
        d.ToolTip = "{}\n{} / {}\n{}\n{} by {} ({})".format(name, e.get("category", ""), e.get("group", ""),
                                                          fmt_size(e.get("size")), e.get("source", ""),
                                                          e.get("author", ""), e.get("license", ""))
        self.control = d
        lb = w.label(name, wrap=True)
        lb.Width = TILE + 6
        self.label = lb

    def _paint(self, sender, e):
        g = e.Graphics
        p = sv.Painter(g)
        p.rect((255, 255, 255), 3, 3, TILE, TILE)
        bmp = bitmap(catalog.thumb_path(self.owner.lib, self.name))
        if bmp is not None:
            g.DrawImage(bmp, drawing.RectangleF(3.0, 3.0, float(TILE), float(TILE)))
        else:
            p.text("(no picture)", 8, TILE / 2.0, (120, 120, 120), p.small)
        sel = self.name in self.owner.selected
        nxt = self.owner.current == self.name
        if sel:
            p.frame(sv._pen(SEL, 3.0), 1.5, 1.5, TILE + 3, TILE + 3)
        elif nxt:
            p.frame(sv._pen(NEXT, 3.0), 1.5, 1.5, TILE + 3, TILE + 3)
        elif self.hover:
            p.frame(sv._pen(HOVER, 1.5), 1.0, 1.0, TILE + 4, TILE + 4)
        tags = (["SELECTED"] if sel else []) + (["NEXT"] if nxt else [])
        x = TILE + 1
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
            self.owner.pick(self.name)


class EntourageWindow(object):
    def __init__(self):
        self.lib = library.get()
        self.current = cmd.current(self.lib)
        self.selected = set()
        self.tiles = []
        self._handlers = None
        self.dirty = False
        st = cmd.settings()
        cats = catalog.categories(self.lib)
        cat = st.get("category") if st.get("category") in cats else (cats[0] if cats else None)
        self.status = w.label("Click a model: MCEntourage places it next. Double-click: place it now.", wrap=True)
        self.category = w.dropdown(cats, cats.index(cat) if cat in cats else 0, self._category_changed, 150)
        self.group = w.dropdown([ALL], 0, self.fill, 150)
        self.search = w.textbox("", None, 140)
        self.search.TextChanged += lambda s, e: self.fill()
        try:
            self.search.PlaceholderText = "search"
        except Exception:
            pass
        self.count = w.label("")
        self.scroll = forms.Scrollable()
        self.form = forms.Form()
        self.form.Title = "Mind Canvas entourage"
        self.form.Resizable = True
        self.form.MinimumSize = drawing.Size(420, 320)
        self.form.Size = drawing.Size(COLS * (TILE + 18) + 50, 640)
        self.form.Closed += lambda s, e: self._closed()
        lay = forms.DynamicLayout()
        lay.Padding = drawing.Padding(6)
        lay.Spacing = drawing.Size(6, 6)
        lay.AddRow(self._bar(w.label("Category"), self.category, w.label("Group"), self.group))
        lay.AddRow(self._bar(w.label("Find"), self.search, self.count))
        lay.Add(self.scroll, yscale=True)
        lay.AddRow(self._bar(w.button("Place", lambda: self.place(self.current)),
                             w.button("Swap selected", self.swap), w.button("Face view", self.face_view),
                             w.button("Add OBJ...", self.add_obj), w.button("Reload", self.reload)))
        lay.AddRow(self.status)
        self.form.Content = lay
        self._groups()
        self.fill()

    @staticmethod
    def _bar(*controls):
        t = forms.TableLayout()
        t.Spacing = drawing.Size(6, 4)
        r = forms.TableRow()
        for c in controls:
            r.Cells.Add(forms.TableCell(c, False))
        r.Cells.Add(forms.TableCell(None, True))
        t.Rows.Add(r)
        return t

    # -- content ----------------------------------------------------------------------------
    def cat(self):
        return w.selected(self.category)

    def _groups(self):
        gs = [g for g in catalog.groups(self.lib, self.cat()) if g]
        w.set_items(self.group, [ALL] + gs, ALL)

    def _category_changed(self):
        self._groups()
        self.fill()

    def visible_names(self):
        text = (self.search.Text or "").strip()
        if text:
            return catalog.search(self.lib, text)
        grp = w.selected(self.group)
        return catalog.names(self.lib, self.cat(), None if grp in (None, ALL) else grp)

    def fill(self):
        ns = self.visible_names()
        self.tiles = []
        grid = forms.TableLayout()
        grid.Spacing = drawing.Size(8, 4)
        grid.Padding = drawing.Padding(4)
        row = None
        for i, n in enumerate(ns):
            t = Tile(self, n)
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
        grid.Rows.Add(forms.TableRow())
        self.scroll.Content = grid
        self.count.Text = "{} model(s)".format(len(ns))

    def reload(self):
        self.lib = library.get(force_reload=True)
        _BITMAPS.clear()
        cats = catalog.categories(self.lib)
        w.set_items(self.category, cats, self.cat())
        self._groups()
        self.fill()
        self.say("Library reloaded: {} models.".format(len(catalog.names(self.lib))))

    # -- selection following -----------------------------------------------------------------
    def hook(self):
        if self._handlers:
            return
        mark = lambda s, e: self._mark()
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

    def _mark(self):
        self.dirty = True

    def _idle(self):
        if self.dirty:
            self.dirty = False
            try:
                self.refresh()
            except Exception as ex:
                print("Mind Canvas entourage window: {}".format(ex))

    def selection(self):
        doc = Rhino.RhinoDoc.ActiveDoc
        if doc is None:
            return []
        return [o for o in doc.Objects.GetSelectedObjects(False, False) or [] if place.is_entourage(o)]

    def refresh(self):
        self.current = cmd.current(self.lib)
        self.selected = set(o.Attributes.GetUserString(place.NAME) for o in self.selection())
        for t in self.tiles:
            t.control.Invalidate()

    def _closed(self):
        self.unhook()
        try:
            scriptcontext.sticky[STATE_KEY + ".location"] = (self.form.Location.X, self.form.Location.Y)
        except Exception:
            pass        # closed before it was shown
        if scriptcontext.sticky.get(STATE_KEY) is self:
            del scriptcontext.sticky[STATE_KEY]

    # -- actions ----------------------------------------------------------------------------
    def say(self, msg):
        self.status.Text = msg
        Rhino.RhinoApp.WriteLine("Mind Canvas: " + msg)

    def pick(self, name):
        cmd.set_current(name)
        self.current = name
        d = catalog.entry(self.lib, name)
        self.say("Next: {} ({}, {}). Double-click or Place to put it in the model.".format(
            name, fmt_size(d.get("size")), d.get("source", "")))
        for t in self.tiles:
            t.control.Invalidate()

    def place(self, name):
        if not name:
            self.say("Click a model first.")
            return
        self.pick(name)
        if not Rhino.RhinoApp.RunScript("_MCEntourage", False):
            self.say("MCEntourage did not run (run tools/install.py to register the MC commands).")

    def swap(self):
        doc = Rhino.RhinoDoc.ActiveDoc
        objs = self.selection()
        if not objs or not self.current:
            self.say("Select placed entourage in the viewport, then click Swap selected.")
            return
        for o in objs:
            place.rebuild(doc, self.lib, o, name=self.current)
        doc.Views.Redraw()
        self.say("Replaced {} model(s) with {}.".format(len(objs), self.current))

    def face_view(self):
        doc = Rhino.RhinoDoc.ActiveDoc
        objs = self.selection() or place.all_figures(doc)
        n = place.face_view(doc, objs, doc.Views.ActiveView.ActiveViewport)
        doc.Views.Redraw()
        self.say("Turned {} model(s) to face the view.".format(n))

    def add_obj(self):
        if not Rhino.RhinoApp.RunScript("_MCEntourage _Import", False):
            self.say("MCEntourage did not run (run tools/install.py to register the MC commands).")
        self.reload()

    def show(self):
        self.form.Owner = w.owner()
        loc = scriptcontext.sticky.get(STATE_KEY + ".location")
        if loc:
            self.form.Location = drawing.Point(int(loc[0]), int(loc[1]))
        self.hook()
        self.form.Show()
        self.refresh()


def current_window():
    p = scriptcontext.sticky.get(STATE_KEY)
    try:
        if p is not None and p.form.Visible:
            return p
    except Exception:
        pass
    return None


def open_library():
    p = current_window()
    if p is not None:
        p.form.BringToFront()
        p.refresh()
        return p
    p = EntourageWindow()
    scriptcontext.sticky[STATE_KEY] = p
    p.show()
    return p
