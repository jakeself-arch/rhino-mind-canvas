"""Runner: build the HLD section-perspective drawing of the current scene and write
docs/spike-output/<NAME>.svg + a PNG preview. Set globals before exec to override:
  NAME (str), TONE (bool), STIPPLE (bool), SKIP_BRICKS (bool)
"""
import os
import json
import Rhino

R = r"C:\Users\jakob\Desktop\BAC\Rhino Mind Canvas\spikes\\"
O = r"C:\Users\jakob\Desktop\BAC\Rhino Mind Canvas\docs\spike-output\\"
for _f in ("_util.py", "hld_core.py", "hld_drawing.py", "svg_preview.py"):
    exec(open(R + _f).read(), globals())

doc = __rhino_doc__
NAME = globals().get("NAME", "10_hld_drawing")
view = doc.Views.ActiveView
cp = [o for o in doc.Objects if isinstance(o, Rhino.DocObjects.ClippingPlaneObject)][0]
plane = Rhino.Geometry.Plane(cp.ClippingPlaneGeometry.Plane)
CUT_Y = plane.Origin.Y

dwg = build_drawing(doc, view, plane, STYLE,
                    tone=globals().get("TONE", True), stipple=globals().get("STIPPLE", True),
                    ground_keep=lambda p: p.Y > CUT_Y + 0.5 and -600 < p.X < 960 and p.Y < 1140
                    and not (0 <= p.X <= 360 and 0 <= p.Y <= 240))
info = write_svg(dwg, O + NAME + ".svg", STYLE)
svg_to_png(O + NAME + ".svg", O + NAME + ".png", scale=4.0)
res = dict(dwg["timing"])
res.update(info)
print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in res.items()}, indent=0))
