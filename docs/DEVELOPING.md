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
- **Joins** (Phase 7, below): floors get per-edge `ctx.join_insets`, roofs their `wall_depth` /
  `wall_ext` / `wall_int` from the walls along their boundary; `base_offset` is still set by hand.

## Joins (Phase 7)
`mindcanvas/joins/`: `plan.py` (pure 2D rules, no Rhino: testable anywhere), `find.py` (detection
from the drivers), `geom.py` (geometry). Joins are computed from **drivers only** (curves, stacks,
params), never from generated parts, so build order never matters.

- **Wall ends** (`plan.Side`: driver end point P, unit tangent t, n = Z x t, `out` +1 at the end /
  -1 at the start, face offsets ext >= cext >= cint >= int). An `EndCut` is a list of zones
  (d_hi, d_lo, line) exterior -> interior; the face of a layer at offset d stops where
  `P + n d + s t` crosses its zone's line (`cut.ext(d)` = how far past the driver end; `cut.cap`
  = the stepped end polyline between two faces). Rules: `plan.l_cut` (wrap / miter / butt; zones
  "outer", "core", "inner" relative to the corner), `plan.t_cut` (core / butt), `plan.t_notch`
  (host notch polygon), `plan.l_backer` / `plan.t_backers` (extra studs in a host's framing).
- **Detection** (`find.py`): L = both end lines cross near both ends (other wall's thickness + 1"),
  15..165 degrees, mutual; T = the end lies within the host (faces +- 1"), away from its ends.
  Primary at an L: `join_priority`, then the thicker core, then the larger id (both walls agree).
  Params: `joins` = {"start" / "end": auto | wrap | miter | butt | none}, `join_priority`.
  Floors / roofs: a wall is aligned with a boundary edge when the edge lies within the wall's
  thickness + 1" and is parallel (`find.aligned_edges`, `Edge.sigma` = +1 when the wall's exterior
  faces away from the polygon). Heights: wall top = floor framing bottom / roof plate (+- 1/2").
- **ctx.joins** (walls, `find.Joins`): `ends` (EndCuts), `notches` (plan polygon, d range, z
  range: subtracted from layers wholly inside that d range), `backers`, `z_top` (band index ->
  model units added to the band top unless the layer sets `extend_top`), `roofs` (roof contexts
  to fill up to), `partners`, `notes` (MCJoin Report). `ctx.join_partners` (any kind) = ids
  rebuilt with this assembly.
- **Components**: `ctx.solids(d_a, d_b, z0, z1)` already stops at join cuts and notches (via
  `joins.geom.band_solids`). Components that build their own geometry along `ctx.curve` must use
  `joins.geom.centerline(ctx, d)` / `outline(ctx, d_a, d_b)` / `band_solids(...)` instead
  (framing does: centerline, tracks, cavity; masonry: `JoinEnd` on the first / last leg and bed
  joints). Brick ties, base flashing and shelf angles still run to the driver ends.
- **Roof infill** (`geom.roof_infill`, built by the wall kind): every layer from its top up to the
  roof's rafter bottom line where that is > 1" higher (framing: gable studs on the stud grid +
  cavity fill), per face, clipped at a gable's ridge. Exterior layers are lowered first to the
  lowest rafter-bottom point over them (eaves).
- **Engine**: `build()` rebuilds `ctx.join_partners` plus the ids stored at the previous build
  (user text `mc.joined`) with `joined=False` (no further cascade); `BuildResult.partners` /
  `.joined`. `rebuild_all` / `build_many` build everything once, then the partners not built yet.
  Live mode: deleting a driver queues its `mc.joined` partners.
- **Testing without Rhino**: `python tests/offline/test_join_plan.py` (plan.py imports nothing from
  Rhino) and `python tests/offline/test_join_find.py` (find.py against a small
  fake of `Rhino.Geometry` (straight polylines) for quick logic checks; geometry needs Rhino
  (`tests/test_phase7.py`).

## UI, entourage, trims (Phase 8)
- **Eto** (`mindcanvas/eto/`): views only; the logic is in plain modules (`asmedit.AssemblyModel`,
  `entourage.place`, `trims`) so tests drive it without clicks. Under Rhino 8 CPython (pythonnet)
  Eto controls take no keyword properties in their constructors: use the helpers in
  `eto/widgets.py` (`label`, `button(text, handler)`, `dropdown(items, index, handler)`, `rows(...)`).
  Python lists work as `DataStore`. Modeless windows (`forms.Form`) are kept in a module list
  (`_OPEN`) so they outlive the command's script; handlers capture `self`. Tests build the views,
  set control values and call the `on_*` handlers (see `tests/test_phase8.py`).
- **Entourage** (`mindcanvas/entourage/`): `shapes.py` is pure Python: a generator
  `fn(params, random.Random) -> [Layer]` registered with `@generator("name")`; a `Layer` is one flat
  card at a `depth` (smaller = nearer the viewer) with closed `loops` (unioned into the card) and
  open `lines`, in inches (x across, y up from the ground). `place.py` builds blocks named
  `MC Entourage <name> #<hash of the shape>` (definition in the XZ plane, facing -Y; cards
  `GAP` = 1/4" apart in depth) and instances with `mc.kind = entourage`, `mc.entourage`,
  `mc.params` (seed, mirror, overrides), `mc.role = entourage`, `mc.draw = nocut,notone`.
  `drawing/scene.py` collects curves only from blocks whose name starts with `MC Entourage `
  (`LINE_BLOCKS`); `pipeline.py` classes their HLD segments as `entourage`.
  Quick offline check: `python -c "import sys; sys.path[:0]=['tests/offline/fake','.']; from
  mindcanvas.entourage import shapes; ..."` (needs the fake `Rhino` only for `units`).
- **Capture** (`mindcanvas/capture.py`): `read(doc, curves, plane, base)` -> (loops, lines) in inches
  (loops counter-clockwise, largest first); `profile_definition` / `entourage_definition`. Save with
  `Library.save_entry(section, name, defn, filename=None)` (default `zz_user_<section>.json`);
  `remove_entry`, `is_user_entry`. Profiles of type `custom` may have `loops` (outline + holes).
- **Sweep component** (`components/sweep.py`): an extra (assembly `extras` or the wall's
  `params["extras"]`, both built by `kinds/wall.build`) with options `profile`, `face`, `z`, `offset`.
  The rail is `joins.geom.centerline(ctx, d)` of the face, the profile plane X = out of the face, Y = up;
  `Brep.CreateFromSweep` miters polyline corners; holes are swept and subtracted; openings cut it
  via `op.cutter`. `mindcanvas/trims.py` adds / removes per-wall trims (`MCTrim`).
- **Assembly editor model** (`mindcanvas/asmedit.py`): edits a copy of an assembly; layer edits
  expand presets first (a shared preset is never changed); `save_as` refuses library names;
  `apply` needs a saved model.

## Mass drivers (Phase 9)
`mindcanvas/masses.py`. A **mass** is a closed solid (Brep / Extrusion) the user pushes and pulls
with the gumball; it controls existing drivers and never replaces them (the kinds are unchanged).
User text: `mc.kind = mass` (`meta.MASS_KIND`, `meta.is_mass`; NOT a driver, so `all_drivers`
never returns it), `mc.type` (what it drives: `opening` in Phase 9), `mc.assembly` (the opening
type for new openings), `mc.params` (`snap`, `swing`, `hinge`, `head`). Masses live on
`docutil.MASS_LAYER` (`MindCanvas::_Masses`): translucent render material, plot weight -1, layer
tag `exclude`, and `drawing/scene.py` skips the layer, so they never reach a drawing.

- **Opening masses**: `crossings(doc, lib, brep, warnings)` intersects the mass with every
  candidate wall's **mid surface** (the oriented driver offset to the middle of the stack, extruded
  vertically; `WallInfo` gets the stack offsets without building the wall). The cut's bounding
  rectangle in (station along the driver as drawn, z) is the **rough opening**; its width is
  measured square to the wall at the middle of the cut (curved walls: the chord). Cuts that span a
  kink of the driver or reach a wall end are rejected (no corner openings); a cut that is not a
  rectangle warns and uses its bounding rectangle. Curtain walls are not hosts yet.
- **Unit size**: `unit_params(type, ro)`: width = RO - 2 shim; windows sill = RO bottom + shim,
  height = RO - 2 shim; doors sill = max(RO bottom, 0), height = RO top - shim - sill. The opening
  keeps `params["ro"]` = {width, bottom, top} (inches above the host base) so SnapHead can move
  the unit without moving the mass. `rough_opening(t, params)` is the inverse (uses "ro" if present).
  `core.update` and `core.sync_from_geometry` drop "ro" when a size / position changes by number or
  by the line, so the mass follows the unit again.
- **Links**: each opening driver carries `mc.mass` (mass id) and `mc.mass.frame` (its plane at the
  last host build: origin + X axis). One mass may drive openings in several walls.
- **mass -> openings**: `sync(doc, mass)` creates / updates / deletes the mass's openings (only
  width / height / sill / station / ro are written to existing openings: type, swing, hinge and head
  stay as edited) and builds each affected host once, inside `_driving()` + `live.quiet()`.
  `make(doc, solid, type, params)` tags a solid and syncs it; `from_opening(doc, op)` boxes an
  existing opening (MCOpeningMass Convert / wall click); `release(doc, mass_id)` handles a deleted
  mass; `engine.delete_openings` deletes masses left without openings (`delete_unused`).
- **openings -> mass**: `engine.build` calls `masses.follow(doc, ctx)` after placing the opening
  lines. Unless a mass sync is driving, a mass with exactly ONE opening is moved rigidly from the
  stored frame to the new one (the wall moved / turned) and then scaled / moved in the opening's
  frame (X along the wall, Z up; its depth is kept) until its cut matches the rough opening
  (`target_local`: centered on the opening's station, not where the host may have nudged it clear
  of a corner). Masses with several openings only follow their own edits. Every mass edit of the
  engine is wrapped in `live.quiet()`.
- **Live mode** (`live.py`): a Replace of a mass queues it; Idle runs `masses.sync`. A deleted mass
  is queued too; Idle runs `masses.release`. Live handlers are closures made at `enable()`: after
  reloading the code, toggle MCLive (tests call `live.disable(); live.enable()`).
- **Not yet**: moving a wall into a free mass does not open it (a mass only syncs on its own
  edits); masses for curtain-wall doors; corner windows.
- **Testing**: `tests/test_phase9.py` calls the live Idle handler directly
  (`scriptcontext.sticky[live.STICKY_KEY]["handlers"][2](None, None)`) after `doc.Objects.Transform`
  / `Replace` / `Delete`, which is what Rhino does after a gumball edit.
- A box with one opening rides along when its opening's frame moves (its wall moved, e.g. by a wall
  mass), even if it still cuts the wall; only a frame that turned around while the box still fits
  (a flipped wall) leaves it in place.

## Wall masses (Phase 10)
`mindcanvas/wallmasses.py`; `masses.sync` / `masses.release` dispatch to it for `mc.type = wall`.
User text: the mass has `mc.assembly` (the wall assembly for a new wall), `mc.wall` (its wall id)
and `mc.params` = `flip`, `side` (outward normal [x, y] of the face the automatic rule chose last),
`wall` (create params); the wall driver has `mc.mass` (`masses.MASS`) and `mc.mass.line` (`LINE`:
driver start / mid point, cap midpoints `ci` / `cj`, end extensions `ext`, which cap it `start`s at;
written at every sync).

- **Footprint** (`Footprint(doc, mass)`, model units): the flat downward bottom face (else an
  error). Outer loop + one hole = a ring (chains A = outer, B = hole; a closed wall). Otherwise the
  loop's segments (split at kinks, collinear lines merged) are searched for two non-adjacent CAP
  segments whose remaining chains stay a constant distance apart (edge midpoints within 15 %; caps
  <= 3 x that thickness; shortest caps win): chains A and B run from cap i to cap j. No such pair:
  the minimum-area rectangle is used (warning). `Chain.o` = outward normal at mid-length,
  `Chain.left` = it is on the left of the chain's direction. `polys` = 2D outline for the 2D tests.
- **Groups**: footprints that overlap in z and lie within `GAP_IN` (1") in plan. `auto_side`: ring ->
  A; a face whose outside point (just off its mid) is enclosed (all of `RAYS` rays hit the group's
  outlines) is interior; else the face farther from the group's area centroid; else the stored
  `side`, else the face toward the active viewport's camera (perspective: camera location;
  parallel views: direction, plan views have no say), else the left of the cap i -> cap j axis.
  Then `flip` takes the other face.
- **Corners** (`_end_cut`): for each cap of a strip, every group member the cap touches (within the
  gap) whose exterior line (extended by its end tangents) crosses this end's tangent line within
  `t_self + t_other + gap` at >= 15 degrees: crossing near that line's end (or past it) = L -> this
  line ends at the crossing (both walls compute the same point); otherwise T -> it ends at the other
  WALL's near face (`m.T` = its assembly thickness inward of its exterior face when we come from
  inside, else its exterior face). Nearest |extension| wins. `_set_end` extends with a line or trims.
- **Driver** (`derive`): the exterior chain (with corners), oriented exterior-on-the-left, offset by
  `-y_ext` (the reference's exterior face offset; new walls `reference = exterior_face`, so 0),
  reversed when flipped (wall `flip` = mass `flip`), at `z0 - base_offset`. Params written: height
  (mass), flip; the rest of the wall's params is kept. The wall's assembly wins over the mass's.
  `_write` replaces the driver only when the curve / height / flip / assembly changed, remapping
  the openings' stations first (`_remap_openings`: projection when the mass did not change, else
  distance from cap i minus the old extension there).
- **sync_many(doc, masses)**: footprints of every wall mass in the doc, groups, the seeds' groups +
  the masses of walls joined to the seeds' walls at the last build (a mass moved away); sides for
  every member of those groups (store `side`), derive + write, then `engine.build_many` on the
  changed walls inside `_driving()` (follow() is off; `masses._driving` is NOT set, so opening masses
  follow their walls). Returns a `masses.SyncResult` (`walls`, `results`, `warnings`).
- **follow(doc, ctx, wall)** (engine.build of a wall, not while driving): mass bottom / height to
  `ctx.base_z` / `ctx.height` (z scale + move); a driver whose start / mid moved from `mc.mass.line`
  moves the mass rigidly (start + direction), then the group is synced.
- **after_params** (`engine.update_params` / `set_assembly` call it via `_after_wall_params`): a
  change of `flip`, `reference`, `layers` or `overrides` (or an assembly change) copies the flip to
  the mass and syncs it (the face position / thickness of this wall and the T ends of its neighbors).
- **release(doc, id)** (live Idle for every deleted id, via `masses.release`): walls with `mc.mass`
  = id are deleted with their parts and openings (opening masses left without openings go too); the
  mass with `mc.wall` = id is deleted; the neighbors are synced, other joined walls rebuilt.
- **Arrows**: `show_arrows(True)` subscribes once to `DisplayPipeline.DrawForeground` (handler kept
  in `scriptcontext.sticky[ARROWS_KEY]`); arrows come from `_store_arrow` at each sync and are drawn
  for visible masses on visible layers. Display only.
- **Panel / selection**: `eto.editor.selected_drivers` maps a selected wall mass to its wall.
- **Testing**: `tests/test_phase10.py` (same live pattern as Phase 9). Note `SetCameraLocations`
  takes (target, camera). Run drawing tests one `run_python` call each.
- **Not yet**: a mass running past a corner by more than the gap makes a T; collinear masses are
  separate walls; corners with plain (mass-less) walls are not adjusted; sloped tops use the highest
  point; masses with two or more holes; moving a wall mass together with its opening mass moves the
  opening mass twice.

## Library files
Add your own files rather than editing someone else's: `library/materials/<topic>.json`,
`library/profiles/<topic>.json`, `library/framing/<system>.json`, `library/assemblies/<topic>.json`,
`library/openings/<topic>.json`. Curtain walls: `library/assemblies/curtainwalls.json`,
`library/profiles/curtainwall.json`, `library/materials/curtainwall.json`. Floors and roofs:
`library/assemblies/floors.json`, `library/assemblies/roofs.json`, `library/framing/joists.json`,
`library/profiles/floors_roofs.json`, `library/materials/floors_roofs.json`. Entourage:
`library/entourage/*.json`; trims: `library/profiles/trim.json`.
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
