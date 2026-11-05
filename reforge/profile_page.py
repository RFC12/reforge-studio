"""Página «Perfil»: Gamertag, imagen, Xbox Live simulado y notificación de logros (con vista previa)."""
import math
import os

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from .profile import TOAST_POSITIONS, Profile, clean_gamertag, import_avatar, valid_gamertag
from .widgets import label

# Imágenes de jugador propias de ReForge (dibujadas, sin recursos de terceros).
GEN_AVATARS = [
    ("#19d3a2", "#0b3d30", "hex"), ("#ff9f1c", "#4a2a00", "bolt"), ("#5b8cff", "#14224d", "star"),
    ("#e5484d", "#47121a", "ring"), ("#b072ff", "#2b1450", "diamond"), ("#f5d90a", "#3d3500", "wave"),
    ("#3dd6f5", "#0b3440", "pad"), ("#ff6ac1", "#4a1236", "crown"),
]


def generated_avatar(index, size=128):
    fg, bg, shape = GEN_AVATARS[index % len(GEN_AVATARS)]
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(bg))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, size, size, size * 0.18, size * 0.18)
    c, r = size / 2, size * 0.30
    p.setBrush(QColor(fg))
    if shape == "hex":
        p.drawPolygon(QPolygonF([QPointF(c + r * math.cos(math.pi / 3 * i + math.pi / 6),
                                         c + r * math.sin(math.pi / 3 * i + math.pi / 6)) for i in range(6)]))
    elif shape == "bolt":
        pts = [(0.55, 0.12), (0.28, 0.55), (0.48, 0.55), (0.40, 0.88), (0.72, 0.42), (0.52, 0.42), (0.62, 0.12)]
        p.drawPolygon(QPolygonF([QPointF(x * size, y * size) for x, y in pts]))
    elif shape == "star":
        p.drawPolygon(QPolygonF([QPointF(c + (r if i % 2 == 0 else r * 0.45) * math.cos(-math.pi / 2 + i * math.pi / 5),
                                         c + (r if i % 2 == 0 else r * 0.45) * math.sin(-math.pi / 2 + i * math.pi / 5))
                                 for i in range(10)]))
    elif shape == "ring":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(fg), size * 0.09))
        p.drawEllipse(QPointF(c, c), r, r)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(fg))
        p.drawEllipse(QPointF(c, c), r * 0.35, r * 0.35)
    elif shape == "diamond":
        p.drawPolygon(QPolygonF([QPointF(c, c - r * 1.1), QPointF(c + r * 0.8, c), QPointF(c, c + r * 1.1),
                                 QPointF(c - r * 0.8, c)]))
    elif shape == "wave":
        path = QPainterPath(QPointF(size * 0.15, c))
        for i in range(4):
            x0 = size * 0.15 + i * size * 0.175
            path.quadTo(QPointF(x0 + size * 0.0875, c - r * (0.8 if i % 2 == 0 else -0.8)), QPointF(x0 + size * 0.175, c))
        p.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor(fg), size * 0.08)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawPath(path)
    elif shape == "pad":
        p.drawRoundedRect(QRectF(c - r * 1.2, c - r * 0.55, r * 2.4, r * 1.1), r * 0.5, r * 0.5)
        p.setBrush(QColor(bg))
        p.drawEllipse(QPointF(c + r * 0.6, c), r * 0.16, r * 0.16)
        p.drawRect(QRectF(c - r * 0.85, c - r * 0.07, r * 0.5, r * 0.14))
        p.drawRect(QRectF(c - r * 0.67, c - r * 0.25, r * 0.14, r * 0.5))
    elif shape == "crown":
        pts = [(0.2, 0.7), (0.2, 0.35), (0.35, 0.5), (0.5, 0.28), (0.65, 0.5), (0.8, 0.35), (0.8, 0.7)]
        p.drawPolygon(QPolygonF([QPointF(x * size, y * size) for x, y in pts]))
    p.end()
    return pm


def avatar_pixmap(profile, size=96):
    path = profile.avatar_path()
    if path:
        src = QPixmap(path)
        if not src.isNull():
            src = src.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                             Qt.TransformationMode.SmoothTransformation)
            out = QPixmap(size, size)
            out.fill(Qt.GlobalColor.transparent)
            p = QPainter(out)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            clip = QPainterPath()
            clip.addRoundedRect(0, 0, size, size, size * 0.18, size * 0.18)
            p.setClipPath(clip)
            p.drawPixmap((size - src.width()) // 2, (size - src.height()) // 2, src)
            p.end()
            return out
    idx = 0
    if profile.avatar.startswith("gen:"):
        try:
            idx = int(profile.avatar[4:])
        except ValueError:
            idx = 0
    return generated_avatar(idx, size)


def _trophy_polys(cx, cy, ir, sq):
    """Trofeo dibujado (mismas proporciones que DrawTrophy en la extensión C++)."""
    P = lambda x, y: QPointF(cx + x * ir * sq, cy + y * ir)  # noqa: E731
    cup = [P(-0.42, -0.46)] + [P(0.42 * math.cos(math.pi * i / 10), -0.46 + 0.58 * math.sin(math.pi * i / 10))
                               for i in range(10, -1, -1)]
    handles = [[P(side * (0.40 + 0.17 * math.cos(-math.pi / 2 + math.pi * i / 8)),
                  -0.27 + 0.17 * math.sin(-math.pi / 2 + math.pi * i / 8)) for i in range(9)] for side in (-1, 1)]
    rects = [(-0.07, 0.08, 0.07, 0.30), (-0.18, 0.26, 0.18, 0.32), (-0.27, 0.32, 0.27, 0.43)]
    return cup, handles, [QRectF(P(x0, y0), P(x1, y1)) for x0, y0, x1, y1 in rects]


class ToastPreview(QWidget):
    """Vista previa de la notificación de logros: misma animación que dibuja el juego (reforge_ext.cpp)."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(340)
        self.position = "bottom_right"
        self.title = "Logro desbloqueado"
        self.accent = QColor("#19d3a2")
        self.badge = QPixmap()             # logo del perfil (vacío = sin logo)
        self.t = 2.4                       # segundo de la animación que se muestra en reposo
        self.total = 5.0
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self._clock = None

    def play(self):
        from time import monotonic
        self._clock = monotonic()
        self.t = 0.0
        self.timer.start()

    def _tick(self):
        from time import monotonic
        self.t = monotonic() - (self._clock or monotonic())
        if self.t >= self.total:
            self.t = 2.4
            self.timer.stop()
        self.update()

    def _acc(self, alpha):
        c = QColor(self.accent)
        c.setAlphaF(max(0.0, min(1.0, alpha)))
        return c

    def paintEvent(self, _e):
        from .toast_anim import compute, out_cubic, seg
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        W, H = self.width(), self.height()
        sw = min(W - 20, (H - 20) * 16 / 9)          # «pantalla» del juego 16:9
        sh = sw * 9 / 16
        sx, sy = (W - sw) / 2, (H - sh) / 2
        p.setPen(QPen(QColor("#2a3340"), 1))
        p.setBrush(QColor("#101722"))
        p.drawRoundedRect(QRectF(sx, sy, sw, sh), 10, 10)
        p.setPen(QColor("#3a4452"))
        f = QFont(self.font())
        f.setPointSizeF(10)
        p.setFont(f)
        p.drawText(QRectF(sx, sy, sw, sh), Qt.AlignmentFlag.AlignCenter, "pantalla del juego")

        has_badge = not self.badge.isNull()
        age, total = self.t, max(3.0, self.total)
        fr = compute(age, total, has_badge)
        if fr.alpha <= 0:
            p.end()
            return
        a = fr.alpha
        s = sh / 720.0 * 1.6
        h = 64 * s
        r = h / 2
        margin = 28 * s
        full_w = 440 * s
        w = h + (full_w - h) * fr.open
        pos = self.position
        left, center, top = "left" in pos, "center" in pos, "top" in pos
        x = sx + (margin if left else ((sw - full_w) / 2 if center else sw - margin - full_w))
        if not left and not center:
            x += full_w - w
        if center:
            x += (full_w - w) / 2
        y = sy + (margin if top else sh - margin - h)
        icon_left = left or center
        c = QPointF(x + r if icon_left else x + w - r, y + r)
        pill = QPainterPath()
        pill.addRoundedRect(QRectF(x, y, w, h), r, r)

        if fr.open > 0:
            p.setPen(Qt.PenStyle.NoPen)
            for i in (3, 2, 1):
                o = 2 * s * i
                p.setBrush(QColor(0, 0, 0, int(38 * a)))
                p.drawRoundedRect(QRectF(x - o / 2, y + o * 0.6, w + o, h + o * 0.6), r + o, r + o)
            p.setBrush(QColor(36, 37, 41, int(238 * a)))
            p.drawPath(pill)
            p.save()
            p.setClipPath(pill)
            p.fillRect(QRectF(x, y, w, r), QColor(255, 255, 255, int(16 * a)))
            if 0 < fr.shine < 1:
                from PySide6.QtGui import QLinearGradient
                bw, bx = 70 * s, x + r * 0.5 + (w - r) * fr.shine
                g = QLinearGradient(bx - bw, 0, bx + bw, 0)
                g.setColorAt(0, QColor(255, 255, 255, 0))
                g.setColorAt(0.5, QColor(255, 255, 255, int(46 * a)))
                g.setColorAt(1, QColor(255, 255, 255, 0))
                p.fillRect(QRectF(max(bx - bw, x + r * 0.45), y, min(2 * bw, x + w - r * 0.45 - max(bx - bw, x + r * 0.45)), h), g)
            p.restore()
            glow = 0.16 + 0.55 * (1 - seg(age, 0.75, 1.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(self._acc(glow * 0.45 * a), 3 * s))
            p.drawRoundedRect(QRectF(x - 1.5 * s, y - 1.5 * s, w + 3 * s, h + 3 * s), r + 1.5 * s, r + 1.5 * s)
            p.setPen(QPen(QColor(112, 114, 120, int(210 * a)), 1.6 * s))
            p.drawPath(pill)

        base = r - 5 * s
        br = base * fr.circle
        p.setBrush(Qt.BrushStyle.NoBrush)
        for wv in (fr.wave, fr.wave2):
            if 0 < wv < 1:
                e = out_cubic(wv)
                p.setPen(QPen(self._acc((1 - wv) ** 2 * 0.85 * a), (3.5 * (1 - wv) + 1) * s))
                p.drawEllipse(c, base * (1 + 1.5 * e), base * (1 + 1.5 * e))
        if 0 < fr.sparks < 1:
            e, fade = out_cubic(fr.sparks), 1 - fr.sparks
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(12):
                ang = 0.35 + i * 0.5235988
                d = base * (1.05 + (1.4 + 0.35 * (i % 3)) * e)
                q = QPointF(c.x() + math.cos(ang) * d, c.y() + math.sin(ang) * d)
                sz = (2.2 + i % 2) * s * (0.4 + 0.6 * fade)
                p.setBrush(QColor(255, 255, 255, int(220 * fade * a)) if i % 2 else self._acc(fade * a))
                p.drawPolygon(QPolygonF([QPointF(q.x(), q.y() - sz * 1.6), QPointF(q.x() + sz, q.y()),
                                         QPointF(q.x(), q.y() + sz * 1.6), QPointF(q.x() - sz, q.y())]))
        if br > 0.5:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(14, 14, 16, int(255 * a)))
            p.drawEllipse(c, br + 3 * s, br + 3 * s)
            rr = br + 1.2 * s
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(64, 66, 72, int(255 * a)), 3.2 * s))
            p.drawEllipse(c, rr, rr)
            box = QRectF(c.x() - rr, c.y() - rr, 2 * rr, 2 * rr)
            for i in range(2):
                a0 = fr.ring + math.pi * i
                pen = QPen(self._acc((0.55 if i else 1.0) * a), 3.2 * s)
                pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                p.setPen(pen)
                p.drawArc(box, int(-math.degrees(a0) * 16), int(-math.degrees(1.25) * 16))
            p.setPen(QPen(QColor(14, 14, 16, int(255 * a)), 2.4 * s))
            for i in range(4):
                ang = math.pi / 4 + math.pi / 2 * i
                dx, dy = math.cos(ang), math.sin(ang)
                p.drawLine(QPointF(c.x() + dx * (rr - 2.6 * s), c.y() + dy * (rr - 2.6 * s)),
                           QPointF(c.x() + dx * (rr + 2.6 * s), c.y() + dy * (rr + 2.6 * s)))
            ir, sq = br - 3 * s, fr.squash
            if ir > 1 and sq > 0.03:
                p.setPen(Qt.PenStyle.NoPen)
                if fr.face == 0 and has_badge:
                    clip = QPainterPath()
                    clip.addEllipse(c, ir * sq, ir)
                    p.save()
                    p.setClipPath(clip)
                    p.setOpacity(a)
                    p.drawPixmap(QRectF(c.x() - ir * sq, c.y() - ir, 2 * ir * sq, 2 * ir), self.badge,
                                 QRectF(self.badge.rect()))
                    p.restore()
                else:
                    p.setBrush(QColor(40, 42, 47, int(255 * a)))
                    p.drawEllipse(c, ir * sq, ir)
                    p.setBrush(QColor(54, 56, 62, int(255 * a)))
                    p.drawEllipse(QPointF(c.x(), c.y() - ir * 0.10), ir * 0.84 * sq, ir * 0.84)
                    white = QColor(238, 238, 240, int(255 * a))
                    cup, handles, rects = _trophy_polys(c.x(), c.y(), ir * 0.95, sq)
                    p.setBrush(white)
                    p.drawPolygon(QPolygonF(cup))
                    for rc in rects:
                        p.drawRect(rc)
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(white, max(1.0, 0.09 * ir * 0.95) * sq + 0.5))
                    for hd in handles:
                        p.drawPolyline(QPolygonF(hd))

        if fr.open >= 0.5 and (fr.title_a > 0 or fr.label_a > 0):
            tx = x + h + 12 * s if icon_left else x + 24 * s
            tmax = w - h - 36 * s
            p.setClipRect(QRectF(tx - 2 * s, y, tmax, h))
            f1 = QFont(self.font())
            f1.setPixelSize(max(8, int(15 * s)))
            p.setFont(f1)
            p.setPen(self._acc(fr.title_a * a))
            p.drawText(QPointF(tx - (1 - fr.title_in) * 18 * s, y + 10 * s + f1.pixelSize()), self.title)
            f2 = QFont(self.font())
            f2.setPixelSize(max(9, int(21 * s)))
            p.setFont(f2)
            p.setPen(QColor(240, 240, 242, int(255 * fr.label_a * a)))
            p.drawText(QPointF(tx - (1 - fr.label_in) * 26 * s, y + 29 * s + f2.pixelSize()),
                       f"{round(20 * fr.count)}G - Primer vuelo")
        p.end()


class ProfilePage(QWidget):
    changed = Signal()

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.profile = Profile.load()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        sc.setWidget(body)
        outer.addWidget(sc)
        v = QVBoxLayout(body)
        v.setContentsMargins(36, 6, 36, 24)
        v.setSpacing(14)

        # ---------------- tarjeta de jugador
        card = QFrame()
        card.setObjectName("Card")
        ch = QHBoxLayout(card)
        ch.setContentsMargins(22, 20, 22, 20)
        ch.setSpacing(20)
        self.avatar_lbl = QLabel()
        self.avatar_lbl.setFixedSize(112, 112)
        ch.addWidget(self.avatar_lbl, 0, Qt.AlignmentFlag.AlignTop)
        info = QVBoxLayout()
        info.addWidget(label("GAMERTAG", "Section"))
        self.tag = QLineEdit(self.profile.gamertag)
        self.tag.setMaxLength(15)
        self.tag.setPlaceholderText("Hasta 15 letras, números o espacios")
        self.tag.setStyleSheet("font-size: 20px; font-weight: 700;")
        self.tag.textEdited.connect(self._tag_edited)
        info.addWidget(self.tag)
        self.tag_hint = label("Los juegos lo muestran como tu nombre de jugador.", "Hint", wrap=True)
        info.addWidget(self.tag_hint)
        self.live = QCheckBox("Conectado a Xbox Live (simulado)")
        self.live.setChecked(self.profile.live)
        self.live.toggled.connect(self._save)
        info.addWidget(self.live)
        info.addWidget(label("El juego cree que hay una sesión de Xbox Live con privilegios online y red "
                             "conectada. Sirve para juegos (arcade y otros) que exigen «estar en Live» para "
                             "abrir menús o modos. No hay servidores: el juego online real no funcionará y "
                             "algún juego podría esperar una conexión que no llega; si pasa, desactívalo.",
                             "Hint", wrap=True))
        ch.addLayout(info, 1)
        v.addWidget(card)

        # ---------------- imagen de jugador
        v.addWidget(label("IMAGEN DE JUGADOR", "Section"))
        grid = QGridLayout()
        grid.setSpacing(10)
        self.av_group = QButtonGroup(self)
        for i in range(len(GEN_AVATARS)):
            b = QPushButton()
            b.setCheckable(True)
            b.setProperty("toggle", True)
            b.setFixedSize(72, 72)
            b.setIcon(generated_avatar(i, 64))
            b.setIconSize(b.size() * 0.86)
            b.clicked.connect(lambda _c=False, n=i: self._pick_generated(n))
            self.av_group.addButton(b, i)
            grid.addWidget(b, 0, i)
        v.addLayout(grid)
        row = QHBoxLayout()
        own = QPushButton("🖼  Usar una imagen propia…")
        own.clicked.connect(self._pick_file)
        row.addWidget(own)
        row.addWidget(label("PNG o JPG; se recorta en cuadrado.", "Hint"))
        row.addStretch(1)
        v.addLayout(row)

        # ---------------- notificación de logros
        v.addWidget(label("NOTIFICACIÓN DE LOGROS", "Section"))
        pos_row = QGridLayout()
        pos_row.setSpacing(8)
        self.pos_group = QButtonGroup(self)
        for i, (key, text) in enumerate(TOAST_POSITIONS):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("toggle", True)
            b.setProperty("toastpos", key)
            b.setChecked(key == self.profile.toast_position)
            b.clicked.connect(self._pos_changed)
            self.pos_group.addButton(b)
            pos_row.addWidget(b, 0 if key.startswith("top") else 1, i % 3)
        v.addLayout(pos_row)
        opts = QHBoxLayout()
        opts.addWidget(QLabel("Duración"))
        self.secs = QDoubleSpinBox()
        self.secs.setRange(2.0, 15.0)
        self.secs.setSingleStep(0.5)
        self.secs.setSuffix(" s")
        self.secs.setValue(float(self.profile.toast_seconds))
        self.secs.valueChanged.connect(self._save)
        opts.addWidget(self.secs)
        opts.addSpacing(16)
        opts.addWidget(QLabel("Título"))
        self.ttl = QLineEdit(self.profile.toast_title)
        self.ttl.setMaxLength(40)
        self.ttl.editingFinished.connect(self._save)
        opts.addWidget(self.ttl, 1)
        test = QPushButton("▶  Probar")
        test.clicked.connect(self.test_toast)
        opts.addWidget(test)
        v.addLayout(opts)
        snd = QHBoxLayout()
        snd.addWidget(QLabel("Sonido"))
        self.snd_group = QButtonGroup(self)
        for key, text in (("reforge", "ReForge"), ("custom", "Personalizado"), ("none", "Sin sonido")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("toggle", True)
            b.setProperty("snd", key)
            b.setChecked(self.profile.toast_sound == key)
            b.clicked.connect(self._sound_changed)
            self.snd_group.addButton(b)
            snd.addWidget(b)
        pick = QPushButton("🎵  Elegir archivo…")
        pick.setToolTip("WAV, MP3, OGG… Se recorta el silencio inicial y se normaliza el volumen.")
        pick.clicked.connect(self._pick_sound)
        snd.addWidget(pick)
        snd.addSpacing(12)
        snd.addWidget(QLabel("Volumen"))
        from PySide6.QtWidgets import QSlider
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(int(self.profile.toast_volume))
        self.vol.setFixedWidth(140)
        self.vol.sliderReleased.connect(self._save)
        snd.addWidget(self.vol)
        snd.addStretch(1)
        v.addLayout(snd)
        self.snd_hint = label("", "Hint", wrap=True)
        v.addWidget(self.snd_hint)
        bdg = QHBoxLayout()
        bdg.addWidget(QLabel("Logo"))
        self.badge_group = QButtonGroup(self)
        for key, text in (("custom", "Mi logo"), ("none", "Sin logo")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("toggle", True)
            b.setProperty("badge", key)
            b.clicked.connect(self._badge_changed)
            self.badge_group.addButton(b)
            bdg.addWidget(b)
        pickb = QPushButton("🖼  Elegir imagen…")
        pickb.setToolTip("PNG, JPG o BMP. Se quita el fondo liso o de cuadros y se centra en un círculo.")
        pickb.clicked.connect(self._pick_badge)
        bdg.addWidget(pickb)
        self.badge_lbl = QLabel()
        self.badge_lbl.setFixedSize(40, 40)
        bdg.addWidget(self.badge_lbl)
        bdg.addStretch(1)
        v.addLayout(bdg)
        self.badge_hint = label("", "Hint", wrap=True)
        v.addWidget(self.badge_hint)
        self.preview = ToastPreview()
        v.addWidget(self.preview)
        v.addWidget(label("Animación de ReForge: la insignia aparece con una onda, la cápsula se despliega con "
                          "chispas, los G cuentan hasta el valor del logro y la insignia alterna tu logo con el icono "
                          "del logro (o un trofeo si el juego no trae icono). F7 dentro del juego abre la lista de "
                          "logros de rexglue. Se aplica a los juegos al recompilarlos con esta versión.",
                          "Hint", wrap=True))
        v.addStretch(1)
        self._refresh()

    # ---------------------------------------------------------------- acciones
    def _tag_edited(self, text):
        ok = valid_gamertag(text)
        self.tag_hint.setText("Los juegos lo muestran como tu nombre de jugador." if ok else
                              "Solo letras sin tildes, números y espacios (máximo 15).")
        if ok:
            self._save()

    def _pick_generated(self, n):
        self.profile.avatar = f"gen:{n}"
        self._save()

    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Imagen de jugador", "", "Imágenes (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        if QPixmap(path).isNull():
            QMessageBox.warning(self, "Imagen", "No se pudo abrir esa imagen.")
            return
        self.profile.avatar = import_avatar(path)
        self._save()

    def _pos_changed(self):
        b = self.pos_group.checkedButton()
        if b:
            self.profile.toast_position = b.property("toastpos")
        self._save()
        self.preview.play()

    def _sound_changed(self):
        b = self.snd_group.checkedButton()
        if b:
            if b.property("snd") == "custom":
                from .sound import custom_sound_path
                if not os.path.isfile(custom_sound_path()):
                    return self._pick_sound()
            self.profile.toast_sound = b.property("snd")
        self._save()

    def _pick_sound(self):
        path, _ = QFileDialog.getOpenFileName(self, "Sonido del logro", "",
                                              "Audio (*.wav *.mp3 *.ogg *.flac *.m4a *.wma);;Todos (*.*)")
        if not path:
            self._refresh()
            return
        from .sound import import_sound
        try:
            import_sound(path)
        except Exception as e:      # noqa: BLE001
            QMessageBox.warning(self, "Sonido", str(e))
            self._refresh()
            return
        self.profile.toast_sound = "custom"
        self._save()
        self.test_toast()

    def _badge_changed(self):
        b = self.badge_group.checkedButton()
        if b:
            from .badge import badge_path
            if b.property("badge") == "custom" and not os.path.isfile(badge_path()):
                return self._pick_badge()
            self.profile.toast_badge = b.property("badge")
        self._save()
        self.preview.play()

    def _pick_badge(self):
        path, _ = QFileDialog.getOpenFileName(self, "Logo de los logros", "", "Imágenes (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            self._refresh()
            return
        from .badge import import_badge
        try:
            import_badge(path)
        except Exception as e:      # noqa: BLE001
            QMessageBox.warning(self, "Logo", str(e))
            self._refresh()
            return
        self.profile.toast_badge = "custom"
        self._save()
        self.preview.play()

    def test_toast(self):
        self.preview.play()
        self.play_sound()

    def play_sound(self):
        from .sound import sound_for_profile
        path = sound_for_profile(self.profile)
        if not path:
            return
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QSoundEffect
        except ImportError:
            return
        if not hasattr(self, "_effect"):
            self._effect = QSoundEffect(self)
        self._effect.stop()
        self._effect.setSource(QUrl.fromLocalFile(path))
        self._effect.setVolume(self.vol.value() / 100.0)
        self._effect.play()

    def _save(self, *_a):
        p = self.profile
        tag = clean_gamertag(self.tag.text())
        if tag:
            p.gamertag = tag
        p.live = self.live.isChecked()
        p.toast_seconds = float(self.secs.value())
        p.toast_title = self.ttl.text().strip() or "Logro desbloqueado"
        p.toast_volume = int(self.vol.value())
        try:
            p.accent = self.win.cfg_accent_hex()
        except Exception:      # noqa: BLE001
            pass
        p.save()
        self._refresh()
        self.changed.emit()

    def _refresh(self):
        p = self.profile
        if hasattr(self, "snd_group"):
            for b in self.snd_group.buttons():
                b.setChecked(b.property("snd") == p.toast_sound)
            from .sound import custom_sound_path
            self.snd_hint.setText({"reforge": "Timbre propio de ReForge.",
                                   "custom": "Tu sonido (" + os.path.basename(custom_sound_path()) + "), "
                                             "recortado y normalizado.",
                                   "none": "Las notificaciones aparecen sin sonido."}.get(p.toast_sound, "") +
                                  " Suena en el juego justo cuando aparece la notificación.")
        if hasattr(self, "badge_group"):
            from .badge import badge_for_profile
            bp = badge_for_profile(p)
            for b in self.badge_group.buttons():
                b.setChecked(b.property("badge") == ("custom" if bp else "none"))
            pm = QPixmap(bp) if bp else QPixmap()
            self.preview.badge = pm
            self.badge_lbl.setPixmap(pm.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation) if bp else QPixmap())
            self.badge_hint.setText("Tu logo alterna con el icono del logro dentro de la insignia." if bp else
                                    "Sin logo: la insignia muestra el icono del logro o un trofeo.")
        self.avatar_lbl.setPixmap(avatar_pixmap(p, 112))
        for b in self.av_group.buttons():
            b.setChecked(p.avatar == f"gen:{self.av_group.id(b)}")
        self.preview.position = p.toast_position
        self.preview.title = p.toast_title
        self.preview.accent = QColor("#" + p.accent)
        self.preview.total = float(p.toast_seconds)
        self.preview.update()

    def refresh(self):
        self.profile = Profile.load()
        self._refresh()


class ProfileChip(QPushButton):
    """Imagen + Gamertag en la barra lateral (abre la página Perfil)."""

    def __init__(self):
        super().__init__()
        self.setObjectName("ProfileChip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 6, 12, 6)
        lay.setSpacing(10)
        self.pic = QLabel()
        self.pic.setFixedSize(36, 36)
        lay.addWidget(self.pic)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.name = QLabel()
        self.name.setStyleSheet("font-weight: 700;")
        self.state = QLabel()
        self.state.setStyleSheet("font-size: 11px; color: #8b96a5;")
        col.addWidget(self.name)
        col.addWidget(self.state)
        lay.addLayout(col, 1)
        self.setMinimumHeight(52)
        self.refresh()

    def refresh(self):
        p = Profile.load()
        self.pic.setPixmap(avatar_pixmap(p, 36))
        self.name.setText(p.gamertag)
        self.state.setText("● Xbox Live (simulado)" if p.live else "○ Perfil local")
        self.setToolTip("Perfil de jugador")
