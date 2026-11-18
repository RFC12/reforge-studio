import os, sys, struct
import numpy as np
from PIL import Image, ImageDraw
BC1, BC2, BC3 = (827611204,), (861165636,), (894720068,)
RGBA, BGRA = (), (21, 22)
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



def load(p):
    raw = open(p, "rb").read()
    nl = raw.index(b"\n")
    _, fmt, w, h, lv = raw[:nl].split()
    return int(fmt), int(w), int(h), raw[nl+1:]

def colorful(a):
    a = a.reshape(-1, 4).astype(np.int32)
    op = a[:, 3] > 160
    mx, mn = a[:, :3].max(1), a[:, :3].min(1)
    return int((op & (mx > 90) & ((mx - mn) > 0.45 * mx)).sum())

d, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
cands = []
for n in sorted(os.listdir(d)):
    fmt, w, h, data = load(os.path.join(d, n))
    if max(w, h) > 512 or min(w, h) < 16:
        continue
    if fmt == 50:
        continue
    px = decode(fmt, w, h, data)
    if px is None:
        continue
    a = np.frombuffer(px, np.uint8).reshape(h, w, 4)
    al = a[:, :, 3]
    transp = (al < 40).mean()
    if transp < 0.15 or transp > 0.97:
        continue
    op = al > 160
    rgb = a[:, :, :3].astype(int)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    green = (op & (g > 120) & (g > r + 40) & (g > b + 40)).sum()
    red = (op & (r > 140) & (r > g + 70) & (r > b + 70)).sum()
    blue = (op & (b > 140) & (b > r + 50) & (b > g + 10)).sum()
    yel = (op & (r > 150) & (g > 130) & (b < 90)).sum()
    score = sum(1 for v in (green, red, blue, yel) if v > 6)
    cands.append((n[:16], fmt, w, h, a, score))
print("candidatas", len(cands))
cands.sort(key=lambda c: (-c[5], c[2] * c[3]))
T = 128
per = 48
for s in range(0, len(cands), per):
    sheet = Image.new("RGB", (8 * (T + 8), 6 * (T + 22)), (60, 60, 60))
    dr = ImageDraw.Draw(sheet)
    for i, (hsh, fmt, w, h, a, c) in enumerate(cands[s:s + per]):
        im = Image.fromarray(a)
        sc = T / max(im.size)
        im = im.resize((max(1, int(im.size[0] * sc)), max(1, int(im.size[1] * sc))), Image.NEAREST if sc > 1 else Image.LANCZOS)
        bg = Image.new("RGBA", im.size, (40, 40, 40, 255))
        bg.alpha_composite(im)
        x, y = (i % 8) * (T + 8) + 4, (i // 8) * (T + 22) + 4
        sheet.paste(bg.convert("RGB"), (x, y))
        dr.text((x, y + T + 2), "%d %s %dx%d" % (s + i, hsh[:8], w, h), fill=(255, 255, 0))
    sheet.save(os.path.join(out, "hoja_%03d.png" % (s // per)))
with open(os.path.join(out, "indice.txt"), "w") as f:
    for i, c in enumerate(cands):
        f.write("%d %s %d %d %d %d\n" % (i, c[0], c[1], c[2], c[3], c[5]))
