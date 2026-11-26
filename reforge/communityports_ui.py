"""Diálogo «Ports de la comunidad»: un PUENTE a puertos nativos de otros autores.

ReForge no recompila estos puertos ni incluye archivos de juego: solo te deja agregarlos desde su GitHub y abrir
su RUNTIME ORIGINAL (su .exe o el lanzador que indique el autor), tal cual. Cada puerto trae su propio runtime,
su propio menú en el juego y su propio sistema de logros (del mismo juego de Xbox 360, mismo Title ID)."""
import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from . import communityports as cp
from .widgets import fit_to_screen, label


class CommunityPortsDialog(QDialog):
    """Puente a los puertos de la comunidad: agrega su GitHub y abre su runtime original."""

    def __init__(self, parent=None, lib=None):
        super().__init__(parent)
        self.lib = lib
        self.setWindowTitle("Ports de la comunidad")
        self.setMinimumWidth(640)
        outer = QVBoxLayout(self)
        outer.addWidget(label("Puente a puertos nativos de otros autores. Agrega el puerto desde su GitHub y abre "
                              "su runtime ORIGINAL (su .exe o lanzador, tal cual lo dejó el autor). Cada puerto "
                              "trae su propio runtime, su menú en el juego y sus logros (del mismo juego, mismo "
                              "Title ID). ReForge no los recompila ni incluye archivos de juego.", "Hint",
                              wrap=True))
        add = QHBoxLayout()
        add_btn = QPushButton("➕  Agregar puerto desde GitHub…")
        add_btn.setObjectName("Primary")
        add_btn.clicked.connect(self._add)
        add.addWidget(add_btn)
        add.addStretch(1)
        outer.addLayout(add)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self.rows = QVBoxLayout(inner)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self._fill()
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        outer.addWidget(bb)
        fit_to_screen(self, 680, 620, limitar=True)

    def _fill(self):
        for port in cp.all_ports():
            self.rows.addWidget(self._card(port))
        self.rows.addStretch(1)

    def _card(self, port):
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.addWidget(label(port.name, "H3"))
        meta = f"Autor: {port.author} · Motor: {port.engine}"
        if port.title_id:
            meta += f" · Title ID: {port.title_id}"
        v.addWidget(label(meta, "Hint"))
        if getattr(port, "notes", ""):
            v.addWidget(label(port.notes, "Hint", wrap=True))
        if getattr(port, "menu_hint", ""):
            v.addWidget(label("🎮  " + port.menu_hint, "Hint", wrap=True))
        v.addWidget(self._status_label(port))
        row = QHBoxLayout()
        if port.repo:
            gh = QPushButton("🌐  GitHub")
            gh.clicked.connect(lambda _=False, p=port: self._open(p.repo))
            row.addWidget(gh)
        pick = QPushButton("📂  Elegir runtime…")
        pick.setToolTip("Apunta al .exe o lanzador original del puerto (el que deja su instalador)")
        pick.clicked.connect(lambda _=False, p=port: self._pick(p))
        row.addWidget(pick)
        openb = QPushButton("▶  Abrir runtime original")
        openb.clicked.connect(lambda _=False, p=port: self._open_runtime(p))
        row.addWidget(openb)
        if cp.is_user_port(port):
            rm = QPushButton("🗑")
            rm.setToolTip("Quitar este puerto de la lista")
            rm.clicked.connect(lambda _=False, p=port: self._remove(p))
            row.addWidget(rm)
        row.addStretch(1)
        v.addLayout(row)
        return card

    def _status_label(self, port):
        exe = cp.saved_exe(port) or cp.locate_built_exe(port)
        if exe:
            txt = f"✅ Runtime listo: {exe}"
        elif port.repo:
            txt = "Aún no has elegido su runtime. Obtén el puerto de su GitHub y pulsa «Elegir runtime…»."
        else:
            txt = "Pulsa «Elegir runtime…» y apunta a su .exe o lanzador."
        return label(txt, "Hint", wrap=True)

    # ---------------------------------------------------------------- acciones
    def _open(self, url):
        try:
            QDesktopServices.openUrl(QUrl(url))
        except Exception:      # noqa: BLE001
            pass

    def _pick(self, port):
        from PySide6.QtWidgets import QFileDialog
        exe, _ = QFileDialog.getOpenFileName(self, f"Elige el runtime original de «{port.name}»", "",
                                             "Ejecutable o lanzador (*.exe *.bat *.cmd);;Todos (*.*)")
        if not exe:
            return
        cp.remember_exe(port, exe)
        self._open_runtime(port, exe)

    def _open_runtime(self, port, path=""):
        from PySide6.QtWidgets import QMessageBox
        ok, msg = cp.open_original(port, path)
        if not ok:
            QMessageBox.warning(self, "Ports de la comunidad", msg)
            self._refresh()
            return
        hint = "\n\n" + port.menu_hint if getattr(port, "menu_hint", "") else ""
        QMessageBox.information(self, "Ports de la comunidad", msg + hint)
        self.accept()

    def _add(self):
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        repo, ok = QInputDialog.getText(self, "Agregar puerto", "URL del GitHub del puerto "
                                        "(p. ej. https://github.com/autor/proyecto):")
        if not ok or not repo.strip():
            return
        repo = repo.strip()
        guess = repo.rstrip("/").split("/")[-1].replace("-", " ").replace("_", " ").title()
        name, ok = QInputDialog.getText(self, "Agregar puerto", "Nombre del juego/puerto:", text=guess)
        if not ok or not name.strip():
            return
        tid, _ = QInputDialog.getText(self, "Agregar puerto", "Title ID (opcional, 8 hex del juego de Xbox 360):")
        cp.add_user_port(name.strip(), repo=repo, title_id=(tid or "").strip())
        self._refresh()
        QMessageBox.information(self, "Ports de la comunidad",
                               f"«{name.strip()}» agregado. Obtén su runtime de GitHub, pulsa «Elegir runtime…» y "
                               "luego «Abrir runtime original».")

    def _remove(self, port):
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(self, "Quitar puerto", f"¿Quitar «{port.name}» de la lista?") \
                == QMessageBox.StandardButton.Yes:
            cp.remove_user_port(port.id)
            self._refresh()

    def _refresh(self):
        try:
            while self.rows.count():
                item = self.rows.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
            self._fill()
        except Exception:      # noqa: BLE001
            pass


def open_dialog(parent=None, lib=None):
    CommunityPortsDialog(parent, lib).exec()
