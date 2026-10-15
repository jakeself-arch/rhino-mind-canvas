# Drawings (Phase 3)

Two ways to look at a cut model:

- **Live view**: a clipping plane, the *MC Section* display mode and section styles per material.
  Quick, interactive and printable, but with one line weight per class and no tone.
- **MCDrawing**: a finished 2D drawing of the current view, written as SVG with true line widths
  plus a PNG preview, and/or baked into the model as curves with plot weights. It draws heavy
  cut outlines over white poché, thin layer lines, material hatches at detail scales, tonal
  hatching on faces turned away from the sun, stippled ground, and lines that get thinner and
  greyer with depth.

## Commands

| command | what it does |
|---|---|
| `MCSetup` | Also adds the hatch patterns and the *MC Section* display mode. |
| `MCDisplaySetup` | Pick a scale. Applies that scale's section styles to every `MindCanvas::<Material>` layer and sets the active view to *MC Section*. `RebuildMode=Yes` recreates the display mode. |
| `MCSectionCut` | Click a wall where you want to cut. This adds a clipping plane perpendicular to the wall at that point and points the active view at the cut: a parallel wall section by default, or a section perspective with `Perspective=Yes`. It also saves a named view. `DepthInches` (default 24) adds a second "depth" plane that hides everything farther than that beyond the cut; this plane makes no poché. |
| `MCDrawing` | Draws the active view, including every clipping plane that clips it. Options: `Scale`, `Output` (SVG / Bake / Both), `Tone`, `Stipple`, `SetLOD` (first rebuild walls at the scale's level of detail), `Folder`, `Window` (drag a rectangle in the view to crop the drawing to it — use it for wall sections so neighboring walls stay off the sheet). Reports the time taken and the output paths. |
| `MCDrawingTag` | Tags objects with `Ground` (stippled beyond the cut and in section), `NoTone`, `Exclude` (left out of drawings) or `NoCut` (drawn but never poché'd). `Mode=Remove` takes a tag off; `Clear` removes all tags. Tags are stored as user text `mc.draw` on the object. You can also put that user text on a layer. |

Typical session: model, then `MCSectionCut` (or place your own clipping plane), then
`MCDisplaySetup` to check the live view, then `MCDrawing`. For a section perspective, put a
clipping plane in a perspective view, aim the camera into the cut, and run `MCDrawing`.

SVG files go to `<model folder>\drawings\<model>_<view>_<Scale>.svg` (or
`Documents\MindCanvas Drawings` for an unsaved model). Baked drawings are placed to the right of
the model at model scale on `MindCanvas Drawing::<class>` layers. Put them in a layout detail at the
same scale to print them at true size. Re-running `MCDrawing` replaces the previous bake.

## Scale presets (`library/styles/`)

| preset | option | ratio | wall LOD | cut appearance |
|---|---|---|---|---|
| 1/16" = 1'-0" | Sixteenth | 1:192 | schematic | white poché, heavy outline |
| 1/8" = 1'-0" | Eighth | 1:96 | schematic | white poché, heavy outline, thin layer lines |
| 1/4" = 1'-0" | Quarter | 1:48 | design | light brick hatch, batt insulation, studs white |
| 1/2" = 1'-0" | Half | 1:24 | design | material hatches, steel black |
| 3/4" = 1'-0" | ThreeQuarter | 1:16 | detail | as 1-1/2" |
| 1-1/2" = 1'-0" | OneAndHalf | 1:8 | detail | every component; brick, batt, gypsum, concrete hatches; steel, ties, flashing, WRB black |
| 3" = 1'-0" | Three | 1:4 | detail | as 1-1/2" with heavier pens |

Below a preset's `min_part_mm`, parts are too small to read on paper. They are left out of the
hidden-line pass but still contribute to the cut outline. If many parts are skipped, MCDrawing
suggests `SetLOD=Yes`.

## Tuning a style

Every preset `extends` `base` (in `base.json`). Nested dicts merge, so a preset only lists what
changes. To make your own, add `library/styles/zz_mine.json`:

```json
{
  "My 1/8\"": {
    "extends": "1/8\" = 1'-0\"", "option": "MyEighth",
    "classes": {"cut": {"w": 0.8}, "tone": {"w": 0.05}},
    "tone": {"levels": [[-0.35, 0.35], [0.05, 0.6], [0.3, 1.1]]},
    "stipple": {"density": 2.5}
  }
}
```

| key | meaning |
|---|---|
| `scale` | Drawing scale ratio. 96 means 1/8" = 1'-0". In a perspective, this scale applies where the view axis meets the cut plane. |
| `lod` | Wall LOD that `SetLOD` switches to. |
| `cut_mode` | `white`: every cut is white poché with no hatches, except ground. `material`: use the per-material settings. |
| `classes.<cls>.w` | Pen width in mm at the near end of the depth range. Classes: `cut` (union outline), `cut_inner` (each material loop), `cut_hatch`, `silhouette`, `edge`, `junction`, `hidden`, `tone`, `stipple` (dot diameter). |
| `depth` | `width_far` and `grey_far` set how thin and how grey the farthest lines get. `gamma` shapes the falloff curve. `far_percentile` picks which depth counts as "far". `split_mm` splits long receding lines so their weight changes along their length. |
| `min_part_mm`, `min_cut_mm` | Paper-size limits. Parts smaller than `min_part_mm` are not drawn. Cut loops smaller than `min_cut_mm` get no hatch and no inner line. |
| `sun` | Vector pointing toward the sun. |
| `tone.levels` | `[[max n·sun, spacing mm], ...]`, darkest first. Faces with a larger n·sun get no tone. |
| `tone.min_mm` | Perspective thinning: lines packed closer than this are dropped, keeping every 2^m-th line. |
| `tone.min_face_mm`, `tone.max_lines`, `tone.step_px` | Face-size filter, safety cap, and z-buffer sampling step. |
| `stipple.density` | Ground dots per mm² near the viewer. `near_p` and `far_p` set the probability that a dot is kept near versus far. `max_samples` caps the work. |
| `stipple.cut_density`, `stipple.band_mm` | Dot density for ground in section, and the depth of the stippled band under a ground *surface* cut line. |
| `junction.on` | Draws lines where solids interpenetrate. Off by default because it is slow. |
| `materials` | Per material name or pattern (`"Brick*"`). Keys: `fill` (`white`, `black`, `grey`, `none`), `hatch` (`{"pattern", "mm", "rot"}`), `batt`, `cross`, `stipple`, `ground`, `inner`, `tone`. The most specific match wins and is merged over `"*"`. |

Hatch patterns (`mindcanvas/drawing/patterns.py`) all have a unit repeat, so `"mm"` is the repeat on
paper: MC Brick, MC Brick Coursing, MC Concrete, MC Earth, MC Batt, MC Rigid, MC Plywood, MC Wood,
MC Gypsum. In the 2D drawing, batt insulation is drawn as a looping curve fitted to each piece, and
wood framing as an X.

The material JSON (`library/materials`) only holds model data and the default live section hatch.
Everything that depends on scale belongs in the style.

## How it works (`mindcanvas/drawing/`)

1. `pipeline.make` finds the clipping planes that clip the view (user text `mc.clip=depth` marks a
   plane that limits depth only). It probes the HLD for the world-to-2D transform, and sets the
   page scale at the cut plane.
2. `scene` explodes block instances recursively and caches geometry, render meshes and boxes per
   definition. It drops parts that are clipped away or out of view, and flags the ones that are
   too small.
3. `hld` runs Rhino's Make2D engine (`HiddenLineDrawing`) for edges and silhouettes.
4. `cut` builds closed loops with `BrepPlane` for each part that straddles the plane. Block parts
   are cut in definition space. The page is then cropped to the content plus a ground margin.
5. `visibility` (z-buffer plus exact ray fallback) clips the lines from `tone` and finds the
   visible ground for `stipple`.
6. `cut` adds the hatches and the union outline. Depth is normalised, with 0 at the cut.
7. The writers output `svg` (layers per class, painter's order), `png` (preview) and `bake`.

Guards against hangs: sample counts are capped (`stipple.max_samples`, `max_cut_dots`,
`tone.max_lines`, 400 z-buffer samples per line), all sampling is clipped to the page, and Esc
cancels between steps inside `MCDrawing`.

## Known limits

- Tone works on planar faces only and does not cast shadows. Curved walls get no tone.
- Junction lines are off by default; assemblies should not overlap.
- The live view cannot do tone, depth fade or a per-segment line hierarchy. Use MCDrawing for
  finished sheets.
- Baked dots are very short strokes. Rhino prints them as dots when the line caps are round.
