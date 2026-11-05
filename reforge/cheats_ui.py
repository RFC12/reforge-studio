"""Ventana «🎯 Trucos»: parches de la base de datos de Xenia Canary para el juego del proyecto."""
import os
import subprocess
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
                               QPushButton, QVBoxLayout)

from . import cheats, game, pc_enhance
from .widgets import label


class _Bridge(QObject):
    progress = Signal(int, int)
    done = Signal(object)


class CheatsDialog(QDialog):
    """rebuild(root): función que recompila el proyecto (Taller) o abre ReForge para hacerlo (lanzador)."""

    def __init__(self, parent, cfg, root, name, rebuild=None):
        super().__init__(parent)
        self.cfg, self.root, self.name, self.rebuild = cfg, root, name, rebuild
        self.exe = game.game_exe(root, name)
        self.title_id = ""
        try:
            from .xex import read_xex_info
            self.title_id = read_xex_info(os.path.join(root, "assets", "default.xex")).get("title_id", "")
        except Exception:      # noqa: BLE001
            pass
        self.setWindowTitle(f"Trucos · {name}")
        self.resize(720, 640)
        v = QVBoxLayout(self)
        v.addWidget(label("BASE DE DATOS DE XENIA CANARY (game-patches)", "Section"))
        row = QHBoxLayout()
        self.db_lbl = label("", "Hint", wrap=True)
        row.addWidget(self.db_lbl, 1)
        self.btn_db = QPushButton("⬇  Descargar / actualizar")
        self.btn_db.clicked.connect(self.download)
        row.addWidget(self.btn_db)
        v.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        self.bar.hide()
        v.addWidget(self.bar)

        v.addWidget(label("VERSIÓN DE TU JUEGO", "Section"))
        vrow = QHBoxLayout()
        self.ver_lbl = label("", "Hint", wrap=True)
        vrow.addWidget(self.ver_lbl, 1)
        self.btn_ident = QPushButton("▶  Identificar")
        self.btn_ident.setToolTip("Abre el juego unos segundos sin trucos para calcular el hash de su versión")
        self.btn_ident.clicked.connect(self.identify)
        vrow.addWidget(self.btn_ident)
        v.addLayout(vrow)

        v.addWidget(label("TRUCOS Y PARCHES DISPONIBLES", "Section"))
        self.list = QListWidget()
        self.list.itemChanged.connect(self._item_changed)
        self.list.currentItemChanged.connect(self._show_desc)
        v.addWidget(self.list, 1)
        self.desc = label("", "Hint", wrap=True)
        v.addWidget(self.desc)
        v.addWidget(label("Los trucos de código se integran en el ejecutable: al cambiarlos hay que recompilar "
                          "(el resto vale al volver a arrancar). Algunos parches de la base de datos son mejoras "
                          "(60 FPS, resolución…) y otros trucos; actívalos de uno en uno si un juego falla.",
                          "Hint", wrap=True))
        bot = QHBoxLayout()
        self.btn_rec = QPushButton("✨  Recomendadas para PC")
        self.btn_rec.setToolTip("Marca las mejoras para PC de este juego: FPS desbloqueados, correcciones gráficas "
                                "y sin desenfoque de movimiento (★ en la lista)")
        self.btn_rec.clicked.connect(self.check_recommended)
        bot.addWidget(self.btn_rec)
        self.btn_none = QPushButton("Quitar todos")
        self.btn_none.clicked.connect(lambda: self._check_all(False))
        bot.addWidget(self.btn_none)
        bot.addStretch(1)
        self.btn_apply = QPushButton("Aplicar")
        self.btn_apply.setObjectName("Primary")
        self.btn_apply.clicked.connect(self.apply)
        bot.addWidget(self.btn_apply)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.reject)
        bot.addWidget(close)
        v.addLayout(bot)
        self.bridge = _Bridge()
        self.bridge.progress.connect(self._progress)
        self.bridge.done.connect(self._downloaded)
        self.patches = []
        self.refresh()

    # ---------------------------------------------------------------- estado
    def module_hash(self):
        return cheats.read_module_info(self.exe).get("hash", "") if self.exe else ""

    def refresh(self):
        info = cheats.db_info()
        self.db_lbl.setText(f"{info['files']} juegos · actualizada {info['updated']}" if info else
                            "Aún no descargada. Pulsa «Descargar» (unos pocos MB, desde GitHub).")
        h = self.module_hash()
        state = cheats.cheats_state(self.root) or {}
        active = set(state.get("patches", []))
        files = cheats.files_for_title(self.title_id) if self.title_id else []
        self.patches = cheats.patches_for(self.title_id, h) if h else []
        if not self.exe:
            ver = "Compila el juego primero."
        elif not h:
            ver = (f"Title ID {self.title_id}. Falta identificar la versión exacta: pulsa «Identificar» (abre el "
                   "juego unos segundos) o juega una vez sin trucos.")
        else:
            ver = f"Title ID {self.title_id} · hash {h}"
            if files and not self.patches:
                other = sorted({x for f in files for x in f.hashes})
                ver += (f"\nLa base de datos tiene parches para este juego pero de otra versión ({', '.join(other)}). "
                        "Puede que necesites otra actualización del juego.")
            elif not files and info:
                ver += "\nLa base de datos no tiene parches para este juego."
        self.ver_lbl.setText(ver)
        self.btn_ident.setEnabled(bool(self.exe) and not active)
        self.list.blockSignals(True)
        self.list.clear()
        from .game_options import GameOptions
        o = GameOptions.load(self.root)
        self.rec_names = {p.name for p in pc_enhance.recommended(self.patches, o.resolution_scale, o.frame_mode())}
        for f, p in self.patches:
            star = "★ " if p.name in self.rec_names else ""
            it = QListWidgetItem(star + p.name + (f"   · {p.author}" if p.author else ""))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if p.name in active else Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, p.name)
            it.setToolTip(p.desc or p.name)
            self.list.addItem(it)
        self.list.blockSignals(False)
        self.btn_apply.setEnabled(bool(self.patches) or bool(active))
        self.btn_none.setEnabled(bool(self.patches))
        self.btn_rec.setEnabled(bool(self.rec_names))
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.desc.setText("")

    def _show_desc(self, cur, _prev=None):
        if not cur:
            return
        name = cur.data(Qt.ItemDataRole.UserRole)
        p = next((p for _f, p in self.patches if p.name == name), None)
        if p:
            self.desc.setText((p.desc or "Sin descripción.") + f"\n{len(p.writes)} cambio(s) en memoria.")

    def _item_changed(self, _it):
        pass

    def _check_all(self, on):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def check_recommended(self):
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) in self.rec_names:
                it.setCheckState(Qt.CheckState.Checked)
        self.desc.setText("★ Marcadas las mejoras para PC: " + pc_enhance.describe(
            [p for _f, p in self.patches if p.name in self.rec_names]) + ". Pulsa «Aplicar» (recompila el juego).")

    def selected(self):
        names = {self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                 if self.list.item(i).checkState() == Qt.CheckState.Checked}
        return [p for _f, p in self.patches if p.name in names]

    # ---------------------------------------------------------------- base de datos
    def download(self):
        self.btn_db.setEnabled(False)
        self.bar.setRange(0, 0)
        self.bar.show()

        def work():
            try:
                n = cheats.download_db(lambda d, t: self.bridge.progress.emit(d, t))
                self.bridge.done.emit(n)
            except Exception as e:      # noqa: BLE001
                self.bridge.done.emit(e)
        threading.Thread(target=work, daemon=True).start()

    def _progress(self, d, t):
        if t:
            self.bar.setRange(0, t)
            self.bar.setValue(d)

    def _downloaded(self, result):
        self.bar.hide()
        self.btn_db.setEnabled(True)
        if isinstance(result, Exception):
            QMessageBox.warning(self, "Base de datos", f"No se pudo descargar: {result}")
        self.refresh()

    # ---------------------------------------------------------------- identificar la versión
    def identify(self):
        if not self.exe:
            return
        from .game_options import GameOptions, write_runtime_config
        try:
            game.prepare_game_runtime(self.cfg, self.exe, self.root)
            write_runtime_config(self.exe, GameOptions.load(self.root))
            proc = game.popen_game(self.cfg, self.exe, self.root)
        except Exception as e:      # noqa: BLE001
            return QMessageBox.warning(self, "Identificar", str(e))
        self.btn_ident.setEnabled(False)
        self.btn_ident.setText("Identificando…")
        start = time.time()

        def tick():
            if self.module_hash() or proc.poll() is not None or time.time() - start > 120:
                timer.stop()
                if proc.poll() is None:
                    try:
                        if os.name == "nt":
                            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                                           creationflags=0x08000000, timeout=30)
                        proc.kill()
                    except Exception:      # noqa: BLE001
                        pass
                self.btn_ident.setText("▶  Identificar")
                if not self.module_hash():
                    QMessageBox.information(self, "Identificar",
                                            "El juego no anotó su versión. Recompílalo con esta versión de ReForge "
                                            "(la extensión ReForge debe estar activa) y vuelve a intentarlo.")
                self.refresh()
        timer = QTimer(self)
        timer.setInterval(1000)
        timer.timeout.connect(tick)
        timer.start()

    # ---------------------------------------------------------------- aplicar
    def apply(self):
        sel = self.selected()
        try:
            changed = cheats.apply_cheats(self.root, sel)
        except Exception as e:      # noqa: BLE001
            return QMessageBox.warning(self, "Trucos", str(e))
        if self.exe:
            try:
                from .profile import write_ext_ini
                from .game_options import GameOptions
                write_ext_ini(self.exe, GameOptions.load(self.root))
            except Exception:      # noqa: BLE001
                pass
        what = (f"{len(sel)} truco(s) activado(s)." if sel else "Trucos quitados.")
        if changed:
            if QMessageBox.question(self, "Recompilar",
                                    what + "\n\nEstos cambios afectan al código del juego: hay que recompilarlo. "
                                    "¿Hacerlo ahora?") == QMessageBox.StandardButton.Yes and self.rebuild:
                self.accept()
                self.rebuild(self.root)
                return
        else:
            QMessageBox.information(self, "Trucos", what + " Se aplican la próxima vez que abras el juego.")
        self.refresh()
