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
        # Fila 1: obtener e instalar dentro de ReForge.
        row1 = QHBoxLayout()
        get = QPushButton("🌐  Obtener (releases)")
        get.clicked.connect(lambda _=False, p=port: self._open(p.releases_url))
        row1.addWidget(get)
        install = QPushButton("⬇  Instalar en ReForge")
        install.clicked.connect(lambda _=False, p=port: self._install(p))
        row1.addWidget(install)
        find = QPushButton("🔍  Buscar juego ya instalado")
        find.clicked.connect(lambda _=False, p=port: self._find(p))
        row1.addWidget(find)
        repo = QPushButton("Código")
        repo.clicked.connect(lambda _=False, p=port: self._open(p.repo))
        row1.addWidget(repo)
        row1.addStretch(1)
        v.addLayout(row1)
        # Fila 2: elegir, renombrar, idioma y jugar.
        row2 = QHBoxLayout()
        pick = QPushButton("Elegir .exe construido…")
        pick.clicked.connect(lambda _=False, p=port: self._pick(p))
        row2.addWidget(pick)
        rename = QPushButton(f"✏  Renombrar a «{port.exe_base}»")
        rename.setEnabled(cp.is_built(port))
        rename.clicked.connect(lambda _=False, p=port: self._rename(p))
        row2.addWidget(rename)
        if port.id == "pinyonshift":
            lang = QPushButton("🌐  Español latino (TU/GOD)")
            lang.clicked.connect(lambda _=False, p=port: self._language(p))
            row2.addWidget(lang)
        play = QPushButton("▶  Jugar")
        play.setEnabled(cp.is_built(port))
        play.clicked.connect(lambda _=False, p=port: self._play(p))
        row2.addWidget(play)
        row2.addStretch(1)
        v.addLayout(row2)
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

    def _connect_and_launch(self, port, exe):
        """Enlaza tu perfil/logros junto al .exe del puerto y lo lanza."""
        from PySide6.QtWidgets import QMessageBox
        res = cp.connect(port, exe, self._game_root_for(port), lib=self.lib)
        cp.remember_exe(port, exe)
        ok, msg = cp.launch(port, exe)
        if not ok:
            QMessageBox.warning(self, "Ports de la comunidad", msg)
            return False
        return True

    def _pick(self, port):
        from PySide6.QtWidgets import QFileDialog
        exe, _ = QFileDialog.getOpenFileName(self, f"Elige el .exe construido de «{port.name}»", "",
                                             "Ejecutable (*.exe)")
        if not exe:
            return
        if self._connect_and_launch(port, exe):
            self.accept()

    def _play(self, port):
        exe = cp.locate_built_exe(port)
        if not exe:
            return
        if self._connect_and_launch(port, exe):
            self.accept()

    def _install(self, port):
        from PySide6.QtWidgets import QMessageBox
        game_dir = self._game_assets_dir(port)
        ok, msg = cp.install_build(port, game_dir=game_dir)
        box = QMessageBox.information if ok else QMessageBox.warning
        box(self, "Instalar en ReForge", msg)

    def _find(self, port):
        from PySide6.QtWidgets import QMessageBox
        exe = cp.find_installed(port)
        if exe:
            # renombrar al nombre bonito y conectar el perfil, sin lanzar
            rok, exe = cp.rename_built(port, exe)
            cp.connect(port, exe, self._game_root_for(port), lib=self.lib)
            QMessageBox.information(self, "Buscar juego ya instalado",
                                    f"Encontrado y conectado:\n{exe}\n\nYa está en la Biblioteca; pulsa «Jugar».")
            self._refresh()
        else:
            dirs = "\n".join(port.known_dirs) or "—"
            QMessageBox.information(self, "Buscar juego ya instalado",
                                    "No encontré el .exe en las carpetas conocidas:\n" + dirs +
                                    "\n\nSi lo instalaste en otra ruta, usa «Elegir .exe construido…».")

    def _rename(self, port):
        from PySide6.QtWidgets import QMessageBox
        exe = cp.locate_built_exe(port)
        if not exe:
            return
        ok, new = cp.rename_built(port, exe)
        if ok:
            QMessageBox.information(self, "Renombrar", f"Renombrado a:\n{new}")
            self._refresh()
        else:
            QMessageBox.warning(self, "Renombrar", "No se pudo renombrar el ejecutable.")

    def _language(self, port):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        root = self._game_root_for(port)
        if not root or root == port.dir():
            QMessageBox.information(self, "Español latino",
                                    "Primero necesito el proyecto de Forza Horizon en ReForge (su assets/"
                                    "default.xex) para aplicarle la actualización. Crea/recompila el juego base "
                                    "y vuelve a intentarlo.")
            return
        src = QFileDialog.getExistingDirectory(self, "Elige la carpeta del GOD/TU (p. ej. FHL-DLC-TU-GOD)")
        if not src:
            return
        try:
            info = cp.apply_title_update(root, src)
        except Exception as e:      # noqa: BLE001
            QMessageBox.warning(self, "Español latino", f"No se pudo aplicar la actualización:\n{e}")
            return
        QMessageBox.information(self, "Español latino",
                               f"Actualización aplicada al proyecto (v{info.get('version', '?')}).\n\nReconstruye "
                               "el puerto (su instalador) para que Horizon salga en español latino.")

    def _game_assets_dir(self, port):
        """La carpeta assets/ del proyecto del mismo juego en ReForge (de donde copiar el default.xex al puerto)."""
        root = self._game_root_for(port)
        import os
        assets = os.path.join(root, "assets") if root else ""
        return assets if assets and os.path.isdir(assets) else ""

    def _refresh(self):
        """Vuelve a dibujar las tarjetas (estado, botones) tras un cambio."""
        try:
            while self.rows.count():
                item = self.rows.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
            for port in cp.all_ports():
                self.rows.addWidget(self._card(port))
            self.rows.addStretch(1)
        except Exception:      # noqa: BLE001
            pass


def open_dialog(parent=None, lib=None):
    CommunityPortsDialog(parent, lib).exec()
