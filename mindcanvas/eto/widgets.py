"""Small Eto helpers for Rhino 8 CPython (pythonnet): Eto controls do not take keyword
properties in their constructors there, so these build and configure them in one call."""

import Eto.Drawing as drawing
import Eto.Forms as forms
import Rhino


def owner():
    try:
        return Rhino.UI.RhinoEtoApp.MainWindow
    except Exception:
        return None


def label(text, bold=False, wrap=False):
    c = forms.Label()
    c.Text = text
    if bold:
        c.Font = drawing.Font(c.Font.Family, c.Font.Size, drawing.FontStyle.Bold)
    if wrap:
        c.Wrap = forms.WrapMode.Word
    return c


def button(text, handler=None, width=None):
    c = forms.Button()
    c.Text = text
    if width:
        c.Width = width
    if handler is not None:
        c.Click += lambda s, e: handler()
    return c


def textbox(text="", handler=None, width=None):
    c = forms.TextBox()
    c.Text = text
    if width:
        c.Width = width
    if handler is not None:
        c.LostFocus += lambda s, e: handler()
    return c


def entry(text="", handler=None, width=None, placeholder=None):
    """A TextBox that commits (handler()) on Enter and when it loses focus."""
    c = textbox(text, handler, width)
    if placeholder:
        try:
            c.PlaceholderText = placeholder
        except Exception:
            pass
    if handler is not None:
        c.KeyDown += lambda s, e: handler() if e.Key == forms.Keys.Enter else None
    return c


def textarea(text="", height=80):
    c = forms.TextArea()
    c.Text = text
    c.Height = height
    c.Font = drawing.Fonts.Monospace(9)
    return c


def dropdown(items, index=0, handler=None, width=None):
    c = forms.DropDown()
    c.DataStore = list(items)
    if items:
        c.SelectedIndex = max(0, min(index, len(items) - 1))
    if width:
        c.Width = width
    if handler is not None:
        c.SelectedIndexChanged += lambda s, e: handler()
    return c


def combobox(items, text=""):
    c = forms.ComboBox()
    c.DataStore = list(items)
    c.Text = text
    return c


def checkbox(text, checked=False, handler=None):
    c = forms.CheckBox()
    c.Text = text
    c.Checked = checked
    if handler is not None:
        c.CheckedChanged += lambda s, e: handler()
    return c


def listbox(items, height=160, handler=None):
    c = forms.ListBox()
    c.DataStore = list(items)
    c.Height = height
    if handler is not None:
        c.SelectedIndexChanged += lambda s, e: handler()
    return c


def rows(*rows_, padding=6, spacing=4):
    """DynamicLayout with one row per argument (a control, or a tuple of controls; None = space)."""
    lay = forms.DynamicLayout()
    lay.Padding = drawing.Padding(padding)
    lay.Spacing = drawing.Size(spacing, spacing)
    for r in rows_:
        if isinstance(r, (tuple, list)):
            lay.AddRow(*r)
        else:
            lay.AddRow(r)
    return lay


def selected(dd):
    v = dd.SelectedValue
    return str(v) if v is not None else None


def set_items(dd, items, value=None):
    items = list(items)
    dd.DataStore = items
    if value in items:
        dd.SelectedIndex = items.index(value)
    elif items:
        dd.SelectedIndex = 0
