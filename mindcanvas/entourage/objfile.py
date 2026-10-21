"""Wavefront OBJ / MTL reading and writing in plain Python (no Rhino), shared by the plugin
(entourage/place.py) and the library build (tools/entourage/build.py).

    read(path)              -> Model: shared vertices, faces grouped by material, Kd colours
    write(path, model, ...) -> OBJ + MTL next to it

Faces keep their polygon size (triangles, quads, n-gons); texture coordinates and normals are
dropped: entourage is drawn in lines and shaded by Rhino, and the library ships no textures.
A material without a Kd colour reads as None (the plugin uses the layer colour).
"""

import os


class Group(object):
    __slots__ = ("material", "faces")

    def __init__(self, material, faces=None):
        self.material = material
        self.faces = faces if faces is not None else []


class Model(object):
    def __init__(self):
        self.vertices = []          # [(x, y, z)]
        self.groups = []            # [Group], faces index self.vertices (0-based)
        self.colors = {}            # material -> (r, g, b) 0..255 or None
        self.comments = []          # leading "# key: value" lines of a library model

    # -- queries -----------------------------------------------------------------------------
    def face_count(self):
        return sum(len(g.faces) for g in self.groups)

    def triangle_count(self):
        return sum(len(f) - 2 for g in self.groups for f in g.faces)

    def bbox(self):
        vs = self.used_vertices()
        if not vs:
            return None
        return ([min(v[i] for v in vs) for i in range(3)], [max(v[i] for v in vs) for i in range(3)])

    def used_vertices(self):
        used = set(i for g in self.groups for f in g.faces for i in f)
        return [self.vertices[i] for i in sorted(used)]

    def header(self):
        """{key: value} from the '# key: value' comment lines at the top of the file."""
        out = {}
        for line in self.comments:
            if ":" in line:
                k, v = line.split(":", 1)
                out[k.strip().lower()] = v.strip()
        return out

    # -- edits -------------------------------------------------------------------------------
    def transform(self, fn):
        self.vertices = [fn(v) for v in self.vertices]
        return self

    def merge(self, other):
        n = len(self.vertices)
        self.vertices.extend(other.vertices)
        for g in other.groups:
            self.group(g.material).faces.extend(tuple(i + n for i in f) for f in g.faces)
        for k, v in other.colors.items():
            self.colors.setdefault(k, v)
        return self

    def group(self, material):
        for g in self.groups:
            if g.material == material:
                return g
        g = Group(material)
        self.groups.append(g)
        return g

    def compact(self):
        """Drop unused vertices, empty groups and degenerate faces."""
        used = {}
        verts = []
        groups = []
        for g in self.groups:
            faces = []
            for f in g.faces:
                f2 = []
                for i in f:
                    if not f2 or f2[-1] != i:
                        f2.append(i)
                if len(f2) > 1 and f2[0] == f2[-1]:
                    f2.pop()
                if len(set(f2)) < 3:
                    continue
                out = []
                for i in f2:
                    j = used.get(i)
                    if j is None:
                        j = used[i] = len(verts)
                        verts.append(self.vertices[i])
                    out.append(j)
                faces.append(tuple(out))
            if faces:
                groups.append(Group(g.material, faces))
        self.vertices, self.groups = verts, groups
        return self


# -- reading ---------------------------------------------------------------------------------
def _index(tok, n):
    i = int(tok.split("/", 1)[0])
    return i - 1 if i > 0 else n + i


def read_mtl(path):
    """{material: (r, g, b) 0..255 or None} from the Kd lines of an MTL file."""
    out = {}
    cur = None
    if not os.path.isfile(path):
        return out
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            a = line.split()
            if not a:
                continue
            if a[0] == "newmtl":
                cur = line.split(None, 1)[1].strip() if len(a) > 1 else ""
                out[cur] = None
            elif a[0] == "Kd" and cur is not None and len(a) >= 4:
                try:
                    out[cur] = tuple(int(round(max(0.0, min(1.0, float(x))) * 255)) for x in a[1:4])
                except ValueError:
                    pass
    return out


def read(path):
    m = Model()
    folder = os.path.dirname(path)
    cur = m.group("default")
    head = True
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#"):
                if head:
                    m.comments.append(line[1:].strip())
                continue
            a = line.split()
            if not a:
                continue
            head = False
            t = a[0]
            if t == "v":
                m.vertices.append((float(a[1]), float(a[2]), float(a[3])))
            elif t == "f":
                n = len(m.vertices)
                face = tuple(_index(tok, n) for tok in a[1:])
                if len(face) >= 3:
                    cur.faces.append(face)
            elif t == "usemtl":
                cur = m.group(line.split(None, 1)[1].strip() if len(a) > 1 else "default")
            elif t == "mtllib" and len(a) > 1:
                rest = line.split(None, 1)[1].strip()
                names = [rest] if os.path.isfile(os.path.join(folder, rest)) else rest.split(" ")
                for name in names:
                    for k, v in read_mtl(os.path.join(folder, name)).items():
                        m.colors.setdefault(k, v)
    m.groups = [g for g in m.groups if g.faces]
    return m


# -- writing ---------------------------------------------------------------------------------
def _num(x, digits):
    s = "{:.{}f}".format(x, digits).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def write(path, model, header=(), digits=3):
    """OBJ + MTL (same base name). `header`: [(key, value)] written as '# key: value' lines."""
    base = os.path.splitext(os.path.basename(path))[0]
    mtl = base + ".mtl"
    lines = ["# {}: {}".format(k, v) for k, v in header]
    lines.append("mtllib " + mtl)
    lines.append("o " + base)
    for v in model.vertices:
        lines.append("v {} {} {}".format(*(_num(c, digits) for c in v)))
    for g in model.groups:
        lines.append("usemtl " + g.material)
        for f in g.faces:
            lines.append("f " + " ".join(str(i + 1) for i in f))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    out = []
    for g in model.groups:
        c = model.colors.get(g.material) or (180, 180, 180)
        out += ["newmtl " + g.material, "Kd {} {} {}".format(*(_num(x / 255.0, 4) for x in c)), ""]
    with open(os.path.join(os.path.dirname(path), mtl), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))
    return path
