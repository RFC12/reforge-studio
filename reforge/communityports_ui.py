"""Diálogo «Ports de la comunidad»: puertos nativos de otros autores (con su propio runtime). ReForge los
obtiene, los orquesta y envuelve el resultado con sus comodidades (lanzador, icono, Biblioteca)."""
import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from . import communityports as cp
from .widgets import fit_to_screen, label


class CommunityPortsDialog(QDialog):
    """Lista los puertos conocidos, su estado y las acciones para obtenerlos, construirlos y jugarlos."""

    def __init__(self, parent=None, lib=None):
        super().__init__(parent)
        self.lib = lib
        self.setWindowTitle("Ports de la comunidad")
        self.setMinimumWidth(640)
        outer = QVBoxLayout(self)
        outer.addWidget(label("Puertos nativos de otros autores, con su PROPIO runtime (resuelven cosas que la "
                              "recompilación interna no puede). ReForge los obtiene y envuelve el resultado con su "
                              "lanzador, su icono y la Biblioteca. Se construyen en tu PC desde tu copia legal del "
                              "juego; ReForge no incluye ningún archivo de juego.", "Hint", wrap=True))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self.rows = QVBoxLayout(inner)
        self.rows.setContentsMargins(0, 0, 0, 0)
        for port in cp.all_ports():
            self.rows.addWidget(self._card(port))
        self.rows.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        outer.addWidget(bb)
        fit_to_screen(self, 680, 620, limitar=True)

    def _card(self, port):
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.addWidget(label(port.name, "H3"))
        v.addWidget(label(f"Autor: {port.author} · Motor: {port.engine} · Title ID: {port.title_id}", "Hint"))
        v.addWidget(label(port.notes, "Hint", wrap=True))
        v.addWidget(self._status_label(port))
        row = QHBoxLayout()
        get = QPushButton("🌐  Obtener (releases)")
        get.clicked.connect(lambda _=False, p=port: self._open(p.releases_url))
        row.addWidget(get)
        repo = QPushButton("Código")
        repo.clicked.connect(lambda _=False, p=port: self._open(p.repo))
        row.addWidget(repo)
        pick = QPushButton("Elegir .exe construido…")
        pick.clicked.connect(lambda _=False, p=port: self._pick(p))
        row.addWidget(pick)
        play = QPushButton("▶  Jugar")
        play.setEnabled(cp.is_built(port))
        play.clicked.connect(lambda _=False, p=port: self._play(p))
        row.addWidget(play)
        row.addStretch(1)
        v.addLayout(row)
        return card

    def _status_label(self, port):
        if cp.is_built(port):
            txt = "✅ Construido y listo para jugar."
        elif port.is_cloned():
            txt = "⬇ Obtenido; falta construirlo con tu copia del juego (su instalador lo hace)."
        else:
            txt = "Aún no obtenido. Pulsa «Obtener» para descargar su release (trae su propio toolchain)."
        return label(txt, "Hint")

    def _open(self, url):
        try:
            QDesktopServices.openUrl(QUrl(url))
        except Exception:      # noqa: BLE001
            pass

    def _game_root_for(self, port):
        """Carpeta del proyecto del mismo juego en ReForge (para el icono real del XEX), o la del propio puerto."""
        try:
            if self.lib is not None:
                for p in getattr(self.lib, "projects", []):
                    if (getattr(p, "title_id", "") or "").upper() == port.title_id:
                        return p.root
        except Exception:      # noqa: BLE001
            pass
        return port.dir()

    def _pick(self, port):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        exe, _ = QFileDialog.getOpenFileName(self, f"Elige el .exe construido de «{port.name}»", "",
                                             "Ejecutable (*.exe)")
        if not exe:
            return
        cp.wrap_in_reforge(port, exe, self._game_root_for(port), lib=self.lib)
        ok, msg = cp.launch(port, exe)
        if not ok:
            QMessageBox.warning(self, "Ports de la comunidad", msg)
        else:
            self.accept()

    def _play(self, port):
        exe = cp.locate_built_exe(port)
        if not exe:
            return
        cp.wrap_in_reforge(port, exe, self._game_root_for(port), lib=self.lib)
        cp.launch(port, exe)
        self.accept()


def open_dialog(parent=None, lib=None):
    CommunityPortsDialog(parent, lib).exec()
