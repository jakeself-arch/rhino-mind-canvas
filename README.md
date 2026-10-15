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
| `MCUpdate` | Rebuild selected walls (Enter = all), e.g. after editing library files |
| `MCLive` | Toggle live update (walls follow their curves while you edit them) |
| `MCSchedule` | Material takeoff (count, ft³, linear ft, ft²), optional CSV |
| `MCPurge` | Remove orphaned parts and unused member blocks |
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
