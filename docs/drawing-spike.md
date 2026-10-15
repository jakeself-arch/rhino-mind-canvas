# Drawing spike: section perspectives in Rhino 8

Phase 0.5 spike. Rhino 8.35 (CPython 3.9.10), RhinoCommon. Every claim below was checked by running
code in Rhino. Test scene: a 30'×20' two-storey box in inches, with layered walls (brick, air,
insulation, sheathing, stud, gypsum), 8" slabs, beams, columns, a stair and tables. It has 3,416
bricks and 152 studs as block instances (3,629 HLD items in all), a ground box, a vertical clipping
plane at y = 120" and a 20 mm perspective camera.

Prototypes are in `spikes/`. Each file is exec'd with `__rhino_doc__` available. Images are in
`docs/spike-output/`.

| file | what |
|---|---|
| `scene_build.py` | test scene (layers `MC::*`, block defs `MC_Brick` / `MC_Stud`, clip plane, camera) |
| `live_view.py` | section styles per layer, hatch patterns, "MC Section" display mode |
| `export_vector.py` | live view → vector PDF / SVG |
| `q2_blocks.py` | block-instance section-style test cases |
| `hld_core.py` | scene collection (blocks exploded with transforms + tags), HLD compute, classification |
| `hld_drawing.py` | full 2D pipeline: HLD edges, cut loops, tone hatch, stipple, z-buffer visibility, SVG writer, bake |
| `run_drawing.py` | runner → `10_hld_drawing.svg/png` |
| `bake_and_print.py` | bake 2D into doc with PlotWeights → PDF/SVG via Rhino print |
| `svg_preview.py` | tiny System.Drawing SVG rasterizer (no PDF/SVG renderer is installed on this machine) |

**Verdict:** use **two paths**.
- **Live view** (clipping plane, section styles and a custom display mode) for working views and
  quick prints. It gets white-fill cuts with heavy outlines and vector export, but it can't do
  tone, depth fade or a real line hierarchy.
- **Drawing pipeline** (HLD, z-buffer and our own 2D writer) for the finished drawing. It gets
  everything in the reference except a hand-drawn look, which we don't want anyway. The scene
  above takes about 15–25 s end to end.

Best result: `10_hld_drawing.png`. Live view: `01_live_mc_section.png`.

---

## Q1: Live view path

**Works**
- Per-layer styles: build a `Rhino.DocObjects.SectionStyle` with:
  - `BackgroundFillMode = SectionBackgroundFillMode.SolidColor`, `BackgroundFillColor = White`
  - `BoundaryVisible = True`, `BoundaryWidthScale = 2–3`
  - `HatchIndex`, `HatchScale`, `HatchRotationRadians`, `HatchPatternColor`
  - `SectionFillRule = SolidObjects`

  Then call `layer.SetCustomSectionStyle(style)`. This works in perspective, including hatches
  (`01_live_mc_section.png`, `02_live_wall_closeup.png`).
- Display mode:
  - Create: `DisplayModeDescription.CopyDisplayMode(DisplayModeDescription.PenId, "MC Section")`.
  - Set attributes: `SetFill(Color.White)`, `ShowIsoCurves = False`, `ShowTangentEdges = False`,
    `UseSectionStyles = True`, `ShowClippingFills = True`, `ShowClippingEdges = True`,
    `ClippingEdgeColorUsage = SolidColor`, `ClippingEdgeThickness = 1`.
  - Commit: `DisplayModeDescription.UpdateDisplayMode(dm)`. Assign:
    `viewport.DisplayMode = dm`.
- Vector export: `ViewCaptureSettings(view, Size(px), dpi)` with `RasterMode = False`,
  `UsePrintWidths = True` and `OutputColor = PrintColor`. Then use either
  `FilePdf.Create(); pdf.AddPage(settings); pdf.Write(path)` or
  `ViewCapture.CaptureToSvg(settings).Save(path)`.

  The output is genuinely vector:
  - section fills are white-filled paths (250 of them)
  - hatch lines are separate paths
  - Pen-mode hidden-line removal is preserved
  - boundaries come out wider (0.48/0.72 pt vs 0.24 pt)

  On this scene the PDF took 12.5 s and the SVG took 8.4 s / 21k paths (`03_live_export.*`).

**Gotchas (all verified)**
1. **Commit layer section styles with `doc.Layers.Modify(layer, index, True)`.** Calling
   `SetCustomSectionStyle` on the table's Layer instance stores the style (it reads back fine), but
   the display ignores it, so the fill stays the layer colour. Object-level styles
   (`attrs.SectionAttributesSource = FromObject` + `attrs.SetCustomSectionStyle`) work through
   `ModifyAttributes`.
2. **`HatchIndex = -1` does not mean "no hatch".** Once the doc has hatch patterns, it falls back
   to a solid hatch in `HatchPatternColor` (default black), which gives black poché. For "white,
   no hatch", use the `Solid` pattern with `HatchPatternColor = White`.
3. **A doc made without a template has zero hatch patterns.** Add them from
   `HatchPattern.Defaults.{Solid,Hatch1,Hatch2,Hatch3,Grid,...}` or build custom ones with
   `HatchLine` (`Angle`, `BasePoint`, `Offset`) + `HatchPattern.AddHatchLine`.
   `Hatch1` = 0.125 units spacing.
4. **Clipping plane side:** display keeps the side the plane normal points to.
   `AddClippingPlane(plane, du, dv, [viewportId])` clips only the listed viewports.
5. **Section hatch scale is in model units.** A fine brick hatch turns solid black when zoomed out,
   so styles must depend on drawing scale.
6. **Silhouette/crease thickness ("Technical" settings) is not exposed** in
   `DisplayPipelineAttributes`. It only exists in the exported ini (`[...\Objects\Technical]`:
   `TechnicalMask`, `TSiThickness` = silhouette, `TCThickness` = crease, `TEThickness`,
   `TIThickness`). You can patch it with `ExportToFile` → edit → `DeleteDisplayMode` →
   `ImportFromFile`. Import works, but I did not verify that the thickness changes reach the
   screen.
7. **Overlapping solids** (slab running through the wall) draw both cut outlines. Assemblies should
   not interpenetrate.

**Limits of the live path:** no tone hatching, no depth fade, line weight only per display-mode
class (pixels), no per-segment control, and no cut-outline hierarchy (every layer gets the same
boundary).

## Q2: Section styles inside block instances

Tested in `q2_blocks.py` / `04_q2_blocks_section_styles.png`. Cubes are left to right A–E.

| case | definition geometry | instance layer | style used |
|---|---|---|---|
| A | layer Brick, `FromLayer` | Concrete | **Brick** (definition object's layer) |
| B | layer Default, `FromParent` | Brick | **Brick** (instance layer) |
| C | layer Default, `FromLayer` | Brick | Default layer (no style, so the display-mode fill) |
| D | layer Brick, `FromParent` | Ground | **Ground** (instance layer) |
| E | nested, `FromParent` at both levels | Ground | **Ground** (works through nesting) |

**Rule:** `SectionAttributesSource` on the definition objects decides. Use `FromParent` and the
instance's layer wins. Use `FromLayer` and the definition object's layer wins.

**Recommendation:** put block-definition geometry on layer 0 with:
- `SectionAttributesSource = FromParent`
- `ColorSource = ColorFromParent`
- `PlotWeightSource = PlotWeightFromParent`
- `PlotColorSource = PlotColorFromParent`

Then one `Brick` definition can serve any material layer, and `docutil.py` should create block
definitions this way. Bricks in the scene (definition on `MC::Brick`, `FromLayer`) also cut
correctly.

## Q3: Make2D path (`Rhino.Geometry.HiddenLineDrawing`)

**API that works**

Parameters:
- `HiddenLineDrawingParameters()` with `AbsoluteTolerance`, `IncludeTangentEdges=False`,
  `IncludeHiddenCurves=False`, `Flatten=False`, `SetViewport(rhinoViewport)` and
  `AddClippingPlane(plane)`.
- `AddGeometry(geom, xform, tag)` takes a transform, so **block instances are handled by
  exploding definitions recursively and passing `InstanceXform`**. Nothing gets baked.
- `tag` is any Python object (a dict). It comes back as `seg.ParentCurve.SourceObject.Tag`, which
  gives source object id and effective layer per segment.

Compute: `HiddenLineDrawing.Compute(params, True)` (multithreaded).

Per segment:
- `seg.SegmentVisibility`: Visible / Hidden / Duplicate / Clipped / Projecting
- `seg.ParentCurve.SilhouetteType`: SectionCut, Crease, NonSilhouetteCrease, Boundary,
  Projecting, Tangent, ...
- `seg.IsSceneSilhouette`
- `seg.ParentCurve.SourceObjectComponentIndex`: BrepEdge / BrepFace
- `seg.CurveGeometry`: the 2D curve
- `ParentCurve` can be `None`, so guard for it.

**Depth per segment:** with `Flatten=False`, output curves keep a depth coordinate.
`hld.WorldToHiddenLine.TryGetInverse()` maps any output point back to exact world coordinates
(verified: corners came back as exactly (330, 220, 8) etc.). Depth = `distance(H2W(mid), camera)`.
`WorldToHiddenLine` is a projective 4×4. `Point3d.Transform` does the w-divide.

**Timings (all multithreaded):**

| scene | items | compute | segments |
|---|---|---|---|
| no bricks | 208 | ~1.2 s | |
| 500 bricks | 556 | 1.1 s | |
| 1,500 bricks | 1,556 | 1.3 s | |
| all bricks | 3,629 | 2.1 s | 3,152 |

Iterating the segments is negligible. Single-threaded is about 5× slower, and
`IncludeHiddenCurves=True` is another 4–5× slower. A real 20'×10' brick-veneer wall is about 3k
parts, so a building is about 30k items: estimate 10–20 s, still fine.

**Gotchas**
1. **The HLD clipping plane keeps the side opposite the display convention.** Pass a flipped copy
   (`pl = Plane(clip); pl.Flip()`).
2. **SectionCut segments also come from the view-frustum planes** (`ClippingPlaneIndex` 3/4 vs 5
   for ours). Filter by checking that the back-projected point lies on the user plane.
3. **HLD only draws each object's own edges.** Interpenetrating or abutting solids (slab into
   wall) get no junction line. The spike adds `Intersection.BrepBrep` junction curves
   (1,082 curves, ~5 s with exact ray clipping). Better: model assemblies without overlaps and
   compute junctions only where parts touch.
4. **Free curves passed through HLD (tone lines) get visibility transitions that are wrong by
   ~10" at 500" (2–3 %).** The error also differed between `IncludeHiddenCurves` on and off.
   Brep edges looked right. Don't use HLD for decoration curves (see Q4).
5. **A `PointCloud` passed to HLD is never occluded** (all points come back Visible). Individual
   `Point` objects are occluded. `HiddenLineDrawingPoint.PointVisibility` is a different enum type
   from `Segment.Visibility`, so compare with `str()`. `Location` is in **world** coordinates,
   while segments are in HL coordinates.
6. `WorldToHiddenLine` is only available on a computed HLD. Compute a trivial one (a single point)
   first to get the 2D frame and the mm-per-world scale before generating tone lines.

**Cut fills:** don't stitch HLD SectionCut segments into loops. For each item whose transformed
bbox straddles the plane, use `Intersection.BrepPlane(brep, plane, tol)` → `Curve.JoinCurves` →
closed loops → project with `WorldToHiddenLine`. Cut faces lie on the plane, so nothing can occlude
them: draw them last, white fill, hatch, outline. That was 127 loops in 0.7 s.

**Outline hierarchy:** use `Curve.CreateBooleanUnion(all page-space loops)` for the heavy
assembly outline (0.7 mm, 110 loops in 0.2 s) and draw each material loop at 0.25 mm. Skip loops
smaller than `lod_min_mm` (bricks at small scale) so they only contribute to the union. Without
this the walls read as black bars.

## Q4: Tone hatching

The prototype is viable and fast: `hld_drawing.tone_hatch_lines`.

**Generating lines**
- For each planar Brep face whose normal is turned away from the sun (`n·sun ≤` threshold),
  generate parallel lines by **even-odd scanline fill of the face loops** in face-plane
  coordinates. This is pure Python.
  - It took 0.3 s for 1,357 segments, versus 18 s with `Brep.CreateContourCurves`.
  - Vertical faces get vertical lines. Horizontal faces get lines along the depth axis, so they
    converge to the vanishing point like the slab undersides in the reference.
- Spacing is specified in **paper mm** per tone level (e.g. 0.55 / 0.95 / 1.7 mm). It is converted
  to world spacing at the face centroid using the projected scale.
- Where perspective compresses lines below `tone_min_mm`, every 2^m-th line is kept (m from the
  local paper spacing), so far surfaces don't turn black.
- **Back-facing faces are culled.** Without this, the hidden stud-side face of the gypsum got
  hatched.

**Visibility uses a z-buffer, not HLD**
- `Rhino.Display.ZBufferCapture(viewport)`. Turn curves, points and isocurves off on it. It
  respects clipping planes.
- `WorldPointAt(x, y)` per sample, through `viewport.GetTransform(World, Screen)`.
- A sample is visible if the z-buffer point lies on **the line's own face plane** (tolerance
  0.15" + 0.15 % of distance).
- Lines are clipped to the section plane analytically first. Otherwise geometry in the clipped
  half-space reads as "in front, therefore visible".
- Lines are sampled every 4 px with 4-step bisection at transitions for crisp ends.
- **Z-buffer gotcha:** depth precision is poor (0.5–1 % of distance). The near plane is auto-fit
  to the whole scene; near/far set through `SetViewProjection` is ignored by the capture. Samples
  in the ambiguous band are therefore resolved with an exact
  `Intersection.MeshRay(sceneMesh, ray)`, with the ray started where it enters the kept
  half-space.
- Cost on this scene: about 44k z-buffer samples + 51k exact rays, roughly 4 s for tone and 5 s
  for junctions. Building the scene mesh takes 1.6 s.

**Not done:** curved faces (use contour curves or the face's UV isocurves), shadow casting (tone is
only from face orientation), and per-material tone overrides.

## Q5: Stipple

**Ground beyond the cut**
- Sample a jittered grid in **screen space** (`viewport.GetFrustumLine(sx, sy)`, intersected with
  the ground plane). This gives uniform paper density, so dots don't pile up at the horizon.
- Keep probability falls with distance (near 0.55 → far 0.12).
- Occlusion uses the same z-buffer plane test.
- 10k candidates → 6.2k visible dots in about 4 s. Most of that time is the Python `GetFrustumLine`
  loop.

**Ground in section:** 2D random dots inside the ground cut loop (point-in-polygon in page space).

**Bug fixed (not re-run):** the ground cut loop can project far beyond the page. The old code
sampled its whole bbox, which hung Rhino for more than 5 minutes on a close camera. The fix clips
the sampling box to the page. A production version should use blue-noise / Poisson-disk sampling.

## Q6: Line weights

There are two working routes. The writer's `STYLE` holds class widths (mm), depth falloff
(`width_far`, `grey_far`) and per-material cut styles.

1. **Own SVG writer (recommended for the finished drawing).**
   - Stroke width = class width × depth factor. Grey grows with depth.
   - Painter's order: projected lines → stipple → white cut fills → paper-space cut hatch → inner
     loops → union outline.
   - Clip to the frame with `<clipPath>`.
   - Paper-space cut hatches use Rhino's own patterns: `Hatch.Create(polyline, patternIndex, rot,
     scale, tol)` → `hatch.Explode()` → line segments.
2. **Bake into the doc and print** (`bake_and_print.py`).
   - Use one sublayer per line class (`MC Drawing::cut/outline/edge/tone/...`) with
     `Layer.PlotWeight`, plus per-object overrides:
     `PlotWeightSource = PlotWeightFromObject; PlotWeight = mm` and
     `PlotColorSource = PlotColorFromObject`.
   - White fills are `Hatch` objects with the Solid pattern in white.
   - Printing with `UsePrintWidths=True` gives exact widths in the vector output: 1,424 distinct
     stroke widths, 0.7 mm = 1.984 pt.
   - **Gotcha:** very thin plot weights (≤ ~0.08 mm) all came out as 0.24 pt (≈ 0.085 mm), which
     looks like a minimum. Fills need draw order (`ObjectAttributes.DisplayOrder`) or projected
     lines show through cut fills. This is not fixed in the spike: see `11_baked_print_preview.png`.
   - This route keeps the drawing editable in Rhino and lets Rhino layouts / PDF handle printing.

---

## Recommended architecture: `mindcanvas/drawing/`

```
drawing/
  styles.py        load library/styles/*.json → DrawingStyle (dataclass); per-scale presets
  sectionstyle.py  live path: ensure hatch patterns, apply SectionStyle per material layer
                   (Layers.Modify!), white-no-hatch via Solid+white, block-def attrs FromParent
  displaymode.py   ensure "MC Section" display mode (CopyDisplayMode(PenId) + attrs; optional
                   ini patch for silhouette thickness); export_view_pdf/svg (ViewCaptureSettings)
  scene.py         collect(doc, filter) -> [Item(geom, xform, tag)] exploding nested blocks;
                   tag = {id, layer, material, role, block}; effective layer per FromParent rule
  hld.py           compute(viewport, items, clip_planes) (flips plane, Flatten=False), probe W2H,
                   classify segments -> Line2D(pts, cls, depth, layer); drop frustum cuts
  cut.py           cut loops (BrepPlane per straddling item), paper LOD, union outline,
                   paper-space hatch (Hatch.Create+Explode), section stipple
  visibility.py    ZVis: ZBufferCapture + plane test + exact MeshRay fallback; clip_segment with
                   bisection; scene mesh cache
  tone.py          scanline tone hatch on planar faces (sun, paper spacing, thinning, backface cull)
  stipple.py       screen-space ground stipple (later: Poisson disk), depth-weighted density
  junction.py      BrepBrep junction lines between touching parts of different materials
  model2d.py       Drawing dataclass: lines, fills, dots, frame; page mapping (frame → page mm)
  writers/svg.py   painter's-order SVG with widths/grey from style
  writers/bake.py  bake to doc layers (MC Drawing::class) with PlotWeight/PlotColor/DisplayOrder,
                   white Solid hatches; then Rhino layout/PDF
  commands: MCSectionView (live), MCDrawing (2D pipeline), MCToneHatch/MCStipple are just
            toggles in the style, not separate geometry in the model.
```

**Data flow (MCDrawing)**

1. View + clip plane + style. Collect items.
2. Probe the HLD for `W2H` and the page scale.
3. Run the HLD for model edges, then classify the segments.
4. Build `ZVis` (z-buffer + scene mesh). Generate tone and junction lines and stipple, and clip
   them with `ZVis`.
5. Build cut loops: fills, hatches, union outline.
6. Normalise depth, then hand everything to the writer (SVG and/or bake).

Keep everything as 3D world data until projection. Store `depth` on every primitive.

**Performance for real walls** (~3k block parts per 20'×10' brick wall):
- HLD scales fine (3.6k items in 2 s).
- Cut loops only touch parts that straddle the plane.
- Tone skips block parts (bricks are below `tone_min_face_area`). If bricks need tone, generate
  it once per block definition and transform it.
- The scene mesh for exact rays should be built from definition meshes × transforms and cached
  per definition.
- Plan for a progress bar (`Compute` overload with `IProgress` / `CancellationToken`) and an LOD
  filter: skip head joints, ties and fasteners beyond a depth/size threshold on paper.

**`library/styles/<scale>.json`** (one per scale preset, e.g. `eighth.json`, `half.json`,
`detail.json`):

```json
{
  "name": "1/4\" design", "page_mm": [420, 297], "margin_mm": 12,
  "classes": {"cut": 0.70, "cut_inner": 0.25, "outline": 0.35, "edge": 0.18,
              "boundary": 0.18, "tone": 0.08, "cut_hatch": 0.08},
  "depth": {"width_far": 0.45, "grey_far": 0.55, "gamma": 0.8},
  "lod_min_mm": 1.2,
  "sun": [-0.55, -0.35, 0.76],
  "tone": {"levels": [[-0.35, 0.55], [0.05, 0.95], [0.25, 1.7]], "min_mm": 0.4,
           "min_face_area": 36, "skip_materials": ["Ground"]},
  "stipple": {"ground_step": 0.0032, "near_p": 0.55, "far_p": 0.12, "dot_mm": 0.16},
  "live": {"boundary_width_scale": 2.0, "clipping_edge_px": 1},
  "materials": {
    "Brick":      {"cut_hatch": {"pattern": "Hatch1", "scale": 6, "rot": 45}},
    "Insulation": {"cut_hatch": {"pattern": "Hatch1", "scale": 4, "rot": 0}},
    "Ground":     {"cut_stipple": 0.9},
    "Concrete":   {"cut_hatch": null}
  }
}
```

The material JSON (`library/materials/*.json`) should keep only identity and model-space data
(colour, render material, and the default section hatch for the live view). Scale-dependent
drawing data belongs in the style JSON, which overrides by material name.

## Known issues / next steps

- The section-stipple page-clip fix is not re-run; my Rhino slot died during the close-camera
  render.
- Bake: set `DisplayOrder` so fills cover lines; bake dots and cut hatches too.
- Tone on curved faces; cast shadows (could ray-cast from the sun with the same scene mesh);
  blue-noise stipple; entourage.
- Remove the `GetFrustumLine` Python loop from stipple: compute rays from the camera frame
  directly.
- Frame clipping in the SVG works through `<clipPath>`, but `svg_preview.py` ignores it, so the
  previews can show content outside the frame.
