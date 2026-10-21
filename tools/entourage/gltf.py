"""Minimal glTF 2.0 reader (.gltf + .bin or .glb) -> objfile.Model, for the library build.

Reads every mesh primitive (triangles, POSITION + indices) of the default scene with its node
transforms (matrix or TRS) applied. Materials: name + baseColorFactor (a texture-only material
reads as None). Y is up, as glTF says; build.py turns it to Z up.
"""

import base64
import json
import os
import struct

from mindcanvas.entourage import objfile

COMP = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _load(path):
    if path.lower().endswith(".glb"):
        data = open(path, "rb").read()
        _, _, n = struct.unpack_from("<4sII", data, 0)
        off = 12
        js, binchunk = None, None
        while off < n:
            ln, typ = struct.unpack_from("<I4s", data, off)
            chunk = data[off + 8: off + 8 + ln]
            if typ == b"JSON":
                js = json.loads(chunk.decode("utf-8"))
            elif typ == b"BIN\x00":
                binchunk = chunk
            off += 8 + ln
        return js, [binchunk]
    js = json.load(open(path, "r", encoding="utf-8"))
    bufs = []
    for b in js.get("buffers", []):
        uri = b.get("uri", "")
        if uri.startswith("data:"):
            bufs.append(base64.b64decode(uri.split(",", 1)[1]))
        else:
            bufs.append(open(os.path.join(os.path.dirname(path), uri), "rb").read())
    return js, bufs


def _accessor(js, bufs, i):
    a = js["accessors"][i]
    bv = js["bufferViews"][a["bufferView"]]
    fmt, size = COMP[a["componentType"]]
    nc = NCOMP[a["type"]]
    stride = bv.get("byteStride") or size * nc
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    buf = bufs[bv["buffer"]]
    out = []
    for k in range(a["count"]):
        v = struct.unpack_from("<" + fmt * nc, buf, base + k * stride)
        out.append(v if nc > 1 else v[0])
    return out


def _matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _node_matrix(n):
    if "matrix" in n:
        m = n["matrix"]       # column-major
        return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
    t = n.get("translation", [0, 0, 0])
    x, y, z, w = n.get("rotation", [0, 0, 0, 1])
    s = n.get("scale", [1, 1, 1])
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    return [[r[i][0] * s[0], r[i][1] * s[1], r[i][2] * s[2], t[i]] for i in range(3)] + [[0, 0, 0, 1]]


def read(path):
    js, bufs = _load(path)
    m = objfile.Model()
    mats = js.get("materials", [])
    for i, mat in enumerate(mats):
        name = mat.get("name") or "material_{}".format(i)
        pbr = mat.get("pbrMetallicRoughness", {})
        f = pbr.get("baseColorFactor")
        m.colors[name] = tuple(int(round(max(0, min(1, c)) ** (1 / 2.2) * 255)) for c in f[:3]) if f else None
    scene = js.get("scenes", [{}])[js.get("scene", 0)]
    ident = [[1 if i == j else 0 for j in range(4)] for i in range(4)]

    def visit(ni, parent):
        n = js["nodes"][ni]
        mx = _matmul(parent, _node_matrix(n))
        if "mesh" in n:
            for prim in js["meshes"][n["mesh"]]["primitives"]:
                if prim.get("mode", 4) != 4 or "POSITION" not in prim["attributes"]:
                    continue
                pos = _accessor(js, bufs, prim["attributes"]["POSITION"])
                idx = _accessor(js, bufs, prim["indices"]) if "indices" in prim else list(range(len(pos)))
                base = len(m.vertices)
                for p in pos:
                    m.vertices.append(tuple(mx[r][0] * p[0] + mx[r][1] * p[1] + mx[r][2] * p[2] + mx[r][3]
                                            for r in range(3)))
                mi = prim.get("material")
                mname = (mats[mi].get("name") or "material_{}".format(mi)) if mi is not None else "default"
                g = m.group(mname)
                flip = _det3(mx) < 0
                for k in range(0, len(idx) - 2, 3):
                    a, b, c = idx[k] + base, idx[k + 1] + base, idx[k + 2] + base
                    g.faces.append((a, c, b) if flip else (a, b, c))
        for c in n.get("children", []):
            visit(c, mx)

    for ni in scene.get("nodes", range(len(js.get("nodes", [])))):
        visit(ni, ident)
    m.groups = [g for g in m.groups if g.faces]
    return m


def _det3(mx):
    a = [r[:3] for r in mx[:3]]
    return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
            + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
