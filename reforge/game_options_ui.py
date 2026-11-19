"""Diálogo «Opciones del juego»: gráficos, controles, audio y reparación automática."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QGridLayout, QHBoxLayout, QLineEdit, QPushButton, QRadioButton, QScrollArea,
                               QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from . import mnklayouts
from .game_options import (CHOICE_NAMES, DEFAULT_KEYBINDS, KEYBIND_LABELS, LICENSE_CHOICES, POST_EFFECTS,
                           PRESENT_EFFECTS, GameOptions, detect_language_choices, language_key,
                           present_effects_supported, set_language_key, write_runtime_config)


def language_combo(root, options):
    """Combo de idiomas: los que se detectan en los archivos del juego (el español ofrece España y México)."""
    from .game_options import windows_language
    cb = QComboBox()
    wl = windows_language()
    cb.addItem(f"Automático · el de Windows: {CHOICE_NAMES.get(f'{wl[0]}:{wl[1]}', 'English')}", "auto")
    cb.addItem("El que elija el juego (normalmente inglés)", "")
    for key in detect_language_choices(root):
        cb.addItem(CHOICE_NAMES[key], key)
    cur = language_key(options)
    if cur and cb.findData(cur) < 0:
        cb.addItem(CHOICE_NAMES.get(cur, cur), cur)
    cb.setCurrentIndex(max(0, cb.findData(cur)))
    return cb
from .widgets import label


def vulkan_in_plugin(cfg):
    prefix = cfg.sdk_prefix()
    dll = os.path.join(prefix, "bin", "rexgpu-xenos.dll") if prefix else ""
    try:
        with open(dll, "rb") as f:
            return b"vulkan-1.dll" in f.read()
    except OSError:
        return None


class GameOptionsDialog(QDialog):
    def __init__(self, parent, cfg, project, exe=""):
        super().__init__(parent)
        self.cfg, self.project, self.exe = cfg, project, exe
        self.o = GameOptions.load(project.root)
        self.setWindowTitle(f"Opciones del juego · {project.name}")
        self.resize(820, 680)
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.setUsesScrollButtons(False)
        tabs.addTab(self._graphics(), "Gráficos")
        tabs.addTab(self._controls(), "Controles")
        tabs.addTab(self._audio_repair(), "Idioma, audio y reparación")
        v.addWidget(tabs, 1)
        where = (f"Se guardan en el proyecto y en {os.path.basename(exe)[:-4] if exe else '<juego>'}.toml "
                 "junto al ejecutable. Se aplican al abrir el juego.")
        v.addWidget(label(where, "Hint", wrap=True))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText("Guardar")
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    # ---------------------------------------------------------------- pestañas
    def _tab(self):
        w = QWidget()
        f = QFormLayout(w)
        f.setVerticalSpacing(10)
        return w, f

    def _graphics(self):
        w, f = self._tab()
        vk = vulkan_in_plugin(self.cfg)
        engine = "Direct3D 12"
        if vk:
            engine += " (Vulkan también incluido en el plugin)"
        f.addRow("Motor gráfico", label(engine, "CardTitle"))
        f.addRow("", label("El runtime de rexglue para Windows trae Direct3D 12. Vulkan existe en el código de "
                           "rexglue pero tu SDK de Windows no lo incluye; OpenGL y Direct3D 11 no existen en rexglue "
                           "(emular la GPU Xenos del Xbox 360 requiere funciones de D3D12/Vulkan). DXVK tampoco sirve: traduce "
                           "Direct3D 8-11, no 12, y su dxgi.dll impediría arrancar (ReForge lo aparta si lo encuentra).",
                           "Hint", wrap=True))
        self.full = QCheckBox("Pantalla completa")
        self.full.setChecked(self.o.fullscreen)
        f.addRow(self.full)
        from .pc_enhance import FPS_MODES, monitor_hz, paced_rate
        hz = monitor_hz()
        self.fps = QComboBox()
        for k, t in FPS_MODES:
            if k == "monitor":
                t = t.replace("tu monitor", f"tu monitor ({hz} Hz)")
            elif k == "auto":
                r = paced_rate(hz, self.o.fps_unlocked)
                if self.o.fps_cap and self.o.fps_cap < r:
                    t += f" · {self.o.fps_cap:g} FPS estables (este juego no aguantó {r:g})"
                else:
                    t += f" · {r:g} FPS en tu monitor de {hz} Hz"
            self.fps.addItem(t, k)
        self.fps.setCurrentIndex(max(0, self.fps.findData(self.o.frame_mode())))
        f.addRow("Fotogramas", self.fps)
        f.addRow("", label("Automático elige un ritmo que divide exacto la frecuencia de tu monitor (165 Hz → 82,5 FPS): "
                           "cada imagen dura lo mismo en pantalla y desaparecen los micro tirones. Sube de 60 solo si el "
                           "juego tiene los FPS desbloqueados (🎯 Trucos → «✨ Recomendadas para PC»; muchos juegos del "
                           "Xbox 360 se limitan a 30 aunque el contador marque más). Si tu monitor tiene G-Sync o "
                           "FreeSync, actívalo en el panel de NVIDIA/AMD: elimina el resto de tirones.", "Hint", wrap=True))
        self.scale = QComboBox()
        self.scale.addItem(f"Automática · según tu tarjeta (ahora {int(self.o.resolution_scale or 1)}×)", 0)
        for n in (1, 2, 3):
            self.scale.addItem({1: "1× (nativo 720p)", 2: "2× (1440p interno)", 3: "3× (2160p interno)"}[n], n)
        self.scale.setCurrentIndex(0 if self.o.resolution_auto else max(1, min(3, int(self.o.resolution_scale))))
        f.addRow("Escala de resolución", self.scale)
        self.effect = QComboBox()
        avail = present_effects_supported(self.exe) if self.exe else None
        effects = [(k, t) for k, t in PRESENT_EFFECTS if avail is None or k in avail]
        for k, t in effects:
            self.effect.addItem(t, k)
        self.effect.setCurrentIndex(max(0, [k for k, _ in effects].index(self.o.present_effect)
                                        if self.o.present_effect in dict(effects) else 0))
        missing = [(k, t) for k, t in PRESENT_EFFECTS if (k, t) not in effects]
        for k, t in missing:      # se ven, pero no se pueden elegir: el runtime oficial no los trae
            self.effect.addItem(f"{t} · necesita rexglue con FidelityFX", k)
            item = self.effect.model().item(self.effect.count() - 1)
            if item is not None:
                item.setEnabled(False)
        if missing:
            self.effect.setToolTip("El SDK oficial de rexglue se publica sin AMD FidelityFX (FSR/CAS). Para más "
                                   "nitidez usa la escala de resolución «Automática» o 2×: el juego se dibuja por "
                                   "dentro a 1440p (supermuestreo real), que se ve mejor que FSR desde 720p.")
        f.addRow("Escalado / nitidez", self.effect)
        self.post = QComboBox()
        for k, t in POST_EFFECTS:
            self.post.addItem(t, k)
        self.post.setCurrentIndex([k for k, _ in POST_EFFECTS].index(self.o.swap_post_effect)
                                  if self.o.swap_post_effect in dict(POST_EFFECTS) else 0)
        f.addRow("Antialiasing", self.post)
        self.aniso = QComboBox()
        aniso_vals = ((-1, "El que pida el juego"), (0, "Desactivado"), (2, "2×"), (3, "4× (predeterminado)"),
                      (4, "8×"), (5, "16×"))      # xenos::AnisoFilter
        for val, t in aniso_vals:
            self.aniso.addItem(t, val)
        idx = [v for v, _t in aniso_vals].index(int(self.o.anisotropic_override)) \
            if int(self.o.anisotropic_override) in [v for v, _t in aniso_vals] else 3
        self.aniso.setCurrentIndex(idx)
        f.addRow("Filtrado anisotrópico", self.aniso)
        self.letter = QCheckBox("Mantener relación de aspecto (barras negras)")
        self.letter.setChecked(self.o.present_letterbox)
        f.addRow(self.letter)
        f.addRow(label("COMPATIBILIDAD (SI VES PANTALLA NEGRA)", "Section"))
        self.rpath = QComboBox()
        for k, t in (("", "Automática"), ("rtv", "RTV · rápida"), ("rov", "ROV · precisa (más compatible)")):
            self.rpath.addItem(t, k)
        self.rpath.setCurrentIndex(max(0, self.rpath.findData(self.o.render_path)))
        f.addRow("Ruta de render", self.rpath)
        self.readback = QCheckBox("Leer en la CPU lo que el juego dibuja en texturas (menús, transiciones)")
        self.readback.setChecked(self.o.readback_resolve)
        self.invfetch = QCheckBox("Permitir datos de textura/vértice no válidos (no descarta dibujos)")
        self.invfetch.setChecked(self.o.allow_invalid_fetch)
        f.addRow(self.readback)
        f.addRow(self.invfetch)
        self.ask = QCheckBox("Mostrar el menú de motor al pulsar ▶ Jugar")
        self.ask.setChecked(self.o.ask_engine_on_play)
        f.addRow(self.ask)
        return w

    def _open_packs(self):
        from .mods_ui import ModsDialog
        ModsDialog(self, self.project.root, self.project.name).exec()

    def _controls(self):
        outer = QWidget()
        ov = QVBoxLayout(outer)
        top = QFormLayout()
        self.backend = QComboBox()
        self.backend.addItem("Automático (recomendado: XInput con mandos Xbox, SDL con el resto)", "auto")
        self.backend.addItem("SDL (Xbox, PlayStation, Switch y genéricos)", "sdl")
        self.backend.addItem("XInput (solo mandos tipo Xbox)", "xinput")
        self.backend.setCurrentIndex(max(0, self.backend.findData(self.o.input_backend)))
        top.addRow("Mandos", self.backend)
        top.addRow("", label("Con mandos de Xbox, XInput es más estable: el controlador SDL de rexglue 0.10 puede "
                             "cerrar el juego si el mando se desconecta y reconecta.", "Hint", wrap=True))
        self.hide_cursor = QCheckBox("Esconder el puntero del ratón al jugar con mando (vuelve al mover el ratón)")
        self.hide_cursor.setChecked(self.o.hide_cursor)
        top.addRow(self.hide_cursor)
        self.guide = QCheckBox("Menú Guía con el botón Xbox/PS del mando o la tecla Inicio (logros, tiempo de "
                               "juego, ajustes y salir del juego sin ratón)")
        self.guide.setChecked(self.o.guide_menu)
        top.addRow(self.guide)
        self.btn_style = QComboBox()
        for k, t in (("auto", "Automático: los del mando conectado (DualSense/DualShock → PlayStation)"),
                     ("xbox", "Xbox (los originales del juego)"), ("playstation", "PlayStation (✕ ○ □ △)")):
            self.btn_style.addItem(t, k)
        self.btn_style.setCurrentIndex(max(0, self.btn_style.findData(self.o.button_style)))
        packs_btn = QPushButton("🎨 Packs y texturas…")
        packs_btn.clicked.connect(self._open_packs)
        style_row = QWidget()
        sr = QHBoxLayout(style_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.addWidget(self.btn_style, 1)
        sr.addWidget(packs_btn)
        top.addRow("Iconos de botones", style_row)
        top.addRow("", label("Cambia los botones dibujados en el juego (texturas .xpr) y en el menú Guía. Los packs "
                             "permiten reemplazar texturas y archivos del juego; los originales se guardan.",
                             "Hint", wrap=True))
        self.mnk = QCheckBox("Jugar con teclado y ratón (se emula un mando de Xbox 360)")
        self.mnk.setChecked(self.o.mnk_mode)
        self.mnk_auto = QCheckBox("Encenderlo solo cuando no haya ningún mando conectado")
        self.mnk_auto.setChecked(bool(getattr(self.o, "mnk_auto", True)))
        self.layout_cb = QComboBox()
        self.layout_cb.addItem("Automático · el que le toque al juego", mnklayouts.AUTO)
        for key in mnklayouts.ORDER:
            self.layout_cb.addItem(mnklayouts.title(key), key)
        cur = getattr(self.o, "mnk_layout", mnklayouts.AUTO)
        self.layout_cb.setCurrentIndex(max(0, self.layout_cb.findData(cur)))
        self.layout_hint = label("", "Hint", wrap=True)
        self.mouse = QCheckBox("Usar el ratón como stick derecho")
        self.mouse.setChecked(self.o.mnk_mouse)
        self.sens = QDoubleSpinBox()
        self.sens.setRange(0.1, 5.0)
        self.sens.setSingleStep(0.1)
        self.sens.setValue(float(self.o.mnk_sensitivity))
        top.addRow(self.mnk)
        top.addRow(self.mnk_auto)
        top.addRow("Reparto de teclas", self.layout_cb)
        top.addRow("", self.layout_hint)
        top.addRow(self.mouse)
        top.addRow("Sensibilidad del ratón", self.sens)
        ov.addLayout(top)
        ov.addWidget(label("Teclas (varias separadas por coma; combinaciones con +, p. ej. Shift+Up):", "Hint",
                           wrap=True))
        grid_w = QWidget()
        g = QGridLayout(grid_w)
        g.setVerticalSpacing(6)
        self.keys = {}
        for i, k in enumerate(DEFAULT_KEYBINDS):
            e = QLineEdit(self.o.keybinds.get(k, DEFAULT_KEYBINDS[k]))
            e.setPlaceholderText(DEFAULT_KEYBINDS[k])
            self.keys[k] = e
            g.addWidget(label(KEYBIND_LABELS[k]), i // 2, (i % 2) * 2)
            e.setMinimumWidth(170)
            g.addWidget(e, i // 2, (i % 2) * 2 + 1)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(3, 1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(grid_w)
        ov.addWidget(sc, 1)
        reset = QPushButton("Restaurar teclas por defecto")
        reset.clicked.connect(lambda: [e.setText(DEFAULT_KEYBINDS[k]) for k, e in self.keys.items()])
        ov.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)
        self.layout_cb.currentIndexChanged.connect(self._layout_changed)
        self._layout_changed(init=True)
        self.mnk.toggled.connect(lambda on: (self.mouse.setEnabled(on), self.sens.setEnabled(on),
                                             self.mnk_auto.setEnabled(on), self.layout_cb.setEnabled(on),
                                             [e.setEnabled(on) for e in self.keys.values()]))
        self.mnk.toggled.emit(self.mnk.isChecked())
        return outer

    def _layout_changed(self, _index=None, init=False):
        """Rellena las teclas con el reparto elegido («automático» deja ver el que le tocaría al juego)."""
        key = self.layout_cb.currentData()
        auto = key == mnklayouts.AUTO
        if auto:
            key, _ = mnklayouts.suggest(getattr(self.project, "name", "") or "",
                                        getattr(self.project, "title_id", "") or "",
                                        os.path.splitext(os.path.basename(self.exe or ""))[0])
            key = key or "teclado"
            self.layout_hint.setText("Por el nombre del juego le toca «" + mnklayouts.title(key) + "». "
                                     + mnklayouts.LAYOUTS[key]["ayuda"]
                                     + " Se vuelve a elegir en cada partida; para cambiar teclas sueltas, "
                                       "elige el reparto en la lista en vez de dejarlo en automático.")
        else:
            self.layout_hint.setText(mnklayouts.LAYOUTS[key]["ayuda"])
        if init and not auto:
            return        # con un reparto elegido a mano mandan las teclas guardadas
        kb = mnklayouts.keybinds(key)
        for k, e in self.keys.items():
            e.setText(kb[k])
        self.mouse.setChecked(bool(mnklayouts.LAYOUTS[key]["mouse"]))
        self.sens.setValue(float(mnklayouts.LAYOUTS[key]["sens"]))

    def _audio_repair(self):
        w, f = self._tab()
        self.lang = language_combo(self.project.root, self.o)
        f.addRow("Idioma del juego", self.lang)
        f.addRow("", label("Se ofrecen los idiomas encontrados en los archivos del juego. Algunos juegos piden el "
                           "idioma de otra forma (XGetLanguage) y rexglue 0.10 responde siempre inglés: en ese "
                           "caso el juego seguirá en inglés.", "Hint", wrap=True))
        self.mute = QCheckBox("Silenciar el audio")
        self.mute.setChecked(self.o.audio_mute)
        f.addRow(self.mute)
        f.addRow(label("LICENCIA (JUEGOS ARCADE)", "Section"))
        self.lic = QComboBox()
        for k, t in LICENSE_CHOICES:
            self.lic.addItem(t, k)
        self.lic.setCurrentIndex(max(0, [k for k, _t in LICENSE_CHOICES].index(self.o.license)
                                     if self.o.license in dict(LICENSE_CHOICES) else 0))
        f.addRow("Licencia", self.lic)
        f.addRow("", label("Los Arcade comprueban si tienes la licencia del juego completo; sin ella muestran "
                           "«Desbloquear juego completo» y funcionan como demo. Es la misma opción que "
                           "license_mask de Xenia, para jugar a tus Arcade como en tu consola. Se aplica al "
                           "lanzar el juego, sin recompilar.", "Hint", wrap=True))
        f.addRow(label("EXTENSIÓN REFORGE", "Section"))
        self.ext = QCheckBox("Perfil, Xbox Live simulado, idioma real y notificación de logros")
        self.ext.setChecked(self.o.reforge_ext)
        f.addRow(self.ext)
        f.addRow("", label("Se añade al proyecto al compilar (src/reforge_ext.cpp). Desactívalo solo si un juego "
                           "no compila con ella; al recompilar se quita sola.", "Hint", wrap=True))
        f.addRow(label("REPARACIÓN DEL ARRANQUE", "Section"))
        self.auto = QCheckBox("Reparar automáticamente cuando el juego se cierre por una función no registrada")
        self.auto.setChecked(self.o.auto_repair)
        f.addRow(self.auto)
        self.rounds = QSpinBox()
        self.rounds.setRange(1, 200)
        self.rounds.setValue(int(self.o.repair_max_rounds))
        f.addRow("Máximo de rondas", self.rounds)
        self.watch = QSpinBox()
        self.watch.setRange(10, 600)
        self.watch.setSuffix(" s")
        self.watch.setValue(int(self.o.repair_watch_seconds))
        f.addRow("Considerar que arrancó si sigue abierto", self.watch)
        f.addRow("", label("Cada ronda declara la dirección del fallo, regenera el código, compila y vuelve a "
                           "lanzar el juego. Las direcciones quedan en reforge_functions.toml.", "Hint", wrap=True))
        return w

    # ---------------------------------------------------------------- guardar
    def save(self):
        o = self.o
        o.fullscreen = self.full.isChecked()
        if self.fps.currentData() != o.frame_mode():
            o.fps_cap = 0.0        # elegido a mano: se quita el tope automático
        o.fps_mode = self.fps.currentData()
        o.vsync = o.fps_mode != "unlimited"
        if int(self.scale.currentData()) == 0:
            o.resolution_auto = True
        else:
            o.resolution_auto = False
            o.resolution_scale = int(self.scale.currentData())
        o.present_effect = self.effect.currentData()
        o.swap_post_effect = self.post.currentData()
        o.anisotropic_override = int(self.aniso.currentData())
        o.present_letterbox = self.letter.isChecked()
        o.render_path = self.rpath.currentData()
        o.readback_resolve = self.readback.isChecked()
        o.allow_invalid_fetch = self.invfetch.isChecked()
        if self.ask.isChecked() != o.ask_engine_on_play:
            o.ask_engine_chosen = True
        o.ask_engine_on_play = self.ask.isChecked()
        o.input_backend = self.backend.currentData()
        o.input_backend_chosen = o.input_backend != "auto"
        o.hide_cursor = self.hide_cursor.isChecked()
        o.guide_menu = self.guide.isChecked()
        o.button_style = self.btn_style.currentData()
        if self.exe:
            try:
                from .texswap import set_menu_style
                set_menu_style(self.exe, "" if o.button_style == "auto" else o.button_style)
            except OSError:
                pass
        o.mods_disabled = GameOptions.load(self.project.root).mods_disabled   # lo guarda el diálogo de packs
        o.mnk_mode = self.mnk.isChecked()
        o.mnk_auto = self.mnk_auto.isChecked()
        o.mnk_layout = self.layout_cb.currentData()
        o.mnk_mouse = self.mouse.isChecked()
        o.mnk_sensitivity = float(self.sens.value())
        o.keybinds = {k: (e.text().strip() or DEFAULT_KEYBINDS[k]) for k, e in self.keys.items()}
        o.audio_mute = self.mute.isChecked()
        o.license = self.lic.currentData()
        set_language_key(o, self.lang.currentData())
        o.auto_repair = self.auto.isChecked()
        o.reforge_ext = self.ext.isChecked()
        o.repair_max_rounds = int(self.rounds.value())
        o.repair_watch_seconds = int(self.watch.value())
        o.save(self.project.root)
        if self.exe and os.path.isfile(self.exe):
            write_runtime_config(self.exe, o)
        self.accept()


ENGINE_PRESETS = [
    ("auto", "Direct3D 12 · Estándar",
     "Lo que decide el runtime."),
    ("rtv", "Direct3D 12 · Rápido (RTV)",
     "La más rápida, pero algunos juegos muestran bloques negros o rayas en suelos y sombras: si pasa, "
     "usa Preciso (ROV)."),
    ("rtv_inv", "Direct3D 12 · Rápido + datos no válidos",
     "Rápido, sin descartar dibujos con datos raros (arregla muchas pantallas negras)."),
    ("rov", "Direct3D 12 · Precisión (ROV)",
     "Dibuja los render targets de forma exacta. Más compatible, más pesado."),
    ("rov_inv", "Direct3D 12 · Preciso + datos no válidos",
     "ROV sin descartar dibujos."),
    ("rtv_rb", "Direct3D 12 · Rápido + lectura de texturas",
     "Para juegos que necesitan leer en CPU lo que dibujan (menús tras un logo). Puede dar tirones."),
    ("compat", "Direct3D 12 · Compatibilidad máxima",
     "ROV + lectura de texturas + datos no válidos. El que más se ve, pero el más lento: usa el "
     "asistente ⚡ para encontrar uno más rápido que también funcione."),
]


class LaunchDialog(QDialog):
    """Menú previo a ▶ Jugar: elegir motor/modo de render y pantalla."""

    def __init__(self, parent, cfg, project, exe=""):
        super().__init__(parent)
        self.cfg, self.project, self.exe = cfg, project, exe
        self.o = GameOptions.load(project.root)
        self.setWindowTitle(f"Jugar · {project.name}")
        self.resize(580, 580)
        v = QVBoxLayout(self)
        v.addWidget(label("MOTOR GRÁFICO", "Section"))
        self.group = QButtonGroup(self)
        current = self.o.preset()
        for key, title, desc in ENGINE_PRESETS:
            rb = QRadioButton(title)
            rb.setProperty("preset", key)
            rb.setChecked(key == current)
            self.group.addButton(rb)
            v.addWidget(rb)
            v.addWidget(label("      " + desc, "Hint", wrap=True))
        if current == "custom":
            rb = QRadioButton("Personalizado (lo elegido en 🎮 Opciones)")
            rb.setProperty("preset", "custom")
            rb.setChecked(True)
            self.group.addButton(rb)
            v.addWidget(rb)
        vk = vulkan_in_plugin(cfg)
        rb = QRadioButton("Vulkan" + ("" if vk else " · no disponible en tu SDK"))
        rb.setEnabled(False)
        v.addWidget(rb)
        if not vk:
            v.addWidget(label("      El SDK de rexglue para Windows trae solo Direct3D 12 (rexgpu-xenos.dll no "
                              "usa vulkan-1.dll). OpenGL y Direct3D 11 no existen en rexglue.", "Hint", wrap=True))
        v.addWidget(label("PANTALLA", "Section"))
        row = QFormLayout()
        self.full = QCheckBox("Pantalla completa")
        self.full.setChecked(self.o.fullscreen)
        row.addRow(self.full)
        self.scale = QComboBox()
        for n, t in ((1, "1× (720p)"), (2, "2× (1440p)"), (3, "3× (2160p)")):
            self.scale.addItem(t, n)
        self.scale.setCurrentIndex(max(0, min(2, int(self.o.resolution_scale) - 1)))
        row.addRow("Resolución interna", self.scale)
        self.lang = language_combo(project.root, self.o)
        row.addRow("Idioma", self.lang)
        v.addLayout(row)
        v.addStretch(1)
        self.dont_ask = QCheckBox("No volver a preguntar (se cambia en 🎮 Opciones)")
        v.addWidget(self.dont_ask)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("▶  Jugar")
        bb.button(QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def choose(self, key):
        for b in self.group.buttons():
            if b.property("preset") == key:
                b.setChecked(True)

    def save(self):
        b = self.group.checkedButton()
        key = b.property("preset") if b else "auto"
        if key != "custom":
            self.o.apply_preset(key)
        self.o.fullscreen = self.full.isChecked()
        if int(self.scale.currentData()) != int(self.o.resolution_scale or 1):
            self.o.resolution_auto = False
        self.o.resolution_scale = int(self.scale.currentData())
        set_language_key(self.o, self.lang.currentData())
        if self.dont_ask.isChecked():
            self.o.ask_engine_on_play = False
        self.o.save(self.project.root)
        if self.exe and os.path.isfile(self.exe):
            write_runtime_config(self.exe, self.o)
        self.accept()
