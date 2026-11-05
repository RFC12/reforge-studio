"""Ventana «⚡ Optimizar» y asistente que busca el modo de imagen más rápido que se ve bien."""
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QRadioButton, QScrollArea, QVBoxLayout, QWidget)

from . import game
from .game_options import GameOptions, write_runtime_config
from .optimizer import (PERF_MODES, QUALITY_LEVELS, RENDER_LADDER, cached_hardware, describe, detect_hardware,
                        nvidia_ai_tips, open_nvidia_app, recommended_scale, shader_cache_info)
from .widgets import label

LADDER_TITLES = {k: t for k, t, *_r in RENDER_LADDER}


class OptimizeDialog(QDialog):
    def __init__(self, parent, cfg, root, name, exe, title_id=""):
        super().__init__(parent)
        self.cfg, self.root, self.name, self.exe, self.title_id = cfg, root, name, exe, title_id
        self.o = GameOptions.load(root)
        self.setWindowTitle(f"Optimizar · {name}")
        self.resize(720, 860)
        self.setMinimumSize(620, 600)
        outer = QVBoxLayout(self)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        sc.setWidget(body)
        outer.addWidget(sc, 1)
        v = QVBoxLayout(body)
        v.setSpacing(10)

        v.addWidget(label("TU EQUIPO", "Section"))
        self.hw = cached_hardware()
        self.hw_lbl = label("", "Hint", wrap=True)
        v.addWidget(self.hw_lbl)
        redetect = QPushButton("Volver a detectar")
        redetect.clicked.connect(self._redetect)
        v.addWidget(redetect, 0, Qt.AlignmentFlag.AlignLeft)

        v.addWidget(label("PERFIL DEL JUEGO", "Section"))
        from .engine import engine_info, ensure_engine
        self.engine_key = ensure_engine(root, self.o)
        info = engine_info(self.engine_key)
        v.addWidget(label(f"{info['name']}" + (f" · {info['kind']}" if info["kind"] else ""), "CardTitle"))
        if info["why"]:
            v.addWidget(label("Perfil automático: " + " ".join(info["why"]), "Hint", wrap=True))
        self.occl = QComboBox()
        for k, t in (("auto", "Automática (según el motor)"), ("fake", "Simuladas · sin esperas (más fluido)"),
                     ("real", "Reales · exactas (más lento)")):
            self.occl.addItem(t, k)
        self.occl.setCurrentIndex(max(0, self.occl.findData(self.o.occlusion)))
        orow = QHBoxLayout()
        orow.addWidget(QLabel("Consultas de oclusión"))
        orow.addWidget(self.occl, 1)
        v.addLayout(orow)
        v.addWidget(label("Cada consulta real obliga a esperar a la GPU: en juegos de acción con muchas (Unreal "
                          "Engine 3) provoca tirones. Simuladas: el juego cree que todo es visible; casi nunca se "
                          "nota (algún destello de luz podría verse a través de paredes).", "Hint", wrap=True))
        self.native = QCheckBox("Compilar para tu procesador (instrucciones AVX2 de tu CPU: -march=native)")
        self.native.setChecked(bool(self.o.cpu_native))
        v.addWidget(self.native)
        v.addWidget(label("El código recompilado usa todas las instrucciones de tu CPU. Se aplica al recompilar "
                          "(todo el juego, varios minutos) y ese .exe solo funcionará en procesadores como el tuyo.",
                          "Hint", wrap=True))

        from . import game as _game
        self.cgopt = QComboBox()
        lvl_now = _game.CODEGEN_LEVEL_TITLES.get(self.o.codegen_level(), "")
        for k, t in (("auto", f"Automática · Segura y se quita sola si el juego falla (ahora: {lvl_now})"),
                     ("max", "Máxima (experimental) · también registros temporales; algunos juegos se cuelgan"),
                     ("safe", "Segura · solo registros de control (CR, CTR, XER)"),
                     ("off", "Desactivada · código como el original")):
            self.cgopt.addItem(t, k)
        self.cgopt.setCurrentIndex(max(0, self.cgopt.findData(self.o.codegen_opt)))
        crow = QHBoxLayout()
        crow.addWidget(QLabel("⚡ Optimización del código"))
        crow.addWidget(self.cgopt, 1)
        v.addLayout(crow)
        v.addWidget(label("El código recompilado guarda los registros del Xbox 360 como variables locales (lo que hace "
                          "XenonRecomp en Unleashed Recompiled): menos accesos a memoria y más FPS cuando el juego "
                          "está limitado por la CPU. Si el juego se cierra o se cuelga antes de comprobarla, el Taller "
                          "baja de nivel, recompila y lo vuelve a probar solo. Se aplica al recompilar (todo el "
                          "juego).", "Hint", wrap=True))

        self.diag = QCheckBox("📈 Diagnóstico de tirones en la próxima partida (log detallado + tiempo de cada fotograma) · "
                              "el ajuste automático lo activa solo cuando hay tirones mientras juegas")
        self.diag.setChecked(bool(getattr(self.o, "diagnostics", False)))
        v.addWidget(self.diag)
        self.autotune = QCheckBox("🔧 Ajuste automático tras cada partida (audio entrecortado, tirones, diagnóstico)")
        self.autotune.setChecked(bool(getattr(self.o, "auto_tune", True)))
        v.addWidget(self.autotune)
        v.addWidget(label("Juega 2-3 minutos con acción y cierra el juego: ReForge cruza cada tirón con lo que rexglue "
                          "hacía en ese instante (shaders, texturas, disco, audio) y te dice la causa. El log detallado "
                          "consume algo de rendimiento: desactívalo al terminar.", "Hint", wrap=True))

        v.addWidget(label("RENDIMIENTO", "Section"))
        self.modes = QButtonGroup(self)
        for key, title, desc in PERF_MODES:
            rb = QRadioButton(title)
            rb.setProperty("mode", key)
            rb.setChecked(self.o.perf_mode == key)
            rb.toggled.connect(self._mode_changed)
            self.modes.addButton(rb)
            v.addWidget(rb)
            v.addWidget(label("      " + desc, "Hint", wrap=True))

        v.addWidget(label("CALIDAD DE IMAGEN", "Section"))
        self.quality = QButtonGroup(self)
        self.rec_scale = recommended_scale(self.hw)
        cur = max(1, min(3, int(self.o.resolution_scale)))
        for n, title, desc in QUALITY_LEVELS:
            rb = QRadioButton(title + ("   ★ recomendada para tu GPU" if n == self.rec_scale else ""))
            rb.setProperty("scale", n)
            rb.setChecked(n == cur)
            self.quality.addButton(rb)
            v.addWidget(rb)
            v.addWidget(label("      " + desc, "Hint", wrap=True))
        self.aniso16 = QCheckBox("Filtrado anisotrópico 16× (texturas nítidas en suelos y paredes lejanas)")
        self.aniso16.setChecked(int(self.o.anisotropic_override) == 5)
        v.addWidget(self.aniso16)
        v.addWidget(label("La escala interna es supermuestreo real: el juego se dibuja a más resolución y se reduce "
                          "a tu pantalla. Si en algún juego ves líneas finas, sombras desplazadas o bordes raros, "
                          "vuelve a 1×. DLSS y FSR 2 no son posibles: necesitan vectores de movimiento que los "
                          "juegos de Xbox 360 no generan.", "Hint", wrap=True))
        tips = nvidia_ai_tips(self.hw)
        if tips:
            card = QFrame()
            card.setObjectName("Card")
            cv = QVBoxLayout(card)
            cv.addWidget(label("IA DE NVIDIA (SIN INTEGRAR EN EL JUEGO)", "Section"))
            cv.addWidget(label(tips, "Hint", wrap=True))
            nv = QPushButton("Abrir NVIDIA App")
            nv.clicked.connect(self._open_nvidia)
            cv.addWidget(nv, 0, Qt.AlignmentFlag.AlignLeft)
            v.addWidget(card)

        v.addWidget(label("MODO DE IMAGEN", "Section"))
        self.render_lbl = label("", "Hint", wrap=True)
        v.addWidget(self.render_lbl)
        assist = QPushButton("🔎  Buscar el modo más rápido que se vea bien")
        assist.setEnabled(bool(exe))
        assist.clicked.connect(self.run_assistant)
        v.addWidget(assist, 0, Qt.AlignmentFlag.AlignLeft)

        v.addWidget(label("CACHÉ DE SHADERS", "Section"))
        base, files = shader_cache_info(title_id, game.manifest_project_name(root) or name)
        total = sum(sz for _f, sz in files)
        v.addWidget(label((f"{len(files)} archivo(s) · {total / 1024:.0f} KB en {base}. " if files else
                           "Aún vacía. ") +
                          "Se llena sola mientras juegas y se carga al arrancar: cada escena nueva puede dar un "
                          "tirón o parpadeo solo la primera vez. Cambiar entre RTV y ROV usa cachés distintas, "
                          "así que conviene quedarse con un modo.", "Hint", wrap=True))
        v.addStretch(1)
        v = outer
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("Guardar")
        ok.setObjectName("Primary")
        ok.clicked.connect(self.save)
        row.addWidget(ok)
        cancel = QPushButton("Cerrar")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        v.addLayout(row)
        self._refresh()

    def _open_nvidia(self):
        if not open_nvidia_app():
            QMessageBox.information(self, "NVIDIA", "No encontré la NVIDIA App ni el Panel de control de NVIDIA. "
                                    "Instálala desde nvidia.com/apps.")

    def _scale(self):
        b = self.quality.checkedButton()
        return int(b.property("scale")) if b else 1

    def _mode(self):
        b = self.modes.checkedButton()
        return b.property("mode") if b else "fluido"

    def _mode_changed(self, *_a):
        self._refresh()

    def _redetect(self):
        log = game.newest_log(self.exe) if self.exe else ""
        self.hw = detect_hardware(log)
        self._refresh()

    def _refresh(self):
        self.hw_lbl.setText(describe(self.hw, self._mode()))
        o = GameOptions.load(self.root)
        key = o.preset()
        self.render_lbl.setText(f"Actual: {LADDER_TITLES.get(key, key)}. El asistente prueba los modos del más "
                                "rápido al más pesado y te pregunta si el juego se ve bien.")

    def save(self):
        o = GameOptions.load(self.root)
        o.perf_mode = self._mode()
        if self._scale() != int(o.resolution_scale or 1):
            o.resolution_auto = False
        o.resolution_scale = self._scale()
        o.engine = self.engine_key
        o.occlusion = self.occl.currentData()
        rebuild = bool(self.native.isChecked()) != bool(o.cpu_native)
        if self.cgopt.currentData() != o.codegen_opt:
            o.codegen_opt = self.cgopt.currentData()
            o.codegen_opt_verified = False
            if o.codegen_opt == "auto":
                o.codegen_opt_level = "safe"
            rebuild = True
        o.cpu_native = self.native.isChecked()
        o.diagnostics = self.diag.isChecked()
        o.auto_tune = self.autotune.isChecked()
        if self.aniso16.isChecked():
            o.anisotropic_override = 5
        elif int(o.anisotropic_override) == 5:
            o.anisotropic_override = 3
        o.save(self.root)
        if self.exe and os.path.isfile(self.exe):
            write_runtime_config(self.exe, o)
        if rebuild:
            QMessageBox.information(self, "Recompilar el juego",
                                    "Se aplicará la próxima vez que pulses «▶ Jugar» o «Compilar» (recompila todo el "
                                    "juego; el Taller lo hace solo).")
        self.accept()

    def run_assistant(self):
        o = GameOptions.load(self.root)
        o.perf_mode = self._mode()
        o.save(self.root)
        AssistantDialog(self, self.cfg, self.root, self.exe).exec()
        self._refresh()


class AssistantDialog(QDialog):
    """Lanza el juego con cada modo de imagen (del más rápido al más pesado) y se queda con el primero
    que el jugador confirma que se ve bien."""

    def __init__(self, parent, cfg, root, exe):
        super().__init__(parent)
        self.cfg, self.root, self.exe = cfg, root, exe
        o0 = GameOptions.load(root)
        self.original = (o0.render_path, o0.readback_resolve, o0.allow_invalid_fetch)
        self.i = -1
        self.proc = None
        self.watch = None
        self.chosen = None
        self.setWindowTitle("Asistente de imagen")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(520, 300)
        v = QVBoxLayout(self)
        self.step = label("", "Section")
        v.addWidget(self.step)
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 20px; font-weight: 700;")
        v.addWidget(self.title)
        self.msg = label("", "Hint", wrap=True)
        v.addWidget(self.msg)
        card = QFrame()
        card.setObjectName("Card")
        cv = QVBoxLayout(card)
        cv.addWidget(label("Entra en una partida (no te quedes en el menú) y mira el escenario 3D: suelos, paredes, "
                           "sombras. ¿Se ve todo con normalidad, sin pantalla negra, bloques negros, rayas ni "
                           "texturas parpadeando?", wrap=True))
        v.addWidget(card)
        v.addStretch(1)
        row = QHBoxLayout()
        self.yes = QPushButton("✔  Se ve bien")
        self.yes.setObjectName("Primary")
        self.yes.clicked.connect(self.accept_mode)
        self.no = QPushButton("✖  Negra o texturas raras")
        self.no.clicked.connect(self.next_mode)
        stop = QPushButton("Cancelar")
        stop.clicked.connect(self.reject)
        row.addWidget(self.yes)
        row.addWidget(self.no)
        row.addStretch(1)
        row.addWidget(stop)
        v.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._poll)
        QTimer.singleShot(0, self.next_mode)

    def _stop_game(self):
        self.timer.stop()
        if self.proc is not None and self.proc.poll() is None:
            game._kill_tree(self.proc)
        self.proc = None

    def _launch(self, key):
        o = GameOptions.load(self.root)
        o.apply_preset(key)
        o.save(self.root)
        write_runtime_config(self.exe, o)
        game.prepare_game_runtime(self.cfg, self.exe, self.root)
        before = game._log_snapshot(self.exe)
        self.proc = game.popen_game(self.cfg, self.exe, self.root)
        self.watch = {"proc": self.proc, "before": before, "path": ""}
        self.timer.start()

    def next_mode(self):
        self._stop_game()
        self.i += 1
        if self.i >= len(RENDER_LADDER):
            self._restore()
            QMessageBox.information(self, "Asistente", "Ningún modo se vio bien. Se deja la configuración que tenías.")
            self.done(0)
            return
        key, title, *_r = RENDER_LADDER[self.i]
        self.step.setText(f"PRUEBA {self.i + 1} DE {len(RENDER_LADDER)}")
        self.title.setText(title)
        self.msg.setText("Abriendo el juego…")
        self.yes.setEnabled(True)
        self.no.setEnabled(True)
        try:
            self._launch(key)
            self.msg.setText("El juego se está abriendo con este modo.")
        except Exception as e:      # noqa: BLE001
            self.msg.setText(f"No se pudo abrir el juego: {e}")

    def _poll(self):
        out = game.check_running_game(self.exe, self.watch) if self.watch else None
        if out is None:
            return
        self.timer.stop()
        self.proc = None
        if out["kind"] == "unregistered":
            self.msg.setText(f"El juego se cerró por una función no registrada (0x{out['address']:08X}). "
                             "Repáralo primero con ▶ Jugar en el Taller y vuelve al asistente.")
            self.yes.setEnabled(False)
            self.no.setEnabled(False)
            self._restore()
        else:
            self.msg.setText("El juego se cerró con este modo. Pulsa «✖» para probar el siguiente.")
            self.yes.setEnabled(False)

    def accept_mode(self):
        key = RENDER_LADDER[self.i][0]
        self.chosen = key
        self.timer.stop()        # el juego sigue abierto: ya se ve bien
        QMessageBox.information(self, "Asistente", f"Listo: «{RENDER_LADDER[self.i][1]}» queda guardado para "
                                                   "este juego. Puedes seguir jugando.")
        self.done(1)

    def _restore(self):
        o = GameOptions.load(self.root)
        o.render_path, o.readback_resolve, o.allow_invalid_fetch = self.original
        o.save(self.root)
        try:
            write_runtime_config(self.exe, o)
        except OSError:
            pass

    def reject(self):
        self._stop_game()
        if self.chosen is None:
            self._restore()
        super().reject()
