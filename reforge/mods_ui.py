"""Diálogo «Packs y texturas»: activar packs de mods/, importar .zip, exportar las texturas del juego."""
import os
import subprocess
import sys
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QVBoxLayout)

from . import mods
from .game_options import GameOptions
from .widgets import fit_to_screen, label


def open_folder(path):
    os.makedirs(path, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)      # noqa: S606
    else:
        subprocess.Popen(["xdg-open", path])


class _Bridge(QObject):
    done = Signal(str)
    step = Signal(str)


class ModsDialog(QDialog):
    def __init__(self, parent, root, name=""):
        super().__init__(parent)
        self.root = root
        self.o = GameOptions.load(root)
        self.setWindowTitle(f"Packs y texturas · {name or os.path.basename(root)}")
        fit_to_screen(self, 640, 520)
        v = QVBoxLayout(self)
        v.addWidget(label("Packs de este juego. Se aplican al abrirlo (orden alfabético: el último manda). "
                          "Al desactivar uno, ReForge devuelve los archivos originales.", "Hint", wrap=True))
        self.list = QListWidget()
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, fn in (("📦 Importar .zip…", self.import_zip), ("📁 Importar carpeta…", self.import_dir),
                         ("🖼 Exportar texturas del juego", self.export), ("📂 Abrir carpeta mods", self.open_dir)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        v.addLayout(row)
        st = mods.status(root)
        applied = len(st["archivos"])
        self.info = label(f"Ahora mismo: iconos {'PlayStation' if st['estilo'] == 'playstation' else 'Xbox'}"
                          + (f" · {applied} archivo(s) del juego modificados" if applied else ""), "Hint", wrap=True)
        v.addWidget(self.info)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close)
        bb.button(QDialogButtonBox.StandardButton.Save).setText("Guardar")
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.bridge = _Bridge()
        self.bridge.step.connect(self.info.setText)
        self.bridge.done.connect(self._export_done)
        self.refresh()

    def refresh(self):
        self.list.clear()
        disabled = set(self.o.mods_disabled or [])
        packs = mods.list_packs(self.root)
        for p in packs:
            info = p["info"]
            extra = " · ".join(x for x in (info.get("autor", ""), info.get("descripcion", "")) if x)
            it = QListWidgetItem(f"{info.get('nombre') or p['name']}  ({p['files']} archivo(s))"
                                 + (f"\n   {extra}" if extra else ""))
            it.setData(Qt.ItemDataRole.UserRole, p["name"])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked if p["name"] in disabled else Qt.CheckState.Checked)
            self.list.addItem(it)
        if not packs:
            it = QListWidgetItem("Sin packs todavía. Importa un .zip o usa «Exportar texturas» para crear el tuyo.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(it)

    def _import(self, src):
        if not src:
            return
        try:
            name = mods.import_pack(self.root, src)
        except Exception as e:      # noqa: BLE001
            QMessageBox.warning(self, "Packs", f"No se pudo importar: {e}")
            return
        mods.write_readme(self.root)
        self.refresh()
        self.info.setText(f"✔ Pack «{name}» importado. Se aplica al abrir el juego.")

    def import_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pack (.zip)", "", "Packs (*.zip)")
        self._import(path)

    def import_dir(self):
        self._import(QFileDialog.getExistingDirectory(self, "Carpeta del pack"))

    def open_dir(self):
        mods.write_readme(self.root)
        open_folder(mods.mods_dir(self.root))

    def export(self):
        self.info.setText("Exportando texturas…")

        def work():
            try:
                n = mods.export_textures(self.root, self.bridge.step.emit)
                self.bridge.done.emit(f"✔ {n} texturas exportadas a mods/{mods.EXPORT_DIR}." if n else
                                      "Este juego no tiene texturas XPR2 que ReForge sepa leer.")
            except Exception as e:      # noqa: BLE001
                self.bridge.done.emit(f"No se pudo exportar: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _export_done(self, msg):
        self.info.setText(msg)
        if msg.startswith("✔"):
            open_folder(os.path.join(mods.mods_dir(self.root), mods.EXPORT_DIR))

    def save(self):
        disabled = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            name = it.data(Qt.ItemDataRole.UserRole)
            if name and it.checkState() != Qt.CheckState.Checked:
                disabled.append(name)
        o = GameOptions.load(self.root)
        o.mods_disabled = disabled
        o.save(self.root)
        self.accept()
