"""Iconos de botones de PlayStation en cualquier juego, reconocidos solos y cambiados en la GPU.

Cómo funciona (con el SDK de ReForge, que lleva el parche «texswap» en rexgpu-xenos.dll):
1. Mientras juegas, la GPU guarda en reforge_textures/dump las texturas pequeñas que el juego usa (una vez
   cada una, con su formato exacto).
2. ReForge las mira solo (al jugar, cada pocos segundos, y al cerrar):
   · por su nombre, si la textura viene de un .xpr del juego (A, BTN_LB, LT, Start…);
   · por su aspecto: círculos de los colores de Xbox (verde A, rojo B, azul X, amarillo Y) con su letra,
     sueltos (un icono) o varios en la misma textura (hojas de iconos, diagramas del mando).
3. Por cada textura reconocida genera la versión PlayStation (✕ ○ □ △, L1/R1, L2/R2, OPTIONS…) con el mismo
   formato y tamaño, y la registra en index.txt como pareja original ↔ PlayStation.
4. La GPU cambia los bytes al subir la textura; style.txt dice qué versión se ve. Cambiarlo (opciones de
   ReForge o menú Guía dentro del juego) cambia los iconos al momento, sin reiniciar.
Nada de esto toca los archivos del juego.
"""
import hashlib
import json
import os
import struct
import sys
import threading
import time

from . import glyphs, xpr

DIR = "reforge_textures"
ALGO_VERSION = 2
FORMATS = {6, 18, 19, 20}
ICON_MAX = 256


def tex_dir(exe):
    return os.path.join(os.path.dirname(exe), DIR)


def plugin_supports(path):
    """¿Este rexgpu-xenos.dll lleva el parche de ReForge?"""
    try:
        with open(path, "rb") as f:
            return b"reforge_textures" in f.read()
    except OSError:
        return False


def read_dump(path):
    """(Texture, bytes, has_mips) de un volcado .rftx de la GPU."""
    with open(path, "rb") as f:
        data = f.read()
    nl = data.find(b"\n")
    head = data[:nl].decode("ascii", "replace").split()
    if nl < 0 or not head or head[0] != "RFTX1" or len(head) < 9:
        raise ValueError("volcado no válido")
    fmt, w, h, pitch, tiled, endian, size, mips = (int(x) for x in head[1:9])
    blob = data[nl + 1:]
    if len(blob) != size:
        raise ValueError("volcado incompleto")
    return xpr.Texture("", fmt, endian, w, h, pitch, bool(tiled), 0), blob, bool(mips)


# ---------------------------------------------------------------- reconocer
def _xpr_names(root):
    """{huella de los primeros bytes: nombre} de las texturas de los .xpr del juego."""
    out = {}
    assets = os.path.join(root, "assets")
    for d, _s, fs in os.walk(assets):
        for f in fs:
            if not f.lower().endswith(".xpr"):
                continue
            try:
                path = os.path.join(d, f)
                if os.path.getsize(path) > 256 << 20:
                    continue
                with open(path, "rb") as fh:
                    data = fh.read()
                for t in xpr.parse(data):
                    if t.supported:
                        raw = data[t.offset: t.offset + min(2048, t.layout()[6])]
                        if len(raw) >= 64:
                            out[hashlib.sha1(raw).hexdigest()] = t.name
            except (OSError, ValueError):
                continue
    return out


def _letter_inside(rgba, w, blob):
    """¿Hay una letra/símbolo dentro del círculo (píxeles claros u oscuros sin color)?"""
    x0, y0, x1, y1, _n = blob
    cx0, cy0 = x0 + (x1 - x0) // 4, y0 + (y1 - y0) // 4
    cx1, cy1 = x1 - (x1 - x0) // 4, y1 - (y1 - y0) // 4
    total = plain = 0
    for y in range(cy0, cy1):
        for x in range(cx0, cx1):
            q = (y * w + x) * 4
            r, g, b, a = rgba[q:q + 4]
            if a < 128:
                continue
            total += 1
            if max(r, g, b) - min(r, g, b) < 60 and (max(r, g, b) > 170 or max(r, g, b) < 70):
                plain += 1
    return total and 0.06 <= plain / total <= 0.88


COLOR_KIND = {"green": "cross", "red": "circle", "blue": "square", "yellow": "triangle"}


def _merge_near(bs, gap=2):
    """Une manchas del mismo color que se tocan: una letra gruesa puede partir el círculo en trozos."""
    bs = [list(b) for b in bs]
    merged = True
    while merged:
        merged = False
        for i in range(len(bs)):
            for j in range(i + 1, len(bs)):
                a, b = bs[i], bs[j]
                if a[0] - gap <= b[2] and b[0] - gap <= a[2] and a[1] - gap <= b[3] and b[1] - gap <= a[3]:
                    bs[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]), a[4] + b[4]]
                    del bs[j]
                    merged = True
                    break
            if merged:
                break
    return [tuple(b) for b in bs]


def analyze(rgba, w, h, name=""):
    """Qué hacer con una textura: ("button", tipo) · ("blobs", [(caja, tipo)]) · ("diagram",) · None."""
    if name:
        kind = glyphs.classify(name)
        if kind:
            return ("button", kind)
        if glyphs.DIAGRAM_RE.search(name) and min(w, h) >= 96 and glyphs.ps_diagram(rgba, w, h) is not None:
            return ("diagram",)
    blobs = {col: _merge_near(bs) for col, bs in glyphs.find_face_buttons(rgba, w, h, 0.45, 0.0).items()}
    found = [(col, b) for col, bs in blobs.items() for b in bs
             if max(b[2] - b[0], b[3] - b[1]) >= 9 and b[4] >= 0.22 * (b[2] - b[0]) * (b[3] - b[1])]
    if not found:
        return None
    x0, y0, x1, y1 = glyphs.alpha_bbox(rgba, w, h)
    area = max(1, (x1 - x0) * (y1 - y0))
    if len(found) == 1 and max(w, h) <= ICON_MAX:
        col, b = found[0]
        bw, bh = b[2] - b[0], b[3] - b[1]
        if bw * bh >= 0.45 * area and 0.75 <= bw / bh <= 1.33 and _letter_inside(rgba, w, b):
            return ("button", COLOR_KIND[col])
        return None
    colors = {c for c, _b in found}
    if len(colors) < 2:
        return None
    sizes = sorted(b[4] for _c, b in found)
    ref = sizes[len(sizes) // 2]
    keep = [(b, COLOR_KIND[c]) for c, b in found if 0.4 <= b[4] / ref <= 2.5 and _letter_inside(rgba, w, b)]
    if len({k for _b, k in keep}) < 2:
        return None
    return ("blobs", keep)


def render(rgba, w, h, plan):
    if plan[0] == "button":
        return glyphs.render_button(rgba, w, h, plan[1])
    if plan[0] == "diagram":
        return glyphs.ps_diagram(rgba, w, h)
    from PySide6 import QtCore, QtGui
    img = glyphs.to_qimage(rgba, w, h).convertToFormat(QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    p = QtGui.QPainter(img)
    for (x0, y0, x1, y1, _n), kind in plan[1]:
        s = max(x1 - x0, y1 - y0) + 3
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        glyphs.draw_button(p, QtCore.QRectF(cx - s / 2, cy - s / 2, s, s), kind)
    p.end()
    return glyphs.from_qimage(img)


# ---------------------------------------------------------------- procesar volcados
def _load_state(d):
    try:
        with open(os.path.join(d, "estado.json"), encoding="utf-8") as f:
            st = json.load(f)
        if st.get("version") == ALGO_VERSION:
            return st
    except (OSError, ValueError):
        pass
    return {"version": ALGO_VERSION, "hechos": {}}


def process(exe, root, names=None):
    """Mira los volcados nuevos y registra las parejas Xbox ↔ PlayStation. Devuelve cuántas añadió."""
    d = tex_dir(exe)
    dump = os.path.join(d, "dump")
    if not os.path.isdir(dump):
        return 0
    st = _load_state(d)
    done = st["hechos"]
    files = [f for f in os.listdir(dump) if f.endswith(".rftx") and f[:-5] not in done]
    if not files:
        return 0
    if names is None:
        names = _xpr_names(root)
    pairs_dir = os.path.join(d, "pares")
    os.makedirs(pairs_dir, exist_ok=True)
    added = 0
    for f in sorted(files):
        key = f[:-5]
        try:
            tex, blob, _mips = read_dump(os.path.join(dump, f))
            if tex.fmt not in FORMATS:
                done[key] = "formato"
                continue
            rgba = xpr.decode(blob, tex)
            name = names.get(hashlib.sha1(blob[:2048]).hexdigest(), "")
            plan = analyze(rgba, tex.width, tex.height, name)
            if not plan:
                done[key] = "-"
                continue
            new = render(rgba, tex.width, tex.height, plan)
            if not new:
                done[key] = "-"
                continue
            out = bytearray(blob)
            xpr.encode_into(out, tex, new)
            if bytes(out) == blob:
                done[key] = "-"
                continue
            with open(os.path.join(pairs_dir, key + ".x.bin"), "wb") as fh:
                fh.write(blob)
            with open(os.path.join(pairs_dir, key + ".p.bin"), "wb") as fh:
                fh.write(bytes(out))
            done[key] = (plan[1] if plan[0] == "button" else plan[0]) + (f" ({name})" if name else "")
            added += 1
        except Exception:      # noqa: BLE001 — una textura rara no detiene el resto
            done[key] = "error"
    if added:
        _write_index(d, done)
    with open(os.path.join(d, "estado.json.tmp"), "w", encoding="utf-8") as fh:
        json.dump(st, fh)
    os.replace(os.path.join(d, "estado.json.tmp"), os.path.join(d, "estado.json"))
    return added


def _write_index(d, done):
    excluded = set()
    try:
        with open(os.path.join(d, "excluir.txt"), encoding="utf-8") as f:
            excluded = {ln.strip() for ln in f if ln.strip()}
    except OSError:
        pass
    lines = [f"pares/{k}.x.bin pares/{k}.p.bin" for k, v in sorted(done.items())
             if v not in ("-", "error", "formato") and k not in excluded
             and os.path.isfile(os.path.join(d, "pares", k + ".p.bin"))]
    tmp = os.path.join(d, "index.txt.tmp")
    with open(tmp, "w", encoding="ascii", newline="\n") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))
    os.replace(tmp, os.path.join(d, "index.txt"))


def recognized(exe):
    """[(clave, qué es)] de las texturas reconocidas (para mostrarlas en opciones)."""
    st = _load_state(tex_dir(exe))
    return [(k, v) for k, v in sorted(st["hechos"].items()) if v not in ("-", "error", "formato")]


def set_style(exe, style):
    d = tex_dir(exe)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "style.txt")
    try:
        if open(path, encoding="ascii").read().strip() == style:
            return
    except OSError:
        pass
    with open(path, "w", encoding="ascii") as f:
        f.write(style + "\n")


def prepare(exe, root, style, learn=True):
    """Antes de abrir el juego: estilo, aprendizaje (volcado) y parejas al día."""
    d = tex_dir(exe)
    os.makedirs(d, exist_ok=True)
    set_style(exe, style)
    flag = os.path.join(d, "dump.on")
    if learn and not os.path.isfile(flag):
        open(flag, "w").close()
    elif not learn and os.path.isfile(flag):
        os.remove(flag)
    if not os.path.isfile(os.path.join(d, "index.txt")):
        open(os.path.join(d, "index.txt"), "w").close()
    return process(exe, root)


def _running(exe):
    if sys.platform != "win32":
        return False
    try:
        fd = os.open(exe, os.O_WRONLY | os.O_APPEND)
    except PermissionError:
        return True
    except OSError:
        return False
    os.close(fd)
    return False


_live = {}


def start_live(exe, root, interval=3.0, max_hours=6):
    """Mientras el juego está abierto, reconoce las texturas nuevas cada pocos segundos (iconos al momento)."""
    key = os.path.abspath(exe)
    if _live.get(key) and _live[key].is_alive():
        return _live[key]

    def run():
        names = None
        t_end = time.time() + max_hours * 3600
        time.sleep(4)
        while time.time() < t_end:
            try:
                if names is None:
                    names = _xpr_names(root)
                process(exe, root, names)
            except Exception:      # noqa: BLE001
                pass
            if not _running(exe):
                break
            time.sleep(interval)

    th = threading.Thread(target=run, daemon=True, name="reforge-texswap")
    _live[key] = th
    th.start()
    return th


def menu_style(exe):
    """Iconos elegidos dentro del juego (menú Guía → Personalizar), o "" si no se tocó."""
    try:
        with open(os.path.join(os.path.dirname(exe), "reforge_menu.ini"), encoding="utf-8") as f:
            for ln in f:
                k, _, v = ln.partition("=")
                if k.strip() == "button_style" and v.strip() in ("xbox", "playstation"):
                    return v.strip()
    except OSError:
        pass
    return ""


def set_menu_style(exe, style):
    """Lleva al menú Guía lo elegido en las opciones de ReForge ("" = automático)."""
    path = os.path.join(os.path.dirname(exe), "reforge_menu.ini")
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        if not style:
            return
        lines = []
    lines = [ln for ln in lines if ln.partition("=")[0].strip() != "button_style"]
    lines.append(f"button_style = {style}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


_ = struct
