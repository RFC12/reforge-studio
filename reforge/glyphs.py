"""Iconos de botones al estilo PlayStation para las texturas de interfaz del juego.

* Texturas de un botón suelto: se reconocen por su nombre («A», «BTN_B», «button_x_small», «LT», «Start»…)
  y se dibuja el equivalente (✕ ○ □ △, L1/R1, L2/R2, OPTIONS, CREATE, PS) en el mismo hueco que ocupaba el
  original, conservando su tamaño y posición.
* Diagramas del mando (texturas grandes con «CONTROL», «PAD», «HELP»… en el nombre): se buscan los cuatro
  botones de colores (verde, rojo, azul, amarillo) y se pintan encima los de PlayStation; las líneas y textos
  del juego quedan donde estaban. Solo se toca si aparecen los cuatro (si no, no hay seguridad).
"""
import colorsys
import re

PS_COLORS = {"cross": (0x7E, 0xB2, 0xDD), "circle": (0xFF, 0x66, 0x6E), "square": (0xE5, 0x9A, 0xCD),
             "triangle": (0x3F, 0xD0, 0xA8)}
XBOX_TO_PS = {"a": "cross", "b": "circle", "x": "square", "y": "triangle",
              "lb": "L1", "l1": "L1", "leftbumper": "L1", "rb": "R1", "r1": "R1", "rightbumper": "R1",
              "lt": "L2", "l2": "L2", "lefttrigger": "L2", "rt": "R2", "r2": "R2", "righttrigger": "R2",
              "start": "options", "menu": "options", "back": "create", "select": "create", "view": "create",
              "guide": "ps", "xbox": "ps", "home": "ps", "l3": "L3", "lsclick": "L3", "r3": "R3", "rsclick": "R3"}
NOISE = {"btn", "button", "buttons", "icon", "ico", "pad", "xb", "xb360", "x360", "glyph", "small", "big", "large",
         "sm", "lg", "hud", "ui", "prompt", "n", "on", "off", "normal", "press", "pressed", "img", "tex", "spr", "gfx",
         "white", "black", "hi", "lo", "s", "m", "l"}
DIAGRAM_RE = re.compile(r"control|pad|gamepad|joy|help|howto|tutorial", re.I)


def classify(name):
    """Qué botón de PlayStation corresponde a una textura por su nombre, o "" si no es un botón."""
    parts = [p for p in re.split(r"[^a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1_\2", name).lower()) if p]
    if not parts:
        return ""
    joined = "".join(parts)
    if joined in XBOX_TO_PS and len(parts) <= 2:
        return XBOX_TO_PS[joined]
    hits = [p for p in parts if p in XBOX_TO_PS]
    rest = [p for p in parts if p not in XBOX_TO_PS and p not in NOISE and not p.isdigit()]
    if len(hits) == 1 and not rest and (len(parts) > 1 or hits[0] in XBOX_TO_PS):
        if hits[0] == "xbox" and len(parts) > 1:      # «xbox_a» → es la A
            return ""
        return XBOX_TO_PS[hits[0]]
    if len(hits) == 2 and hits[0] == "xbox" and not rest:
        return XBOX_TO_PS[hits[1]]
    return ""


# ---------------------------------------------------------------- Qt
def _qt():
    from PySide6 import QtCore, QtGui
    return QtCore, QtGui


def to_qimage(rgba, w, h):
    _c, g = _qt()
    return g.QImage(bytes(rgba), w, h, w * 4, g.QImage.Format.Format_RGBA8888).copy()


def from_qimage(img):
    _c, g = _qt()
    img = img.convertToFormat(g.QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    bpl = img.bytesPerLine()
    raw = bytes(img.constBits())
    if bpl == w * 4:
        return raw[:w * h * 4]
    return b"".join(raw[y * bpl: y * bpl + w * 4] for y in range(h))


def alpha_bbox(rgba, w, h, threshold=24):
    xs, ys = [], []
    for y in range(h):
        row = rgba[y * w * 4:(y + 1) * w * 4]
        for x in range(w):
            if row[x * 4 + 3] > threshold:
                xs.append(x)
                ys.append(y)
    if not xs:
        return 0, 0, w, h
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def draw_button(painter, rect, kind):
    """Dibuja el botón `kind` de PlayStation dentro de `rect` (QRectF)."""
    c, g = _qt()
    painter.save()
    painter.setRenderHint(g.QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(g.QPainter.RenderHint.TextAntialiasing)
    s = min(rect.width(), rect.height())
    grad = g.QLinearGradient(rect.topLeft(), rect.bottomLeft())
    grad.setColorAt(0, g.QColor(70, 72, 78))
    grad.setColorAt(1, g.QColor(18, 18, 22))
    rim = g.QPen(g.QColor(150, 152, 160, 220), max(1.0, s * 0.05))
    white = g.QColor(245, 245, 248)
    if kind in PS_COLORS:
        r = s / 2 - rim.widthF() / 2
        ctr = rect.center()
        painter.setPen(rim)
        painter.setBrush(grad)
        painter.drawEllipse(ctr, r, r)
        col = g.QColor(*PS_COLORS[kind])
        pen = g.QPen(col, max(1.4, s * 0.1))
        pen.setCapStyle(c.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(c.Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(c.Qt.BrushStyle.NoBrush)
        k = s * 0.22
        if kind == "cross":
            painter.drawLine(c.QPointF(ctr.x() - k, ctr.y() - k), c.QPointF(ctr.x() + k, ctr.y() + k))
            painter.drawLine(c.QPointF(ctr.x() - k, ctr.y() + k), c.QPointF(ctr.x() + k, ctr.y() - k))
        elif kind == "circle":
            painter.drawEllipse(ctr, k * 1.05, k * 1.05)
        elif kind == "square":
            painter.drawRect(c.QRectF(ctr.x() - k * 0.95, ctr.y() - k * 0.95, k * 1.9, k * 1.9))
        else:
            tri = g.QPolygonF([c.QPointF(ctr.x(), ctr.y() - k * 1.15), c.QPointF(ctr.x() + k * 1.1, ctr.y() + k * 0.8),
                               c.QPointF(ctr.x() - k * 1.1, ctr.y() + k * 0.8)])
            painter.drawPolygon(tri)
    else:
        label = {"options": "", "create": "", "ps": "PS"}.get(kind, kind)
        box = c.QRectF(rect)
        pad = rim.widthF()
        box.adjust(pad, pad, -pad, -pad)
        path = g.QPainterPath()
        if kind in ("L2", "R2"):           # gatillo: arriba redondeado
            rr = box.width() * 0.45
            path.moveTo(box.left(), box.bottom())
            path.lineTo(box.left(), box.top() + rr)
            path.quadTo(box.left(), box.top(), box.left() + rr, box.top())
            path.lineTo(box.right() - rr, box.top())
            path.quadTo(box.right(), box.top(), box.right(), box.top() + rr)
            path.lineTo(box.right(), box.bottom())
            path.closeSubpath()
        elif kind in ("ps", "L3", "R3"):
            path.addEllipse(box)
        else:
            path.addRoundedRect(box, box.height() * 0.32, box.height() * 0.32)
        painter.setPen(rim)
        painter.setBrush(grad)
        painter.drawPath(path)
        painter.setPen(white)
        if kind in ("options", "create"):  # ≡ (OPTIONS) o ⋮ con flecha (CREATE): iconos de línea
            pen = g.QPen(white, max(1.0, s * 0.08))
            pen.setCapStyle(c.Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            cx, cy, k = box.center().x(), box.center().y(), min(box.width(), box.height()) * 0.24
            for i in (-1, 0, 1):
                if kind == "options":
                    painter.drawLine(c.QPointF(cx - k, cy + i * k * 0.7), c.QPointF(cx + k, cy + i * k * 0.7))
                else:
                    painter.drawLine(c.QPointF(cx + i * k * 0.7, cy - k), c.QPointF(cx + i * k * 0.7, cy + k))
        else:
            f = g.QFont("Segoe UI")
            f.setBold(True)
            f.setPixelSize(max(6, int(min(box.height() * 0.6, box.width() * (0.5 if len(label) > 1 else 0.7)))))
            painter.setFont(f)
            painter.drawText(box, int(c.Qt.AlignmentFlag.AlignCenter), label)
    painter.restore()


def render_button(rgba, w, h, kind):
    """Nueva textura (RGBA) con el botón `kind` en el hueco del original."""
    c, g = _qt()
    x0, y0, x1, y1 = alpha_bbox(rgba, w, h)
    img = g.QImage(w, h, g.QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(c.Qt.GlobalColor.transparent)
    p = g.QPainter(img)
    rect = c.QRectF(x0, y0, x1 - x0, y1 - y0)
    if kind in PS_COLORS or kind in ("ps", "L3", "R3"):     # redondos: cuadrado centrado en el hueco
        s = min(rect.width(), rect.height())
        rect = c.QRectF(rect.center().x() - s / 2, rect.center().y() - s / 2, s, s)
    draw_button(p, rect, kind)
    p.end()
    return from_qimage(img)


# ---------------------------------------------------------------- diagramas del mando
def _hue_class(r, g, b, min_s=0.45):
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if s < min_s or v < 0.35:
        return ""
    h *= 360
    if 62 <= h <= 170:
        return "green"
    if h <= 14 or h >= 340:
        return "red"
    if 190 <= h <= 250:
        return "blue"
    if 30 <= h <= 61:
        return "yellow"
    return ""


def find_face_buttons(rgba, w, h, min_s=0.45, min_fill=0.45):
    """{color: [(x0, y0, x1, y1, n)]} de manchas redondas de color (los botones A/B/X/Y y el botón Guía)."""
    cls = [""] * (w * h)
    for i in range(w * h):
        q = i * 4
        if rgba[q + 3] > 128:
            cls[i] = _hue_class(rgba[q], rgba[q + 1], rgba[q + 2], min_s)
    seen = bytearray(w * h)
    out = {}
    for i in range(w * h):
        col = cls[i]
        if not col or seen[i]:
            continue
        stack, n = [i], 0
        seen[i] = 1
        x0 = y0 = 1 << 30
        x1 = y1 = -1
        while stack:
            j = stack.pop()
            n += 1
            x, y = j % w, j // w
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
            for k in (j - 1 if x else -1, j + 1 if x + 1 < w else -1, j - w, j + w):
                if 0 <= k < w * h and not seen[k] and cls[k] == col:
                    seen[k] = 1
                    stack.append(k)
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        if n >= 10 and 0.6 <= bw / bh <= 1.6 and n >= min_fill * bw * bh:
            out.setdefault(col, []).append((x0, y0, x1 + 1, y1 + 1, n))
    return out


def ps_diagram(rgba, w, h):
    """Diagrama con los botones de PlayStation pintados encima, o None si no hay seguridad de dónde están."""
    blobs = find_face_buttons(rgba, w, h)
    if not all(blobs.get(k) for k in ("green", "red", "blue", "yellow")):
        return None
    pick = {k: max(blobs[k], key=lambda b: b[4]) for k in ("red", "blue", "yellow")}
    ref = sorted(b[4] for b in pick.values())[1]
    greens = sorted(blobs["green"], key=lambda b: abs(b[4] - ref))
    pick["green"] = greens[0]
    if not 0.4 <= pick["green"][4] / ref <= 2.5:
        return None
    guide = [b for b in greens[1:] if b[4] > 1.8 * ref]
    if not guide:   # el botón Guía suele ser un aro verde más claro: segunda pasada más permisiva
        a = pick["green"]
        guide = [b for b in find_face_buttons(rgba, w, h, 0.22, 0.3).get("green", [])
                 if b[4] > 1.8 * ref and not (b[0] <= (a[0] + a[2]) / 2 <= b[2] and b[1] <= (a[1] + a[3]) / 2 <= b[3])]
    c, g = _qt()
    img = to_qimage(rgba, w, h).convertToFormat(g.QImage.Format.Format_ARGB32_Premultiplied)
    p = g.QPainter(img)
    names = {"green": "cross", "red": "circle", "blue": "square", "yellow": "triangle"}
    todo = [(pick[k], names[k]) for k in names]
    if guide:
        todo.append((max(guide, key=lambda b: b[4]), "ps"))
    for (x0, y0, x1, y1, _n), kind in todo:
        s = max(x1 - x0, y1 - y0) + 4
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        draw_button(p, c.QRectF(cx - s / 2, cy - s / 2, s, s), kind)
    p.end()
    return from_qimage(img)
