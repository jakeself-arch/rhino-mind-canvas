"""Phase 3 drawing system.

Live path (working views, quick prints):
    patterns      hatch patterns built in code
    sectionstyle  per-material section styles for a drawing scale
    displaymode   the "MC Section" display mode

2D path (finished drawings, MCDrawing):
    styles  scene  hld  cut  visibility  tone  stipple  junction  model2d
    pipeline.make(doc, view, style) -> model2d.Drawing
    writers.svg / writers.png / writers.bake

    from mindcanvas.drawing import pipeline
    dwg = pipeline.make(doc, doc.Views.ActiveView, "1/8")
    pipeline.write(dwg, r"C:\\out\\section", svg=True, png=True)
"""
