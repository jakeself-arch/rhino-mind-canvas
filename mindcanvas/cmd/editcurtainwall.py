"""MCEditCurtainWall: change the grid, joint style and infill of selected curtain walls.

Options: Height, BaseOffset, Spacing, Grid (Equal / Fixed / List), Bays (list widths),
Transoms (heights), Rows (infill per row, bottom -> top: V = vision, S = spandrel,
B = shadow box), Cell (click cells to cycle vision -> spandrel -> shadow box; the wall rebuilds
as you click), ClearCells, Style, Mullion (profile), Spandrel (Glass / Metal), Slabs (anchor
heights), Stack (unitized stack joints), Location, Flip, Detail. Enter applies."""

import Rhino

from .. import engine, library, meta, units
from ..kinds import curtainwall as cwkind
from ..curtainwall import settings as cwsettings
from . import ui
from .curtainwall import STYLE_OPTIONS
from .wall import LOD_OPTIONS

RI = Rhino.Input
GRID_OPTIONS = ["Equal", "Fixed", "List"]
REF_OPTIONS = ["Glass", "GlassCenter", "ExteriorFace", "MullionBack"]
SPANDREL_OPTIONS = ["Glass", "Metal"]
INFILL_CODES = {"v": "vision", "s": "spandrel", "b": "shadow_box", "sb": "shadow_box"}
CYCLE = ["vision", "spandrel", "shadow_box"]


def parse_lengths(text):
    out = []
    for tok in text.replace(";", ",").split(","):
        tok = tok.strip()
        if tok:
            out.append(round(units.parse_length(tok), 4))
    return out


def parse_rows(text):
    out = []
    for tok in text.replace(";", ",").replace(" ", ",").split(","):
        tok = tok.strip().lower()
        if not tok:
            continue
        t = INFILL_CODES.get(tok, tok)
        if t not in cwsettings.INFILLS:
            raise ValueError("unknown infill '{}' (use V, S, B or vision / spandrel / shadow_box)".format(tok))
        out.append(t)
    return out


def fmt_lengths(vals):
    return ", ".join(units.format_inches(units.parse_length(v)) for v in vals) or "none"


def fmt_rows(rows):
    inv = {"vision": "V", "spandrel": "S", "shadow_box": "B"}
    return ",".join(inv.get(r, r) for r in rows)


def get_string(prompt, default):
    res = RI.RhinoGet.GetString(prompt, True, default)
    if isinstance(res, tuple):
        rc, val = res[0], res[1]
    else:
        rc, val = res, default
    if rc != Rhino.Commands.Result.Success:
        return None
    return val if val is not None else default


def pick_cells(doc, drv):
    """Click cells of one curtain wall: each click cycles its infill and rebuilds."""
    lib = library.get()
    n = 0
    while True:
        go = RI.Custom.GetObject()
        go.SetCommandPrompt("Click a panel to cycle vision / spandrel / shadow box (Enter to finish)")
        go.SubObjectSelect = False
        go.GroupSelect = False
        go.AcceptNothing(True)
        did = str(drv.Id)
        go.SetCustomGeometryFilter(RI.Custom.GetObjectGeometryFilter(
            lambda o, g, ci: meta.get(o, meta.DRIVER) == did))
        if go.Get() != RI.GetResult.Object:
            break
        ref = go.Object(0)
        pt = ref.SelectionPoint()
        if not pt.IsValid:
            pt = ref.Object().Geometry.GetBoundingBox(True).Center
        doc.Objects.UnselectAll()
        drv = doc.Objects.FindId(drv.Id)
        ctx = cwkind.make_context(doc, lib, drv, meta.get(drv, meta.ASSEMBLY), meta.params(drv))
        hit = ctx.grid.cell_at(pt)
        if hit is None:
            continue
        cur = ctx.grid.infill(*hit)
        nxt = CYCLE[(CYCLE.index(cur) + 1) % len(CYCLE)] if cur in CYCLE else "vision"
        infill = dict(ctx.cw.get("infill") or {})
        cells = dict(infill.get("cells") or {})
        cells["{},{}".format(*hit)] = nxt
        infill["cells"] = cells
        infill.setdefault("rows", ctx.grid.row_types)
        r = engine.update_params(doc, drv, {"infill": infill}, lib)
        drv = doc.Objects.FindId(r.driver_id)
        ui.say("Cell {} -> {}".format(hit, nxt))
        n += 1
        doc.Views.Redraw()
    return n


def run():
    doc = ui.doc()
    lib = library.get()
    drivers = ui.select_drivers("Select curtain walls to edit", kind=cwkind.KIND)
    if not drivers:
        return ui.Result.Cancel
    d0 = drivers[0]
    p = meta.params(d0)
    asm = lib.assembly(meta.get(d0, meta.ASSEMBLY))
    st = cwsettings.merged(asm, p)
    opt_h = ui.length_option(units.parse_length(p.get("height", asm.get("default_height", 160))), doc)
    opt_base = ui.length_option(units.parse_length(p.get("base_offset", 0)), doc)
    opt_sp = ui.length_option(units.parse_length(st.get("spacing", 60)), doc)
    opt_flip = RI.Custom.OptionToggle(bool(p.get("flip", False)), "No", "Yes")
    grid_i = cwsettings.GRIDS.index(st.get("grid", "equal")) if st.get("grid") in cwsettings.GRIDS else 0
    style_i = list(cwkind.STYLES).index(st["style"])
    ref_i = list(cwkind.REFERENCES).index(st.get("reference", "glass"))
    lod_i = list(cwkind.LODS).index(p.get("lod", "detail"))
    spandrel_i = 1 if str(st["spandrel"].get("panel", "glass")).lower() == "metal" else 0
    bays = list(st.get("bays") or [])
    transoms = list(st.get("transoms") or [])
    slabs = list(st.get("slabs") or [])
    stack = list(st.get("stack") or [])
    rows = list((st.get("infill") or {}).get("rows") or ["vision"])
    mullion = st["mullion"]
    changes = {}

    gg = RI.Custom.GetOption()
    gg.AcceptNothing(True)
    while True:
        gg.SetCommandPrompt("Curtain wall: grid {} | transoms {} | rows {} | {} (Enter to apply)".format(
            fmt_lengths(bays) if GRID_OPTIONS[grid_i] == "List" else units.format_inches(
                units.to_inches(doc, opt_sp.CurrentValue)), fmt_lengths(transoms), fmt_rows(rows), mullion))
        gg.ClearCommandOptions()
        ui.add_option_double(gg, "Height", opt_h)
        ui.add_option_double(gg, "BaseOffset", opt_base)
        ui.add_option_double(gg, "Spacing", opt_sp)
        i_grid = ui.add_option_list(gg, "Grid", GRID_OPTIONS, grid_i)
        i_bays = gg.AddOption("Bays")
        i_tr = gg.AddOption("Transoms")
        i_rows = gg.AddOption("Rows")
        i_cell = gg.AddOption("Cell")
        i_clear = gg.AddOption("ClearCells")
        i_style = ui.add_option_list(gg, "Style", STYLE_OPTIONS, style_i)
        i_mull = gg.AddOption("Mullion")
        i_span = ui.add_option_list(gg, "Spandrel", SPANDREL_OPTIONS, spandrel_i)
        i_slabs = gg.AddOption("Slabs")
        i_stack = gg.AddOption("Stack")
        i_ref = ui.add_option_list(gg, "Location", REF_OPTIONS, ref_i)
        ui.add_option_toggle(gg, "Flip", opt_flip)
        i_lod = ui.add_option_list(gg, "Detail", LOD_OPTIONS, lod_i)
        res = gg.Get()
        if res == RI.GetResult.Nothing:
            break
        if res != RI.GetResult.Option:
            return ui.Result.Cancel
        oi = gg.OptionIndex()
        try:
            if oi == i_grid:
                grid_i = gg.Option().CurrentListOptionIndex
            elif oi == i_style:
                style_i = gg.Option().CurrentListOptionIndex
            elif oi == i_ref:
                ref_i = gg.Option().CurrentListOptionIndex
            elif oi == i_lod:
                lod_i = gg.Option().CurrentListOptionIndex
            elif oi == i_span:
                spandrel_i = gg.Option().CurrentListOptionIndex
            elif oi == i_bays:
                s = get_string("Bay widths, repeated (e.g. 60, 30)", ", ".join(str(b) for b in bays))
                if s is not None:
                    bays = parse_lengths(s)
                    grid_i = 2 if bays else grid_i
            elif oi == i_tr:
                s = get_string("Transom heights above the base (e.g. 30, 10'-6\")", ", ".join(str(t) for t in transoms))
                if s is not None:
                    transoms = parse_lengths(s)
            elif oi == i_rows:
                s = get_string("Infill per row, bottom to top (V vision, S spandrel, B shadow box)", fmt_rows(rows))
                if s is not None:
                    rows = parse_rows(s) or ["vision"]
            elif oi == i_slabs:
                s = get_string("Slab top heights above the base for anchors (blank = none)", ", ".join(str(v) for v in slabs))
                if s is not None:
                    slabs = parse_lengths(s)
            elif oi == i_stack:
                s = get_string("Unitized stack joint heights above the base", ", ".join(str(v) for v in stack))
                if s is not None:
                    stack = parse_lengths(s)
            elif oi == i_mull:
                names = sorted(n for n, pr in lib.data["profiles"].items() if pr.get("family") == "cw_mullion")
                picked = ui.pick_from_list("Mind Canvas - Mullion", "Mullion profile", names, mullion)
                if picked:
                    mullion = picked
            elif oi == i_cell:
                n = pick_cells(doc, doc.Objects.FindId(d0.Id))
                ui.say("{} cell(s) changed on the first curtain wall.".format(n))
                d0 = doc.Objects.FindId(d0.Id)
            elif oi == i_clear:
                changes["clear_cells"] = True
        except ValueError as ex:
            ui.say("  " + str(ex))

    for d in drivers:
        d = doc.Objects.FindId(d.Id)
        cur = cwsettings.merged(lib.assembly(meta.get(d, meta.ASSEMBLY)), meta.params(d))
        infill = dict(cur.get("infill") or {})
        infill["rows"] = rows
        if changes.get("clear_cells"):
            infill["cells"] = {}
        spandrel = dict(meta.params(d).get("spandrel") or {})
        spandrel["panel"] = SPANDREL_OPTIONS[spandrel_i].lower()
        upd = {
            "height": round(units.to_inches(doc, opt_h.CurrentValue), 4),
            "base_offset": round(units.to_inches(doc, opt_base.CurrentValue), 4),
            "spacing": round(units.to_inches(doc, opt_sp.CurrentValue), 4),
            "grid": cwsettings.GRIDS[grid_i],
            "bays": bays,
            "transoms": transoms,
            "slabs": slabs,
            "stack": stack,
            "infill": infill,
            "style": cwkind.STYLES[style_i],
            "mullion": mullion,
            "spandrel": spandrel,
            "reference": cwkind.REFERENCES[ref_i],
            "flip": bool(opt_flip.CurrentValue),
            "lod": cwkind.LODS[lod_i],
        }
        ui.report(engine.update_params(doc, d, upd, lib), "Updated:")
    doc.Views.Redraw()
    return ui.Result.Success
