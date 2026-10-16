# Rhino Mind Canvas

Parametric building assemblies inside Rhino 8: draw a curve, pick an assembly, and get
every layer of the wall, floor or roof as real geometry — sheathing, insulation, individual studs,
joists and rafters, individual bricks with mortar joints, ties and flashing, curtain-wall mullions,
shingle courses, fascia and gutters — on material layers with section hatches, ready for detailed
section drawings.

## Install (once)
1. Open Rhino 8.
2. Run `_RunPythonScript` and choose `tools/install.py` in this folder.
   This registers the `MC...` commands as Rhino aliases. Re-run it if new commands are added.
3. In each model, run **`MCSetup`** once. It tightens the model tolerance to 0.001"
   (thin layers such as a 1/32" membrane disappear at Rhino's default 0.01 ft) and turns on
   live update.

## Commands
| Command | What it does |
|---|---|
| `MCSetup` | Prepare the model (tolerance, driver layer, live update on) |
| `MCWall` | Pick an assembly, then select curves (or `Draw`) to make walls. Options: Height, Location line, Flip, Detail level |
| `MCEdit` | Change height, base offset, location line, flip or detail level of selected walls |
| `MCSetAssembly` | Swap the assembly type of selected walls |
| `MCJoin` | How selected walls join others: `Start` / `End` = Auto / Wrap / Miter / Butt / None, `Priority` (at an L the higher one runs through), `Report` lists every join (L, T, floors, roofs) |
| `MCLayers` | Edit the layer stack of selected walls: Replace, Insert, Remove, Thickness, ToExterior/ToInterior, Mirror, Reset, **SaveAs** a new assembly. Changes show immediately; Esc undoes them |
| `MCFraming` | Switch selected walls between wood and metal framing, change stud spacing / gauge |
| `MCOpening` | Place windows and doors: click a wall where the center goes (repeat, Enter to finish). Options: Type, Width, Height, Sill, Swing, Hinge (doors), HeadCourse (brick: None / Soldier / Sailor), SnapHead (default Yes: in brick walls the head lands on the coursing) |
| `MCEditOpening` | Change the type, size, sill, swing / hinge, head course or SnapHead of selected windows / doors (click their line or any of their parts), or `Remove` them |
| `MCCurtainWall` | Pick a curtain-wall assembly, then select curves (or `Draw`). Options: Height, Spacing (grid module), Style (Captured / SSG4 / SSG2 / Butt / Unitized), Detail level |
| `MCEditCurtainWall` | Grid (Equal / Fixed / List, Spacing, Bays), Transoms, Rows (infill per row), Cell (click panels to cycle vision / spandrel / shadow box), Style, Mullion profile, Spandrel (Glass / Metal), Slabs (anchors), Stack (unitized), Location, Flip, Detail, Height, BaseOffset |
| `MCFloor` | Pick a floor assembly, then select closed boundary curves (or `Draw`). Options: Elevation (framing bottom, e.g. the wall height), Span (Short / Long / Edge: click the edge the joists bear on), System (Keep / Wood / Metal), Detail |
| `MCEditFloor` | Elevation, Reference (FramingBottom / FramingTop / Top / Bottom), Span (Short / Long / Edge / Rotate90), SpacingInches, System, Detail |
| `MCRoof` | Pick a roof assembly, then select closed boundary curves (the plate line; or `Draw`). Options: PlateHeight, Shape (Flat / Shed / Gable), Pitch (x in 12), Overhang, Rake, Ridge (Long / Short / Edge), Flip (shed high side), System, Detail |
| `MCEditRoof` | The same options on selected roofs |
| `MCUpdate` | Rebuild selected assemblies (Enter = all), e.g. after editing library files |
| `MCLive` | Toggle live update (walls, floors and roofs follow their curves while you edit them) |
| `MCSchedule` | Material takeoff (count, ft³, linear ft, ft²), a window / door schedule (type, size, sill, count), a curtain-wall panel schedule (panels per infill type, glass / panel area), a floor / roof schedule (area, joist / rafter count, member, spacing, span, pitch, ridge and plate heights) and a joist / rafter cut list (member, length, count), optional CSV |
| `MCPurge` | Remove orphaned parts, openings whose wall is gone, and unused member blocks |
| `MCLibrary` | Reload the library, list assemblies, open the library folder |
| `MCSectionCut` | Click a wall, curtain wall, floor or roof: clipping plane perpendicular to it + a saved section view (floors are cut along the joists, roofs along the slope of the face you click). `Plan=Yes`: a horizontal cut at the picked height (or `CutHeightInches` above the base) and a top view, for plan details |
| `MCDisplaySetup` | Apply a drawing scale's section styles and the *MC Section* display mode to the view |
| `MCDrawing` | Finished 2D drawing of the current view (SVG with true line weights + PNG, or baked curves): cut poché, material hatches, tone hatching, stipple. `Window` crops it |
| `MCDrawingTag` | Mark objects as Ground (stippled), NoTone, Exclude or NoCut for drawings |

Drawing guide: [docs/DRAWING.md](docs/DRAWING.md).

## How walls work
- The **curve is the wall**. It lives on the `MindCanvas::_Drivers` layer (orange, never prints).
  Edit the curve (move points, move, rotate, scale) and the wall rebuilds. Delete the curve and
  the wall goes with it.
- Wall parts are grouped. To change a wall, edit its curve or use `MCEdit`; editing parts directly
  is overwritten on the next rebuild.
- **Exterior side**: on an open curve the exterior is on the **left** of the drawing direction;
  on a closed curve it is outside. Use `Flip` to reverse.
- **Location line**: where the curve sits in the stack — exterior face, interior face, center,
  or the faces/center of the structural core.
- **Detail level**: `Schematic` (solid layers, fast), `Design` (members), `Detail` (everything).
- Every material has its own layer under `MindCanvas::` with color, render material, print
  weight and a **section style**, so clipping planes show cut hatches automatically.
- Undo after a live update takes two steps (first the rebuild, then your edit).

## Windows and doors
- `MCOpening` → pick a type → click the wall. The opening is a short **cyan line** on
  `MindCanvas::_Openings`, across the unit width at its sill, on the wall's curve. Move it along
  the wall (or up / down to change the sill) and the wall rebuilds; scale it with `Scale1D` to
  change the width; delete it and the wall closes up. Edit the wall's curve and the openings
  keep their distance along it. Deleting a wall deletes its openings.
- **Width / height** are the unit (frame outside) size; **sill** is the unit's bottom above the
  wall base. Doors sit on the floor; **Hinge** is left / right as seen from the exterior.
- Every layer is cut: sheathing, insulation, membranes and gypsum to the rough opening (unit +
  1/2"), cladding in front of the frame to the unit + a 3/8" sealant joint.
- **Framing**: wood gets king + jack studs, a built-up header sized by the span (plies + plywood
  spacer or rigid insulation to fill the wall), a rough sill and cripples on the stud grid;
  metal gets boxed jamb studs, head / sill track and a box header (or `header_type: "L"` in the
  framing layer options for an L-header). Studs inside the opening are dropped; the layout keeps
  its grid. Insulation and bridging stop at the opening, bottom plates are cut at doors.
- **Frame position**: windows and doors sit at the insulation / weather line — the face of the
  first solid layer behind the cladding's air space (the continuous insulation in the brick
  walls, the WRB in the 2x6 brick wall). Set `"position": "brick"` in a type to set the frame
  in the masonry opening instead (`"set"` = how far in front of the back of the brick).
- **Brick**: whole bricks are cut around the opening with closures at the jambs (no slivers),
  a steel angle lintel sits in the first bed joint over the head with 6" bearing, an optional
  soldier or sailor course rides on it, the sill is a rowlock sloped out 15° on a mortar wedge
  (cut square at the cavity), with head flashing + end dams, weeps over the lintel, sill
  flashing. Sheet-metal closures line the jambs and head from the frame out to 1/2" behind the
  brick face, with sealant and backer rod between them and the brick.
- **SnapHead** (on by default in `MCOpening` / `MCEditOpening`): in a brick wall a window's
  sill moves (a door's height changes) by up to half a course so the head + sealant joint lands
  on a bed joint and the lintel sits right over the frame. With it off, an off-course head
  leaves a gap under the lintel and you get a warning.
- The unit: frame, sashes / mullions and insulated glass (two lites + spacer) for windows;
  frame, leaf (optional glass lite), threshold and a swing arc in plan for doors; interior jamb
  liners and a stool, a sill pan and a head drip cap (walls without brick).
- Types live in `library/openings/*.json` (see "Customizing the library").

## Curtain walls
- `MCCurtainWall` → pick an assembly (`CW - Captured, Aluminum 2-1/2 x 6`, `CW - 4-Side SSG ...`,
  `CW - 2-Side SSG ...`, `CW - Butt Glazed ...`, `CW - Unitized ...`, steel and timber versions)
  → select curves. Like walls, the **curve is the curtain wall** (exterior on the left of an open
  curve, outside of a closed one; `Location` says where the curve sits: exterior face of the
  glass by default, glass centre, face of the caps, or back of the mullions).
- **Grid**: each straight run is divided into bays — `Equal` (equal bays no wider than
  `Spacing`), `Fixed` (a `Spacing` module from the start of each run, the remainder in the last
  bay), or `List` (bay widths, repeated). Polyline kinks over 25° get an **L-shaped corner
  mullion** (convex and concave); arcs are **faceted**: every bay is a flat panel and the mullion
  between two facets sits on the bisector. `Transoms` are heights above the base; the sill and
  head are always there.
- **Infill** per row (bottom → top, the last repeats; `Rows` in `MCEditCurtainWall`, e.g. `V,V,S`)
  and per cell (`Cell`: click panels to cycle **vision** → **spandrel** → **shadow box**):
  vision = insulated glass (two lites + spacer); spandrel = opaque spandrel glass (or a metal
  panel: `Spandrel=Metal`) with an air space, mineral wool and a back pan; shadow box = vision
  glass with a back pan and insulation at the back of the mullions.
- **Joint styles** (`Style`):
  - **Captured** (stick): tube mullion with screw spline, thermal isolator, pressure plate, snap
    cap and EPDM gaskets each side of the glass; verticals run full height, horizontals between.
  - **SSG4** (4-side structurally glazed): no caps — structural silicone + spacer tape bond the
    glass to the tube, a silicone weather seal on a backer rod fills the joint.
  - **SSG2**: SSG verticals with captured horizontals (`"ssg_sides": "horizontal"` swaps them).
  - **Butt**: no vertical mullions — silicone butt joints (outer + inner seal, backer rod),
    captured head and sill; `"butt": {"backup": "fin"}` adds glass fins.
  - **Unitized**: split mullions (male / female halves with integral exterior lips, interlocking
    legs, weather and air seal gaskets); `Stack` heights get split horizontals (stack joints);
    the sill sits on a starter sill, the head in a head receptor.
- **Mullions**: `Mullion` picks a profile — aluminum (default `2-1/2 x 6`), steel tubes, or timber
  (solid glulam with an aluminum glazing adaptor carrying the pressure plate).
- **Detail level**: Schematic (panels + plain mullion boxes), Design (profiles, caps, glass as one
  slab, back pans), Detail (gaskets, isolators, pressure plates, IGU lites + spacers, silicone,
  backer rods, setting blocks, perimeter sealant + backer rod at head / sill / jambs, and with
  `Slabs` set: clip-angle anchors at every mullion, fire safing + smoke seal at each slab edge).
- **Doors**: `MCOpening` with a door type on a curtain wall puts the door in the bay you click; it
  fills the bay's clear width, gets a transom over its head, and the sill under it is left out
  (`Door - Aluminum Entrance, Full Lite` is made for this).
- **Drawings**: `MCSectionCut` works on curtain walls; `Plan=Yes` makes a plan detail at a
  mullion. See `docs/drawings/d_curtainwall_*.png` for 1-1/2" plans of every style and sections
  at a spandrel / slab edge.
- `MCSchedule` lists panels per curtain wall and infill type with their glass area; the
  takeoff totals mullion / transom / cap lengths and glass area per material.

## How walls join (Phase 7)
Joins are automatic: draw walls so their ends meet and they join; nothing to select.
- **L**: two wall ends whose lines cross near both ends (drawn on any location line). The layers
  outside the structure miter around the corner on each side; one wall's framing runs through to
  the far face of the other's framing, the other stops against it (a backer stud in the through
  wall gives the inside finish nailing). Brick on both walls of a square corner **laps**: the
  courses alternate. Styles (`MCJoin`): **Wrap** (default), **Miter** (everything on one miter),
  **Butt** (one wall runs through whole), **None**. `Priority` picks the wall that runs through
  (else the thicker structure).
- **T**: a wall ending inside another wall (on its face, center or core). The joining wall's
  framing runs through the host's finish to its studs; the host's finish is notched around it and
  gets two backer studs. `Butt` stops the joining wall at the host's face (no notch).
- **Under a floor**: a wall whose top is at the floor's framing bottom and that runs along the
  floor's boundary carries its exterior layers (sheathing, WRB, cladding) up over the rim joist to
  the wall above. The floor's ceiling and finish floor stop at the interior face of the wall on each
  edge (no fixed inset).
- **Under a roof**: a wall whose top is at the roof's plate height along its plate line gives the
  roof its bearing-wall dimensions; its exterior layers stop under the rafter tails; gable-end and
  shed walls are filled up to the underside of the rafters (gable studs on the stud grid, cavity
  fill, every layer).
- Moving, editing or deleting a wall, floor or roof rebuilds everything joined to it (also what it
  was joined to before the edit).

## Floors and roofs
- **The closed curve is the floor / roof.** A floor's boundary is the outside face of its rim
  (= the outside face of the wall framing below); a roof's boundary is the **plate line** (the
  outside face of the wall framing it bears on). Edit the curve and the floor / roof rebuilds.
- **Stacking on walls**: give a floor `Elevation` = the wall height (its joists bear on the top
  plates) and the wall above `BaseOffset` = the top of the subfloor; give a roof `PlateHeight` = the
  wall height. Draw the boundary on the outside face of the wall framing (walls with Location =
  CoreExterior can share the same curve points). The joins then do the rest (see above); without
  walls, ceilings stop `inset` inside the boundary (6" = a 2x6 wall + 1/2" gypsum).
- **Floors** (`Floor - 2x10 Wood Joists, Plywood`, `... 11-7/8" I-Joist, OSB`,
  `... 10" Metal Joists, Plywood`, `... Concrete on Metal Deck / 10" Metal Joists`): layers top →
  bottom (finish, subfloor / deck + concrete, joists, ceiling). Joists run across the **short** way
  by default (`Span`: Long, an angle, or click the edge they bear on), every `spacing` from the
  boundary, between the rim joists all around (wood: 2x rim / rim board plies; metal: joist track
  with the C-joists inside it). L-shapes and notches work: a joist only exists where both of its
  sides are inside the rim. Detail adds solid blocking rows (metal: C blocking + a flat strap under
  the bottom flanges) at most 8' apart and insulation between the joists (`cavity_fill`,
  `fill_depth`). A composite metal deck has ribs across the joists and the concrete topping is
  poured into its flutes as one solid. A span longer than the typical table in
  `library/framing/joists.json` gives a warning.
- **Wood ↔ metal** is one line, as for walls: `System=Metal` (or
  `engine.set_override(doc, floor, "Framing", "system", "metal")`); a 2x10 becomes a 10" C-joist.
- **Roofs** (`Roof - Asphalt Shingle / 2x8 Rafters, Vented Attic`, `... 2x10 Rafters, Cathedral`,
  `... 2x10 Rafters, Shed`, `Roof - Low Slope Membrane / 2x10 Joists`):
  - **Gable**: the ridge runs along the long side (`Ridge`: Short, an angle, or the edge you click),
    centred between the eave walls. Rafters every `spacing` with a **birdsmouth** on the plate (seat
    = full wall depth), a ridge board one size deeper than the rafter plumb cut, end rafters over the
    gable walls, barge rafters at the rake overhang carried by flat 2x4 lookouts.
  - **Shed**: one slope; rafters bear on both walls (the high wall's plate height is in
    `MCSchedule`); `Flip` puts the high side on the other side.
  - **Flat** (low slope): level joists, the slope comes from **tapered insulation** (`taper`: in /
    ft, thickening away from the low eave), stacked 2x nailers around the edge, membrane wrapped
    over them under the edge metal.
  - `Pitch` is rise in 12; `Overhang` is the eave (plate line to the face of the fascia), `Rake` the
    gable-end / side overhang.
  - Layers on the roof plane follow it out to the fascia (roofing, underlayment with an **ice and
    water shield** strip from the eave to 24" inside the wall, sheathing); layers under the rafters
    (cathedral ceilings) stop at the inside of the walls. An attic `ceiling` stack puts ceiling
    joists beside every rafter (heel-cut under the roof), blown insulation between and over them
    (kept under the roof with a vent gap) and the gypsum ceiling.
  - **Detail** (vs Design): shingle courses (5" exposure, each course a thin wedge so the section
    shows the overlap), ice shield, drip edges, K-style gutters on the low eaves, vented soffit with
    a soffit nailer, vented bird blocks between the rafters on the plate, lookouts, ridge cap,
    insulation. Design has rafters, ridge, fascia, sub-fascia, soffit, rake boards. Schematic
    shows every layer as a solid slab.
- **Drawings**: `MCSectionCut` on a floor cuts along the joists, on a roof along the slope. See
  `docs/drawings/e_roof_eave_section_1-1-2.png`, `e_roof_flat_edge_1-1-2.png`,
  `e_floor_section_1-1-2.png`, `e_floor_deck_section_1-1-2.png`.

### Example: two-sided brick wall
Select a brick-veneer wall → `MCLayers` → `Replace` → pick the last layer (Gypsum) →
choose the brick layer from the list → optionally `Insert` an "Air Space" before it →
Enter. To reuse it, `SaveAs` "Brick Both Sides / 6in Metal Stud".

## Customizing the library (no code)
Everything lives in `library/` as JSON. Add a new file rather than editing the shipped ones;
files load alphabetically and later entries with the same name win. Run `MCLibrary` or
`MCUpdate` to see changes. Lengths are inches and accept `5.5`, `"3-5/8"`, `"1'-6\""`.

- **Material** (`library/materials/*.json`): color, render (gloss, transparency), section
  (`fill`: white / solid / hatch / none, `hatch`, `scale`, `rotation`), print weight (mm).
- **Profile** (`library/profiles/*.json`): member cross-sections — `rect`, `c_stud`, `track`,
  `angle`, `tube`, or `custom` with a list of points.
- **Framing system** (`library/framing/*.json`): wood / metal rules — which studs, plates,
  tracks, bridging.
- **Assembly** (`library/assemblies/*.json`): a stack of layers from exterior to interior:
  ```json
  "My Wall": {
    "kind": "wall", "default_height": "10'", "default_reference": "interior_face",
    "layers": [
      {"name": "Siding",    "component": "solid",    "material": "Fiber Cement Siding", "thickness": "5/8"},
      {"name": "Air Gap",   "component": "void",     "thickness": "3/4"},
      {"name": "Sheathing", "component": "solid",    "material": "OSB Sheathing", "thickness": "7/16"},
      {"name": "Framing",   "component": "framing",  "thickness": "5-1/2", "core": true,
       "options": {"system": "wood", "spacing": 16, "cavity_fill": "Mineral Wool Batt"}},
      {"name": "Gypsum",    "component": "solid",    "material": "Gypsum Board", "thickness": "5/8"}
    ]
  }
  ```
- **Window / door type** (`library/openings/*.json`): size, sill, frame (face, depth, material),
  operation (fixed / casement / awning / double_hung / sliding), sash, mullions, glazing; doors:
  leaf (thickness, material, glass lite), threshold, swing / hinge. Brick details under
  `"masonry"` (lintel, bearing, head course, sill, slope, flashing, weeps). See the comment at
  the top of `windows.json` for every key. Lintels are `family: "lintel"` angles in
  `library/profiles/openings.json`, picked by `max_span`; headers come from the framing
  system's `"header"` table (`library/framing/*.json`).
- **Curtain wall** (`library/assemblies/*.json`, `"kind": "curtain_wall"`): style, mullion
  (+ optional transom) profile, grid, spacing, transoms, infill rows, and any setting from
  `mindcanvas/curtainwall/settings.py` (glazing, bite, gasket, cap depth, SSG joint, butt joint /
  fins, unitized split, spandrel, shadow box, anchors, perimeter joint). See the comment at the
  top of `library/assemblies/curtainwalls.json`:
  ```json
  "My Curtain Wall": {
    "kind": "curtain_wall", "default_height": "13'-4\"", "style": "captured",
    "mullion": "CW Aluminum 2-1/2 x 7-1/2", "grid": "fixed", "spacing": 60,
    "transoms": [30, 126], "infill": {"rows": ["vision", "vision", "spandrel"]},
    "cap": {"depth": "1-1/2"}, "glazing": {"lites": 2, "glass": "1/4", "space": "1/2"}
  }
  ```
  Mullion profiles live in `library/profiles/curtainwall.json` (`width`, `depth`, `t`, `material`,
  `solid` for timber).
- **Floor** (`library/assemblies/*.json`, `"kind": "floor"`): layers TOP → BOTTOM; components
  `solid` / `membrane` / `void` (option `inset`), `joists` (`system`, `joist`, `spacing`, `rim`,
  `rim_plies`, `blocking`, `blocking_spacing`, `cavity_fill`, `fill_depth`), `deck` (`profile`,
  `fill`):
  ```json
  "My Floor": {
    "kind": "floor",
    "layers": [
      {"name": "Subfloor", "component": "solid",  "material": "Plywood Sheathing", "thickness": "3/4"},
      {"name": "Framing",  "component": "joists", "material": "Wood Framing", "thickness": "11-1/4",
       "core": true, "options": {"system": "wood", "spacing": 12, "cavity_fill": "Mineral Wool Batt"}},
      {"name": "Ceiling",  "component": "solid",  "material": "Gypsum Board", "thickness": "5/8",
       "options": {"inset": 6}}
    ]
  }
  ```
- **Roof** (`"kind": "roof"`): `shape` (flat / shed / gable), `pitch`, `overhang`, `rake`, `ridge`,
  `wall_depth` / `wall_ext` / `wall_int` (the bearing walls), `trim` (any key of `TRIM` in
  `mindcanvas/roofs/shape.py`: fascia, sub-fascia, soffit + vent + nailer, drip edge, gutter
  (`"k"` or null), rake board, barge, lookout, bird blocks, ridge cap, edge nailer), `layers` on
  the roof plane TOP → BOTTOM around the `rafters` layer (`system`, `rafter`, `spacing`,
  `cavity_fill`, `fill_depth`), layer options `taper` (in / ft), `eave_membrane`
  (`{"material", "width"}`), `region` (overhang / interior), shingles `exposure` / `tip`, and an
  optional attic `ceiling` stack (a `joists` layer = ceiling joists). See the comment at the top of
  `library/assemblies/roofs.json`.
- **Joists and rafters** (`library/framing/joists.json`): the `wood_joists` / `metal_joists`
  systems (member family, spacing, rim plies, blocking, strap, ridge family, typical spans,
  member names). Members are profiles in `library/profiles/floors_roofs.json` (lumber, I-joists
  `"type": "i_joist"`, rim boards, metal C-joists + joist tracks, composite decks).
- **Layer preset** (`library/layers/*.json`): a reusable layer ("Gypsum Board 5/8",
  "Metal Studs 6"). Appears in `MCLayers`; assemblies can use `{"preset": "Gypsum Board 5/8"}`
  and override any key. Every layer used in any assembly also shows up in `MCLayers`,
  so the brick layer of a brick assembly can be dropped into another wall.
- **Your own assemblies**: `MCLayers` → `SaveAs` writes to
  `library/assemblies/zz_user_assemblies.json`. Edit or delete entries there freely.
- **New kinds of sub-components** (code): add one Python file to `mindcanvas/components/`.
  See `docs/DEVELOPING.md`.

## Project layout
See `PLAN.md` for the architecture and roadmap and `docs/DEVELOPING.md` for the developer contract.
