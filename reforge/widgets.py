"""Componentes visuales: logo, tiles, seguimiento de pasos, consola de log."""
import html
import math
import os

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget)


def current_accent():
    return QApplication.instance().property("accent") or "#19d3a2"


def paint_logo(p, rect, accent):
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    cx, cy = rect.center().x(), rect.center().y()
    r = min(rect.width(), rect.height()) / 2
    hexa = QPolygonF([QPointF(cx + r * math.cos(math.radians(60 * i - 90)),
                              cy + r * math.sin(math.radians(60 * i - 90))) for i in range(6)])
    g = QLinearGradient(rect.topLeft(), rect.bottomRight())
    g.setColorAt(0, QColor(accent).lighter(120))
    g.setColorAt(1, QColor(accent).darker(220))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawPolygon(hexa)
    # anillo interior
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(255, 255, 255, 70), max(1.0, r * 0.06)))
    ri = r * 0.78
    p.drawPolygon(QPolygonF([QPointF(cx + ri * math.cos(math.radians(60 * i - 90)),
                                     cy + ri * math.sin(math.radians(60 * i - 90))) for i in range(6)]))
    f = QFont("Segoe UI", 10)
    f.setPixelSize(max(8, int(r * 0.95)))
    f.setWeight(QFont.Weight.Black)
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(rect), Qt.AlignmentFlag.AlignCenter, "R")


class Logo(QWidget):
    def __init__(self, size=46, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _e):
        p = QPainter(self)
        paint_logo(p, QRectF(self.rect()).adjusted(1, 1, -1, -1), current_accent())


def logo_pixmap(size, accent):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    paint_logo(p, QRectF(0, 0, size, size).adjusted(2, 2, -2, -2), accent)
    p.end()
    return pm


def label(text, obj=None, wrap=False):
    l = QLabel(text)
    if obj:
        l.setObjectName(obj)
    l.setWordWrap(wrap)
    return l


def repolish(w):
    for x in [w] + w.findChildren(QWidget):
        x.style().unpolish(x)
        x.style().polish(x)


class Tile(QFrame):
    """Tile estilo dashboard de consola: navegable con teclado (flechas/Enter)."""
    clicked = Signal()

    def __init__(self, glyph, title, subtitle="", hero=False, w=250, h=170, parent=None):
        super().__init__(parent)
        self.setObjectName("Tile")
        self.setProperty("hero", hero)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(w, h)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.addWidget(label(glyph, "TileGlyph"))
        lay.addStretch(1)
        lay.addWidget(label(title, "TileTitle"))
        if subtitle:
            lay.addWidget(label(subtitle, "TileSub", wrap=True))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.focusNextChild()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.focusPreviousChild()
        else:
            super().keyPressEvent(e)


class StepPill(QFrame):
    GLYPH = {"done": "✓", "error": "✕", "skipped": "–"}

    def __init__(self, number, title):
        super().__init__()
        self.setObjectName("StepPill")
        self.number = str(number)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 10, 6, 9)
        v.setSpacing(6)
        self.num = label(self.number, "StepNum")
        self.num.setFixedSize(26, 26)
        self.num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.num, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = label(title, "StepTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.title)
        self.set_state("pending")

    def set_state(self, state):
        self.setProperty("state", state)
        self.num.setText(self.GLYPH.get(state, self.number))
        repolish(self)


class StepTracker(QWidget):
    def __init__(self, titles):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.pills = []
        for i, t in enumerate(titles, 1):
            p = StepPill(i, t)
            self.pills.append(p)
            h.addWidget(p, 1)

    def set_state(self, i, state):
        if 0 <= i < len(self.pills):
            self.pills[i].set_state(state)

    def reset(self, enabled):
        for p, on in zip(self.pills, enabled):
            p.set_state("pending" if on else "off")


class LogView(QPlainTextEdit):
    """Consola coloreada con escritura por lotes (soporta miles de líneas/seg)."""
    COLORS = {"info": "#c9d1d9", "head": "#ffffff", "ok": "#3fb950", "warn": "#e3b341",
              "err": "#ff7b72", "dim": "#5c6673"}

    def __init__(self):
        super().__init__()
        self.setObjectName("Log")
        self.setReadOnly(True)
        self.setMaximumBlockCount(30000)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._pending = []
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._flush)
        self._timer.start()
        self.errors = 0
        self.warnings = 0

    def write(self, text, level="info"):
        if level == "err":
            self.errors += 1
        elif level == "warn":
            self.warnings += 1
        color = current_accent() if level == "cmd" else self.COLORS.get(level, "#c9d1d9")
        weight = "font-weight:700;" if level in ("head", "cmd") else ""
        for line in str(text).split("\n"):
            self._pending.append(f'<span style="color:{color};{weight}white-space:pre">'
                                 f'{html.escape(line)}</span>')

    # Máximo de líneas que se vuelcan en un solo tick. Un appendHtml con miles de líneas de golpe bloquea el
    # hilo de la interfaz varios segundos (o minutos si son decenas de miles): la ventana queda «No responde».
    # Volcando por trozos acotados —y dejando el resto para los siguientes ticks (80 ms)— la UI nunca se
    # congela aunque una compilación haya soltado un diluvio de líneas que se acumularon en el buffer.
    _MAX_FLUSH = 600

    def _flush(self):
        if not self._pending:
            return
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        if len(self._pending) > self._MAX_FLUSH:
            chunk, self._pending = self._pending[:self._MAX_FLUSH], self._pending[self._MAX_FLUSH:]
        else:
            chunk, self._pending = self._pending, []
        self.appendHtml("<br>".join(chunk))
        if at_bottom:
            bar.setValue(bar.maximum())

    def clear_log(self):
        self._pending = []
        self.errors = self.warnings = 0
        self.clear()


class PathField(QWidget):
    """Campo de texto + botón «Examinar»."""
    changed = Signal(str)

    def __init__(self, kind="file", filt="", placeholder=""):
        super().__init__()
        self.kind, self.filt = kind, filt
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.textChanged.connect(self.changed)
        b = QPushButton("…")
        b.setFixedWidth(40)
        b.setToolTip("Examinar")
        b.clicked.connect(self.browse)
        h.addWidget(self.edit, 1)
        h.addWidget(b)

    def text(self):
        return self.edit.text().strip()

    def setText(self, t):
        self.edit.setText(t or "")

    def browse(self):
        start = self.text()
        if self.kind == "dir":
            p = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta", start)
        elif self.kind == "save":
            p, _ = QFileDialog.getSaveFileName(self, "Guardar como", start, self.filt)
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Seleccionar archivo", start, self.filt)
        if p:
            self.setText(p)


def fit_to_screen(dialog, ancho, alto, limitar=False):
    """Abre el diálogo del tamaño pedido sin salirse nunca de la pantalla.

    Una pantalla de 1080 píxeles de alto (o cualquiera con el escalado de Windows subido) deja menos
    sitio del que parece, y un diálogo que pide más altura de la que hay se abre con los botones de
    Guardar y Cancelar por debajo del borde, fuera del alcance del ratón. `limitar` pone además un
    máximo: solo para diálogos cuyo contenido va dentro de una zona con barra de desplazamiento, donde
    recortar la altura no esconde nada.
    """
    from PySide6.QtWidgets import QApplication
    try:
        pantalla = dialog.screen() or QApplication.primaryScreen()
        libre = pantalla.availableGeometry()
        ancho = min(ancho, libre.width() - 60)
        alto = min(alto, libre.height() - 60)
        if limitar:
            dialog.setMaximumHeight(libre.height() - 40)
    except Exception:      # noqa: BLE001
        pass
    dialog.resize(max(520, ancho), max(380, alto))


# ---------------------------------------------------------------- carátulas de juego
_COVER_CACHE = {}


def _cover_bytes(root, name):
    """PNG de la carátula: la imagen real del juego (del XEX, cacheada en reforge_icon.png) o, si no la
    hay, una generada a partir del nombre. Nunca lanza: una ficha sin carátula no debe romper la lista."""
    try:
        png = os.path.join(root, "reforge_icon.png")
        if os.path.isfile(png):
            with open(png, "rb") as f:
                return f.read()
    except OSError:
        pass
    try:
        from . import gameicon
        xex = os.path.join(root, "assets", "default.xex")
        if os.path.isfile(xex):
            data, _src = gameicon.title_png(xex)
            if data:
                try:
                    with open(os.path.join(root, "reforge_icon.png"), "wb") as f:
                        f.write(data)      # cachea para la próxima vez
                except OSError:
                    pass
                return data
    except Exception:      # noqa: BLE001
        pass
    try:
        from . import gameicon
        return gameicon.fallback_png(name or "ReForge")
    except Exception:      # noqa: BLE001
        return b""


def cover_pixmap(root, name, size, radius=12):
    """QPixmap cuadrado con la carátula del juego, escalada a `size` y con esquinas redondeadas."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QBrush, QImage, QPainter, QPainterPath, QPixmap

    key = (os.path.abspath(root), size, radius)
    if key in _COVER_CACHE:
        return _COVER_CACHE[key]
    data = _cover_bytes(root, name)
    src = QPixmap()
    if data:
        img = QImage()
        img.loadFromData(data)
        if not img.isNull():
            src = QPixmap.fromImage(img)
    if src.isNull():
        src = logo_pixmap(size, current_accent())
    scaled = src.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(path)
    x = (size - scaled.width()) // 2
    y = (size - scaled.height()) // 2
    p.drawPixmap(x, y, scaled)
    # borde sutil
    p.setClipping(False)
    from PySide6.QtGui import QColor, QPen
    p.setPen(QPen(QColor(255, 255, 255, 22), 1))
    p.setBrush(QBrush(Qt.BrushStyle.NoBrush))
    p.drawRoundedRect(QRectF(0.5, 0.5, size - 1, size - 1), radius, radius)
    p.end()
    _COVER_CACHE[key] = out
    return out


class GameCard(QFrame):
    """Ficha de juego con carátula para «Recientes» del Inicio: navegable y clicable como un Tile."""
    clicked = Signal()

    def __init__(self, root, name, subtitle="", w=210, h=116, parent=None):
        super().__init__(parent)
        self.setObjectName("Tile")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(w, h)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 14, 16, 14)
        lay.setSpacing(14)
        cover = QLabel()
        cover.setPixmap(cover_pixmap(root, name, 62))
        cover.setFixedSize(62, 62)
        lay.addWidget(cover, 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(3)
        col.addStretch(1)
        t = label(name, "TileTitle")
        t.setToolTip(name)
        col.addWidget(t)
        if subtitle:
            col.addWidget(label(subtitle, "TileSub", wrap=True))
        col.addStretch(1)
        lay.addLayout(col, 1)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.focusNextChild()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.focusPreviousChild()
        else:
            super().keyPressEvent(e)
