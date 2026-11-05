"""Logo de las notificaciones de logros (la imagen que elija el usuario).

Se recorta automáticamente: se quita el fondo liso o de cuadros (el típico «PNG falso» con fondo
transparente pintado) rellenando desde los bordes, se centra en un cuadrado y se guarda a 256×256.
Para el juego se exporta como píxeles RGBA sin comprimir («reforge_badge.rgba») que la extensión
C++ carga como textura sin necesitar decodificadores.
"""
import os
import struct
from collections import deque

from .core import config_dir

SIZE = 256


def badge_path():
    return os.path.join(config_dir(), "profile", "badge.png")


def _is_bg(r, g, b, a, corners):
    if a < 16:
        return True
    mx, mn = max(r, g, b), min(r, g, b)
    if mx > 222 and mx - mn < 14:           # blanco / gris claro (fondo o cuadros de «transparencia»)
        return True
    return any(abs(r - cr) + abs(g - cg) + abs(b - cb) < 36 for cr, cg, cb in corners)


def import_badge(src, dst=None):
    """Prepara la imagen elegida como logo. Devuelve la ruta del PNG guardado."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter

    img = QImage(src)
    if img.isNull():
        raise RuntimeError("No se pudo abrir esa imagen (usa PNG, JPG o BMP).")
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    if max(img.width(), img.height()) > 512:
        img = img.scaled(512, 512, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    bpl = img.bytesPerLine()
    data = bytes(img.constBits())[: bpl * h]

    def px(x, y):
        o = y * bpl + x * 4
        return data[o], data[o + 1], data[o + 2], data[o + 3]

    corners = [px(0, 0)[:3], px(w - 1, 0)[:3], px(0, h - 1)[:3], px(w - 1, h - 1)[:3]]
    if any(px(x, y)[3] < 16 for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))):
        corners = []                         # PNG con transparencia real: solo cuenta el canal alfa
    bg = bytearray(w * h)
    q = deque()
    for x in range(w):
        q.extend(((x, 0), (x, h - 1)))
    for y in range(h):
        q.extend(((0, y), (w - 1, y)))
    while q:                                 # relleno desde los bordes: solo el fondo conectado
        x, y = q.popleft()
        i = y * w + x
        if bg[i] or not _is_bg(*px(x, y), corners):
            continue
        bg[i] = 1
        if x > 0:
            q.append((x - 1, y))
        if x < w - 1:
            q.append((x + 1, y))
        if y > 0:
            q.append((x, y - 1))
        if y < h - 1:
            q.append((x, y + 1))
    xs = [i % w for i in range(w * h) if not bg[i]]
    ys = [i // w for i in range(w * h) if not bg[i]]
    if not xs or len(xs) < w * h * 0.02:     # no se distingue el logo: la imagen entera
        x0, y0, x1, y1 = 0, 0, w - 1, h - 1
        bg = bytearray(w * h)
    else:
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    out = QImage(img)
    for i in range(w * h):
        if bg[i]:
            out.setPixelColor(i % w, i // w, QColor(0, 0, 0, 0))
    side = max(x1 - x0 + 1, y1 - y0 + 1)
    cx, cy = (x0 + x1 + 1) / 2, (y0 + y1 + 1) / 2
    sq = QImage(side, side, QImage.Format.Format_RGBA8888)
    sq.fill(Qt.GlobalColor.transparent)
    p = QPainter(sq)
    p.drawImage(int(side / 2 - cx), int(side / 2 - cy), out)
    p.end()
    sq = sq.scaled(SIZE, SIZE, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    dst = dst or badge_path()
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if not sq.save(dst, "PNG"):
        raise RuntimeError("No se pudo guardar el logo.")
    return dst


def badge_for_profile(profile):
    if getattr(profile, "toast_badge", "none") == "custom" and os.path.isfile(badge_path()):
        return badge_path()
    return ""


def export_for_game(profile, exe_dir):
    """Escribe reforge_badge.rgba junto al juego (o lo quita). Devuelve el nombre del archivo o ''."""
    dst = os.path.join(exe_dir, "reforge_badge.rgba")
    src = badge_for_profile(profile)
    if not src:
        if os.path.exists(dst):
            try:
                os.remove(dst)
            except OSError:
                pass
        return ""
    from PySide6.QtGui import QImage
    img = QImage(src).convertToFormat(QImage.Format.Format_RGBA8888)
    if img.isNull():
        return ""
    w, h = img.width(), img.height()
    bpl = img.bytesPerLine()
    raw = bytes(img.constBits())[: bpl * h]
    rows = b"".join(raw[y * bpl: y * bpl + w * 4] for y in range(h))
    tmp = dst + ".tmp"
    with open(tmp, "wb") as f:
        f.write(b"RFBG" + struct.pack("<II", w, h) + rows)
    os.replace(tmp, dst)
    return os.path.basename(dst)
