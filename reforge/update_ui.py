"""Ventana de actualización de ReForge Studio: pulida, con el logo, la versión que tienes frente a la de
GitHub y las novedades renderizadas. Evita tener que entrar a GitHub y actualizar a mano con el instalador.

El algoritmo de «hay versión nueva» vive en update.py (consulta GitHub, compara versiones y verifica el
SHA-256). Aquí solo está la presentación y la orquestación de descargar → instalar.
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QTextBrowser, QVBoxLayout, QWidget)

from . import update as upd
from .widgets import current_accent, label, logo_pixmap

# Resultado de la ventana de oferta
ACTUALIZAR, MAS_TARDE, OMITIR = "actualizar", "mas_tarde", "omitir"


def _pill(texto, valor, accent, fuerte=False):
    """Una «pastilla» versión: etiqueta pequeña arriba, versión grande abajo."""
    w = QFrame()
    w.setObjectName("VerPill")
    col = (f"background:{accent}; color:#04130e;" if fuerte
           else "background:#141a21; color:#e7ebef; border:1px solid #232c36;")
    w.setStyleSheet(f"#VerPill {{ {col} border-radius:10px; }}")
    v = QVBoxLayout(w)
    v.setContentsMargins(16, 8, 16, 9)
    v.setSpacing(0)
    cap = QLabel(texto)
    cap.setStyleSheet("font-size:10px; font-weight:700; letter-spacing:2px; background:transparent;"
                      + ("color:#06321f;" if fuerte else "color:#8b97a5;"))
    val = QLabel(valor)
    val.setStyleSheet("font-size:20px; font-weight:800; background:transparent;"
                      + ("color:#04130e;" if fuerte else "color:#ffffff;"))
    v.addWidget(cap)
    v.addWidget(val)
    return w


def _notes_html_css(accent):
    return f"""
    QTextBrowser {{ background:#0e1216; border:1px solid #1d242d; border-radius:10px;
                    color:#c7ced6; padding:10px 14px; font-size:13px; }}
    """


class UpdateDialog(QDialog):
    """Ofrece instalar la versión nueva, mostrando las novedades. `accion` queda en ACTUALIZAR/MAS_TARDE/OMITIR."""

    def __init__(self, parent, info, current):
        super().__init__(parent)
        self.info = info
        self.accion = MAS_TARDE
        accent = current_accent()
        self.setWindowTitle("Actualización de ReForge Studio")
        self.setWindowIcon(QIcon(logo_pixmap(256, accent)))
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(16)

        # --- Encabezado: logo + título ---
        head = QHBoxLayout()
        head.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(56, accent))
        logo.setFixedSize(56, 56)
        head.addWidget(logo)
        tit = QVBoxLayout()
        tit.setSpacing(2)
        t1 = QLabel("ReForge Studio")
        t1.setStyleSheet("font-size:21px; font-weight:800; color:#ffffff;")
        t2 = QLabel("Hay una actualización disponible")
        t2.setStyleSheet(f"font-size:13px; color:{accent}; font-weight:600;")
        tit.addWidget(t1)
        tit.addWidget(t2)
        head.addLayout(tit)
        head.addStretch(1)
        root.addLayout(head)

        # --- Comparación de versiones ---
        fecha = _fecha_corta(info.get("published") or info.get("date") or "")
        vers = QHBoxLayout()
        vers.setSpacing(10)
        vers.addWidget(_pill("VERSIÓN ACTUAL", f"v{current}", accent, fuerte=False))
        flecha = QLabel("→")
        flecha.setStyleSheet("font-size:22px; color:#5b6672; font-weight:800;")
        vers.addWidget(flecha)
        vers.addWidget(_pill("NUEVA VERSIÓN", f"v{info['version']}", accent, fuerte=True))
        if fecha:
            f = QLabel("publicada\n" + fecha)
            f.setStyleSheet("font-size:11px; color:#7c8894;")
            f.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            vers.addWidget(f)
        vers.addStretch(1)
        root.addLayout(vers)

        # --- Novedades ---
        root.addWidget(label("NOVEDADES DE ESTA VERSIÓN", "Section"))
        notas = QTextBrowser()
        notas.setOpenExternalLinks(True)
        notas.setStyleSheet(_notes_html_css(accent))
        texto = (info.get("notes") or "").strip()
        if texto:
            notas.setMarkdown(texto)
        else:
            notas.setPlainText("Sin notas para esta versión.")
        notas.setMinimumHeight(190)
        root.addWidget(notas, 1)

        # --- Botones ---
        botones = QHBoxLayout()
        b_omitir = QPushButton("Omitir esta versión")
        b_omitir.setCursor(Qt.CursorShape.PointingHandCursor)
        b_omitir.clicked.connect(lambda: self._fin(OMITIR))
        b_tarde = QPushButton("Más tarde")
        b_tarde.setCursor(Qt.CursorShape.PointingHandCursor)
        b_tarde.clicked.connect(lambda: self._fin(MAS_TARDE))
        b_ahora = QPushButton("⬇  Actualizar ahora")
        b_ahora.setObjectName("Primary")
        b_ahora.setCursor(Qt.CursorShape.PointingHandCursor)
        b_ahora.clicked.connect(lambda: self._fin(ACTUALIZAR))
        botones.addWidget(b_omitir)
        botones.addStretch(1)
        botones.addWidget(b_tarde)
        botones.addWidget(b_ahora)
        root.addLayout(botones)
        b_ahora.setDefault(True)

    def _fin(self, accion):
        self.accion = accion
        self.accept()


class DownloadDialog(QDialog):
    """Descarga el instalador con barra de progreso pulida y lo lanza. Cierra ReForge al terminar."""

    def __init__(self, parent, info, silent=False):
        super().__init__(parent)
        self.info = info
        self.silent = silent
        self.ruta = ""
        self.error = ""
        accent = current_accent()
        self.setWindowTitle("Actualizando ReForge Studio")
        self.setWindowIcon(QIcon(logo_pixmap(256, accent)))
        self.setMinimumWidth(460)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(48, accent))
        logo.setFixedSize(48, 48)
        head.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(f"Descargando la versión {info['version']}")
        t.setStyleSheet("font-size:16px; font-weight:700; color:#ffffff;")
        self.sub = QLabel("Preparando la descarga…")
        self.sub.setStyleSheet("font-size:12px; color:#8b97a5;")
        col.addWidget(t)
        col.addWidget(self.sub)
        head.addLayout(col)
        head.addStretch(1)
        root.addLayout(head)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        root.addWidget(self.bar)

        fila = QHBoxLayout()
        fila.addStretch(1)
        self.b_cancel = QPushButton("Cancelar")
        self.b_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        fila.addWidget(self.b_cancel)
        root.addLayout(fila)

        self._cancel = None
        self.b_cancel.clicked.connect(self._pedir_cancel)

    def _pedir_cancel(self):
        if self._cancel:
            self._cancel()
        self.reject()

    def start(self):
        """Arranca la descarga en segundo plano. Al terminar bien, instala y cierra la app."""
        from .runner import run_in_thread
        cfg = upd.load_config()

        def work(ctx):
            self.ruta = upd.download(
                self.info, progress=lambda d, t: ctx.progress(int(d * 1000 / max(1, t)), 1000),
                cancelled=ctx.cancelled, token=cfg.get("token") or "")

        def done(ok, err):
            if not ok:
                self.error = str(err)
                self.reject()
                return
            self.sub.setText("Descarga verificada. Abriendo el instalador…")
            upd.cleanup(keep=self.ruta)
            try:
                # En una actualización silenciosa (automática), reabrir ReForge solo al terminar,
                # salvo que el usuario lo haya desactivado. Así la versión nueva aparece sin abrirla a mano.
                relaunch = self.silent and cfg.get("auto_relaunch", True)
                upd.install(self.ruta, silent=self.silent, relaunch=relaunch)
            except upd.UpdateError as e:
                self.error = str(e)
                self.reject()
                return
            QApplication.quit()

        th = run_in_thread(work, done)
        self._cancel = th.cancel_event.set
        th.progress_signal.connect(self._avance)
        self.exec()

    def _avance(self, v, _m):
        self.bar.setValue(v)
        total = self.info.get("size") or 0
        if total:
            mb = total / 1e6
            self.sub.setText(f"{v / 10:.0f}%  ·  {mb:.0f} MB")


def offer(parent, info):
    """Muestra la ventana de oferta y actúa según la elección. Devuelve True si se lanzó la actualización."""
    cfg = upd.load_config()
    if cfg.get("auto_install"):
        return _descargar(parent, info, silent=True)
    dlg = UpdateDialog(parent, info, upd.current_version())
    dlg.exec()
    if dlg.accion == OMITIR:
        upd.save_config(skip=info["version"])
        return False
    if dlg.accion != ACTUALIZAR:
        return False
    return _descargar(parent, info, silent=False)


def _descargar(parent, info, silent):
    from PySide6.QtWidgets import QMessageBox
    dlg = DownloadDialog(parent, info, silent=silent)
    dlg.start()
    if dlg.error:
        QMessageBox.warning(parent, "Actualización", f"No se pudo actualizar: {dlg.error}")
        return False
    return True


def _fecha_corta(iso):
    """2026-11-21T18:57:31Z → 21/11/2026."""
    if not iso or len(iso) < 10:
        return ""
    try:
        y, m, d = iso[:10].split("-")
        return f"{d}/{m}/{y}"
    except ValueError:
        return ""
