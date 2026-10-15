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

## Library files
Add your own files rather than editing someone else's: `library/materials/<topic>.json`,
`library/profiles/<topic>.json`, `library/framing/<system>.json`, `library/assemblies/<topic>.json`.
Material entries: see `library/materials/core.json` (color, render, section, print).

## Commands
Command logic lives in `mindcanvas/cmd/<name>.py` with `run()`; `commands/MC<Name>.py` is a
6-line entry script (copy an existing one). Shared helpers in `mindcanvas/cmd/ui.py`
(`select_drivers`, `pick_from_list`, `pick_assembly`, option helpers, `report`).
Engine API: `engine.create / build / update_params / set_override / set_assembly / rebuild_all`.

## Version control
GitHub: `jakeself-arch/rhino-mind-canvas`, branch `main`. Commit when a phase or feature is done
and its tests pass; run the regression tests (`tests/test_phase*.py`, `test_layers.py`) first.
Don't commit `docs/captures/` churn from exploratory runs unless the images document a result.

## Ownership while agents work in parallel
Only edit the files your brief assigns to you. If you need a change in a shared module
(`engine.py`, `geo.py`, `components/base.py`, `kinds/wall.py`, `docutil.py`, `cmd/ui.py`),
make the smallest additive change possible (new helper function, no signature changes) and
say so in your final report.
