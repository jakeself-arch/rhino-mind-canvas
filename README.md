# Rhino Mind Canvas

Parametric building assemblies inside Rhino 8: draw a curve, pick an assembly, and get
every layer of the wall as real geometry — sheathing, insulation, individual studs and
tracks, individual bricks with mortar joints, ties and flashing — on material layers with
section hatches, ready for detailed section drawings.

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
| `MCLayers` | Edit the layer stack of selected walls: Replace, Insert, Remove, Thickness, ToExterior/ToInterior, Mirror, Reset, **SaveAs** a new assembly. Changes show immediately; Esc undoes them |
| `MCFraming` | Switch selected walls between wood and metal framing, change stud spacing / gauge |
| `MCOpening` | Place windows and doors: click a wall where the center goes (repeat, Enter to finish). Options: Type, Width, Height, Sill, Swing, Hinge (doors), HeadCourse (brick: None / Soldier / Sailor), SnapHead (default Yes: in brick walls the head lands on the coursing) |
| `MCEditOpening` | Change the type, size, sill, swing / hinge, head course or SnapHead of selected windows / doors (click their line or any of their parts), or `Remove` them |
| `MCUpdate` | Rebuild selected walls (Enter = all), e.g. after editing library files |
| `MCLive` | Toggle live update (walls follow their curves while you edit them) |
| `MCSchedule` | Material takeoff (count, ft³, linear ft, ft²) and a window / door schedule (type, size, sill, count), optional CSV |
| `MCPurge` | Remove orphaned parts, openings whose wall is gone, and unused member blocks |
| `MCLibrary` | Reload the library, list assemblies, open the library folder |
| `MCSectionCut` | Click a wall: clipping plane perpendicular to it + a saved wall-section view |
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
