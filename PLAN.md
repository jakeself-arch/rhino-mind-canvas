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
  engine.py            build / rebuild / delete for a driver
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
| — | **Review checkpoint with user** | |
| 4 | Openings: windows/doors, headers, jambs, sills, lintels, soldier courses | |
| 5 | Curtain wall: grid, IGUs, spandrels, joint styles (captured, 4-side SSG, 2-side SSG, butt, unitized), mullion materials | |
| 6 | Floors + roofs: joists, rafters, flat/shed/gable | |
| 7 | Joins: L/T wall joins, wall↔floor, wall↔roof | |
| 8 | UI + entourage: Eto panel, assembly editor, profile capture, line-drawn entourage | |

## Resume here
_Updated at every milestone. A new session should read this section, `docs/DEVELOPING.md`, then continue._

**Current state (2026-10-14): REVIEW CHECKPOINT.** Phases 0, 0.5, 1, 2, 3 done and verified in Rhino.
All tests pass: `tests/test_phase0.py`, `test_phase1.py`, `test_phase2.py`, `test_layers.py`,
`test_phase3.py` (`run(doc, parts="a"|"b"|"ab")`). Extra beyond plan: per-wall layer editing
(`MCLayers`, `mindcanvas/stack.py`, `library/layers/`) incl. two-sided brick; `MCDrawing Window` crop.
Sample drawings: `docs/drawings/a_section_perspective_eighth.png`, `b_wall_section_1-1-2.png`.

**Waiting on the user's review** before Phase 4 (openings). Do not start Phase 4 until they say so.

**Open items noted at review:** 1/8" style tuning vs the reference (layer lines inside cut walls,
floor textures, denser tone); track legs overlap sheathing by steel thickness; insulation passes
through bridging; plates mitered not lapped; brick corners at curved segments approximate.

**Version control:** git repo, remote https://github.com/jakeself-arch/rhino-mind-canvas (private,
branch `main`). Commit at each milestone (phase done, tests passing) with a clear message and push.
Pushing from the agent shell may fail with "terminal prompts disabled" if credentials expire — then run
`git push` in the user's Terminal panel so the GitHub sign-in can appear.

**Testing gotchas:** new Rhino instances stall on the "Autosave Recovery" dialog (user's autosave
files in `%LOCALAPPDATA%\McNeel\Rhinoceros\8.0\AutoSave` — never delete them). Before running any
test (they clear the doc), confirm the slot's doc is NOT one of the user's models (check `doc.Path`).

## Drawing scale presets
| Scale | LOD | Cut appearance |
|---|---|---|
| 1/16"–1/8" | schematic | heavy outline, white fill |
| 1/4"–1/2" | design | major layers outlined, light hatches |
| 3/4"–3" | detail | full material hatches, every component |
