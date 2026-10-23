"""Writes printable QR tags (binary STL, millimetres), one per spot.

Per spot: spot-<n>-tag.stl (one body), spot-<n>-base.stl + spot-<n>-qr.stl (two bodies in final position, for two colours).
Run: python tools/make_qr_stl.py urls.json [output-folder]
urls.json maps the spot number to its address, for example {"1": "http://homeassistant.local:8100/s/<secret>/platz/1"}.
Growmi shows these addresses on its QR page (Master data -> QR labels). Needs: pip install segno
"""
import json
import math
import struct
import sys
from pathlib import Path

import segno

OUT = Path("stl")
MODULE = 1.2     # mm per QR module: 3 lines of a 0.4 mm nozzle
QUIET = 3        # modules of empty border around the code
BASE = 2.0       # plate thickness
RAISE = 0.8      # height of the dark parts above the plate (4 layers at 0.2 mm)
STRIP = 14.0     # strip under the code that carries the slot number
EYE_OUTER, EYE_INNER, EYE_RISE = 7.0, 3.0, 4.0  # eyelet for a cable tie or cord
SEG = 2.0        # stroke of the digit

Tri = tuple


def box(x0, y0, z0, x1, y1, z1) -> list[Tri]:
    v = {(i, j, k): (x1 if i else x0, y1 if j else y0, z1 if k else z0) for i in (0, 1) for j in (0, 1) for k in (0, 1)}
    quads = [((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)),  # bottom (-z)
             ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)),  # top (+z)
             ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)),  # front (-y)
             ((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)),  # back (+y)
             ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)),  # left (-x)
             ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1))]  # right (+x)
    tris = []
    for a, b, c, d in quads:
        tris += [(v[a], v[b], v[c]), (v[a], v[c], v[d])]
    return tris


def ring(cx, cy, z0, z1, r_out, r_in, n=64) -> list[Tri]:
    tris = []
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        o0, o1 = (cx + r_out * math.cos(a0), cy + r_out * math.sin(a0)), (cx + r_out * math.cos(a1), cy + r_out * math.sin(a1))
        i0, i1 = (cx + r_in * math.cos(a0), cy + r_in * math.sin(a0)), (cx + r_in * math.cos(a1), cy + r_in * math.sin(a1))
        P = lambda p, z: (p[0], p[1], z)
        tris += [(P(o0, z1), P(i0, z1), P(i1, z1)), (P(o0, z1), P(i1, z1), P(o1, z1)),   # top
                 (P(o0, z0), P(i1, z0), P(i0, z0)), (P(o0, z0), P(o1, z0), P(i1, z0)),   # bottom
                 (P(o0, z0), P(o1, z1), P(o1, z0)), (P(o0, z0), P(o0, z1), P(o1, z1)),   # outer wall
                 (P(i0, z0), P(i1, z0), P(i1, z1)), (P(i0, z0), P(i1, z1), P(i0, z1))]   # inner wall
    return tris


DIGITS = {"1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc"}


def digit_boxes(ch, cx, y0, z0, z1, w=8.0, h=12.0, t=SEG) -> list[Tri]:
    x0 = cx - w / 2
    seg = {"a": (x0, y0 + h - t, x0 + w, y0 + h), "g": (x0, y0 + h / 2 - t / 2, x0 + w, y0 + h / 2 + t / 2),
           "d": (x0, y0, x0 + w, y0 + t), "f": (x0, y0 + h / 2, x0 + t, y0 + h), "b": (x0 + w - t, y0 + h / 2, x0 + w, y0 + h),
           "e": (x0, y0, x0 + t, y0 + h / 2), "c": (x0 + w - t, y0, x0 + w, y0 + h / 2)}
    return [t_ for s in DIGITS[ch] for t_ in box(seg[s][0], seg[s][1], z0, seg[s][2], seg[s][3], z1)]


def write_stl(path: Path, tris: list[Tri], name: str) -> None:
    with open(path, "wb") as f:
        f.write(name.encode()[:80].ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        for a, b, c in tris:
            u, w = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
            n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
            ln = math.sqrt(sum(x * x for x in n)) or 1.0
            f.write(struct.pack("<12fH", *(x / ln for x in n), *a, *b, *c, 0))


def qr_runs(matrix, x0, y_top):
    """Horizontal runs of dark modules as (x0, y0, x1, y1) rectangles."""
    for r, row in enumerate(matrix):
        c = 0
        while c < len(row):
            if row[c]:
                s = c
                while c < len(row) and row[c]:
                    c += 1
                yield (x0 + s * MODULE, y_top - (r + 1) * MODULE, x0 + c * MODULE, y_top - r * MODULE)
            else:
                c += 1


def build(slot: str, url: str):
    q = segno.make(url, error="m")
    matrix = [list(r) for r in q.matrix]
    n = len(matrix)
    side = n * MODULE + 2 * QUIET * MODULE
    width, height = side, side + STRIP
    base = box(0, 0, 0, width, height, BASE) + ring(width / 2, height + EYE_RISE, 0, BASE, EYE_OUTER, EYE_INNER)
    x0, y_top = QUIET * MODULE, height - QUIET * MODULE
    top = BASE + RAISE
    dark = [t for (a, b, c, d) in qr_runs(matrix, x0, y_top) for t in box(a, b, BASE, c, d, top)]
    dark += digit_boxes(slot, width / 2, (STRIP - 12.0) / 2, BASE, top)
    return base, dark, (width, height, n, q.version)


def main() -> None:
    global OUT
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if len(sys.argv) > 2:
        OUT = Path(sys.argv[2])
    OUT.mkdir(exist_ok=True)
    urls = json.load(open(sys.argv[1]))
    for slot, url in sorted(urls.items()):
        base, dark, (w, h, n, ver) = build(slot, url)
        # the combined body lets the dark parts sink 0.2 mm into the plate so slicers merge them cleanly
        sunk = [(tuple((x, y, z - 0.2 if abs(z - BASE) < 1e-9 else z) for x, y, z in t)) for t in dark]
        write_stl(OUT / f"spot-{slot}-tag.stl", base + sunk, f"QR spot {slot}")
        write_stl(OUT / f"spot-{slot}-base.stl", base, f"QR spot {slot} base")
        write_stl(OUT / f"spot-{slot}-qr.stl", dark, f"QR spot {slot} code")
        print(f"spot {slot}: QR version {ver} ({n}x{n}), plate {w:.1f} x {h + 2 * EYE_OUTER + EYE_RISE - EYE_OUTER:.1f} mm, "
              f"{len(base) + len(sunk)} triangles")


if __name__ == "__main__":
    sys.exit(main())
