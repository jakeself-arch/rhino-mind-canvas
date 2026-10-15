# Developing Rhino Mind Canvas

Read `PLAN.md` first. This file is the contract for anyone adding components.

## Runtime
Rhino 8.35, CPython **3.9** (no `match`, no `X | Y` type unions). RhinoCommon via pythonnet:
- `from Rhino.Geometry import *` does NOT work — use `G = Rhino.Geometry; G.Point3d(...)`.
- Enum members named `None` need `getattr(Enum, "None")`.
- Methods with `ref`/`out` params return tuples, e.g. `go.AddOptionDouble(...)` → `(index, opt)`.

## Running code in Rhino (tests / experiments)
Use the Rhino MCP tools (ToolSearch "rhino"). **Spawn your own slot** (`spawn_slot`, version "8")
and pass it on every call; close it when done. Then:

```python
import sys, runpy
ROOT = r"C:\Users\jakob\Desktop\BAC\Rhino Mind Canvas"
if ROOT not in sys.path: sys.path.insert(0, ROOT)
from mindcanvas import dev; dev.reload_all()          # pick up code edits
runpy.run_path(ROOT + r"\tests\test_phase0.py")["run"](__rhino_doc__)
```
Use `__rhino_doc__` as the document (never `scriptcontext.doc`). Call
`engine.setup_document(doc)` first — the default 0.01 ft tolerance drops thin layers.
Screenshots: `get_viewport_image` output is too large for the tool channel; instead use
`runpy.run_path(ROOT + r"\tests\capture.py")["capture"](doc, "name", view="Perspective", mode="Shaded")`
which writes `docs/captures/name.png` — then view it with the Read tool. `box=` (a BoundingBox) zooms to a region.
To test commands: `tools/install.py` registers aliases, then `run_command("MCUpdate _Enter")`.

## Geometry conventions
- Model units vary (the user's files are in **feet**). Library values are **inches**.
  Convert with `ctx.u(value)` (accepts `5.5`, `"3-5/8"`, `"1'-6\""`).
- Wall driver: horizontal curve. Signed offsets: **positive = exterior = LEFT of the curve
  direction**. `ctx.curve` is already oriented (closed = clockwise, flip applied).
- `LayerBand`: `d_ext > d_int` are the band's faces as signed offsets from the driver.
  `band.d_mid`, `band.thickness`. Wall spans `ctx.base_z` .. `ctx.base_z + ctx.height`;
  `ctx.z_range(band)` honors `extend_bottom` / `extend_top` options.
- `geo.offset(curve, d, tol)`, `geo.band_region`, `geo.band_solids`, `geo.frame_at(curve, t, z)`
  (X = tangent, Y = exterior, Z = up), `geo.kink_parameters(curve)` (corner params),
  `geo.box(plane, x0, x1, y0, y1, z0, z1)`, `geo.extrude_profile(profile_curve, plane, h)`.
- Profiles: `profiles.build(defn, ctx.s)` → list of closed XY curves in model units
  (X = width along wall, Y = depth through wall). Types: rect, c_stud, track, angle, tube, custom.

## Writing a component
One file in `mindcanvas/components/`, auto-registered:
```python
from .base import Component, Part, register

@register
class Framing(Component):
    name = "framing"
    def build(self, ctx, band):
        opts = ctx.options(band)        # layer options merged with per-wall overrides
        ...
        return [Part(brep, "Wood Framing", role="stud", extra={"length": 92.625})]
```
- `Part(geometry, material, role, extra={...})` — `extra` becomes user text `mc.x.<key>`;
  use `length` (inches) and `area` (in²) so `MCSchedule` can total them.
- Repeated identical members → block instances: `idx = ctx.block("MC Stud 2x6 92.625", [brep_at_origin], material)`
  then `Part(material=..., role="stud", block=idx, xform=Rhino.Geometry.Transform.PlaneToPlane(Plane.WorldXY, frame))`.
  The block name MUST encode every dimension that affects the geometry.
- Respect `ctx.lod`: `"schematic"` → fall back to a plain solid band
  (`ctx.solids(band.d_ext, band.d_int)`); `"design"` → members; `"detail"` → everything.
- Cross-layer access: `ctx.bands`, `ctx.band(name)`, `ctx.neighbor(band, ±1)`.
  Assembly-level `extras` (list of specs with `component`, `name`, `material`, `options`) are built
  with a zero-thickness pseudo band — use them for things spanning several layers (ties, flashing).
- `ctx.warn(msg)` for non-fatal problems. Raise only when nothing sensible can be built.

## Per-wall layer stacks
A wall may carry its own stack in `params["layers"]` (set by `MCLayers` / `engine.set_layers`);
it replaces `assembly["layers"]`. Always get a wall's layers via
`kinds.wall.effective_layers(lib, driver)` / `layer_specs(lib, assembly, params)`, never
`assembly["layers"]` directly. Layer specs may be presets (`{"preset": name, ...}`) —
expand with `lib.resolve_layer(spec)`. Consequences for components:
- Don't assume a layer's position (e.g. brick may be the interior-most layer) or a fixed
  name (duplicates get " (2)"); find neighbors through `ctx.bands`.
- Assembly `extras` come from the assembly and may not match an edited stack — be defensive.

## Openings (windows, doors)
`mindcanvas/openings/` (`core.py` drivers + placement + cutters, `geom.py` section sweeps and
mitered frames, `units.py` unit geometry). An opening is a driver of the HOSTED kind
`opening` (`kinds/opening.py`): `mc.host` = host driver id, params in inches (width, height,
sill, station = distance along the host curve as drawn, swing, hinge, head, overrides).
Its parts belong to the **host** (`mc.driver` = host id) and carry `mc.x.opening`.
`engine.build(opening)` re-reads the opening's line (`sync_from_geometry`) and builds the host;
after every host build `engine` moves each opening line to where the host put it.

- **Hosts** resolve openings while making their context: `ctx.openings = openings.resolve(ctx,
  driver_obj, place)` where `place(ctx, station, half_width) -> (plane, s)` is host specific
  (`kinds/wall.place_opening` keeps openings clear of ends and corners). A future host
  (curtain wall, floor, roof) only needs its own `place` and to build `openings.units` — or
  its own unit builder — for each record.
- **`Opening` record** (model units): `plane` (origin on the oriented driver at z = 0, X along
  the host, Y exterior), `op.local(pt)` / `op.pt(x, y, z)` (y = signed offset like band d),
  unit `W, H, z0, z1`, rough opening `rx, rz0, rz1`, frame faces `y_fe, y_fi`, wall faces
  `y_ext, y_int`, `masonry_ext` (the exterior brick band, if any), `t` = merged type dict
  (`core.DEFAULTS[category]` ← library type ← params["overrides"]).
- **Components** cut themselves: `openings.cut(ctx, breps, band)` (rough opening in the backup,
  unit + sealant joint in cladding in front of the frame), or `op.cutter(...)` +
  `openings.subtract(...)` for custom holes. Members along the wall: `opgeom.sweep(ctx, op,
  poly_yz, x0, x1)` (straight prism, or lofted along the trimmed host curve).
  Framing (`Layout._openings`, `_wood_openings`, `_metal_openings`) and masonry (`MOpening`,
  `Veneer.spans / _apply_openings / _mo_parts`) read the records directly.
- Opening types are data (`library/openings/*.json`); add keys to `core.DEFAULTS` with a
  default so existing types keep working.
- Live mode: moving / deleting an opening rebuilds its host; deleting a host deletes its
  openings. Wrap engine-side edits of driver objects in `live.quiet()`.

## Curtain walls
Kind `curtain_wall` (`kinds/curtainwall.py`), code in `mindcanvas/curtainwall/`. It has no layer
stack and no components; the kind builds everything itself.

- **Settings** (`settings.py`): `merged(assembly, params)` = `DEFAULTS` ← assembly ← driver
  params ← `params["overrides"]` (dicts merge, lists replace). Add a new key to `DEFAULTS` with a
  default so existing assemblies keep working. `Dims(lib, settings)` resolves every section
  dimension in **inches** (IGU thickness `T`, gasket `g`, bite, spline, cap, SSG joint, split, ...)
  and the mullion / transom profiles (`mp`, `tp`: `w`, `D`, `t`, `material`, `solid`).
  `V_STYLE` / `H_STYLE` map a system style to the joint style of verticals and horizontals
  (captured / ssg / butt / split / unit).
- **Context**: `make_context` returns a `BuildContext` with `ctx.cw` (settings), `ctx.dims`,
  `ctx.yG` (y of the exterior glass face; y = signed offset, + = exterior, as for walls),
  `ctx.grid`, one pseudo band "Curtain Wall" (`d_ext` = front of caps, `d_int` = back of
  mullions; used by section cuts and openings) and `ctx.openings`.
- **Grid** (`grid.py`, model units): `vertices` (kind `start` / `end` / `inline` / `corner`,
  `X` = mullion axis on the bisector, `turn` in degrees, + = concave), `bays` (straight chords:
  `frame(u, z)`, `local(p)`, `world(u, y, z)`), `horizontals` (sill / transom / stack / head),
  `rows`, `infill(bay, row)`, `cell_at(point)`.
- **Sections** (`sections.py`): 2D member sections in (a, q) inches — a across the member, q depth
  behind the glass face. `vertical(dims, kind, lod)` / `horizontal(dims, kind, lod)` return a
  `Section` with `members` (role, material, loops, `cover`, `detail`), the glass edges
  `edge_neg` / `edge_pos`, `struct_half` / `cover_half` (where crossing members stop) and
  `setting` (setting block seat). A new joint style = a new section function + an entry in
  `V_STYLE` / `H_STYLE`.
- **Build** (`build.py`): every bay end gets a `BayEnd` (glass edge u, `struct` / `cover` /
  `miter` cut lines); horizontals are swept between those lines (trimmed at facets), verticals
  are extruded plan sections, corners are built in world plan (L tube from two legs + covers
  clipped on the bisector). **Every part is a block instance** whose name is
  `MC CW <role> <dims> #<hash>`; the hash covers every number that shapes it, so identical
  members share a definition. Parts carry `mc.x.length` (mullions, transoms, caps, plates) and
  `mc.x.area` + `mc.x.panel` + `mc.x.cell` on the first lite of each panel.
- **Openings** in a curtain wall: `kinds.curtainwall.place_opening` snaps an opening to the bay
  nearest its station; `Builder._openings` sizes it to the bay's clear width, adds a head transom
  and drops the infill (and, for doors, the sill) below it; the unit comes from `openings.units`.
- **Schedule**: `kinds.curtainwall.summary(ctx)` (panels per infill type with nominal areas,
  bays, rows) feeds `schedule.curtain_walls`.
- Drawing: `drawing.sectioncut.wall_frame` works for any kind with bands (a curtain wall uses the
  bay chord under the point); `sectioncut.make_plan` makes a horizontal cut for plan details.

## Floors and roofs
Kinds `floor` (`kinds/floor.py`, code in `mindcanvas/floors/`) and `roof` (`kinds/roof.py`, code
in `mindcanvas/roofs/`). Both are driven by a **closed horizontal boundary**: for floors the outside
face of the rim, for roofs the plate line (outside face of the wall framing). Shared geometry is in
`mindcanvas/hgeo.py`.

- **Local frames** (`hgeo.Frame(xdir)`): x = a horizontal direction, y = Z × x, z = world z
  (frames sit at z = 0). Members are **section polygons in (x, z) extruded along y**
  (`hgeo.prism_xz`), built once at y = 0 and placed as block instances
  (`frame.placed(y, x) * Translation(0, 0, z)`); block names hash the section and the extrusion
  length (`hgeo.tag`). Never cache a block by length only when its geometry sits at an absolute y.
- **Irregular footprints**: `hgeo.slab_between(poly, below=[lines], above=[lines])` builds the
  solid over a plan polygon between lines z = a + b·x from planar faces (strips where the
  envelope changes line, unioned). Avoid `Brep.Trim(plane)` (it sometimes keeps the wrong side —
  `hgeo.keep_below` checks the centroid and falls back to `Brep.Split`) and Booleans against a
  footprint prism (coplanar end faces fail).
- **Floor bands**: `LayerBand.d_ext` / `d_int` are absolute top / bottom z. `reference`
  (framing_bottom | framing_top | top | bottom) + `base_offset` place the stack; the joist layer is
  the first `joists` (or `core`) layer. `ctx.jdir` = joist direction (`span`: short | long |
  degrees), `ctx.poly_world`, `ctx.local_poly(frame)`. Builders per component in
  `floors/build.py` (`BUILDERS`: solid / membrane / void / joists / deck); add a component there.
- **Joist systems**: `floors/joists.system(lib, "wood")` → `wood_joists` (`library/framing/joists.json`,
  `"use": "joists"`); `select_member` picks by layer thickness or keeps the nominal depth across a
  system swap; `layer_thickness` fits the layer (metal + 2 × track t). `JoistLayout`: rim inset,
  joists every `spacing` from the boundary's low y, segments = chords of the rim's inside polygon
  for both joist sides (L-shapes work), blocking `rows()`, `neighbors()`.
- **Roof settings** (`roofs/shape.py`): `DEFAULTS` ← assembly ← params (`trim` merges). `faces()`
  returns one `Face` per roof plane: frame (x = uphill, y = ridge direction), `poly` (overhang
  footprint, CCW, clipped at the ridge for gables), `plate` (boundary), `v_ridge`, slope `p`,
  `zb` (rafter bottom line: wood through the inner edge of the eave wall at plate height = full
  birdsmouth seat; metal through the outer edge), `zt`, and `lines[band.index] = (bottom, top)`
  for every roof-plane layer (normal offsets; `taper` layers tilt their top). Roof bands carry
  normal offsets from the rafter bottom; ceiling bands (`ctx.ceiling_bands`) absolute z.
- **Roof builder** (`roofs/build.py`, `Builder.run`): roof-plane layers per face (shingle courses,
  eave membrane split, edge nailers on low-slope roofs), rafters per footprint chord with
  birdsmouths at each bearing (low: seat at the inner edge; high: at the outer edge), barge
  rafters, ridge, eave trim (fascia, sub-fascia, soffit + vent + nailer, drip edge, K gutter on
  low eaves), rake trim (rake board, drip, lookouts), oblique-edge fascia bands, ridge cap,
  ceiling stack (ceiling joists beside the rafters, heel-cut under the rafter tops; insulation and
  blankets kept under the roof minus `baffle_gap`). `self.layer` sets the parts' `mc.layer`.
- **Schedule / drawing**: `kinds.floor.summary`, `kinds.roof.summary` feed `schedule.floors_roofs`;
  `schedule.framing_members` is the joist / rafter cut list (roles in `FRAMING_ROLES`). A kind may
  define `section_frame(ctx, point) -> (plane, extents)`; `drawing.sectioncut.wall_frame` uses it
  (floors: along the joists; roofs: along the slope of the face under the point).
- **Phase 7 hooks**: floors / roofs know nothing about walls yet: `base_offset` (wall height),
  roof `wall_depth` / `wall_ext` / `wall_int`, floor layer `inset`.

## Library files
Add your own files rather than editing someone else's: `library/materials/<topic>.json`,
`library/profiles/<topic>.json`, `library/framing/<system>.json`, `library/assemblies/<topic>.json`,
`library/openings/<topic>.json`. Curtain walls: `library/assemblies/curtainwalls.json`,
`library/profiles/curtainwall.json`, `library/materials/curtainwall.json`. Floors and roofs:
`library/assemblies/floors.json`, `library/assemblies/roofs.json`, `library/framing/joists.json`,
`library/profiles/floors_roofs.json`, `library/materials/floors_roofs.json`.
Material entries: see `library/materials/core.json` (color, render, section, print).

## Commands
Command logic lives in `mindcanvas/cmd/<name>.py` with `run()`; `commands/MC<Name>.py` is a
6-line entry script (copy an existing one). Shared helpers in `mindcanvas/cmd/ui.py`
(`select_drivers`, `pick_from_list`, `pick_assembly`, option helpers, `report`).
Engine API (any kind, incl. curtain walls): `engine.create / build / build_many / update_params / set_override / set_assembly /
rebuild_all / add_opening / update_opening / delete_openings`.

## Version control
GitHub: `jakeself-arch/rhino-mind-canvas`, branch `main`. Commit when a phase or feature is done
and its tests pass; run the regression tests (`tests/test_phase*.py`, `test_layers.py`) first.
Don't commit `docs/captures/` churn from exploratory runs unless the images document a result.

## Ownership while agents work in parallel
Only edit the files your brief assigns to you. If you need a change in a shared module
(`engine.py`, `geo.py`, `components/base.py`, `kinds/wall.py`, `docutil.py`, `cmd/ui.py`),
make the smallest additive change possible (new helper function, no signature changes) and
say so in your final report.
