"""Build the entourage model library (library/entourage) from free CC0 sources.

    python -I tools/entourage/build.py [--cache DIR] [--only REGEX] [--sheet PNG]

recipe.json lists the sources (download URL, author, license, axis convention) and, per
category, the models to take: source file, real-world size, turn, extra parts. For each model:

    1. download the source pack once (cache, default %TEMP%/mindcanvas_entourage_cache)
    2. read the OBJ / glTF, turn it Z up, add parts (hair on a head), turn it to face -Y
    3. scale it to its real size (inches), centre it on the origin, base on the ground (z = 0)
    4. write library/entourage/models/<category>/<name>.obj (+ .mtl) and a PNG thumbnail
       library/entourage/thumbs/<category>/<name>.png
    5. write the catalog library/entourage/<category>.json and library/entourage/CREDITS.md

Only CC0 (public domain) sources are used, so the models can live in this repository and be
used in any drawing without credit (CREDITS.md credits them anyway).
"""

import argparse
import fnmatch
import json
import math
import os
import re
import sys
import tempfile
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from mindcanvas.entourage import objfile, thumbs  # noqa: E402
from mindcanvas.entourage.catalog import center, rotate_z, scale, slug, tidy_materials, to_z_up  # noqa: E402
import gltf  # noqa: E402

OUT = os.path.join(ROOT, "library", "entourage")
UA = {"User-Agent": "Mozilla/5.0 (Rhino Mind Canvas entourage build)"}
POLYHAVEN_FILES = "https://api.polyhaven.com/files/{}"
POLYHAVEN_INFO = "https://api.polyhaven.com/info/{}"


def say(*a):
    print(*a)
    sys.stdout.flush()


def inches(spec):
    """5'-9"  30"  15'  4.5'  12 -> inches."""
    if isinstance(spec, (int, float)):
        return float(spec)
    s = spec.replace(" ", "")
    m = re.match(r"^(?:(-?[\d.]+)')?-?(?:([\d.]+)\")?$", s)
    if not m or not (m.group(1) or m.group(2)):
        raise ValueError("Bad length '{}'".format(spec))
    return float(m.group(1) or 0) * 12.0 + float(m.group(2) or 0)


def feet_inches(x):
    ft = int(x // 12)
    inch = int(round(x - ft * 12))
    if inch == 12:
        ft, inch = ft + 1, 0
    return "{}'-{}\"".format(ft, inch) if ft else "{}\"".format(inch)


# -- sources ---------------------------------------------------------------------------------
def fetch(url, path):
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    say("  download", url)
    data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600).read()
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return path


class Sources(object):
    def __init__(self, recipe, cache):
        self.recipe = recipe
        self.cache = cache
        self._index = {}

    def info(self, sid):
        return self.recipe["sources"][sid]

    def folder(self, sid):
        """Extracted pack folder (zip sources)."""
        src = self.info(sid)
        d = os.path.join(self.cache, sid)
        if not os.path.isdir(d):
            z = fetch(src["zip"], os.path.join(self.cache, sid + ".zip"))
            with zipfile.ZipFile(z) as zf:
                zf.extractall(d + ".part")
            os.replace(d + ".part", d)
        return d

    def find(self, sid, pattern):
        d = self.folder(sid)
        files = self._index.get(sid)
        if files is None:
            files = self._index[sid] = sorted(
                os.path.relpath(os.path.join(r, f), d).replace("\\", "/") for r, _, fs in os.walk(d) for f in fs)
        hits = [f for f in files if fnmatch.fnmatch(f, pattern) or fnmatch.fnmatch(f, "*/" + pattern)]
        if not hits:
            raise IOError("{}: no file matches '{}'".format(sid, pattern))
        return os.path.join(d, hits[0])

    def polyhaven_height(self, asset):
        """Height (inches) Poly Haven publishes for a model (its 'dimensions', mm, z last)."""
        p = fetch(POLYHAVEN_INFO.format(asset), os.path.join(self.cache, "polyhaven", asset, "info.json"))
        dims = json.load(open(p, "r", encoding="utf-8")).get("dimensions")
        return dims[2] / 25.4 if dims and len(dims) == 3 else None

    def polyhaven(self, asset, res="1k"):
        """Download a Poly Haven model's glTF + bin (no textures); returns the .gltf path."""
        d = os.path.join(self.cache, "polyhaven", asset)
        meta_path = os.path.join(d, "files.json")
        fetch(POLYHAVEN_FILES.format(asset), meta_path)
        files = json.load(open(meta_path, "r", encoding="utf-8"))
        g = (files["gltf"].get(res) or list(files["gltf"].values())[0])["gltf"]
        # every resolution shares one .bin, stored with the resolution it was made for: take
        # that resolution's .gltf so the buffer layout matches
        for inc in g.get("include", {}).values():
            m = re.search(r"/gltf/([^/]+)/", inc["url"])
            if inc["url"].lower().endswith(".bin") and m and m.group(1) in files["gltf"]:
                g = files["gltf"][m.group(1)]["gltf"]
        path = fetch(g["url"], os.path.join(d, os.path.basename(g["url"])))
        for rel, inc in g.get("include", {}).items():
            if rel.lower().endswith(".bin"):
                b = fetch(inc["url"], os.path.join(d, rel))
                want = [x.get("byteLength") for x in json.load(open(path, "r", encoding="utf-8")).get("buffers", [])]
                if os.path.getsize(b) not in want:
                    raise IOError("Poly Haven '{}': the .bin does not match its .gltf (stale download)".format(asset))
        return path

    def load(self, sid, item_file):
        src = self.info(sid)
        if src.get("kind") == "polyhaven":
            m = gltf.read(self.polyhaven(item_file))
        else:
            p = self.find(sid, item_file)
            m = gltf.read(p) if p.lower().endswith((".gltf", ".glb")) else objfile.read(p)
        return to_z_up(m, src.get("up", "y"))


def head_points(m, material="skin"):
    """Points of the head: the largest connected piece of the skin material (hands and arms are
    the smaller ones), in a stable order (first use in the face list)."""
    parent = {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    order = []
    for g in m.groups:
        if g.material.lower() != material:
            continue
        for f in g.faces:
            ks = [m.vertices[i] for i in f]
            for k in ks:
                if k not in parent:
                    parent[k] = k
                    order.append(k)
            for k in ks[1:]:
                a, b = find(ks[0]), find(k)
                if a != b:
                    parent[a] = b
    comps = {}
    for k in order:
        comps.setdefault(find(k), []).append(k)
    return max(comps.values(), key=len) if comps else []


def rigid_fit(P, Q):
    """Rotation R (3x3) and translation t with R p + t ~ q (Horn's quaternion method).
    Returns (R, t, rms)."""
    n = float(len(P))
    cp = [sum(p[i] for p in P) / n for i in range(3)]
    cq = [sum(q[i] for q in Q) / n for i in range(3)]
    S = [[sum((p[i] - cp[i]) * (q[j] - cq[j]) for p, q in zip(P, Q)) for j in range(3)] for i in range(3)]
    (sxx, sxy, sxz), (syx, syy, syz), (szx, szy, szz) = S
    N = [[sxx + syy + szz, syz - szy, szx - sxz, sxy - syx],
         [syz - szy, sxx - syy - szz, sxy + syx, szx + sxz],
         [szx - sxz, sxy + syx, -sxx + syy - szz, syz + szy],
         [sxy - syx, szx + sxz, syz + szy, -sxx - syy + szz]]
    shift = sum(abs(x) for r in N for x in r) + 1.0
    q = [1.0, 0.0, 0.0, 0.0]
    for _ in range(500):
        v = [sum((N[i][j] + (shift if i == j else 0.0)) * q[j] for j in range(4)) for i in range(4)]
        ln = math.sqrt(sum(x * x for x in v)) or 1.0
        q = [x / ln for x in v]
    w, x, y, z = q
    Rm = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
          [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
          [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    t = [cq[i] - sum(Rm[i][j] * cp[j] for j in range(3)) for i in range(3)]
    err = 0.0
    for p, qq in zip(P, Q):
        r = [sum(Rm[i][j] * p[j] for j in range(3)) + t[i] for i in range(3)]
        err += sum((r[i] - qq[i]) ** 2 for i in range(3))
    return Rm, t, math.sqrt(err / n)


def seat_on_head(head, part, drop=0.0):
    """Move a hair / hat part (modelled around its own origin) onto an upright head: footprint
    centre over the head's, its top `drop` x its height above the head's top."""
    hx = (min(v[0] for v in head) + max(v[0] for v in head)) / 2.0
    hy = (min(v[1] for v in head) + max(v[1] for v in head)) / 2.0
    hz = max(v[2] for v in head)
    (px0, py0, pz0), (px1, py1, pz1) = part.bbox()
    dx, dy, dz = hx - (px0 + px1) / 2.0, hy - (py0 + py1) / 2.0, hz + drop * (pz1 - pz0) - pz1
    return part.transform(lambda v: (v[0] + dx, v[1] + dy, v[2] + dz))


def attach_head(body, part, drop=0.0, reference=None):
    """Put a hair part on the body's head. With `reference` (the same figure standing upright,
    same mesh): seat the part on the upright head, then carry it with the head's rigid motion
    to the posed head, so tilted and bowed heads keep their hair."""
    head = head_points(body)
    if reference is not None:
        ref = head_points(reference)
        if len(ref) == len(head) and head:
            seat_on_head(ref, part, drop)
            Rm, t, rms = rigid_fit(ref, head)
            size = max(max(v[i] for v in head) - min(v[i] for v in head) for i in range(3))
            if rms < 0.05 * size:
                part.transform(lambda v: tuple(sum(Rm[i][j] * v[j] for j in range(3)) + t[i] for i in range(3)))
                return body.merge(part)
            say("  (head fit rms {:.3f}: hair seated upright)".format(rms))
    seat_on_head(head or body.used_vertices(), part, drop)
    return body.merge(part)


def size_to(m, item):
    (x0, y0, z0), (x1, y1, z1) = m.bbox()
    dims = {"width": x1 - x0, "depth": y1 - y0, "height": z1 - z0, "length": max(x1 - x0, y1 - y0)}
    for key in ("height", "length", "width", "depth"):
        if key in item:
            if dims[key] <= 0:
                raise ValueError("zero {}".format(key))
            return scale(m, inches(item[key]) / dims[key])
    if "scale" in item:
        return scale(m, float(item["scale"]))
    return m


def gamma(m, g):
    """Linear MTL colours (Blender 2.7x exports) -> display colours."""
    if g:
        for k, c in m.colors.items():
            if c:
                m.colors[k] = tuple(int(round(255 * (x / 255.0) ** (1.0 / g))) for x in c)
    return m


def recolor(m, colors):
    for k, v in (colors or {}).items():
        for g in m.groups:
            if fnmatch.fnmatch(g.material.lower(), k.lower()):
                m.colors[g.material] = tuple(v)
    return m


# -- build -----------------------------------------------------------------------------------
def build_item(src, cat, item):
    sid = item.get("src") or cat.get("src")
    info = src.info(sid)
    m = gamma(src.load(sid, item["file"]), info.get("gamma"))
    if "rotate_source" in item or "rotate_source" in info:
        m = rotate_z(m, item.get("rotate_source", info.get("rotate_source", 0)))
    if info.get("scale"):
        m = scale(m, float(info["scale"]))
    if info.get("kind") == "polyhaven":
        # a few Poly Haven files are authored at the wrong scale: trust the published size
        want = src.polyhaven_height(item["file"])
        bb = m.bbox()
        have = bb[1][2] - bb[0][2]
        if want and have > 0 and not 0.8 < want / have < 1.25:
            say("  {}: file is {:.0f}\" high, Poly Haven says {:.0f}\"; rescaled".format(item["name"], have, want))
            m = scale(m, want / have)
    for part in item.get("add", []):
        p = gamma(src.load(part.get("src", sid), part["file"]), info.get("gamma"))
        if info.get("scale"):
            p = scale(p, float(info["scale"]))
        if part.get("attach") == "head":
            ref = None
            if part.get("reference"):
                ref = src.load(part.get("src", sid), part["reference"])
                if info.get("scale"):
                    ref = scale(ref, float(info["scale"]))
            attach_head(m, p, float(part.get("drop", 0.0)), ref)
        else:
            m.merge(p)
    m = rotate_z(m, item.get("rotate", cat.get("rotate", info.get("rotate", 0))))
    m = size_to(m, item)
    m = center(m, item.get("mount", cat.get("mount", "floor")))
    m = tidy_materials(m)
    m = recolor(m, dict(info.get("colors", {}), **item.get("colors", {})))
    m.compact()
    return m, sid


def run(args):
    global OUT
    OUT = args.out
    recipe = json.load(open(os.path.join(HERE, "recipe.json"), "r", encoding="utf-8"))
    src = Sources(recipe, args.cache)
    only = re.compile(args.only, re.I) if args.only else None
    images = []
    credits = {}
    failed = []
    kept = set()
    total = 0
    for cat in recipe["categories"]:
        cname = cat["name"]
        cslug = slug(cname)
        catalog = {"_comment": "Entourage models ({}), built by tools/entourage/build.py from recipe.json. "
                               "Units inches, Z up, origin on the ground at the footprint centre, "
                               "front facing -Y.".format(cname)}
        cat_path = os.path.join(OUT, cslug + ".json")
        if only and os.path.isfile(cat_path):
            old = json.load(open(cat_path, "r", encoding="utf-8"))
            catalog.update(dict((k, v) for k, v in old.items() if not k.startswith("_")))
        touched = False
        for item in cat["items"]:
            name = item["name"]
            if only and not only.search(name):
                continue
            touched = True
            try:
                m, sid = build_item(src, cat, item)
            except Exception as e:
                say("FAILED {}: {}".format(name, e))
                failed.append(name)
                continue
            info = src.info(sid)
            rel = "models/{}/{}.obj".format(cslug, slug(name))
            path = os.path.join(OUT, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            (x0, y0, z0), (x1, y1, z1) = m.bbox()
            header = [("Rhino Mind Canvas entourage", name), ("Category", cname),
                      ("Source", "{} by {}".format(info["title"], info["author"])),
                      ("Source file", item["file"]), ("License", info["license"]), ("Link", info["page"]),
                      ("Units", "inches, Z up, origin on the ground at the footprint centre, front -Y")]
            objfile.write(path, m, header)
            entry = {"file": rel, "category": cname, "group": item.get("group", cat.get("group", "")),
                     "size": [round(x1 - x0, 1), round(y1 - y0, 1), round(z1 - z0, 1)],
                     "triangles": m.triangle_count(), "source": info["title"], "author": info["author"],
                     "license": info["license"], "url": info["page"]}
            for k in ("face_view", "heading", "mount", "tags"):
                if k in item or k in cat:
                    entry[k] = item.get(k, cat.get(k))
            tpath = os.path.join(OUT, "thumbs", cslug, slug(name) + ".png")
            os.makedirs(os.path.dirname(tpath), exist_ok=True)
            img = thumbs.render(m, args.thumb)
            thumbs.write_png(tpath, img)
            entry["thumb"] = "thumbs/{}/{}.png".format(cslug, slug(name))
            images.append(img)
            catalog[name] = entry
            kept.update([rel, os.path.splitext(rel)[0] + ".mtl", entry.get("thumb")])
            credits.setdefault(sid, []).append(name)
            total += 1
            say("{:<44} {:>6} tris  {} x {} x {}".format(name, m.triangle_count(), feet_inches(x1 - x0),
                                                           feet_inches(y1 - y0), feet_inches(z1 - z0)))
        if touched:
            with open(cat_path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(catalog, f, indent=1, sort_keys=False)
                f.write("\n")
    if not only:
        write_credits(recipe, credits)
        prune(kept)
    if args.sheet and images:
        thumbs.sheet(args.sheet, images)
        say("contact sheet:", args.sheet)
    say("{} model(s).".format(total))
    if failed:
        say("{} FAILED (left out): {}".format(len(failed), ", ".join(failed)))


def prune(kept):
    """Delete model / thumbnail files no catalog entry uses (renamed or dropped models). Your own
    models (my-models, zz_user_entourage.json) are kept."""
    n = 0
    for sub in ("models", "thumbs"):
        top = os.path.join(OUT, sub)
        for root, _, files in os.walk(top):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), OUT).replace(os.sep, "/")
                if rel not in kept and "/my-models/" not in rel:
                    os.remove(os.path.join(root, f))
                    n += 1
    if n:
        say("removed {} unused file(s)".format(n))


def write_credits(recipe, credits):
    lines = ["# Entourage model credits", "",
             "Every model in `library/entourage/models` comes from a **CC0 1.0 (public domain)** source:",
             "free to use, change and share for any purpose, no attribution required. They are credited",
             "here anyway. The models were converted (Z up, inches, real-world size, front facing -Y, no",
             "textures) by `tools/entourage/build.py` from `tools/entourage/recipe.json`.", ""]
    for sid, info in recipe["sources"].items():
        names = credits.get(sid)
        if not names:
            continue
        lines += ["## {} by {}".format(info["title"], info["author"]), "",
                  "- License: {} ({})".format(info["license"], info.get("license_url", "https://creativecommons.org/publicdomain/zero/1.0/")),
                  "- Link: {}".format(info["page"]),
                  "- Models ({}): {}".format(len(names), ", ".join(sorted(names))), ""]
    with open(os.path.join(OUT, "CREDITS.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", default=os.path.join(tempfile.gettempdir(), "mindcanvas_entourage_cache"))
    ap.add_argument("--only", help="regex: rebuild only the models whose name matches")
    ap.add_argument("--sheet", help="also write a contact sheet of the thumbnails to this PNG")
    ap.add_argument("--thumb", type=int, default=160, help="thumbnail size in pixels")
    ap.add_argument("--out", default=OUT, help="library folder to write (default library/entourage)")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
