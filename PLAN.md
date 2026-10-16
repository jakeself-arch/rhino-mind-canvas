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
  live.py              watches driver edits and rebuilds (toggle)
  schedule.py          quantity takeoff -> CSV
  drawing/             phase 3: display mode, MCDrawing, tone hatch, stipple, line weights
  dev.py               reload helper for development
library/
  materials/*.json     name -> color, render, section hatch, line weight
  profiles/*.json      name -> parametric profile definition
  framing/*.json       framing systems (wood, metal) — stud/plate/track rules
  assemblies/*.json    assembly definitions (stack of layers)
  styles/*.json        drawing styles per scale
commands/              one Rhino entry script per command (MCWall.py, MCUpdate.py, ...)
tools/install.py       registers command aliases in Rhino
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
| 7 | Joins: L/T wall joins, wall↔floor, wall↔roof | Code complete, **not yet run in Rhino** (`MCJoin`; `mindcanvas/joins/`; branch `claude/phase-7-resume-xd05z7`; run `tests/test_phase7.py`) |
| 8 | UI + entourage: Eto panel, assembly editor, profile capture, line-drawn entourage | |

## Resume here
_Updated at every milestone. A new session should read this section, `docs/DEVELOPING.md`, then continue._

**Current state (2026-10-15): Phase 7 (joins) verified in Rhino** on branch
`claude/phase-7-resume-xd05z7`. `tests/test_phase7.py` (`run(doc, drawing_on=True, captures=True,
log=<path>)`, ~17 s) passes; the offline tests (`tests/offline/test_join_plan.py`,
`test_join_find.py`) run with Rhino's CPython (`%USERPROFILE%\.rhinocode\py39-rh8\python.exe`,
no system Python on this machine). Only test fixes were needed: the 2x6 wood wall's sheathing is
OSB, and the gable section's crop window spans the wall normal (it was zero-width) at a quarter
point off the ridge. `test_phase0`..`test_phase6` + `test_layers` still pass with joins on (the
earlier drawings only changed by random curls / stipple). New drawings: `docs/drawings/f_corner_plan_1-1-2`,
`f_tee_plan_1-1-2`, `f_gable_section_1-1-2`. Open in the gable section: the gable wall's interior
gypsum continues above the ceiling into the attic. **Next: PR + merge, then Phase 8.**
Phases 0, 0.5, 1–7 done and verified in Rhino. All earlier tests passed at Phase 7:
`tests/test_phase0.py`, `test_phase1.py`,
`test_phase2.py`, `test_layers.py`, `test_phase3.py` (`run(doc, parts="a"|"b"|"ab")`),
`test_phase4.py` (`run(doc, drawing_on=True, captures=True)`, ~30 s), `test_phase5.py`
(`run(doc, drawing_on=True, captures=True, log=<path>)`, ~45 s), `test_phase6.py`
(`run(doc, drawing_on=True, captures=True, log=<path>)`, ~25 s; `only="drawings"` runs just the
details). Run each in an empty, unsaved document of your own `spawn_slot` (they clear the doc;
`test_phase5`..`test_phase7` assert `not doc.Path`). After a run, `git checkout` the regenerated
images of earlier phases (`git diff --name-only -- docs | xargs git checkout --`) unless joins
changed them on purpose.
Sample drawings: `docs/drawings/a_section_perspective_eighth.png`, `b_wall_section_1-1-2.png`,
`c_window_section_1-1-2.png`, `d_curtainwall_plan_<style>.png` (1-1/2" plans at a vertical
mullion for captured / ssg4 / ssg2 / butt / unitized), `d_curtainwall_plan_corner.png`,
`d_curtainwall_section_spandrel.png` and `d_curtainwall_section_unitized.png` (1-1/2" sections
at a transom / spandrel / slab edge with anchors and safing), `e_roof_eave_section_1-1-2.png`
(gable eave on a 2x6 wall), `e_roof_flat_edge_1-1-2.png` (low-slope edge),
`e_floor_section_1-1-2.png` (platform frame: wall, rim, joist, subfloor, wall above) and
`e_floor_deck_section_1-1-2.png` (concrete on composite deck over C-joists).

**Workflow for phases 7–8 (user, 2026-10-15):** continue through every remaining phase without
review stops, one phase per session: branch from main, PR, merge when the tests pass, then the
next session starts from main. Phase 7 lives on `claude/phase-7-resume-xd05z7` (cloud session
branch name) until it is verified.

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
