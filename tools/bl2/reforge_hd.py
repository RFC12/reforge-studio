"""ReForge HD: escala con IA (Real-ESRGAN) las texturas de interfaz capturadas de un juego DirectX 9 y las
deja como pak (reforge_paks\\HD\\<huella>.png) para que ReForge DualSense las ponga en alta resolución.

Uso: python reforge_hd.py <carpeta Win32 del juego> <realesrgan-ncnn-vulkan.exe> [--todo]
Solo procesa las texturas nuevas (las ya escaladas se saltan), así que se puede volver a ejecutar tras jugar.
"""
import os, sys, shutil, subprocess, tempfile
import numpy as np
from PIL import Image

DXT1, DXT3, DXT5 = 827611204, 861165636, 894720068


def _rgb565(c):
    r = ((c >> 11) & 31).astype(np.int32) * 255 // 31
    g = ((c >> 5) & 63).astype(np.int32) * 255 // 63
    b = (c & 31).astype(np.int32) * 255 // 31
    return np.stack([r, g, b], -1)


def _color(blocks, punch):
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


def _alpha5(blocks):
    a0 = blocks[:, 0].astype(np.int32); a1 = blocks[:, 1].astype(np.int32)
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
    if fmt in (21, 22):
        a = np.frombuffer(data[:w * h * 4], np.uint8).reshape(h, w, 4)[:, :, [2, 1, 0, 3]].copy()
        if fmt == 22:
            a[:, :, 3] = 255
        return a
    if fmt not in (DXT1, DXT3, DXT5):
        return None
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    size = 8 if fmt == DXT1 else 16
    raw = np.frombuffer(data[:bw * bh * size], np.uint8)
    if len(raw) < bw * bh * size:
        return None
    blk = raw.reshape(-1, size)
    if fmt == DXT1:
        px = _color(blk, True)
    else:
        px = _color(blk[:, 8:], False)
        if fmt == DXT5:
            px[:, :, 3] = _alpha5(blk[:, :8])
        else:
            nib = np.stack([blk[:, :8] & 15, blk[:, :8] >> 4], -1).reshape(-1, 16)
            px[:, :, 3] = nib.astype(np.int32) * 17
    img = px.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return np.ascontiguousarray(img[:h, :w]).astype(np.uint8)


def load(p):
    raw = open(p, "rb").read()
    nl = raw.index(b"\n")
    parts = raw[:nl].split()
    return int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]), raw[nl + 1:]


def is_ui(a, levels):
    """Interfaz: transparencia real, no es un mapa de normales ni una textura de mundo repetible."""
    al = a[:, :, 3]
    t = (al < 40).mean()
    if t < 0.08 or t > 0.985:
        return False
    rgb = a[:, :, :3].reshape(-1, 3).astype(np.float32)
    m = rgb.mean(0)
    if m[2] > 180 and abs(m[0] - 128) < 40 and abs(m[1] - 128) < 40:   # mapa de normales
        return False
    return True


def bleed(a, it=8):
    """Extiende el color de los píxeles visibles hacia los transparentes (evita halos al escalar)."""
    a = a.astype(np.float32)
    rgb, al = a[:, :, :3], a[:, :, 3]
    known = al > 8
    rgb = np.where(known[..., None], rgb, 0)
    for _ in range(it):
        if known.all():
            break
        acc = np.zeros_like(rgb); cnt = np.zeros(al.shape, np.float32)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            k = np.roll(np.roll(known, dy, 0), dx, 1)
            acc += np.roll(np.roll(rgb, dy, 0), dx, 1) * k[..., None]
            cnt += k
        new = (~known) & (cnt > 0)
        rgb[new] = acc[new] / cnt[new][:, None]
        known = known | new
    out = np.concatenate([rgb, al[..., None]], -1)
    return np.clip(out, 0, 255).astype(np.uint8)


def target_scale(w, h):
    m = max(w, h)
    return 4 if m <= 256 else 2 if m <= 512 else 0


def esrgan(exe, src_dir, dst_dir, model="realesrgan-x4plus-anime"):
    r = subprocess.run([exe, "-i", src_dir, "-o", dst_dir, "-n", model, "-s", "4", "-f", "png"],
                       cwd=os.path.dirname(exe), capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:])
        raise SystemExit("Real-ESRGAN falló")


def upscale_images(exe, items, out_dir):
    """items: lista de (nombre, rgba uint8, escala). Escribe out_dir/nombre.png en alta resolución."""
    if not items:
        return 0
    tmp = tempfile.mkdtemp(prefix="reforge_hd_")
    src, dst = os.path.join(tmp, "in"), os.path.join(tmp, "out")
    os.makedirs(src); os.makedirs(dst)
    for name, a, sc in items:
        Image.fromarray(bleed(a)).save(os.path.join(src, name + ".png"))
    esrgan(exe, src, dst)
    n = 0
    for name, a, sc in items:
        p = os.path.join(dst, name + ".png")
        if not os.path.exists(p):
            continue
        im = Image.open(p).convert("RGBA")
        h, w = a.shape[:2]
        tw, th = w * sc, h * sc
        if im.size != (tw, th):
            im = im.resize((tw, th), Image.LANCZOS)
        up = np.array(im)
        # alfa: el de la IA puede inventar bordes; se usa el original escalado suave y se recorta con el de la IA
        al = np.array(Image.fromarray(a[:, :, 3]).resize((tw, th), Image.BICUBIC)).astype(np.int32)
        up[:, :, 3] = np.clip((al + up[:, :, 3].astype(np.int32)) // 2, 0, 255)
        Image.fromarray(up).save(os.path.join(out_dir, name + ".png"))
        n += 1
    shutil.rmtree(tmp, ignore_errors=True)
    return n


def main():
    game, exe = sys.argv[1], sys.argv[2]
    dump = os.path.join(game, "reforge_textures", "dump9")
    out = os.path.join(game, "reforge_paks", "HD")
    os.makedirs(out, exist_ok=True)
    if not os.path.exists(os.path.join(out, "pak.ini")):
        open(os.path.join(out, "pak.ini"), "w").write("[pak]\nenabled=1\n; Texturas de interfaz escaladas con IA (Real-ESRGAN)\n")
    done = {n[:16] for n in os.listdir(out)}
    items, stats = [], {"vistas": 0, "interfaz": 0, "nuevas": 0}
    for n in sorted(os.listdir(dump)):
        h = n[:16]
        stats["vistas"] += 1
        fmt, w, hh, lv, data = load(os.path.join(dump, n))
        sc = target_scale(w, hh)
        if not sc or min(w, hh) < 16:
            continue
        a = decode(fmt, w, hh, data)
        if a is None or not is_ui(a, lv):
            continue
        stats["interfaz"] += 1
        if h in done:
            continue
        items.append((h, a, sc))
    stats["nuevas"] = len(items)
    print(stats, flush=True)
    total = 0
    for i in range(0, len(items), 60):
        total += upscale_images(exe, items[i:i + 60], out)
        print("escaladas", total, "de", len(items), flush=True)
    # los iconos de PlayStation también en alta resolución
    ps = os.path.join(game, "reforge_paks", "PlayStation")
    if os.path.isdir(ps):
        src = os.path.join(ps, "original")
        os.makedirs(src, exist_ok=True)
        todo = []
        for n in os.listdir(ps):
            if not n.endswith(".png"):
                continue
            if not os.path.exists(os.path.join(src, n)):
                shutil.copy(os.path.join(ps, n), os.path.join(src, n))
            a = np.array(Image.open(os.path.join(src, n)).convert("RGBA"))
            sc = target_scale(a.shape[1], a.shape[0])
            if sc:
                todo.append((n[:-4], a, sc))
        print("iconos PlayStation en HD:", upscale_images(exe, todo, ps))


if __name__ == "__main__":
    main()
