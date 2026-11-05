"""Ventana «⬆ Actualización»: instalar o quitar la actualización de título (TU) de un proyecto."""
import os

from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QMessageBox, QPushButton, QVBoxLayout

from .title_update import TitleUpdateError, check_update, install_update, installed_update, remove_update
from .widgets import label


class UpdateDialog(QDialog):
    def __init__(self, parent, root, name):
        super().__init__(parent)
        self.root, self.name = root, name
        self.changed = False
        self.setWindowTitle(f"Actualización · {name}")
        self.resize(560, 330)
        v = QVBoxLayout(self)
        v.addWidget(label("ACTUALIZACIÓN DEL JUEGO (TITLE UPDATE)", "Section"))
        self.state = label("", "CardTitle", wrap=True)
        v.addWidget(self.state)
        v.addWidget(label("Elige el paquete de la actualización (archivo sin extensión, normalmente dentro de "
                          "<TitleID>/000B0000) o un default.xexp. ReForge comprueba que sea de este juego y de "
                          "esta versión, coloca default.xexp junto a default.xex y el resto en «update» (el "
                          "juego lo ve como update:). Después hay que volver a generar el código y compilar: "
                          "el ejecutable recompilado incluye el parche.", "Hint", wrap=True))
        v.addStretch(1)
        row = QHBoxLayout()
        self.btn_install = QPushButton("⬆  Instalar actualización…")
        self.btn_install.setObjectName("Primary")
        self.btn_install.clicked.connect(self.install)
        self.btn_remove = QPushButton("Quitar (volver al juego base)")
        self.btn_remove.clicked.connect(self.remove)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        row.addWidget(self.btn_install)
        row.addWidget(self.btn_remove)
        row.addStretch(1)
        row.addWidget(close)
        v.addLayout(row)
        self._refresh()

    def _refresh(self):
        tu = installed_update(self.root)
        if tu:
            self.state.setText(f"Instalada: versión {tu.get('version', '?')}"
                               + (f" (desde {tu['from_version']})" if tu.get("from_version") else "")
                               + (f" · {tu['name']}" if tu.get("name") else ""))
        else:
            self.state.setText("Sin actualización: se usa el juego base.")
        self.btn_remove.setEnabled(bool(tu))

    def install(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Actualización del juego", "",
                                                  "Actualización: paquete TU o default.xexp (*)")
        if not path:
            return
        try:
            info = check_update(self.root, path)
            msg = (f"Actualización {info['version']} (desde {info['from_version']}) para el Title ID "
                   f"{info['title_id']}" + (f" · {info['files']} archivos" if info.get("files") else "") +
                   ".\n\n¿Instalarla en el proyecto?")
            if QMessageBox.question(self, "Actualización", msg) != QMessageBox.StandardButton.Yes:
                return
            install_update(self.root, path)
        except (TitleUpdateError, OSError) as e:
            QMessageBox.warning(self, "Actualización", str(e))
            return
        self.changed = True
        self._refresh()

    def remove(self):
        if QMessageBox.question(self, "Actualización", "¿Quitar la actualización y volver al juego base?") \
                != QMessageBox.StandardButton.Yes:
            return
        if remove_update(self.root):
            self.changed = True
        self._refresh()


def open_update_dialog(workshop, project):
    d = UpdateDialog(workshop, project.root, project.name)
    d.exec()
    if d.changed and os.path.isfile(os.path.join(project.root, "CMakeLists.txt")):
        if QMessageBox.question(workshop, "Recompilar",
                                "Para que el juego use este cambio hay que volver a generar el código y "
                                "compilar. ¿Hacerlo ahora?") == QMessageBox.StandardButton.Yes:
            workshop.load_project(project)
            workshop.rebuild_current()
