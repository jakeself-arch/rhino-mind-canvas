"""Drawing tags: user text `mc.draw` on an object (or its layer), a comma list of
    ground    stippled as ground (beyond the cut and in section)
    notone    never tone-hatched
    exclude   left out of drawings
    nocut     drawn, but not cut (no poche)
"""

import System

KEY = "mc.draw"
FLAGS = ("ground", "notone", "exclude", "nocut")


def parse(text):
    return set(f.strip().lower() for f in (text or "").split(",") if f.strip().lower() in FLAGS)


def flags(doc, obj):
    out = parse(obj.Attributes.GetUserString(KEY))
    layer = doc.Layers[obj.Attributes.LayerIndex]
    while layer is not None:
        out |= parse(layer.GetUserString(KEY))
        if layer.ParentLayerId == System.Guid.Empty:
            break
        layer = doc.Layers.FindId(layer.ParentLayerId)
    return out


def set_flags(doc, obj, add=(), remove=(), clear=False):
    cur = set() if clear else parse(obj.Attributes.GetUserString(KEY))
    cur = (cur | set(add)) - set(remove)
    attrs = obj.Attributes.Duplicate()
    attrs.SetUserString(KEY, ",".join(sorted(cur)) if cur else None)
    doc.Objects.ModifyAttributes(obj, attrs, True)
    return cur
