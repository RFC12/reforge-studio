"""Lanzador propio de cada juego recompilado (estilo Xbox).

Se abre con  ReForgeStudio.exe --launcher "<carpeta del proyecto>"  (acceso directo del escritorio y
«Jugar <juego>.bat»). Permite elegir motor/modo de render, idioma, pantalla y controles antes de jugar,
vigila el juego y, si se cierra por una función no registrada, ofrece repararlo en ReForge Studio.
"""
import os
import sys

from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from . import game
from .core import AppConfig, Library
from .game_options import GameOptions, detect_languages, language_key, set_language_key, write_runtime_config
from .game_options_ui import language_combo
from .game_options_ui import ENGINE_PRESETS, GameOptionsDialog, vulkan_in_plugin
from .widgets import fit_to_screen, label

PRESET_TITLES = {k: t for k, t, _d in ENGINE_PRESETS}
PRESET_DESC = {k: d for k, _t, d in ENGINE_PRESETS}


def reforge_command(*args):
    """Programa y argumentos para volver a abrir ReForge Studio (instalado o desde código)."""
    if getattr(sys, "frozen", False):
        return sys.executable, list(args)
    main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    return sys.executable, [main_py, *args]


def project_title(root):
    lib = Library.load()
    p = lib.get(root)
    if p and p.name:
        return p.name, p.title_id
    return game.manifest_project_name(root) or os.path.basename(os.path.normpath(root)), ""


class GameLauncher(QWidget):
    def __init__(self, root):
        super().__init__()
        self.root = os.path.abspath(root)
        self.cfg = AppConfig.load()
        self.name, self.title_id = project_title(self.root)
        self.exe = game.game_exe(self.root, self.name)
        self.o = GameOptions.load(self.root)
        self.proc = None
        self.watch = None
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._poll)
        self.setWindowTitle(f"{self.name} · ReForge")
        self.setObjectName("Root")
        fit_to_screen(self, 720, 640)
        self._build()

    # ---------------------------------------------------------------- interfaz
    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(36, 28, 36, 24)
        v.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(label("REFORGE · LANZADOR", "Section"), 1)
        from .profile import Profile
        from .profile_page import avatar_pixmap
        prof = Profile.load()
        pic = QLabel()
        pic.setPixmap(avatar_pixmap(prof, 40))
        head.addWidget(pic)
        who = QVBoxLayout()
        who.setSpacing(0)
        who.addWidget(QLabel(f"<b>{prof.gamertag}</b>"))
        who.addWidget(label("● Xbox Live (simulado)" if prof.live else "○ Perfil local", "Hint"))
        head.addLayout(who)
        v.addLayout(head)
        title = QLabel(self.name)
        title.setStyleSheet("font-size: 30px; font-weight: 700;")
        v.addWidget(title)
        sub = " · ".join(x for x in (f"Title ID {self.title_id}" if self.title_id else "",
                                     os.path.basename(self.exe) if self.exe else "sin ejecutable") if x)
        v.addWidget(label(sub, "Hint"))

        card = QFrame()
        card.setObjectName("Card")
        f = QFormLayout(card)
        f.setContentsMargins(20, 18, 20, 18)
        f.setVerticalSpacing(12)

        self.engine = QComboBox()
        for k, t, _d in ENGINE_PRESETS:
            self.engine.addItem(t, k)
        cur = self.o.preset()
        if cur == "custom":
            self.engine.addItem("Personalizado (🎮 Opciones)", "custom")
        self.engine.addItem("Vulkan · no disponible en tu SDK" if not vulkan_in_plugin(self.cfg) else "Vulkan", "vulkan")
        vk_item = self.engine.model().item(self.engine.count() - 1)
        vk_item.setEnabled(False)
        self.engine.setCurrentIndex(max(0, self.engine.findData(cur)))
        self.engine_hint = label("", "Hint", wrap=True)
        self.engine.currentIndexChanged.connect(self._engine_hint)
        f.addRow("Motor", self.engine)
        f.addRow("", self.engine_hint)
        self._engine_hint()

        self.lang = language_combo(self.root, self.o)
        langs = detect_languages(self.root)
        f.addRow("Idioma", self.lang)
        f.addRow("", label(("Detectados en los archivos del juego." if langs else
                            "No se detectaron idiomas en los archivos; se muestran todos.") +
                           " Algunos juegos piden el idioma de otra forma y pueden seguir en inglés.",
                           "Hint", wrap=True))

        self.full = QCheckBox("Pantalla completa")
        self.full.setChecked(self.o.fullscreen)
        self.scale = QComboBox()
        for n, t in ((1, "1× (720p)"), (2, "2× (1440p)"), (3, "3× (2160p)")):
            self.scale.addItem(t, n)
        self.scale.setCurrentIndex(max(0, min(2, int(self.o.resolution_scale) - 1)))
        row = QHBoxLayout()
        row.addWidget(self.full)
        row.addStretch(1)
        row.addWidget(QLabel("Resolución"))
        row.addWidget(self.scale)
        f.addRow("Pantalla", row)

        self.pad = QComboBox()
        self.pad.addItem("Mando · Automático (XInput con mandos Xbox, SDL con el resto)", "auto")
        self.pad.addItem("Mando · SDL (Xbox, PlayStation, Switch, genéricos)", "sdl")
        self.pad.addItem("Mando · XInput (solo tipo Xbox)", "xinput")
        self.pad.setCurrentIndex(max(0, self.pad.findData(self.o.input_backend)))
        self.mnk = QCheckBox("Teclado y ratón (emula un mando)")
        self.mnk.setChecked(self.o.mnk_mode)
        f.addRow("Controles", self.pad)
        f.addRow("", self.mnk)
        v.addWidget(card)

        more = QPushButton("⚙  Más opciones (teclas, gráficos, audio)…")
        more.clicked.connect(self.more_options)
        optim = QPushButton("⚡  Optimizar rendimiento…")
        optim.clicked.connect(self.optimize)
        optim.setEnabled(bool(self.exe))
        mrow = QHBoxLayout()
        cheats_btn = QPushButton("🎯  Trucos…")
        cheats_btn.setToolTip("Trucos y parches de la base de datos de Xenia Canary")
        cheats_btn.clicked.connect(self.open_cheats)
        mrow.addWidget(more)
        mrow.addWidget(optim)
        mrow.addWidget(cheats_btn)
        mrow.addStretch(1)
        v.addLayout(mrow)
        v.addStretch(1)
        self.status = label("Listo para jugar." if self.exe else "Este proyecto aún no está compilado.",
                            "Hint", wrap=True)
        v.addWidget(self.status)
        bot = QHBoxLayout()
        self.studio = QPushButton("Abrir en ReForge Studio")
        self.studio.clicked.connect(self.open_studio)
        bot.addWidget(self.studio)
        bot.addStretch(1)
        self.play_btn = QPushButton("▶   JUGAR")
        self.play_btn.setObjectName("Primary")
        self.play_btn.setMinimumSize(220, 54)
        self.play_btn.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.play_btn.setEnabled(bool(self.exe))
        self.play_btn.clicked.connect(self.play)
        bot.addWidget(self.play_btn)
        v.addLayout(bot)

    def _engine_hint(self):
        self.engine_hint.setText(PRESET_DESC.get(self.engine.currentData(), "Lo elegido en 🎮 Opciones."))

    # ---------------------------------------------------------------- acciones
    def collect(self):
        o = GameOptions.load(self.root)
        key = self.engine.currentData()
        if key not in ("custom", "vulkan"):
            o.apply_preset(key)
        set_language_key(o, self.lang.currentData())
        o.fullscreen = self.full.isChecked()
        if int(self.scale.currentData()) != int(o.resolution_scale or 1):
            o.resolution_auto = False
        o.resolution_scale = int(self.scale.currentData())
        o.input_backend = self.pad.currentData()
        o.input_backend_chosen = o.input_backend != "auto"
        o.mnk_mode = self.mnk.isChecked()
        o.save(self.root)
        self.o = o
        return o

    def more_options(self):
        self.collect()

        class _P:
            pass
        p = _P()
        p.root, p.name = self.root, self.name
        GameOptionsDialog(self, self.cfg, p, self.exe).exec()
        self.o = GameOptions.load(self.root)
        self.full.setChecked(self.o.fullscreen)
        self.mnk.setChecked(self.o.mnk_mode)
        self.lang.setCurrentIndex(max(0, self.lang.findData(language_key(self.o))))

    def optimize(self):
        self.collect()
        from .optimizer_ui import OptimizeDialog
        OptimizeDialog(self, self.cfg, self.root, self.name, self.exe, self.title_id).exec()
        self.o = GameOptions.load(self.root)
        self.engine.setCurrentIndex(max(0, self.engine.findData(self.o.preset())))

    def play(self):
        if self.proc is not None and self.proc.poll() is None:
            return
        o = self.collect()
        try:
            from .autoconfig import apply as autoconfig
            line = autoconfig(self.root, self.exe)
            write_runtime_config(self.exe, o)
            game.prepare_game_runtime(self.cfg, self.exe, self.root)
            before = game._log_snapshot(self.exe)
            self.proc = game.popen_game(self.cfg, self.exe, self.root)
        except Exception as e:      # noqa: BLE001
            QMessageBox.critical(self, "No se pudo iniciar", str(e))
            return
        self.watch = {"proc": self.proc, "before": before, "path": ""}
        self.play_btn.setEnabled(False)
        self.play_btn.setText("En juego…")
        self.status.setText(f"Jugando con {self.engine.currentText()}. El lanzador vigila el juego."
                            + (f"\n⚙ {line}" if line else ""))
        self.showMinimized()
        from .watcher import write_marker
        write_marker(self.exe)          # ReForge Studio sabe que este lanzador ya vigila el juego
        self.timer.start()

    def _poll(self):
        from .watcher import clear_marker, write_marker
        out = game.check_running_game(self.exe, self.watch) if self.watch else {"kind": "clean"}
        if out is None:
            write_marker(self.exe)
            return
        clear_marker(self.exe)
        self.timer.stop()
        self.proc = None
        self.play_btn.setEnabled(True)
        self.play_btn.setText("▶   JUGAR")
        self.showNormal()
        self.raise_()
        self.activateWindow()
        # Cierre INTERMITENTE conocido (carrera en una completion asíncrona del runtime de rexglue que a veces
        # lanza 'Invalid UTF-8', 'Not enough space' o aborta sin escribir nada, y el despachador vuelve fatal):
        # como solo pasa en parte de los arranques, se reintenta un par de veces y el juego abre casi siempre.
        # Solo para este caso concreto.
        if out["kind"] in ("crash", "guest_av", "fatal") \
                and (game.known_runtime_race(game._read_log_text(out.get("path"))) or game.runtime_abort(out)) \
                and getattr(self, "_intermit_retries", 0) < 8:
            # A veces el cierre se repite varias veces seguidas antes de que el arranque «cuele» (Asura's Wrath
            # llegó a necesitar 8). Se reintenta solo, sin que el jugador tenga que cerrar y abrir a mano.
            self._intermit_retries = getattr(self, "_intermit_retries", 0) + 1
            self.status.setText(f"Cierre intermitente al arrancar; reintentando ({self._intermit_retries}/8)…")
            QTimer.singleShot(400, self.play)
            return
        self._intermit_retries = 0
        if out["kind"] == "unregistered":
            addr = out["address"]
            self.status.setText(f"El juego se cerró: falta la función 0x{addr:08X}.")
            box = QMessageBox(self)
            box.setWindowTitle("El juego se cerró")
            box.setText(f"El juego llamó a una función que no se recompiló (0x{addr:08X}).\n\n"
                        "ReForge Studio puede declararla, recompilar y volver a probar automáticamente.")
            fix = box.addButton("🔧  Reparar ahora", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Más tarde", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is fix:
                self.repair(addr)
        elif out["kind"] in ("crash", "guest_av"):
            from . import game as _game
            self.status.setText(_game.crash_advice(out, self.root))
        elif out["kind"] == "fatal":
            self.status.setText("El juego se cerró con un error: " + (out.get("lines") or ["?"])[-1][-160:])
        else:
            msg = "Juego cerrado. Listo para jugar otra vez."
            try:
                from .perfdiag import report
                lines, _main = report(out.get("path") or game.newest_log(self.exe), self.exe)
                tir = [ln for ln in lines if "tirón" in ln]
                if tir:
                    msg += "  " + tir[0]
                from .perfdiag import auto_tune
                tuned = auto_tune(self.root, self.exe, out.get("path") or game.newest_log(self.exe))
                if tuned:
                    msg += "  🔧 " + tuned[0]
            except Exception:      # noqa: BLE001
                pass
            self.status.setText(msg)

    def open_cheats(self):
        from .cheats_ui import CheatsDialog
        CheatsDialog(self, self.cfg, self.root, self.name, rebuild=self._rebuild_in_studio).exec()

    def _rebuild_in_studio(self, root):
        prog, args = reforge_command("--rebuild", root)
        if QProcess.startDetached(prog, args):
            self.close()
        else:
            QMessageBox.warning(self, "Recompilar", "No se pudo abrir ReForge Studio.")

    def repair(self, addr):
        prog, args = reforge_command("--repair", self.root, f"0x{addr:08X}")
        if QProcess.startDetached(prog, args):
            self.close()
        else:
            QMessageBox.warning(self, "Reparar", "No se pudo abrir ReForge Studio.")

    def open_studio(self):
        prog, args = reforge_command("--open-project", self.root)
        QProcess.startDetached(prog, args)

    def closeEvent(self, e):
        self.timer.stop()
        from .watcher import clear_marker
        if self.exe:
            clear_marker(self.exe)
        e.accept()


def run_launcher(root):
    from .theme import accent_color, build_qss
    app = QApplication.instance()
    cfg = AppConfig.load()
    try:
        accent = accent_color(cfg.accent)
        app.setProperty("accent", accent)
        app.setStyleSheet(build_qss(accent))
    except Exception:      # noqa: BLE001 — el lanzador funciona aunque falle el tema
        pass
    w = GameLauncher(root)
    w.show()
    return app.exec()
