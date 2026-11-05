"""Reconoce los iconos de botones de Xbox en las texturas volcadas por ReForge DualSense y genera sus
versiones de PlayStation (reforge_textures\\swap\\<hash>.dds), que la DLL pone en lugar de las originales.

Uso:  python iconos_ps.py "H:\\Call of Duty Advanced Warfare"
Necesita PySide6 (para dibujar los símbolos) y el código de ReForge (reforge/glyphs.py, reforge/texswap.py).
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(os.path.dirname(HERE)), os.path.dirname(HERE), HERE):
    sys.path.insert(0, p)
from reforge import texswap  # noqa: E402

SRGB = {72, 75, 78, 91, 93, 99}
BC1, BC2, BC3, BC4, BC5, BC7 = (70, 71, 72), (73, 74, 75), (76, 77, 78), (79, 80, 81), (82, 83, 84), (97, 98, 99)
RGBA, BGRA = (27, 28, 29), (87, 90, 91)


import numpy as np


def _rgb565(c):
    r = ((c >> 11) & 31).astype(np.int32) * 255 // 31
    g = ((c >> 5) & 63).astype(np.int32) * 255 // 63
    b = (c & 31).astype(np.int32) * 255 // 31
    return np.stack([r, g, b], -1)


def _color(blocks, punch):
    """blocks: (N, 8) uint8 -> (N, 16, 4) RGBA."""
    c0 = blocks[:, 0].astype(np.uint16) | (blocks[:, 1].astype(np.uint16) << 8)
    c1 = blocks[:, 2].astype(np.uint16) | (blocks[:, 3].astype(np.uint16) << 8)
    bits = blocks[:, 4:8].copy().view("<u4")[:, 0]
    p0, p1 = _rgb565(c0), _rgb565(c1)
    four = (c0 > c1) | (not punch)
    pal = np.zeros((len(blocks), 4, 4), np.int32)
    pal[:, 0, :3], pal[:, 1, :3] = p0, p1
    pal[:, 2, :3] = np.where(four[:, None], (2 * p0 + p1) // 3, (p0 + p1) // 2)
    pal[:, 3, :3] = np.where(four[:, None], (p0 + 2 * p1) // 3, 0)
    pal[:, :, 3] = 255
    pal[:, 3, 3] = np.where(four, 255, 0)
    idx = (bits[:, None] >> (2 * np.arange(16, dtype=np.uint32))) & 3
    return np.take_along_axis(pal, idx[:, :, None].astype(np.int64).repeat(4, 2), 1)


def _alpha_interp(blocks):
    a0 = blocks[:, 0].astype(np.int32)
    a1 = blocks[:, 1].astype(np.int32)
    bits = np.zeros(len(blocks), np.uint64)
    for i in range(6):
        bits |= blocks[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
    pal = np.zeros((len(blocks), 8), np.int32)
    pal[:, 0], pal[:, 1] = a0, a1
    big = a0 > a1
    for i in range(6):
        pal[:, 2 + i] = np.where(big, ((6 - i) * a0 + (i + 1) * a1) // 7, 0)
    for i in range(4):
        pal[:, 2 + i] = np.where(big, pal[:, 2 + i], ((4 - i) * a0 + (i + 1) * a1) // 5)
    pal[:, 6] = np.where(big, pal[:, 6], 0)
    pal[:, 7] = np.where(big, pal[:, 7], 255)
    idx = (bits[:, None] >> (np.uint64(3) * np.arange(16, dtype=np.uint64))) & np.uint64(7)
    return np.take_along_axis(pal, idx.astype(np.int64), 1)


def decode(fmt, w, h, data):
    if fmt in RGBA or fmt in BGRA:
        a = np.frombuffer(data[:w * h * 4], np.uint8).reshape(h, w, 4).copy()
        if fmt in BGRA:
            a[:, :, [0, 2]] = a[:, :, [2, 0]]
        return a.tobytes()
    if not (fmt in BC1 or fmt in BC2 or fmt in BC3):
        return None
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    size = 8 if fmt in BC1 else 16
    raw = np.frombuffer(data[:bw * bh * size], np.uint8)
    if len(raw) < bw * bh * size:
        return None
    blk = raw.reshape(-1, size)
    if fmt in BC1:
        px = _color(blk, True)
    else:
        px = _color(blk[:, 8:], False)
        if fmt in BC3:
            px[:, :, 3] = _alpha_interp(blk[:, :8])
        else:
            nib = np.stack([blk[:, :8] & 15, blk[:, :8] >> 4], -1).reshape(-1, 16)
            px[:, :, 3] = nib.astype(np.int32) * 17
    img = px.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return np.ascontiguousarray(img[:h, :w]).astype(np.uint8).tobytes()


def quick_colorful(rgba, w, h):
    """Descarte rápido: un icono de botón de Xbox tiene verde, rojo, azul o amarillo saturados y opacos."""
    a = np.frombuffer(rgba, np.uint8).reshape(-1, 4).astype(np.int32)
    op = a[:, 3] > 160
    mx, mn = a[:, :3].max(1), a[:, :3].min(1)
    sat = op & (mx > 90) & ((mx - mn) > 0.45 * mx)
    return sat.sum() >= 40


def write_dds(path, w, h, rgba, srgb):
    fmt = 29 if srgb else 28  # R8G8B8A8_UNORM(_SRGB)
    hdr = bytearray(148)
    hdr[0:4] = b"DDS "
    struct.pack_into("<IIIIIII", hdr, 4, 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x8, h, w, w * 4, 0, 1)
    struct.pack_into("<I", hdr, 76, 32)
    struct.pack_into("<I", hdr, 80, 0x4)
    hdr[84:88] = b"DX10"
    struct.pack_into("<I", hdr, 108, 0x1000)
    struct.pack_into("<IIIII", hdr, 128, fmt, 3, 0, 1, 0)
    with open(path + ".tmp", "wb") as f:
        f.write(bytes(hdr) + rgba)
    os.replace(path + ".tmp", path)


def main(game):
    tdir = os.path.join(game, "reforge_textures")
    ddir = os.path.join(tdir, "dump")
    sdir = os.path.join(tdir, "swap")
    os.makedirs(sdir, exist_ok=True)
    stats = {"texturas": 0, "sin_decodificar": 0, "iconos": 0}
    formats = {}
    for n in sorted(os.listdir(ddir)):
        if not n.endswith(".rftx"):
            continue
        raw = open(os.path.join(ddir, n), "rb").read()
        nl = raw.index(b"\n")
        _, fmt, w, h, _mips, _arr = raw[:nl].split()
        fmt, w, h = int(fmt), int(w), int(h)
        stats["texturas"] += 1
        formats[fmt] = formats.get(fmt, 0) + 1
        if w < 8 or h < 8:
            continue
        if max(w, h) > 1024:
            continue
        rgba = decode(fmt, w, h, raw[nl + 1:])
        if rgba is None:
            stats["sin_decodificar"] += 1
            continue
        if not quick_colorful(rgba, w, h):
            continue
        stats["candidatas"] = stats.get("candidatas", 0) + 1
        plan = texswap.analyze(rgba, w, h)
        if not plan:
            continue
        new = texswap.render(rgba, w, h, plan)
        if not new:
            continue
        write_dds(os.path.join(sdir, n[:16] + ".dds"), w, h, new, fmt in SRGB)
        try:  # vista previa: original | PlayStation
            from reforge import glyphs
            from PySide6 import QtGui
            pdir = os.path.join(tdir, "preview")
            os.makedirs(pdir, exist_ok=True)
            both = QtGui.QImage(w * 2, h, QtGui.QImage.Format.Format_RGBA8888)
            both.fill(0)
            p = QtGui.QPainter(both)
            p.drawImage(0, 0, glyphs.to_qimage(rgba, w, h))
            p.drawImage(w, 0, glyphs.to_qimage(new, w, h))
            p.end()
            both.save(os.path.join(pdir, n[:16] + ".png"))
        except Exception as e:  # noqa: BLE001
            print("vista previa:", e)
        stats["iconos"] += 1
        print("icono:", n, w, "x", h, plan[0], plan[1] if plan[0] == "button" else len(plan[1]))
    print("formatos (DXGI):", formats)
    print(stats)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else r"H:\Call of Duty Advanced Warfare")
