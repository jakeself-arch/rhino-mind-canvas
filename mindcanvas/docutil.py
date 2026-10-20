"""Rhino document helpers: layers, render materials, section styles, blocks, groups."""

import json

import System
import Rhino

ROOT_LAYER = "MindCanvas"
DRIVER_LAYER = ROOT_LAYER + "::_Drivers"
MASS_LAYER = ROOT_LAYER + "::_Masses"     # opening masses (masses.py): never drawn
PREVIEW_LAYER = ROOT_LAYER + "::_Preview" # the assembly editor's sample (preview.py): never drawn
SIG_KEY = "mc.matsig"
SIG_VERSION = "|ss2"  # bump to re-apply section styles to existing layers

_DocObjects = Rhino.DocObjects


def _color(rgb, default=(0, 0, 0)):
    rgb = rgb or default
    return System.Drawing.Color.FromArgb(int(rgb[0]), int(rgb[1]), int(rgb[2]))


# -- layers ---------------------------------------------------------------
def ensure_layer(doc, full_path, color=None):
    """Create (or find) a layer by full path "A::B::C". Returns the index."""
    idx = doc.Layers.FindByFullPath(full_path, -1)
    if idx >= 0:
        return idx
    parent_id = System.Guid.Empty
    path = []
    for name in full_path.split("::"):
        path.append(name)
        sub = "::".join(path)
        idx = doc.Layers.FindByFullPath(sub, -1)
        if idx < 0:
            layer = _DocObjects.Layer()
            layer.Name = name
            layer.ParentLayerId = parent_id
            if color is not None and sub == full_path:
                layer.Color = _color(color)
            idx = doc.Layers.Add(layer)
        parent_id = doc.Layers[idx].Id
    return idx


def material_layer_path(material_name):
    return "{}::{}".format(ROOT_LAYER, material_name.replace("::", "-"))


def ensure_driver_layer(doc):
    idx = ensure_layer(doc, DRIVER_LAYER, (255, 120, 0))
    layer = doc.Layers[idx]
    if layer.PlotWeight != -1:
        layer.PlotWeight = -1  # drivers never print
        doc.Layers.Modify(layer, idx, True)
    return idx


def find_hatch_pattern(doc, name):
    """Pattern index; Rhino defaults and the MC patterns (drawing/patterns.py)
    are added on demand (a template-less doc has no patterns at all)."""
    from .drawing import patterns
    return patterns.index(doc, name)


def _section_style(doc, spec, color):
    ss = _DocObjects.SectionStyle()
    fill = (spec or {}).get("fill", "white")
    white = System.Drawing.Color.White
    black = System.Drawing.Color.Black
    ss.BoundaryVisible = spec.get("boundary", True) if spec else True
    ss.BoundaryWidthScale = float((spec or {}).get("boundary_weight", 1.0))
    ss.BoundaryColor = black
    ss.BoundaryPrintColor = black
    ss.SectionFillRule = _DocObjects.ObjectSectionFillRule.SolidObjects
    bg = white
    if fill == "none":
        # "None" is a Python keyword: pythonnet does not expose the member as an attribute
        ss.BackgroundFillMode = System.Enum.Parse(_DocObjects.SectionBackgroundFillMode, "None")
    else:
        ss.BackgroundFillMode = _DocObjects.SectionBackgroundFillMode.SolidColor
        bg = white if fill in ("white", "hatch") else _color(spec.get("color"), (0, 0, 0))
        ss.BackgroundFillColor = bg
        ss.BackgroundFillPrintColor = bg
    hidx = find_hatch_pattern(doc, spec.get("hatch")) if fill == "hatch" else -1
    if hidx >= 0:
        ss.HatchIndex = hidx
        ss.HatchScale = float(spec.get("scale", 1.0))
        ss.HatchRotationRadians = Rhino.RhinoMath.ToRadians(float(spec.get("rotation", 0.0)))
        ss.HatchPatternColor = _color(spec.get("hatch_color"), (0, 0, 0))
        ss.HatchPatternPrintColor = ss.HatchPatternColor
    else:
        # HatchIndex -1 is NOT "no hatch": the display falls back to a solid
        # hatch in HatchPatternColor (black). Use Solid in the fill colour.
        ss.HatchIndex = find_hatch_pattern(doc, "Solid")
        ss.HatchPatternColor = bg
        ss.HatchPatternPrintColor = bg
    return ss


def apply_material_to_layer(doc, idx, material_name, mat):
    """Push a library material onto its layer: color, render material,
    print weight and section style. Skips work if nothing changed."""
    layer = doc.Layers[idx]
    sig = json.dumps(mat, sort_keys=True) + SIG_VERSION
    if layer.GetUserString(SIG_KEY) == sig:
        return
    layer.Color = _color(mat.get("color"), (160, 160, 160))
    layer.PlotColor = _color(mat.get("print", {}).get("color"), (0, 0, 0))
    weight = mat.get("print", {}).get("weight")
    if weight is not None:
        layer.PlotWeight = float(weight)

    render = mat.get("render", {})
    rm = _DocObjects.Material()
    rm.Name = "MC " + material_name
    rm.DiffuseColor = _color(render.get("color") or mat.get("color"), (160, 160, 160))
    rm.Transparency = float(render.get("transparency", 0.0))
    rm.Shine = float(render.get("gloss", 0.1)) * _DocObjects.Material.MaxShine
    if layer.RenderMaterialIndex >= 0 and layer.RenderMaterialIndex < doc.Materials.Count:
        doc.Materials.Modify(rm, layer.RenderMaterialIndex, True)
    else:
        layer.RenderMaterialIndex = doc.Materials.Add(rm)

    layer.SetCustomSectionStyle(_section_style(doc, mat.get("section"), layer.Color))
    layer.SetUserString(SIG_KEY, sig)
    doc.Layers.Modify(layer, idx, True)


def ensure_material_layer(doc, lib, material_name):
    idx = ensure_layer(doc, material_layer_path(material_name))
    apply_material_to_layer(doc, idx, material_name, lib.material(material_name))
    return idx


# -- blocks ---------------------------------------------------------------
def ensure_block(doc, name, geometries, layer_index, description="Rhino Mind Canvas"):
    """Find or create a block definition. `name` must encode the geometry
    (e.g. "MC Brick 7.625x2.25x3.625") so identical members share a block.
    Definition geometry takes section style, colour and print attributes
    from the instance (FromParent), so the instance's layer decides."""
    idef = doc.InstanceDefinitions.Find(name)
    if idef is not None and not idef.IsDeleted:
        return idef.Index
    attrs = []
    for _ in geometries:
        a = _DocObjects.ObjectAttributes()
        a.LayerIndex = layer_index
        a.ColorSource = _DocObjects.ObjectColorSource.ColorFromParent
        a.MaterialSource = _DocObjects.ObjectMaterialSource.MaterialFromLayer
        a.PlotWeightSource = _DocObjects.ObjectPlotWeightSource.PlotWeightFromParent
        a.PlotColorSource = _DocObjects.ObjectPlotColorSource.PlotColorFromParent
        a.SectionAttributesSource = _DocObjects.ObjectSectionAttributesSource.FromParent
        attrs.append(a)
    return doc.InstanceDefinitions.Add(
        name, description, Rhino.Geometry.Point3d.Origin, geometries, attrs)


def purge_unused_blocks(doc, prefix="MC "):
    removed = 0
    for idef in list(doc.InstanceDefinitions):
        if idef is None or idef.IsDeleted or not idef.Name.startswith(prefix):
            continue
        if not idef.InUse(0):
            if doc.InstanceDefinitions.Delete(idef.Index, True, True):
                removed += 1
    return removed


# -- groups ---------------------------------------------------------------
def ensure_group(doc, name):
    g = doc.Groups.FindName(name)
    if g is not None and not g.IsDeleted:
        return g.Index
    return doc.Groups.Add(name)
