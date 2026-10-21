"""Thumbnails of library models in plain Python: a flat-shaded z-buffer render of an
objfile.Model (Z up, front -Y) from the front-left, above, written as PNG (zlib, no PIL). Used by
the library build (tools/entourage/build.py) and by MCEntourage Import (your own OBJ files).

    render(model, size)           -> rows of (r, g, b)
    write_png(path, rows)
    sheet(path, images, cols)     contact sheet of several renders (build.py --sheet)
"""

import math
import struct
import zlib

BG = (255, 255, 255)
LIGHT = (-0.45, -0.7, 0.75)
VIEW_AZ = math.radians(-35.0)     # camera swung from the front (-Y) toward -X
VIEW_EL = math.radians(22.0)
SS = 2                            # supersampling


def _norm(v):
    l = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / l, v[1] / l, v[2] / l)


def _camera():
    # camera looks along d (from the front-left, above, toward the model)
    d = _norm((-math.sin(VIEW_AZ) * math.cos(VIEW_EL), math.cos(VIEW_AZ) * math.cos(VIEW_EL), -math.sin(VIEW_EL)))
    right = _norm((d[1], -d[0], 0.0))
    up = (right[1] * d[2] - right[2] * d[1], right[2] * d[0] - right[0] * d[2], right[0] * d[1] - right[1] * d[0])
    return d, right, up


def render(model, size=160, default=(170, 170, 170)):
    d, right, up = _camera()
    L = _norm(LIGHT)
    n = size * SS
    verts = model.vertices
    proj = [(v[0] * right[0] + v[1] * right[1] + v[2] * right[2],
             v[0] * up[0] + v[1] * up[1] + v[2] * up[2],
             v[0] * d[0] + v[1] * d[1] + v[2] * d[2]) for v in verts]
    used = set(i for g in model.groups for f in g.faces for i in f)
    if not used:
        return [[BG] * size for _ in range(size)]
    xs = [proj[i][0] for i in used]
    ys = [proj[i][1] for i in used]
    w = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    s = (n * 0.9) / w
    cx = (max(xs) + min(xs)) / 2.0
    cy = (max(ys) + min(ys)) / 2.0
    P = [((p[0] - cx) * s + n / 2.0, n / 2.0 - (p[1] - cy) * s, p[2]) for p in proj]
    zbuf = [[1e30] * n for _ in range(n)]
    img = [[BG] * n for _ in range(n)]
    for g in model.groups:
        col = model.colors.get(g.material) or default
        for f in g.faces:
            a = verts[f[0]]
            for k in range(1, len(f) - 1):
                b, c = verts[f[k]], verts[f[k + 1]]
                nv = _norm(((b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1]),
                            (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]),
                            (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])))
                if nv[0] * d[0] + nv[1] * d[1] + nv[2] * d[2] > 0:
                    nv = (-nv[0], -nv[1], -nv[2])      # two-sided
                lam = max(0.0, nv[0] * L[0] + nv[1] * L[1] + nv[2] * L[2])
                k2 = 0.45 + 0.55 * lam
                shade = tuple(min(255, int(ch * k2 + 255 * 0.12 * (1 - k2))) for ch in col)
                _tri(P[f[0]], P[f[k]], P[f[k + 1]], shade, zbuf, img, n)
    # downsample
    out = []
    for y in range(size):
        row = []
        for x in range(size):
            r = g_ = b = 0
            for yy in range(SS):
                src = img[y * SS + yy]
                for xx in range(SS):
                    p = src[x * SS + xx]
                    r += p[0]
                    g_ += p[1]
                    b += p[2]
            k = SS * SS
            row.append((r // k, g_ // k, b // k))
        out.append(row)
    return out


def _tri(p0, p1, p2, col, zbuf, img, n):
    minx = max(0, int(min(p0[0], p1[0], p2[0])))
    maxx = min(n - 1, int(max(p0[0], p1[0], p2[0])) + 1)
    miny = max(0, int(min(p0[1], p1[1], p2[1])))
    maxy = min(n - 1, int(max(p0[1], p1[1], p2[1])) + 1)
    if minx > maxx or miny > maxy:
        return
    area = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (p1[1] - p0[1])
    if abs(area) < 1e-12:
        return
    inv = 1.0 / area
    for y in range(miny, maxy + 1):
        py = y + 0.5
        zr = zbuf[y]
        ir = img[y]
        for x in range(minx, maxx + 1):
            px = x + 0.5
            w0 = ((p1[0] - px) * (p2[1] - py) - (p2[0] - px) * (p1[1] - py)) * inv
            w1 = ((p2[0] - px) * (p0[1] - py) - (p0[0] - px) * (p2[1] - py)) * inv
            w2 = 1.0 - w0 - w1
            if w0 < 0 or w1 < 0 or w2 < 0:
                continue
            z = w0 * p0[2] + w1 * p1[2] + w2 * p2[2]
            if z < zr[x]:
                zr[x] = z
                ir[x] = col


def write_png(path, rows):
    h = len(rows)
    w = len(rows[0]) if h else 0
    raw = b"".join(b"\x00" + bytes(c for px in row for c in px) for row in rows)

    def chunk(t, data):
        return struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def sheet(path, images, cols=8, gap=4):
    if not images:
        return
    size = len(images[0])
    rows_n = (len(images) + cols - 1) // cols
    W = cols * (size + gap) + gap
    H = rows_n * (size + gap) + gap
    canvas = [[(200, 200, 200)] * W for _ in range(H)]
    for i, im in enumerate(images):
        ox = gap + (i % cols) * (size + gap)
        oy = gap + (i // cols) * (size + gap)
        for y, row in enumerate(im):
            canvas[oy + y][ox:ox + size] = row
    write_png(path, canvas)
