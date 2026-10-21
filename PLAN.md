# Rhino Mind Canvas — Plan

Parametric building assemblies (walls, floors, roofs, curtain walls) inside Rhino 8, with
individual framing members and a drawing system aimed at highly detailed, line-based
section perspectives.

## Decisions
- **Platform:** Python 3 (Rhino 8 CPython 3.9) + RhinoCommon. Grasshopper optional later.
- **Units:** imperial. Library values are inches; strings like `"3-5/8"`, `"1'-6\""` are accepted.
- **Naming:** plain dimensional names (`3-5/8" Metal Stud, 20 ga`, `2x6 Wood Stud`). Generic profiles, no manufacturers.
- **Detail:** individual studs/tracks/plates/bricks. Wood ↔ metal framing must be a one-line swap.
- **Use:** academic, personal. Drawing quality matters most.
- **Drawing target:** crisp digital version of a 1960s–70s hand-drawn section perspective:
  heavy cut lines with white-filled cut poché, strong line-weight hierarchy, parallel-line tonal
  hatching for shade, stipple for ground, monochrome black on white. Not a hand-drawn look.

## Architecture

```
mindcanvas/            Python package (the engine)
  units.py             length parsing ("3-5/8", 1'-6") and inch -> model-unit scale
  library.py           loads + merges library/**/*.json; registries for materials, profiles,
                       framing systems, assemblies, styles
  profiles.py          builds 2D profile curves (rect, c_stud, track, custom)
  meta.py              user-text keys linking drivers <-> parts
  docutil.py           layers, render materials, section styles, groups, block definitions
  geo.py               shared geometry (signed offsets, band regions, extrusion, frames)
  components/          one file per component type, auto-registered
    base.py            Component base class, Part, LayerBand, BuildContext
    solid.py           continuous layer (sheathing, gypsum, rigid insulation, membrane, void)
    framing.py         studs/plates/tracks/cavity fill (phase 1)
    masonry.py         bricks, mortar, ties, flashing, weeps (phase 2)
    sweep.py           a profile swept along a wall face: trims, cornices (phase 8)
  kinds/               assembly kinds (how a driver becomes layer bands)
    wall.py
    opening.py         hosted kind: an opening builds through its host
    curtainwall.py     phase 5: curtain walls (grid of mullions, transoms, infill)
    floor.py           phase 6: floors (closed boundary + layer stack top -> bottom)
    roof.py            phase 6: roofs (closed plate-line boundary, flat / shed / gable)
  floors/              phase 6: joist systems + member selection + JoistLayout (joists.py), layer
                       builders: slabs, rim / joists / blocking / bridging / fill, metal deck (build.py)
  roofs/               phase 6: settings + faces (shape.py: local frame per roof plane, overhang
                       footprint, rafter bottom line), Builder (build.py: rafters with birdsmouth,
                       ridge, barge, lookouts, ceiling joists, layers, shingle courses, eave / rake trim)
  hgeo.py              phase 6: local frames, (x, z) section polygons extruded along y, plan
                       polygon helpers (chords, offsets, clipping), slab_between (planar-face solids)
  curtainwall/         phase 5: settings (defaults <- assembly <- params), grid (runs, bays,
                       vertices, rows), sections (2D member sections per joint style), build
                       (3D members as hashed block instances, corners, infill, anchors, seals)
  openings/            phase 4: opening drivers + placement (core), section sweeps / mitered
                       frames (geom), window + door units, trim, sill pan, drip (units)
  joins/               phase 7: plan.py (pure 2D L / T rules: EndCut zones, notches, backers),
                       find.py (detection from drivers: walls, floors, roofs), geom.py (joined
                       outlines / solids, centerline, roof infill)
  engine.py            build / rebuild / delete for a driver (+ rebuild joined partners)
  entourage/           3D model library: objfile.py (OBJ / MTL), catalog.py (entries, import),
                       thumbs.py (PNG pictures), place.py (mesh blocks, placement, FaceView)
  capture.py           phase 8: curves drawn in Rhino -> custom profiles in the library
  trims.py             phase 8: per-wall trims (sweep extras in params["extras"])
  asmedit.py           phase 8: assembly editor model (no UI)
  eto/                 phase 8: Eto views: widgets.py, editor.py (assembly editor), panel.py (MCPanel)
  asmview.py           phase 12: the drawn layer section as plain Python (layout, hit tests, click / drag
                       reorder / drag thickness with snapping); eto/sectionview.py paints it
  asmfields.py         phase 12: typed fields for component options + assembly settings
  preview.py           phase 12: live preview sample of an unsaved assembly (MindCanvas::_Preview);
                       eto/visual.py = the visual assembly editor window
  live.py              watches driver edits and rebuilds (toggle)
  masses.py            phase 9: mass drivers: solids pushed / pulled with the gumball that write the
                       params of existing drivers (opening masses: box cut = rough opening)
  wallmasses.py        phase 10: wall masses: a strip / ring / block solid -> a wall driver on its exterior face
  schedule.py          quantity takeoff -> CSV
  drawing/             phase 3: display mode, MCDrawing, tone hatch, stipple, line weights
  dev.py               reload helper for development
library/
  materials/*.json     name -> color, render, section hatch, line weight
  profiles/*.json      name -> parametric profile definition
  framing/*.json       framing systems (wood, metal) — stud/plate/track rules
  assemblies/*.json    assembly definitions (stack of layers)
  styles/*.json        drawing styles per scale
  entourage/           276 CC0 3D models: <category>.json, models/*.obj, thumbs/*.png, CREDITS.md
commands/              one Rhino entry script per command (MCWall.py, MCUpdate.py, ...)
tools/install.py       registers command aliases in Rhino
tools/entourage/       build.py + recipe.json: download, normalise and picture the entourage library
tests/                 scripts run inside Rhino (via run_python) that build + assert
docs/                  findings, user guide
```

### Core concepts
- **Driver**: a curve in the Rhino doc carrying user text `mc.kind=driver`, `mc.assembly`,
  `mc.params` (JSON: height, base offset, reference line, flip, overrides).
- **Parts**: generated objects carrying `mc.kind=part`, `mc.driver=<driver id>`, `mc.layer`,
  `mc.role`, `mc.material`. Parts + driver share a Rhino group.
- **Rebuild**: delete parts found by `mc.driver`, regenerate, regroup. `MCUpdate` or live mode.
- **Wall frame convention**: offsets are signed, **positive = toward exterior**. For an open
  driver curve the exterior is on the LEFT of the curve direction (Z × tangent). Closed
  drivers are oriented clockwise so the exterior is outside. `flip` reverses this.
- **Layer bands**: the wall kind turns the assembly stack into bands `(d_ext, d_int)` measured
  from the driver, then hands each band to its component's `build()`. The `BuildContext`
  exposes the whole stack so components that span layers (brick ties) can find their neighbors.
- **Material layers**: `MindCanvas::<Material>` with color, render material and section style.
- **Repetition**: identical members (same stud length, every brick) are block instances.
- **Level of detail**: `schematic` (solid layers) / `design` (studs, mullions) /
  `detail` (bricks, mortar, ties, fasteners). Components degrade gracefully.

## Roadmap
| Phase | Scope | Status |
|---|---|---|
| 0 | Foundation: package, library, units, solid component, wall kind, engine, MCWall/MCUpdate, live, install | Done |
| 0.5 | Drawing spike: perspective clipping + section styles, Make2D in perspective, depth banding, tone hatch | Done |
| 1 | Framed walls: wood + metal, swappable systems, plates/tracks, corners, cavity fill, bridging | Done (`MCFraming`; known: track legs overlap sheathing by steel thickness, fill passes through bridging, mitered plates) |
| 2 | Brick veneer: bricks, bonds, mortar, ties, flashing, weeps, shelf angle | Done (two-sided brick via MCLayers verified; known: curved-segment corners approximate, shelf angle/flashing not tied to modeled structure) |
| 3 | Drawing system: display mode, MCDrawing, line weights, MCToneHatch, MCStipple, scale presets | Done (MCDrawing/MCSectionCut/MCDisplaySetup/MCDrawingTag; tone + stipple are MCDrawing options; outputs in docs/drawings/) |
| — | **Review checkpoint with user** | Done (user approved, Phase 4 started) |
| 4 | Openings: windows/doors, headers, jambs, sills, lintels, soldier courses | Done (`MCOpening`/`MCEditOpening`; PR jakeself-arch/rhino-mind-canvas#1) |
| — | **Review checkpoint with user** | Skipped: user asked (2026-10-15) to continue through phases 5–8 without review stops |
| 5 | Curtain wall: grid, IGUs, spandrels, joint styles (captured, 4-side SSG, 2-side SSG, butt, unitized), mullion materials | Done (`MCCurtainWall`/`MCEditCurtainWall`; kind `curtain_wall`; PR jakeself-arch/rhino-mind-canvas#2) |
| 6 | Floors + roofs: joists, rafters, flat/shed/gable | Done (`MCFloor`/`MCEditFloor`/`MCRoof`/`MCEditRoof`; kinds `floor`, `roof`; PR jakeself-arch/rhino-mind-canvas#3) |
| 7 | Joins: L/T wall joins, wall↔floor, wall↔roof | Done (`MCJoin`; `mindcanvas/joins/`; PR jakeself-arch/rhino-mind-canvas#4; verified in Rhino 2026-10-15) |
| 8 | UI + entourage: Eto panel, assembly editor, profile capture, line-drawn entourage | Done (`MCPanel`/`MCAssemblyEditor`/`MCProfileCapture`/`MCTrim`/`MCEntourage`; PR jakeself-arch/rhino-mind-canvas#5; verified in Rhino 2026-10-15) |
| | **Second roadmap (2026-10-15): push / pull mass drivers + visual editors.** Masses show overall form only (their thickness is arbitrary); they control the existing drivers, the kinds are not rewritten. | |
| 9 | Mass drivers core + opening masses: a box crossing a wall = the rough opening (width x height; depth ignored); gumball scale / move / face drag rebuilds in live mode; numeric edits resize the box | Done (`MCOpeningMass`; `mindcanvas/masses.py`; PR jakeself-arch/rhino-mind-canvas#6; user approved the merge 2026-10-16) |
| — | **Review checkpoint with user**: try the gumball workflow before Phase 10 | Done (user approved Phase 9, asked for Phase 10) |
| 10 | Wall masses: box / extruded footprint -> wall line, base, height (thickness arbitrary); the finished exterior face on the mass's outer face (user, 2026-10-16), a flip arrow, closed rings orient themselves, open groups: exterior away from the group | Done (`MCWallMass`; `mindcanvas/wallmasses.py`; branch `phase10-wall-masses`, PR jakeself-arch/rhino-mind-canvas#7) |
| 11 | Roof masses: triangular extrusion = gable (base = plate line, slopes = pitch, extrusion direction = ridge, bottom = plate height), wedge = shed, box = flat; overhang / rake stay settings; auto-join to wall masses | |
| 12 | Visual assembly editor: drawn layer section (material colors + hatches), click a layer to edit, drag to reorder, drag an edge to change thickness (snaps 1/16" or library sizes), per-key option widgets instead of raw JSON, live sample-wall preview | Done, awaiting review (`MCAssemblyEditor` / panel open it; `mindcanvas/asmview.py`, `asmfields.py`, `preview.py`, `eto/visual.py`, `eto/sectionview.py`; branch `claude/phase12-visual-editor-725423`, PR jakeself-arch/rhino-mind-canvas#8) |
| 13 | Profile editor: named fields for parametric profiles (stud, track, mullion) with a live drawing; custom profiles on a "profile board" in Rhino, re-captured automatically when edited | |
| CW | Visual curtain-grid editor (user request 2026-10-18, ArchiCAD-style): the elevation in a window, drag / add / delete grid lines and transoms (transoms in some bays only), paint panels, doors (single + pair) in bays with a draggable head, 3D preview, auto apply | Done (`MCCurtainGrid`; `curtainwall/gridedit.py`, `gridio.py`, `eto/cwgrid*.py`; branch `cw-grid-editor`, built on `phase10-wall-masses`) |
| UI | Viewport editing + picking by sight (user request 2026-10-20, from a brainstorm): drag handles on the selected assemblies, hover labels, ghost previews in MCOpening / MCWall Draw; the assembly palette (drawn tiles, built on Phase 12); layer = assembly; dress massing solids (one solid = one story, floors where they stack, no roofs) | Done (`MCHandles`, `MCPalette`, `MCPaintAssembly`, `MCAssemblyLayers`, `MCDress`; `mindcanvas/viewport/`, `eto/palette.py`, `eto/tiles.py`, `laylink.py`, `dress.py`; branch `claude/ui-smoothness-visual-design-4af79f`, includes Phase 12) |

## Resume here
_Updated at every milestone. A new session should read this section, `docs/DEVELOPING.md`, then continue._

**2026-10-20: entourage rebuilt as a 3D model library** on branch
`claude/entourage-3d-asset-library-ce3a9a`. The user asked to remove the line-drawn figures (Phase 8
`shapes.py`, `people.json`, `plants.json`, figure capture) and shop the web for free OBJ entourage.
Shipped: 276 CC0 models (Quaternius, Kenney via OpenGameArt; Poly Haven via its API) in
`library/entourage/` (OBJ + MTL + PNG picture, real size in inches), built reproducibly by
`tools/entourage/build.py` from `recipe.json`; `MCEntourage` (ghost, Aim, RandomModel, Swap, Import
your own OBJ) and the picture window `MCEntourageLibrary`; aliases `EN`, `EL`. CC0 only because the
repository is public. Tests: `tests/offline/test_entourage_library.py`, `tests/test_entourage.py`,
`tests/test_phase8.py` pass (drawings each in their own call). Not covered: the ghost and the Import
dialogs by hand (macro-driven placement with Aim / RandomModel was run). Gaps: the posed people are
low-poly (about 1,000 triangles) and the Quaternius buses are short (25' shuttle, 22' school bus);
no realistic CC0 people were found; Google Drive (Quaternius' own host) refused downloads (quota),
so the OpenGameArt mirrors are used.

**2026-10-20: viewport editing + picking by sight** on branch `claude/ui-smoothness-visual-design-4af79f`
(from main 797b2ed, with Phase 12 / PR jakeself-arch/rhino-mind-canvas#8 merged in because the
palette's tiles use its drawn section). The user asked for a smoother, more visual UI for studio work,
chose the "edit in the viewport" and "pick assemblies by sight" groups of a brainstorm, and decided:
build on Phase 12; dressing = one solid per story; no roofs from dressing for now; handles show on
selection. Details in the README ("Editing in the viewport, picking by sight") and
`docs/DEVELOPING.md` ("Viewport editing, palette, assembly layers, dressing").
- Built: drag handles + hover labels (`viewport/shapes.py`, `overlay.py`, `MCHandles`), MCOpening's
  ghost + MCWall Draw's band (`viewport/ghost.py`), the palette (`eto/palette.py`, `eto/tiles.py`,
  `MCPalette`, `MCPaintAssembly`), layer = assembly (`laylink.py`, `MCAssemblyLayers`), dressing
  (`dress.py`, `MCDress`; wall-mass param `top_cut`). `MCSetup` turns on handles, labels and layer
  watching; `MCInspector` turns on handles / labels; the inspector's "Edit assembly" opens the Phase 12
  editor; aliases `PA`, `AL`, `DM`, `VH`.
- Tests (each in its own run_python call, own spawned slot): `tests/test_viewui.py`,
  `test_palette.py`, `test_laylink.py`, `test_dress.py` pass, and so do `test_phase7`, `test_phase9`,
  `test_phase10`, `test_phase12`, `test_inspector`, `test_cwgrid` (run with drawings / captures off).
- Not yet / checked by hand only: real mouse drags in a live Rhino (the tests drive the mouse
  callback with stand-in events; Undo of a drag cannot run inside run_python), the palette window's
  look (only its tiles were rendered), roofs from massing (Phase 11), a story larger than the one
  below gets a floor only over the lower outline.

**2026-10-19: fast UI** (user request: fewer clicks, more Rhino-like) on branch `fast-ui`
(branched from `cw-grid-editor`). From a brainstorm of six ideas the user picked the inspector,
short aliases and a match tool first. Details in the README ("Fast modeling") and
`docs/DEVELOPING.md` ("Inspector, match, aliases").
- `MCInspector` (`I`): a window that follows the selection; edits walls, curtain walls, floors,
  roofs and windows / doors at once (`mindcanvas/props.py` + `eto/inspector.py`); double-click
  an assembly opens it (curtain walls: the grid editor). `MCMatch` (`MT`): match assembly +
  settings. Create commands no longer open the assembly dialog (current assembly per kind,
  saved with the model). Short aliases in `tools/aliases.json`.
- Tests: `tests/test_inspector.py` (~4 s) and `tests/offline/test_match_aliases.py` pass;
  `test_phase8` passes. The window layout was checked on rendered PNGs. Not verified by the agent: a
  real mouse double-click in a viewport (the callback was driven directly), and the short aliases
  in the user's Rhino (install.py was not run, so the user's alias settings are unchanged).
- Remaining ideas from the brainstorm: layer = assembly (draw on a layer to get that assembly),
  dress any massing solid, work at Schematic and add detail where sections cut, a window ghost
  that follows the cursor, drag handles in the viewport.

**2026-10-18: visual curtain-grid editor** (user request, outside the numbered phases) done on
branch `cw-grid-editor` (branched from `phase10-wall-masses`, so it includes PR #7's commits until
that merges). Details in `docs/DEVELOPING.md` ("Curtain walls" -> Visual grid editor) and the
README.
- Grid mode `custom` (`verticals` = stations along the driver as drawn; a flip keeps them),
  transoms `{"z", "at": [stations]}` crossing only some bays (`grid.bay_hs`), cells counted per
  bay. Numeric grids still work and keep partial transoms.
- `MCCurtainGrid` (also `MCEditCurtainWall` -> `Editor`, panel "Curtain grid editor"): Select /
  Grid line / Transom / Delete / Paint / Door tools, Ctrl-drag a transom segment, typed values,
  Divide bay, Equalize run, undo, snap + magnet, exterior / interior view, auto apply (on; ~0.1 s
  rebuild of a 30' wall at detail), 3D preview lines in the viewports.
- Curved walls (user request 2026-10-18, same day): verified on arcs, circles, splines and
  line + arc; the editor shows chord (panel) widths, each panel's deviation from the curve and
  the facet angles, flags panels beyond `Max off the curve` (3") and `Fit curve` divides them;
  doors in curved bays sit flat in their panel. Captures `cwgrid_curved_editor.png`,
  `cwgrid_curved_plan.png`.
- Doors: `leaf.leaves = 2` = a pair (hinged at both jambs, two swings); new types `Door -
  Aluminum Entrance, Full Lite Pair`, `Narrow Stile`, `Narrow Stile Pair`.
- Tests: `tests/test_cwgrid.py` (`run(doc, captures=True, log=None)`, ~2 s) and
  `tests/offline/test_cw_gridedit.py` pass (both cover curved walls); `test_phase4`, `test_phase5`, `test_phase8` pass.
  Captures: `docs/captures/cwgrid_editor.png`, `cwgrid_wall.png`.
- Not yet: merging panels across a grid line (a vertical that stops at a transom), windows /
  vents placed by the editor, a door spanning two bays (widen its bay instead); the window's layout was only checked through its handlers
  (not looked at on screen by the agent).

**Current state (2026-10-16): second roadmap, Phase 10 (wall masses) done on branch
`phase10-wall-masses` (PR jakeself-arch/rhino-mind-canvas#7), not merged** (the user decides when to merge). Next is Phase 11
(roof masses): start it only when the user asks.

**Phase 10 summary** (details in `docs/DEVELOPING.md`, "Wall masses"):
- User decisions (2026-10-16): the wall's finished EXTERIOR face lies on the mass's outer face (the
  wall grows inward by the assembly thickness; the mass keeps the thickness it was drawn with);
  the exterior side of masses that are not a closed ring is the face away from their group's
  center; a lone box faces the camera at creation and keeps that side.
- `mindcanvas/wallmasses.py`: a solid tagged `mc.type = wall` (`mc.wall` = its wall, the wall
  `mc.mass` + `mc.mass.line`). Its flat bottom face is read as a STRIP (box, L / polyline strip,
  curved strip: two long faces between two caps), a RING (one hole -> a closed wall) or a PERIMETER
  (user request 2026-10-16: any solid block, a cube, an L-shaped / polygonal / round building ->
  ONE closed wall around its whole outline, exterior outside, growing inward; partition masses
  inside it T into its interior face). Mode (mass param `mode`, MCWallMass Mode / SetMode): Auto
  = a strip when its thickness is at most 1/3 of its length, a ring with one hole, else a
  perimeter; Strip / Perimeter force either reading. The
  exterior face line is extended / trimmed so the drivers meet at corners (L: both to the crossing
  of the exterior faces; T: to the other wall's near face), so Phase 7 joins work unchanged.
  Driver = exterior face line offset by the reference (new walls: `exterior_face`), at the mass
  bottom - base_offset; height = mass height; wall `flip` mirrors the mass's `flip`.
- Two-way: `sync` / `sync_many` (mass -> the walls of its group; live mode on every gumball edit,
  via `masses.sync`), `follow` (engine.build: base / height edits resize the mass, a moved driver
  line moves it), `after_params` (MCEdit Flip / Location, MCLayers, set_assembly re-derive from the
  mass), `release` (a deleted mass deletes its wall + openings; a deleted wall deletes its mass;
  neighbors re-derived). Openings keep their place along the wall; opening masses ride along with
  a moved wall (`masses._fit` now moves a box with its opening's frame even when it still fits).
- `MCWallMass` (`cmd/wallmass.py`): select solids -> wall masses of the chosen assembly; options
  Assembly / Mode / SetMode / Flip (perimeters keep the exterior outside) / Convert (existing walls
  get a mass, keeping their place) / Show. Panel Build
  tab: "Wall mass". A blue arrow (display only) shows each mass's exterior side.
- `tests/test_phase10.py` (`run(doc, drawing_on=True, captures=True, log=<path>)`, ~9 s) passes, and
  so do `test_phase0`..`test_phase9` + `test_layers` (run the drawing tests one `run_python` call
  each: several in one call leave the section cuts empty). Live rebuilds: wood ring wall height
  scale 0.34 s, face drag of a corner mass (3 walls) 0.49 s, brick veneer 24' wall at detail moved
  0.46 s. Captures: `docs/captures/phase10_wall_masses.png` (masses + arrows),
  `phase10_wall_masses_walls.png` (masses hidden), `phase10_perimeter_walls.png` (a cube with a
  partition and a window, an L-shaped block, a cylinder).
- Limits: a mass that runs past a corner by more than 1" (its end does not touch the other mass)
  makes a T, not an L; collinear masses are not merged; corners between a mass wall and a plain
  wall are not adjusted; a sloped top uses the highest point; masses with more than one hole are
  rejected (a perimeter ignores holes: no courtyard walls); two touching perimeter blocks make two
  closed walls (draw one block per building); selecting a wall mass AND its opening mass and moving both moves the opening mass
  twice; a wall moved into a free opening mass still does not open.

**Phase 9** (mass drivers + opening masses) is merged into main from branch
`phase9-opening-masses` (PR jakeself-arch/rhino-mind-canvas#6).

**Phase 12 (visual assembly editor, 2026-10-16; built in parallel with Phase 10, not merged yet)**
(details in `docs/DEVELOPING.md`, "Visual assembly editor"): `MCAssemblyEditor` and the panel's "Edit
assembly" open `eto/visual.py`: a drawn section of the layer stack (walls exterior -> interior as a
plan cut, floors / roofs top -> bottom, a roof's attic ceiling as a second stack; curtain walls are
settings only) at true relative thickness with material tints + simple hatches, framing members at
true size, core box, location line, labels. Click selects, drag reorders, dragging a boundary changes
a thickness (1/16", Alt = 1/64"; framing / joist / rafter layers snap to the library member depths
of their system, a named joist / rafter follows). Typed fields for the layer, each known option of
its component and the assembly settings (dropdowns, lengths like 3-5/8 or 1'-6", checkboxes),
advanced JSON for nested keys. Live preview: a 4' sample (floors 4' x 4', roofs 8' x 6', curtain
walls 10') of the unsaved assembly on `MindCanvas::_Preview`, right of the model, rebuilt 0.6 s after
a change, removed on close. The Phase 8 list editor stays reachable ("List editor..."). Logic in
`asmedit.py` (extended), `asmview.py`, `asmfields.py`, `preview.py`. `tests/test_phase12.py`
(`run(doc, captures=True, log=<path>)`, ~3 s) passes, and so do `test_phase0`..`test_phase9` +
`test_layers`. Pictures: `docs/captures/phase12_section_*.png`, `phase12_window.png`,
`phase12_preview.png`. Not yet: undo inside the editor, keyboard nudging, trims / extras in the
drawing, a curtain-wall drawing (Phase 13 does profiles).

**Phase 9 summary** (details in `docs/DEVELOPING.md`, "Mass drivers"):
- `mindcanvas/masses.py`: a closed solid tagged `mc.kind = mass` on `MindCanvas::_Masses`
  (translucent, never printed, layer tag `exclude`, skipped by the drawing scene). Where it cuts a
  wall's mid surface, the cut's bounding rectangle is the rough opening; the opening driver gets
  width / height / sill / station from it (unit = RO - shims; doors have no shim at the floor) and
  `params["ro"]`. One box through two walls opens both; corners / wall ends are rejected.
- Two-way: `masses.sync` (mass -> openings, run by live mode on every Replace of a mass) and
  `masses.follow` (engine.build: a mass with one opening follows numeric edits, a moved opening
  line and a moved / turned wall; SnapHead moves only the unit). Deleting a box deletes its
  openings; deleting a wall / removing an opening deletes boxes left without openings; a type change
  in MCEditOpening goes to the box.
- `MCOpeningMass` (`cmd/openingmass.py`): click a wall (opening + box) or select solids (each
  becomes a mass), options Type / Width / Height / Sill / Swing / Hinge / HeadCourse / SnapHead /
  Convert (box existing openings) / Show. Panel Build tab: "Opening mass".
- `tests/test_phase9.py` (`run(doc, drawing_on=True, captures=True, log=<path>)`, ~9 s) passes, and
  so do `test_phase0`..`test_phase8` + `test_layers`. Live rebuild of a 24' brick veneer wall at
  detail after a gumball move: ~0.5 s. New outputs: `docs/drawings/h_opening_masses_quarter`
  (a brick wall whose three openings come from masses; no mass in the drawing),
  `docs/captures/phase9_masses.png`.
- Not yet: a wall moved into a free box does not open (a box syncs on its own edits only);
  curtain-wall hosts; corner windows.

**Previous state (2026-10-15): the first roadmap was complete.** Phase 8 (UI + entourage) is done and
verified in Rhino on branch `phase8-ui-entourage` (PR jakeself-arch/rhino-mind-canvas#5). `tests/test_phase8.py`
(`run(doc, drawing_on=True, captures=True, log=<path>)`, ~16 s) passes, and so do
`test_phase0`..`test_phase7` + `test_layers` on the same code. The Phase 7 open item is fixed: under
an attic ceiling a gable wall's interior layers (gypsum) stop at the ceiling. Fixing it also showed
that the sheathing of joined gable walls was not filled up to the rafters (its join-zone face had
extra collinear points; `joins.geom.band_polys` now simplifies them), so `f_gable_section_1-1-2`
changed on purpose. New drawings: `docs/drawings/g_section_perspective_quarter` (gable house cut
across the ridge, people, trees, shrubs, tone + stipple), `g_entourage_sheet_quarter` (every library
figure), `g_trim_base_1-1-2` / `g_trim_crown_1-1-2` (swept trims in section).

**Testing.** Every test runs in an empty, unsaved document of your own `spawn_slot` (they clear the
doc; `test_phase5`..`test_phase10` assert `not doc.Path`): `tests/test_phase0.py`, `test_phase1.py`,
`test_phase2.py`, `test_layers.py`, `test_phase3.py` (`run(doc, parts="a"|"b"|"ab")`),
`test_phase4.py` (`run(doc, drawing_on=True, captures=True)`, ~30 s), `test_phase5.py` to
`test_phase10.py` (`run(doc, drawing_on=True, captures=True, log=<path>)`; 45 / 25 / 17 / 16 / 9 / 9 s;
`test_phase12.py` the same, ~3 s;
`test_phase6` takes `only="drawings"`). Offline (no Rhino): `tests/offline/test_join_plan.py`,
`test_entourage_shapes.py`,
`test_join_find.py` with `%USERPROFILE%\.rhinocode\py39-rh8\python.exe` (no system Python on this
machine). After a run, `git checkout` the regenerated images of earlier phases
(`git diff --name-only -- docs | xargs git checkout --`) unless a change was on purpose.
`test_phase8` writes `zz_test_phase8.json` library files and test assemblies into
`zz_user_assemblies.json`, and removes / restores them at the end (also when it fails).
Sample drawings: `docs/drawings/a_section_perspective_eighth.png`, `b_wall_section_1-1-2.png`,
`c_window_section_1-1-2.png`, `d_curtainwall_plan_<style>.png` (1-1/2" plans at a vertical
mullion for captured / ssg4 / ssg2 / butt / unitized), `d_curtainwall_plan_corner.png`,
`d_curtainwall_section_spandrel.png` and `d_curtainwall_section_unitized.png` (1-1/2" sections
at a transom / spandrel / slab edge with anchors and safing), `e_roof_eave_section_1-1-2.png`
(gable eave on a 2x6 wall), `e_roof_flat_edge_1-1-2.png` (low-slope edge),
`e_floor_section_1-1-2.png` (platform frame: wall, rim, joist, subfloor, wall above),
`e_floor_deck_section_1-1-2.png` (concrete on composite deck over C-joists), `f_*` (joins),
`g_*` (entourage, trims).

**Workflow (user, 2026-10-15):** phases 5-8 ran without review stops, one phase per session: branch
from main, PR, merge when the tests pass. With Phase 8 merged there is no next phase; further work
starts from the known gaps below.

**Phase 8 summary** (branch `phase8-ui-entourage`):
- **Entourage** (`mindcanvas/entourage/`, `library/entourage/*.json`, command `MCEntourage`):
  pure-Python generators (`shapes.py`: `person` front / walk, suit / coat / dress, bag, bent arm,
  child by height; `tree` bare (recursive branching, scaled to its height) / canopy (scalloped
  crown + foliage strokes) / conifer; `shrub`; `custom` = captured) produce layered 2D cards in
  inches. `place.py` turns a figure into a block (one planar Brep card per layer, unioned outlines,
  stacked 1/4" apart in depth, plus line curves), shared per shape hash; instances face -Y and
  `face_view` turns them about their base point toward a viewport's camera; `rebuild` reseeds /
  mirrors in place. Drawings: `scene.py` collects the curves of `MC Entourage` blocks, the HLD
  draws them (curves on a card stay visible; cards hide what is behind them), `pipeline.py` gives
  their segments the class `entourage` (style `classes.entourage`, 0.2 mm; thinner at 1/8" and
  1/16"); figures carry `mc.draw = notone,nocut` (no tone, no poche).
- **Profile capture** (`mindcanvas/capture.py`, `MCProfileCapture`, `MCEntourage Capture`): curves
  in the active construction plane, relative to a base point, polylinized at 1/64", become a
  `custom` profile (`loops` with holes; `profiles.custom` reads them) in
  `library/profiles/zz_user_profiles.json`, or a `custom` figure in
  `library/entourage/zz_user_entourage.json`. `Library.save_entry / remove_entry / is_user_entry`
  (library assemblies, profiles and figures are never overwritten).
- **Trims** (`components/sweep.py`, `mindcanvas/trims.py`, `MCTrim`, `library/profiles/trim.json`):
  the `sweep` component sweeps a profile along the interior / exterior face at base / top / a
  height (mitered around polyline corners, stopped at join cuts, cut at openings, takeoff length);
  used as an assembly extra or per wall in `params["extras"]` (the wall kind now builds both).
- **Assembly editor** (`mindcanvas/asmedit.py` model, `mindcanvas/eto/editor.py` view,
  `MCAssemblyEditor`): modeless Eto window: assemblies by kind, layer list with name / component /
  material / thickness / core / options JSON, add / duplicate / remove / up / down / mirror, other
  settings as JSON (curtain walls are settings only), checks, Save As (user assemblies only),
  Apply to the selected assemblies.
- **Panel** (`mindcanvas/eto/panel.py`, `MCPanel`): modeless Eto window with tabs Build (command
  buttons), Selection (assembly / height / base offset / LOD -> Apply, Edit assembly), Drawing
  (scale, tone, stipple, SetLOD, folder -> draw the active view; section cut, display setup, tags),
  Entourage (figure, height, random, mirror -> Place, Face the view, Capture), Library.
- Eto under Rhino 8 CPython: controls take no keyword properties in their constructors (use
  `eto/widgets.py`); modeless windows are kept alive in a module list (`_OPEN`).

**Known gaps (end of the roadmap)**, beyond the per-phase limitations below:
- UI: the panel is a floating Eto window, not a docked Rhino panel (docking needs a compiled
  plug-in to register a panel class); the Selection tab edits height / base offset / LOD /
  assembly only (the other options stay in the MCEdit* commands); the assembly editor edits
  options and settings as raw JSON (no per-key widgets) and has no live preview (Apply after Save);
  command buttons need the `tools/install.py` aliases; the Eto UI is tested through its handlers
  (no click / layout / HiDPI testing).
- Entourage: people are simple outline figures (front standing and walking profile only; no
  seated figures, cyclists, groups, cars or furniture); figures are flat cards, so they read
  correctly only after FaceView (MCEntourage faces the view at placement) and look thin from the
  side; people do not vary by seed (trees and shrubs do); no automatic scatter; captured figures
  have a single card layer.
- Trims: no miter where two separate walls' trims meet at a joined corner (each stops square at
  the face line), no returns at free wall ends and no casings around openings (the trim just stops
  at the rough opening); exterior trims sit on the cladding face (the cladding is not stopped above
  a water table); trims are not offered in MCLayers.
- Profile capture: captured profiles are used by trims only (framing, mullion and lintel families
  need their own dimension keys); arcs become polylines.
- Still open from earlier phases: see the Phase 1-7 limitations below (track legs vs sheathing,
  insulation through bridging, mitered plates, no auto-height, single-ridge roofs, no floor
  openings, joins only between separate drivers' ends, ...).

**Phase 7 summary** (package `mindcanvas/joins/`, command `MCJoin`): automatic joins found from the
drivers. **L** between two wall ends (wrap: layers outside the core miter on each side of the corner,
the primary core runs to the other's outer core face, the secondary stops at the primary's inner
core face, backer stud; miter; butt; none; `join_priority`); square brick-on-brick corners lap
course by course (`masonry.JoinEnd`). **T** (joining core through the host's finish to its core,
host notched + two backer studs; butt). **Wall under a floor** (exterior layers up over the rim to
the wall above / the structure top; floor ceilings and finish floors with an `inset` option inset
per edge to the walls' interior faces). **Wall under a roof** (roof `wall_depth` / `wall_ext` /
`wall_int` from the walls unless set in its params; exterior layers lowered under the rafters;
every layer filled up to the rafter bottom line: gable ends, shed side and high walls, gable studs
+ fill). Engine cascade (`build(..., joined=True)`, `mc.joined`), live delete cascade. Hooks:
`BuildContext.solids` / `z_range`, `kinds.wall.stack_offsets`, `floors.build.edge_slab`.

**Phase 7 known limitations:** joins only between separate wall drivers' ends (a wall's own
polyline corners work as before); three walls at one point: the closest pair wins; joined walls must
overlap in height; an L or T cut applies over each wall's whole height (only a T host's notch is
limited to the joining wall's height); curved hosts are linearized at the T point; brick
ties, base flashing and shelf angles still end at the driver ends; masonry in a T host is not
notched; roof infill only on straight walls (curved walls warned) and stops at the rafter bottom
line (no rake plate, exterior layers do not continue up to the roof deck at the rake); exterior
layers at eaves stop at the lowest rafter-bottom point over them (a < 1" wedge is left out);
wall `base_offset` / floor `base_offset` / roof `base_offset` are still set by hand (no
auto-height); floors / roofs are matched to walls by straight edges within the wall thickness + 1".

**Phase 6 summary** (branch `phase6-floors-roofs`, PR jakeself-arch/rhino-mind-canvas#3): kinds `floor` (`kinds/floor.py` +
`mindcanvas/floors/`) and `roof` (`kinds/roof.py` + `mindcanvas/roofs/`), shared geometry in
`mindcanvas/hgeo.py`. Library: `library/assemblies/floors.json` (2x10 wood, 11-7/8" I-joist,
10" metal C-joist, concrete on metal deck), `library/assemblies/roofs.json` (gable vented attic,
cathedral gable, shed, low-slope membrane with tapered insulation), joist / rafter systems
`wood_joists` / `metal_joists` in `library/framing/joists.json` (`"use": "joists"`, so MCFraming
does not list them), profiles in `library/profiles/floors_roofs.json` (boards, I-joists, rim
boards, metal joists + joist tracks, flat strap, composite decks; new profile type `i_joist`),
materials in `library/materials/floors_roofs.json`, drawing styles for them in `base.json`.
Commands `MCFloor`, `MCEditFloor`, `MCRoof`, `MCEditRoof`; `MCSectionCut` cuts floors (along the
joists) and roofs (along the slope); `MCSchedule` adds a floor / roof schedule and a joist /
rafter cut list (`_Framing.csv`); `MCDrawing SetLOD`, `MCUpdate`, `MCPurge`, live mode work.

**Phase 6 known limitations:** floors have no holes / stair openings; joists are square-cut where
they meet an oblique rim (small gap); the rim is one continuous ring per ply (one part); blocking
rows are spaced over the overall joist run; no hangers, web stiffeners, squash blocks or clip
angles; I-joists are one solid (one material). Roofs: one ridge per roof (no hips, valleys or
cross gables) — a gable on an L uses one ridge over the whole footprint (notch eaves sit higher
than the plate), so L-shapes are meant for flat / shed; the shed's high side follows the boundary
(longest edge, clockwise) — use `Flip`; metal rafters have no birdsmouth or clips (the bottom
passes over the outer plate corner) and no lookouts / bird blocks; full trim (fascia, sub-fascia,
soffit, gutter, rake board, barge, lookouts) only on edges parallel / perpendicular to the ridge,
oblique edges get a fascia band; rake soffits, gutter hangers / downspouts, ridge vents, vent
baffles (only the air gap) and gable-end walls are not modeled; ceiling joists butt at the ridge
line; shingles are continuous courses (no tabs); low-slope edge nailers only on rectangular
footprints (irregular flat roofs keep the insulation to the edge).

**Phase 5 summary** (branch `phase5-curtain-wall`, PR jakeself-arch/rhino-mind-canvas#2): kind `curtain_wall` (`kinds/curtainwall.py` + `mindcanvas/curtainwall/`),
assemblies in `library/assemblies/curtainwalls.json`, mullion profiles in
`library/profiles/curtainwall.json`, materials in `library/materials/curtainwall.json`, a CW door
type in `library/openings/curtainwall_doors.json`. Commands `MCCurtainWall`, `MCEditCurtainWall`;
`MCSectionCut` takes curtain walls and has `Plan=Yes` (horizontal clipping plane, plan detail);
`MCSchedule` adds a curtain-wall panel schedule; `MCOpening` puts a door in a curtain-wall bay;
`MCDrawing SetLOD` also rebuilds curtain walls.

**Phase 5 known limitations:** corner mullions are an L of two tube legs (one per face, mitered
covers wrap the corner; concave corners use the same L pushed to the interior) — no special
corner extrusions; glass in arc facets is square-cut and meets the bisector mullion at a slight
angle; transoms stop at the end of the corner L (a small hollow behind the cap at transom
height); only one opening per bay, doors take the bay's full clear width, windows in a bay are
not supported (the hook works but the unit is a regular window frame); unitized jambs reuse the
split-mullion halves (no special jamb receptor); setting blocks only under captured / pocket
glazing (none for 4-side SSG); anchors are generic clip angles (no embed plates / bolts) and
skip corners and butt joints; the floor slab is not modeled (tests add a concrete box);
curtain-wall parts carry no `mc.x.length` for gaskets / seals (takeoff counts them by part).

**Phase 4 review (2026-10-14), addressed:** frames sit at the insulation line (brick returns get
sheet-metal closures + sealant at the brick face; `"position": "brick"` keeps the old placement);
SnapHead (default on) puts heads on the brick coursing; window liners get lighter tone in drawings
(material style `"tone": <spacing multiplier>`).

**Phase 4 known limitations:** with SnapHead off, a head off the coursing leaves a gap under the
lintel (warned);
jamb closures are cut at the masonry opening line (no bonding-out of the opening width); openings
on curved walls are straight units with planar jambs, members along the wall follow the curve;
end dams are thin plates that slightly overlap the brick at the lintel ends; the L-header sits on
the wall's top track (not with a deflection track); door frames wrap walls up to 8-3/4" thick,
thicker walls get a 4-3/4" frame + liners; no hinges / hardware; no opening can straddle a
corner (it is pushed clear); interior brick sills are cut courses (no stool brick).

**Open items noted at the Phase 3 review:** 1/8" style tuning vs the reference (layer lines inside
cut walls, floor textures, denser tone); track legs overlap sheathing by steel thickness; insulation
passes through bridging; plates
mitered not lapped; brick corners at curved segments approximate.

**Version control:** git repo, remote https://github.com/jakeself-arch/rhino-mind-canvas (private,
branch `main`). Commit at each milestone (phase done, tests passing) with a clear message and push.
Since Phase 4, work happens on a branch with a PR (`gh` is at `C:\Program Files\GitHub CLI\gh.exe`,
not on PATH in the agent shell; signed in as jakeself-arch).
Pushing from the agent shell may fail with "terminal prompts disabled" if credentials expire — then run
`git push` in the user's Terminal panel so the GitHub sign-in can appear.

**Testing gotchas:** new Rhino instances stall on the "Autosave Recovery" dialog (user's autosave
files in `%LOCALAPPDATA%\McNeel\Rhinoceros\8.0\AutoSave` — never delete them). Before running any
test (they clear the doc), confirm the slot's doc is NOT one of the user's models (check `doc.Path`)
— and re-check before EVERY run: the user can open a model in an adopted slot at any time (it
happened during Phase 4). `spawn_slot` worked without the recovery dialog in Phase 4. Rhino crashed
once mid-build (not reproducible); write progress to a log file in long test scripts.

## Drawing scale presets
| Scale | LOD | Cut appearance |
|---|---|---|
| 1/16"–1/8" | schematic | heavy outline, white fill |
| 1/4"–1/2" | design | major layers outlined, light hatches |
| 3/4"–3" | detail | full material hatches, every component |
