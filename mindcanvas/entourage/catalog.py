"""The entourage catalog in plain Python (no Rhino): library entries, categories, model files, and
adding your own OBJ files (MCEntourage Import / the library window's Add OBJ...).

A library entry (library/entourage/<category>.json, name -> entry):

    file        models/<category>/<name>.obj (+ .mtl), relative to library/entourage
    thumb       thumbs/<category>/<name>.png
    category    People | Trees | Plants | Vehicles | Furniture | Kitchen & Bath | Lighting | Site | My Models
    group       sub-group shown in the library window (Standing, Conifer, Seating, ...)
    size        [width, depth, height] in inches
    face_view   true: turned to face the view when placed (people)
    heading     true: the model runs along X and drives toward +X (vehicles); Aim points its nose
    mount       "ceiling": the origin is the top (pendants, ceiling fans)
    source, author, license, url, triangles

Model files are normalised: inches, Z up, origin on the ground at the footprint centre, the front
facing -Y (vehicles run along X, heading +X). tools/entourage/build.py makes the shipped ones;
add_model() does the same for your own.
"""

import math
import os
import re

from . import objfile, thumbs

SECTION = "entourage"
ORDER = ("People", "Trees", "Plants", "Vehicles", "Furniture", "Kitchen & Bath", "Lighting", "Site")
USER_CATEGORY = "My Models"
USER_FILE = "zz_user_entourage.json"
UNITS = {"inches": 1.0, "feet": 12.0, "millimeters": 1 / 25.4, "centimeters": 1 / 2.54, "meters": 1 / 0.0254}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# -- catalog queries -------------------------------------------------------------------------
def entries(lib):
    """{name: entry} of the entourage models whose file exists."""
    return dict((n, d) for n, d in lib.data[SECTION].items() if isinstance(d, dict) and "file" in d)


def folder(lib):
    return os.path.join(lib.directory, SECTION)


def model_path(lib, name):
    d = entry(lib, name)
    return os.path.join(folder(lib), d["file"].replace("/", os.sep))


def thumb_path(lib, name):
    d = entry(lib, name)
    return os.path.join(folder(lib), d["thumb"].replace("/", os.sep)) if d.get("thumb") else None


def entry(lib, name):
    d = lib.data[SECTION].get(name)
    if not isinstance(d, dict) or "file" not in d:
        raise KeyError("Entourage model '{}' is not in library/entourage".format(name))
    return d


def categories(lib):
    """Categories in display order: the shipped ones first, then any others."""
    have = set(d.get("category", USER_CATEGORY) for d in entries(lib).values())
    return [c for c in ORDER if c in have] + sorted(have - set(ORDER))


def groups(lib, category):
    out = []
    for n in names(lib, category):
        g = entries(lib)[n].get("group", "")
        if g not in out:
            out.append(g)
    return out


def names(lib, category=None, group=None):
    """Names in catalog order (as listed in the JSON files), filtered by category / group."""
    out = []
    for n, d in entries(lib).items():
        if category is not None and d.get("category", USER_CATEGORY) != category:
            continue
        if group is not None and d.get("group", "") != group:
            continue
        out.append(n)
    return out


def search(lib, text, category=None):
    words = [w for w in text.lower().split() if w]
    out = []
    for n in names(lib, category):
        d = entries(lib)[n]
        hay = " ".join([n, d.get("category", ""), d.get("group", "")] + list(d.get("tags", []))).lower()
        if all(w in hay for w in words):
            out.append(n)
    return out


def height(lib, name):
    """Library height of a model (inches)."""
    d = entry(lib, name)
    if d.get("size"):
        return float(d["size"][2])
    bb = objfile.read(model_path(lib, name)).bbox()
    return bb[1][2] - bb[0][2]


# -- normalising -----------------------------------------------------------------------------
def to_z_up(m, up):
    if up == "y":
        m.transform(lambda v: (v[0], -v[2], v[1]))
    return m


def rotate_z(m, deg):
    if not deg:
        return m
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return m.transform(lambda v: (v[0] * c - v[1] * s, v[0] * s + v[1] * c, v[2]))


def scale(m, k):
    return m.transform(lambda v: (v[0] * k, v[1] * k, v[2] * k))


def center(m, mount="floor"):
    """Footprint centre on the origin; the base (or, mount 'ceiling', the top) at z = 0."""
    (x0, y0, z0), (x1, y1, z1) = m.bbox()
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    z = z1 if mount == "ceiling" else z0
    return m.transform(lambda v: (v[0] - cx, v[1] - cy, v[2] - z))


def tidy_materials(m, prefix=""):
    """Plain material names (letters, digits, _), unique per model."""
    seen = {}
    for g in m.groups:
        name = re.sub(r"[^A-Za-z0-9_]+", "_", g.material).strip("_") or "Material"
        name = prefix + name
        old = g.material
        if name in seen and seen[name] != old:
            k = 2
            while name + str(k) in seen:
                k += 1
            name += str(k)
        seen[name] = old
        m.colors[name] = m.colors.get(old)
        g.material = name
    return m


# -- your own models -------------------------------------------------------------------------
def add_model(lib, src, name, units="inches", up="z", height=None, turn=0.0, group="", mount="floor",
              face_view=False, category=USER_CATEGORY):
    """Normalise an OBJ file and add it to the library as `name` (library/entourage/
    zz_user_entourage.json, models/my-models/, thumbs/my-models/). units: the file's units
    (UNITS); up: 'z' or 'y'; height: real height in inches (scales the model; None keeps the
    units); turn: degrees about Z so the front faces -Y. Returns the entry."""
    if name in lib.data[SECTION] and not lib.is_user_entry(SECTION, name):
        raise ValueError("'{}' is a library model; choose another name.".format(name))
    m = objfile.read(src)
    if not m.face_count():
        raise ValueError("No faces in {}".format(src))
    m = to_z_up(m, up)
    m = scale(m, UNITS.get(units, 1.0))
    m = rotate_z(m, turn)
    if height:
        bb = m.bbox()
        h = bb[1][2] - bb[0][2]
        if h > 0:
            m = scale(m, float(height) / h)
    m = center(m, mount)
    m = tidy_materials(m)
    m.compact()
    cs = slug(category) or "my-models"
    rel = "models/{}/{}.obj".format(cs, slug(name))
    path = os.path.join(folder(lib), rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    objfile.write(path, m, [("Rhino Mind Canvas entourage", name), ("Category", category),
                            ("Source file", os.path.basename(src)),
                            ("Units", "inches, Z up, origin on the ground at the footprint centre, front -Y")])
    tpath = os.path.join(folder(lib), "thumbs", cs, slug(name) + ".png")
    os.makedirs(os.path.dirname(tpath), exist_ok=True)
    thumbs.write_png(tpath, thumbs.render(m, 160))
    (x0, y0, z0), (x1, y1, z1) = m.bbox()
    d = {"file": rel, "thumb": "thumbs/{}/{}.png".format(cs, slug(name)), "category": category, "group": group,
         "size": [round(x1 - x0, 1), round(y1 - y0, 1), round(z1 - z0, 1)], "triangles": m.triangle_count(),
         "source": os.path.basename(src), "license": "your own"}
    if mount != "floor":
        d["mount"] = mount
    if face_view:
        d["face_view"] = True
    lib.save_entry(SECTION, name, d, USER_FILE)
    lib.load()
    return d


def remove_model(lib, name):
    """Remove one of your own models (entry, OBJ, MTL, thumbnail). Library models stay."""
    if not lib.is_user_entry(SECTION, name):
        raise ValueError("'{}' is a library model; only your own models can be removed.".format(name))
    d = entry(lib, name)
    for rel in (d.get("file"), d.get("thumb")):
        if not rel:
            continue
        p = os.path.join(folder(lib), rel.replace("/", os.sep))
        for q in (p, os.path.splitext(p)[0] + ".mtl") if p.endswith(".obj") else (p,):
            if os.path.isfile(q):
                os.remove(q)
    lib.remove_entry(SECTION, name, USER_FILE)
    lib.load()
