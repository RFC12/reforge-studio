"""Páginas de la aplicación: Inicio, Taller, Biblioteca, XenonRecomp y Ajustes."""
import datetime
import os
import shutil
import subprocess
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from .core import (Project, cmake_build_cmd, cmake_codegen_cmd, cmake_configure_cmd, copy_tree,
                   detect_tools, find_outputs, human_size, open_path, rexglue_init_cmd, sanitize_name,
                   NO_WINDOW)
from . import autorecompile, game, sdkcompat   # noqa: F401 — import estático para que PyInstaller los empaquete
from .game_options import GameOptions, ensure_paths_hook, write_runtime_config


def _validate_sdk(cfg, root, build, env, ctx):
    """Valida el SDK contra el proyecto. Nunca tumba la compilación por un fallo propio: si la validación no
    está disponible o revienta por un motivo inesperado, se avisa y se sigue; solo detiene el build cuando el
    SDK es de verdad incompatible y no hay alternativa (sdkcompat lanza ese error a propósito, con mensaje claro)."""
    try:
        sdkcompat.ensure_compatible(cfg, root, build, env, ctx)
    except RuntimeError:
        raise            # incompatibilidad real y sin recambio: mensaje claro, debe detenerse
    except Exception as e:      # noqa: BLE001 — cualquier otro fallo del salvaguarda no debe romper el build
        ctx.log(f"(validación de SDK omitida por un fallo interno: {e})", "dim")


def prepare_project(root, ctx):
    """Antes de compilar: gancho de carpeta del juego + extensión de perfil, idioma y logros."""
    if ensure_paths_hook(root):
        ctx.log("Gancho OnConfigurePaths añadido a src/*_app.h: el .exe encuentra assets aunque se abra "
                "con doble clic.", "dim")
    try:
        from .gamedb import apply as apply_gamedb
        apply_gamedb(root, ctx.log)
    except Exception as e:      # noqa: BLE001 — la base de compatibilidad nunca debe tumbar la preparación
        ctx.log(f"(base de compatibilidad omitida por un fallo interno: {e})", "dim")
        from .optimizer import apply_gfx_hint, apply_title_hint
        for m in (apply_title_hint(root), apply_gfx_hint(root)):
            if m:
                ctx.log(m, "ok")
    try:
        from .engine import apply_engine_profile
        apply_engine_profile(root, ctx.log)
    except Exception as e:      # noqa: BLE001
        ctx.log(f"No se pudo detectar el motor del juego: {e}", "warn")
    from .ext_cpp import ensure_reforge_ext, ext_unavailable_reason, remove_reforge_ext
    if not GameOptions.load(root).reforge_ext:
        removed = remove_reforge_ext(root)
        ctx.log("Extensión ReForge desactivada en 🎮 Opciones" + (": quitada (" + ", ".join(removed) + ")."
                                                                 if removed else "."), "warn")
        return
    sin_menu = ext_unavailable_reason(root)
    if sin_menu:
        ctx.log(f"Menú Guía no disponible en este proyecto: {sin_menu}", "warn")
        return
    changed = ensure_reforge_ext(root)
    if changed:
        ctx.log("Extensión ReForge (menú Guía, perfil, Live simulado, idioma y notificación de logros): "
                + ", ".join(changed), "ok")
    else:
        ctx.log("Proyecto preparado (gancho de carpeta y extensión ReForge al día).", "dim")
from .runner import PipelineRunner, Step
from .theme import ACCENTS
from .widgets import GameCard, LogView, PathField, StepTracker, Tile, cover_pixmap, label, repolish
from .xex import read_xex_info, read_xex_info_bytes
from .xcontent import XContentError, XContentPackage, find_package, read_magic
from .xiso import XisoError, XisoImage

# Orígenes admitidos (orden del desplegable «Origen del juego»)
SOURCE_MODES = [
    ("iso", "Imagen ISO de Xbox 360 (.iso)"),
    ("pkg", "Paquete GOD / XBLA (Games on Demand, Arcade, demos)"),
    ("xex", "Archivo XEX (default.xex u otro .xex)"),
    ("folder", "Carpeta ya extraída"),
    ("none", "Sin origen (solo compilar)"),
]
SOURCE_HINTS = {
    "iso": "Admite ISO completas (XGD1/2/3) y XISO recortadas. Si eliges un paquete GOD/XBLA o un .xex, "
           "se detecta solo.",
    "pkg": "Elige la carpeta del juego (la del Title ID) o el archivo sin extensión dentro de 00007000 (GOD) "
           "o 000D0000 (XBLA). En GOD, la carpeta «<archivo>.data» con Data0000… debe estar al lado.",
    "xex": "Se copia la carpeta del .xex con todos sus archivos; el .xex elegido pasa a ser default.xex.",
    "folder": "La carpeta debe contener default.xex en su raíz.",
}


def detect_source_kind(path):
    """«iso», «pkg», «xex» o «folder» según lo que haya en la ruta ('' si no se reconoce)."""
    if not path:
        return ""
    if os.path.isdir(path):
        if os.path.isfile(os.path.join(path, "default.xex")):
            return "folder"
        return "pkg" if find_package(path) else ""
    if not os.path.isfile(path):
        return ""
    low = path.lower()
    if low.endswith(".xex"):
        return "xex"
    if read_magic(path):
        return "pkg"
    if low.endswith((".iso", ".xiso")):
        return "iso"
    return ""


def folder_stats(path, limit=20000):
    n = total = 0
    for dirpath, _d, files in os.walk(path):
        for fn in files:
            n += 1
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
            if n >= limit:
                return n, total, True
    return n, total, False

# El rexglue actual exige el default.xex en el init, así que el juego se extrae primero.
STEP_DEFS = [
    ("assets", "Juego → assets", "Extraer ISO, GOD o XBLA, o copiar"),
    ("verify", "Verificar XEX", "default.xex en la raíz"),
    ("init", "Crear proyecto", "rexglue init --xex-path"),
    ("configure", "Configurar", "cmake -DCMAKE_BUILD_TYPE"),
    ("codegen", "Codegen", "<nombre>_codegen"),
    ("build", "Compilar", "cmake --build --parallel"),
]
SHORT = {"init": "Proyecto", "assets": "Assets", "verify": "XEX", "configure": "CMake",
         "codegen": "Codegen", "build": "Compilar"}


def scroll_wrap(widget):
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setWidget(widget)
    s.setFrameShape(QFrame.Shape.NoFrame)
    return s


def panel():
    f = QFrame()
    f.setObjectName("Panel")
    v = QVBoxLayout(f)
    v.setContentsMargins(20, 18, 20, 18)
    v.setSpacing(10)
    return f, v


# =============================================================================
#  INICIO
# =============================================================================
class HomePage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        outer.addWidget(scroll_wrap(inner))
        v = QVBoxLayout(inner)
        v.setContentsMargins(36, 10, 36, 30)
        v.setSpacing(18)

        # Aviso compacto cuando falta preparar el entorno
        self.env_banner = QFrame()
        self.env_banner.setObjectName("Card")
        bh = QHBoxLayout(self.env_banner)
        bh.setContentsMargins(18, 10, 12, 10)
        bh.addWidget(label("⚠", "TileGlyph"))
        self.env_banner_text = label("Falta preparar el entorno de compilación.", "CardTitle", wrap=True)
        bh.addWidget(self.env_banner_text, 1)
        b_env = QPushButton("⚡  Abrir Entorno")
        b_env.setObjectName("Primary")
        b_env.clicked.connect(lambda: win.go("env"))
        bh.addWidget(b_env)
        self.env_banner.hide()
        v.addWidget(self.env_banner)

        grid = QGridLayout()
        grid.setSpacing(14)
        hero = Tile("⬢", "Nuevo juego desde ISO",
                    "Extrae la imagen, crea el proyecto rexglue, genera el código y compila "
                    "el ejecutable para PC en un solo flujo.", hero=True, w=480, h=300)
        hero.clicked.connect(lambda: win.new_from_iso())
        grid.addWidget(hero, 0, 0, 2, 2)
        tiles = [
            ("▦", "Biblioteca", "Tus proyectos recompilados", lambda: win.go("library")),
            ("⚒", "Taller", "Pipeline paso a paso", lambda: win.go("workshop")),
            ("⟁", "XenonRecomp", "Análisis XEX y TOML", lambda: win.go("xenon")),
            ("⚙", "Ajustes", "Herramientas y compilador", lambda: win.go("settings")),
        ]
        for i, (g, t, s, cb) in enumerate(tiles):
            tile = Tile(g, t, s)
            tile.clicked.connect(cb)
            grid.addWidget(tile, i // 2, 2 + i % 2)
        for c in range(4):
            grid.setColumnStretch(c, 1)
        v.addLayout(grid, 3)

        v.addWidget(label("RECIENTES", "Section"))
        self.recent_row = QHBoxLayout()
        self.recent_row.setSpacing(14)
        v.addLayout(self.recent_row, 1)

        self.patch_section = label("COMPLEMENTOS INSTALADOS", "Section")
        self.patch_section.hide()
        v.addWidget(self.patch_section)
        self.patch_row = QHBoxLayout()
        self.patch_row.setSpacing(14)
        self.patch_row.addStretch(1)
        v.addLayout(self.patch_row)
        self._patch_tiles = []   # (owner, tile)

        v.addWidget(label("ESTADO DEL ENTORNO", "Section"))
        self.env_label = label("", "Hint", wrap=True)
        v.addWidget(self.env_label)
        self.hero = hero

    def set_env_status(self, missing):
        names = {"rexglue": "rexglue", "vs": "Visual Studio C++", "clang": "Clang 20+", "cmake": "CMake",
                 "ninja": "Ninja", "vcredist": "Visual C++ Redistributable"}
        if missing:
            self.env_banner_text.setText("Falta preparar el entorno: " +
                                         ", ".join(names.get(m, m) for m in missing))
        self.env_banner.setVisible(bool(missing))

    def add_patch_tile(self, glyph, title, subtitle, callback, owner=""):
        t = Tile(glyph, title, subtitle, w=220, h=110)
        t.setMaximumWidth(320)
        t.clicked.connect(callback)
        self.patch_row.insertWidget(self.patch_row.count() - 1, t)
        self._patch_tiles.append((owner, t))
        self.patch_section.show()

    def remove_patch_tiles(self, owner):
        for o, t in list(self._patch_tiles):
            if o == owner:
                self.patch_row.removeWidget(t)
                t.deleteLater()
                self._patch_tiles.remove((o, t))
        self.patch_section.setVisible(bool(self._patch_tiles))

    def refresh(self):
        while self.recent_row.count():
            it = self.recent_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        recents = self.win.lib.recent(4)
        if not recents:
            self.recent_row.addWidget(label("Aún no hay proyectos. Empieza con «Nuevo juego desde ISO».",
                                            "Hint"))
        for p in recents:
            sub = " · ".join(x for x in (p.title_id and f"ID {p.title_id}", p.status, p.updated) if x)
            t = GameCard(p.root, p.name, sub, w=210, h=116)
            t.clicked.connect(lambda pr=p: self.win.open_project(pr))
            self.recent_row.addWidget(t)
        self.recent_row.addStretch(1) if len(recents) < 4 else None
        cfg = self.win.cfg
        parts = []
        for key, name in (("rexglue", "rexglue"), ("cmake", "CMake")):
            path = cfg.tool(key)
            ok = os.path.isfile(path) or shutil.which(path)
            parts.append(f"{'✔' if ok else '✖'} {name}")
        parts.append(f"⚡ {cfg.jobs} hilos de compilación")
        parts.append(f"📁 {cfg.workspace}")
        self.env_label.setText("     ".join(parts))


# =============================================================================
#  TALLER (pipeline completo)
# =============================================================================
class WorkshopPage(QWidget):
    project_changed = Signal()

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.runner = PipelineRunner(self)
        self.current = None
        self._auto_name = True
        self._result = {}
        self._mode = "build"            # build | play | repair
        self._watch_result = None
        self._repair_round = 0
        self._repair_seen = set()
        self._auto_maint = set()
        self._play_after_build = False  # al terminar de compilar, abrir el juego solo
        self.restarting = set()         # proyectos que el Taller cerró para recompilar (no es un fallo)
        self.handled_logs = set()       # partidas ya analizadas aquí (el vigilante general no las repite)
        self._live = None               # lector del log en vivo de la partida vigilada
        self._session = None            # juego abierto que se sigue vigilando
        self._session_timer = QTimer(self)
        self._session_timer.setInterval(1000)
        self._session_timer.timeout.connect(self._poll_session)
        self._active_keys = []

        root = QHBoxLayout(self)
        root.setContentsMargins(36, 10, 36, 30)
        root.setSpacing(20)

        # ---------------- columna izquierda: formulario ----------------
        form_w = QWidget()
        fv = QVBoxLayout(form_w)
        fv.setContentsMargins(0, 0, 8, 0)
        fv.setSpacing(14)

        p1, v1 = panel()
        v1.addWidget(label("1 · ORIGEN DEL JUEGO", "Section"))
        self.mode = QComboBox()
        self.mode.addItems([t for _k, t in SOURCE_MODES])
        self.mode.currentIndexChanged.connect(self._mode_changed)
        v1.addWidget(self.mode)
        self.src = PathField("file", "Juegos de Xbox 360: ISO, XEX o paquete GOD/XBLA (*)",
                             "Selecciona la ISO, el paquete GOD/XBLA o el .xex del juego…")
        self.src.changed.connect(lambda _t: self._scan_timer.start())
        v1.addWidget(self.src)
        self.src_info = label(SOURCE_HINTS["iso"], "Hint", wrap=True)
        v1.addWidget(self.src_info)
        fv.addWidget(p1)

        p2, v2 = panel()
        v2.addWidget(label("2 · PROYECTO", "Section"))
        f2 = QFormLayout()
        f2.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        f2.setVerticalSpacing(8)
        self.name = QLineEdit()
        self.name.setPlaceholderText("ej. alice")
        self.name.textEdited.connect(self._name_edited)
        self.name.textChanged.connect(self._update_root)
        self.parent_dir = PathField("dir", placeholder="Carpeta donde se crean los proyectos")
        self.parent_dir.setText(win.cfg.workspace)
        self.parent_dir.changed.connect(self._update_root)
        f2.addRow("Nombre", self.name)
        f2.addRow("Ubicación", self.parent_dir)
        v2.addLayout(f2)
        self.root_lbl = label("", "Hint", wrap=True)
        v2.addWidget(self.root_lbl)
        fv.addWidget(p2)

        p3, v3 = panel()
        v3.addWidget(label("3 · PASOS", "Section"))
        self.checks = {}
        for key, title, sub in STEP_DEFS:
            cb = QCheckBox(f"{title}  —  {sub}")
            cb.setChecked(True)
            cb.toggled.connect(self._refresh_tracker)
            self.checks[key] = cb
            v3.addWidget(cb)
        self.clean = QCheckBox("Borrar la carpeta build antes de configurar")
        v3.addWidget(self.clean)
        self.open_after = QCheckBox("Abrir la carpeta del ejecutable al terminar")
        self.open_after.setChecked(True)
        v3.addWidget(self.open_after)
        fv.addWidget(p3)

        btns = QHBoxLayout()
        self.start_btn = QPushButton("▶   Iniciar recompilación")
        self.start_btn.setObjectName("Primary")
        self.start_btn.clicked.connect(self.start)
        self.cancel_btn = QPushButton("■  Cancelar")
        self.cancel_btn.setObjectName("Danger")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.runner.cancel)
        btns.addWidget(self.start_btn, 1)
        btns.addWidget(self.cancel_btn)
        fv.addLayout(btns)
        fv.addStretch(1)

        left = scroll_wrap(form_w)
        left.setFixedWidth(450)
        root.addWidget(left)

        # ---------------- columna derecha: progreso y log ----------------
        rv = QVBoxLayout()
        rv.setSpacing(12)
        head = QHBoxLayout()
        self.status_lbl = label("Listo", "BigNumber")
        head.addWidget(self.status_lbl, 1)
        self.stats_lbl = label("", "Hint")
        head.addWidget(self.stats_lbl)
        rv.addLayout(head)
        self.tracker = StepTracker([SHORT[k] for k, _t, _s in STEP_DEFS])
        rv.addWidget(self.tracker)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(8)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        rv.addWidget(self.progress)
        self.log = LogView()
        rv.addWidget(self.log, 1)
        bot = QHBoxLayout()
        self.btn_proj = QPushButton("📁  Proyecto")
        self.btn_proj.clicked.connect(lambda: open_path(self._root()))
        self.btn_out = QPushButton("🎮  Carpeta")
        self.btn_out.clicked.connect(self._open_output)
        self.btn_out.setEnabled(False)
        self.btn_out.setToolTip("Abrir la carpeta del ejecutable recompilado")
        self.btn_save = QPushButton("💾  Log")
        self.btn_save.clicked.connect(self._save_log)
        self.btn_save.setToolTip("Guardar el log en la carpeta logs del proyecto")
        self.btn_upd = QPushButton("⬆  Actualización")
        self.btn_upd.setToolTip("Instalar o quitar la actualización del juego (title update / default.xexp)")
        self.btn_upd.clicked.connect(self.open_update)
        self.btn_upd.setEnabled(False)
        self.btn_extra = QPushButton("💿  Discos y DLC")
        self.btn_extra.setToolTip("Añade al juego recompilado sus otros discos, contenido descargable (DLC), el "
                                  "contenido que instalaba el disco 2 y la actualización: eliges la carpeta del "
                                  "juego (GOD/Content) o la ISO y ReForge encuentra e instala todo")
        self.btn_extra.clicked.connect(self.open_extras)
        self.btn_extra.setEnabled(False)
        self.btn_cheats = QPushButton("🎯  Trucos")
        self.btn_cheats.setToolTip("Trucos y parches de la base de datos de Xenia Canary para este juego")
        self.btn_cheats.clicked.connect(self.open_cheats)
        self.btn_cheats.setEnabled(False)
        self.btn_clear = QPushButton("Limpiar")
        self.btn_clear.clicked.connect(self.log.clear_log)
        self.btn_play = QPushButton("▶  Jugar")
        self.btn_play.setObjectName("Primary")
        self.btn_play.setToolTip("Ejecuta el .exe x64 recompilado con los archivos del juego (assets)")
        self.btn_play.clicked.connect(self.play)
        self.btn_play.setEnabled(False)
        self.btn_lnk = QPushButton("🖥  Escritorio")
        self.btn_lnk.setToolTip("Crea en el Escritorio el acceso al lanzador del juego (motor, idioma, controles)")
        self.btn_lnk.clicked.connect(self.make_shortcut)
        self.btn_lnk.setEnabled(False)
        self.btn_opts = QPushButton("🎮  Opciones")
        self.btn_opts.setToolTip("Gráficos, controles (mando / teclado y ratón), audio y reparación automática")
        self.btn_opts.clicked.connect(self.open_options)
        self.btn_optim = QPushButton("⚡  Optimizar")
        self.btn_optim.setToolTip("Rendimiento según tu equipo y asistente para el modo de imagen más rápido")
        self.btn_optim.clicked.connect(self.open_optimizer)
        self.btn_fix = QPushButton("🔧  Reparar")
        self.btn_fix.setToolTip("Lee el último log del juego y repara el fallo de arranque (función no registrada)")
        self.btn_fix.clicked.connect(self.repair_from_log)
        self.btn_fix.setEnabled(False)
        self.btn_sweep = QPushButton("🔬  Barrido completo")
        self.btn_sweep.setToolTip("Revisa de una vez todas las capas (compilación Release, XEX, archivos del juego, "
                                  "código recompilado, avisos del compilador, mandos, rendimiento), corrige lo que "
                                  "pueda, recompila, prueba el arranque y repara en rondas. Al final, un informe.")
        self.btn_sweep.clicked.connect(self.full_sweep)
        self.btn_sweep.setEnabled(False)
        self._sweep = False
        self.btn_out.setText("📂  Carpeta")
        for b in (self.btn_play, self.btn_optim, self.btn_fix, self.btn_opts, self.btn_lnk):
            b.setMinimumWidth(120)
            bot.addWidget(b, 1)
        rv.addLayout(bot)
        bot2 = QHBoxLayout()
        for b in (self.btn_proj, self.btn_out, self.btn_save, self.btn_upd, self.btn_extra, self.btn_cheats,
                  self.btn_sweep):
            bot2.addWidget(b)
        bot2.addStretch(1)
        bot2.addWidget(self.btn_clear)
        rv.addLayout(bot2)
        root.addLayout(rv, 1)

        self.runner.log.connect(self.log.write)
        self.runner.progress.connect(self._on_progress)
        self.runner.step_state.connect(self._on_step_state)
        self.runner.finished.connect(self._on_finished)

        self._scan_timer = QTimer(self)
        self._scan_timer.setSingleShot(True)
        self._scan_timer.setInterval(350)
        self._scan_timer.timeout.connect(self._scan_source)
        self._stat_timer = QTimer(self)
        self._stat_timer.setInterval(500)
        self._stat_timer.timeout.connect(self._update_stats)
        self._update_root()
        self._refresh_tracker()

    # ---------------------------------------------------------------- helpers
    def _mode_key(self):
        return SOURCE_MODES[max(0, self.mode.currentIndex())][0]

    def _set_mode(self, key):
        self.mode.setCurrentIndex([k for k, _t in SOURCE_MODES].index(key))

    def _root(self):
        name = self.name.text().strip()
        parent = self.parent_dir.text()
        return os.path.abspath(os.path.join(parent, name)) if (name and parent) else ""

    def _name_edited(self, _t):
        self._auto_name = not self.name.text().strip()

    def _update_root(self, *_):
        n = self.name.text().strip()
        if n and n != sanitize_name(n):
            self.root_lbl.setObjectName("HintErr")
            self.root_lbl.setText(f"Usa solo minúsculas, números y _ (sugerido: {sanitize_name(n)}). "
                                  "El target de codegen será <nombre>_codegen.")
        else:
            r = self._root()
            self.root_lbl.setObjectName("Hint")
            self.root_lbl.setText(f"Raíz del proyecto: {r}\nAssets: {os.path.join(r, 'assets')}" if r
                                  else "Escribe un nombre de proyecto.")
        repolish(self.root_lbl)

    def _mode_changed(self, _i):
        k = self._mode_key()
        self.src.setEnabled(k != "none")
        self.src.kind = "dir" if k == "folder" else "file"
        self.src.filt = {"iso": "Juegos de Xbox 360: ISO, XEX o paquete GOD/XBLA (*)",
                         "pkg": "Paquete GOD/XBLA: archivo sin extensión (*)",
                         "xex": "Ejecutables Xbox 360 (*.xex);;Todos (*)"}.get(k, "")
        self.src.edit.setPlaceholderText({
            "iso": "Selecciona la ISO, el paquete GOD/XBLA o el .xex del juego…",
            "pkg": "Paquete GOD/XBLA: archivo de cabecera o carpeta del Title ID…",
            "xex": "Selecciona el .xex del juego…",
        }.get(k, "Carpeta con el contenido del juego (default.xex)…"))
        self.checks["assets"].setChecked(k != "none")
        self._scan_source()

    def _refresh_tracker(self, *_):
        if not self.runner.running:
            self.tracker.reset([self.checks[k].isChecked() for k, _t, _s in STEP_DEFS])

    def _set_info(self, text, kind="Hint"):
        self.src_info.setObjectName(kind)
        self.src_info.setText(text)
        repolish(self.src_info)

    def _suggest_name(self, base):
        if self._auto_name or not self.name.text().strip():
            self.name.setText(sanitize_name(base))
            self._auto_name = True

    def _scan_source(self):
        k, path = self._mode_key(), self.src.text()
        if k == "none":
            self._set_info("Se usarán los assets que ya existan en el proyecto.")
            return
        if not path:
            self._set_info(SOURCE_HINTS.get(k, ""))
            return
        found = detect_source_kind(path)
        if found and found != k:
            self._set_mode(found)            # se reescanea con el modo correcto
            return
        if k == "pkg":
            try:
                with XContentPackage(path) as pkg:
                    files = pkg.files()
                    xe = pkg.find("default.xex")
                    txt = (f"✔ {pkg.layout} · {pkg.title_name or pkg.display_name or 'sin nombre'} · "
                           f"Title ID {pkg.title_id} · {len(files)} archivos · {human_size(pkg.total_size())}")
                    if pkg.content_type == 0x000B0000:
                        txt += ("\n⚠ Es una actualización del juego: compila primero el juego base y luego "
                                "instálala con «⬆ Actualización».")
                    elif not pkg.is_game:
                        txt += "\n⚠ Este paquete no es un juego (es " + pkg.content_name.lower() + \
                               "): no tiene un ejecutable que compilar."
                    elif not xe:
                        txt += "\n⚠ No se encontró default.xex en la raíz del paquete."
                    self._set_info(txt, "HintOk" if (xe and pkg.is_game) else "HintErr")
                    self._suggest_name(pkg.title_name or pkg.display_name or
                                       os.path.basename(os.path.normpath(path)))
            except XContentError as e:
                self._set_info(str(e), "HintErr")
            except OSError as e:
                self._set_info(f"No se pudo leer: {e}", "HintErr")
            return
        if k == "xex":
            if not os.path.isfile(path):
                return self._set_info("El archivo no existe.", "HintErr")
            try:
                info = read_xex_info(path)
            except Exception as e:      # noqa: BLE001
                return self._set_info(f"No es un XEX válido: {e}", "HintErr")
            folder = os.path.dirname(os.path.abspath(path))
            n, total, more = folder_stats(folder)
            txt = (f"✔ XEX · Title ID {info.get('title_id', '?')} · se copiará «{os.path.basename(folder)}» "
                   f"({'más de ' if more else ''}{n} archivos · {human_size(total)})")
            if os.path.basename(path).lower() != "default.xex":
                txt += f"\n{os.path.basename(path)} se guardará como default.xex."
            if more or total > 64 * 1024 ** 3:
                txt += "\n⚠ Esa carpeta es enorme: pon el .xex en una carpeta solo con los archivos del juego."
            self._set_info(txt, "HintErr" if more else "HintOk")
            self._suggest_name(os.path.basename(folder))
            return
        if k == "iso":
            if not os.path.isfile(path):
                return self._set_info("El archivo no existe.", "HintErr")
            try:
                with XisoImage(path) as img:
                    files = img.files()
                    xe = img.find("default.xex")
                    tid = ""
                    if xe:
                        try:
                            tid = read_xex_info_bytes(img.read_file(xe, 1024 * 1024)).get("title_id", "")
                        except Exception:
                            pass
                    txt = (f"✔ {img.layout} · {len(files)} archivos · {human_size(img.total_size())}"
                           + (f" · Title ID {tid}" if tid else ""))
                    if not xe:
                        txt += "\n⚠ No se encontró default.xex en la raíz de la imagen."
                    self._set_info(txt, "HintOk" if xe else "HintErr")
                    self._suggest_name(os.path.splitext(os.path.basename(path))[0])
            except XisoError as e:
                self._set_info(str(e), "HintErr")
            except OSError as e:
                self._set_info(f"No se pudo leer: {e}", "HintErr")
        else:
            if not os.path.isdir(path):
                return self._set_info("La carpeta no existe.", "HintErr")
            xex = os.path.join(path, "default.xex")
            if os.path.isfile(xex):
                try:
                    tid = read_xex_info(xex).get("title_id", "")
                except Exception:
                    tid = ""
                self._set_info("✔ default.xex encontrado" + (f" · Title ID {tid}" if tid else ""),
                               "HintOk")
            else:
                self._set_info("⚠ Esta carpeta no tiene default.xex en la raíz.", "HintErr")
            self._suggest_name(os.path.basename(os.path.normpath(path)))

    # ---------------------------------------------------------------- carga
    def load_project(self, p):
        if self.runner.running:
            return
        self.current = p
        self._set_mode("none")
        self.src.setText("")
        self._auto_name = False
        self.name.setText(p.name)
        self.parent_dir.setText(os.path.dirname(os.path.abspath(p.root)))
        self.checks["init"].setChecked(False)
        self.checks["assets"].setChecked(False)
        for k in ("verify", "configure", "codegen", "build"):
            self.checks[k].setChecked(True)
        self.btn_out.setEnabled(bool(p.output and os.path.exists(p.output)))
        self._update_play()
        self.status_lbl.setText(p.name)

    def new_from_iso(self):
        if self.runner.running:
            return
        self.current = None
        self._set_mode("iso")
        self.name.setText("")
        self._auto_name = True
        for cb in self.checks.values():
            cb.setChecked(True)
        self.status_lbl.setText("Listo")
        self.src.browse()

    # ---------------------------------------------------------------- pipeline
    def start(self):
        if self.runner.running:
            return
        cfg = self.win.cfg
        name = self.name.text().strip()
        if not name or name != sanitize_name(name):
            return QMessageBox.warning(self, "Nombre inválido",
                                       "Usa un nombre en minúsculas, con números o guiones bajos.")
        root = self._root()
        mode, src = self._mode_key(), self.src.text()
        keys = [k for k, _t, _s in STEP_DEFS if self.checks[k].isChecked()]
        if not keys:
            return QMessageBox.information(self, "Nada que hacer", "Activa al menos un paso.")
        if "assets" in keys:
            if mode == "none":
                keys.remove("assets")
            elif mode == "iso" and not os.path.isfile(src):
                return QMessageBox.warning(self, "Falta la ISO", "Selecciona una imagen ISO válida.")
            elif mode == "folder" and not os.path.isdir(src):
                return QMessageBox.warning(self, "Falta la carpeta", "Selecciona la carpeta del juego.")
            elif mode == "pkg" and not os.path.exists(src):
                return QMessageBox.warning(self, "Falta el paquete", "Selecciona el paquete GOD/XBLA del juego.")
            elif mode == "xex" and not os.path.isfile(src):
                return QMessageBox.warning(self, "Falta el XEX", "Selecciona el archivo .xex del juego.")
            elif mode == "xex" and folder_stats(os.path.dirname(os.path.abspath(src)))[2]:
                return QMessageBox.warning(self, "Carpeta demasiado grande",
                                           "La carpeta del .xex tiene demasiados archivos. Pon el .xex en una "
                                           "carpeta solo con los archivos del juego.")
        if "init" not in keys and not os.path.isdir(root):
            return QMessageBox.warning(self, "Proyecto inexistente",
                                       f"No existe {root}.\nActiva «Crear proyecto».")
        assets = os.path.join(root, "assets")
        if "assets" in keys and os.path.isdir(assets) and any(
                f.lower() != ".gitkeep" for f in os.listdir(assets)):
            r = QMessageBox.question(self, "assets no está vacío",
                                     "La carpeta assets ya tiene contenido. ¿Sobrescribir archivos?")
            if r != QMessageBox.StandardButton.Yes:
                return
        problems = self._preflight(keys)
        if problems:
            box = QMessageBox(self)
            box.setWindowTitle("Falta preparar el entorno")
            box.setText("Antes de recompilar hay que resolver esto:\n\n• " + "\n• ".join(problems))
            go = box.addButton("Abrir Entorno", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is go:
                self.win.go("env")
            return
        if cfg.build_type.lower() == "debug" and ({"configure", "build"} & set(keys)) \
                and not getattr(self, "_debug_ok", False):
            r = QMessageBox.question(
                self, "Compilación Debug",
                "La compilación está en «Debug» (Ajustes). Con un juego recompilado eso significa compilar mucho "
                "más lento, un .exe enorme y el juego muy lento (sin optimizaciones). ¿Cambiar a «Release»?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if r == QMessageBox.StandardButton.Yes:
                cfg.build_type = "Release"
                cfg.save()
            else:
                self._debug_ok = True
        os.makedirs(os.path.dirname(root), exist_ok=True)

        self._result = {}
        steps = self._build_steps(name, root, mode, src, keys)
        self._active_keys = keys
        self.log.clear_log()
        self.log.write(f"ReForge Studio · {datetime.datetime.now():%Y-%m-%d %H:%M:%S}", "dim")
        self.log.write(f"Proyecto «{name}» → {root}", "dim")

        enabled = [k in keys for k, _t, _s in STEP_DEFS]
        self.tracker.reset(enabled)
        p = self.win.lib.get(root) or Project(name=name, root=root)
        p.name, p.status = name, "Compilando"
        if mode != "none" and src:
            p.source = src
        self.current = self.win.lib.upsert(p)
        self.project_changed.emit()

        self._set_running(True)
        self.status_lbl.setText("Trabajando…")
        self._stat_timer.start()
        self.runner.start(steps, project_root=root)

    def _preflight(self, keys):
        cfg = self.win.cfg
        problems = []
        if "init" in keys:
            exe = cfg.tool("rexglue")
            if not (os.path.isfile(exe) or shutil.which(exe)):
                problems.append("rexglue no está instalado (Entorno → «Preparar todo» lo descarga).")
            elif not cfg.cli_flavor:
                from .toolchain import rexglue_cli_flavor
                cfg.cli_flavor = rexglue_cli_flavor(exe if os.path.isfile(exe) else shutil.which(exe),
                                                    cfg.environment()) or "project"
                cfg.save()
        if any(k in keys for k in ("configure", "codegen", "build")):
            exe = cfg.tool("cmake")
            if not (os.path.isfile(exe) or shutil.which(exe)):
                problems.append("CMake no está instalado o no se encuentra.")
            from .game import is_clang
            if not is_clang(cfg.cxx_compiler):
                problems.append("Falta configurar Clang 20+: rexglue no se puede compilar con MSVC (cl.exe). "
                                "Entorno → instala LLVM/Clang y pulsa «Aplicar configuración».")
        return problems

    def _refresh_tools(self, root):
        """Elige las versiones MÁS NUEVAS instaladas de VS, CMake, Ninja y Clang antes de compilar o reparar.

        Solo sube de versión: si la configurada ya es la más nueva (o no se puede ejecutar) no se toca. El SDK
        de rexglue se cambia solo en proyectos nuevos: en una build que funciona obligaría a recompilar todo y
        una versión *dev* nueva puede no compilar el juego.
        """
        cfg = self.win.cfg
        if not getattr(cfg, "latest_tools", True):
            return
        from . import toolchain
        build = os.path.join(root, "build")
        try:
            changes, info = toolchain.upgrade_config(cfg, allow_sdk=not os.path.isdir(build))
        except Exception as e:      # noqa: BLE001
            self.log.write(f"No se pudieron comprobar las últimas versiones de las herramientas: {e}", "dim")
            return
        line = toolchain.describe(info)
        if line:
            self.log.write("🧰 " + line, "dim")
        for c in changes:
            self.log.write("↑ " + c, "ok")
        if changes:
            cfg.save()
        newer_sdk = toolchain.sdk_update_available(cfg, info)
        if newer_sdk and os.path.isdir(build):
            self.log.write(f"Hay un SDK de rexglue más nuevo ({newer_sdk}; este proyecto usa "
                           f"{toolchain.sdk_version(cfg)}). Se usará al crear proyectos nuevos: cambiarlo aquí "
                           "obliga a recompilar el juego entero.", "dim")

    def _build_steps(self, name, root, mode, src, keys):
        cfg = self.win.cfg
        self._refresh_tools(root)
        env = cfg.environment()
        build = os.path.join(root, "build")
        assets = os.path.join(root, "assets")
        steps = []

        def do_assets(ctx):
            os.makedirs(assets, exist_ok=True)
            if mode == "iso":
                with XisoImage(src) as img:
                    files = img.files()
                    ctx.log(f"Imagen {img.layout} · {len(files)} archivos · {human_size(img.total_size())}")
                    n, total = img.extract(
                        assets,
                        progress=lambda d, t: ctx.progress(int(d * 1000 / max(t, 1)), 1000),
                        cancelled=ctx.cancelled,
                        on_file=lambda e: ctx.log(f"  {e.path}  ({human_size(e.size)})", "dim"))
            elif mode == "pkg":
                with XContentPackage(src) as pkg:
                    files = pkg.files()
                    ctx.log(f"Paquete {pkg.layout} · {pkg.title_name or pkg.display_name} · Title ID "
                            f"{pkg.title_id} · {len(files)} archivos · {human_size(pkg.total_size())}")
                    if not pkg.is_game:
                        ctx.log(f"Este paquete es {pkg.content_name.lower()}, no un juego.", "warn")
                    n, total = pkg.extract(
                        assets,
                        progress=lambda d, t: ctx.progress(int(d * 1000 / max(t, 1)), 1000),
                        cancelled=ctx.cancelled,
                        on_file=lambda e: ctx.log(f"  {e.path}  ({human_size(e.size)})", "dim"))
            elif mode == "xex":
                folder = os.path.dirname(os.path.abspath(src))
                n, total = copy_tree(folder, assets, ctx)
                if os.path.basename(src).lower() != "default.xex":
                    target = os.path.join(assets, "default.xex")
                    if os.path.isfile(target):
                        os.replace(target, os.path.join(assets, "default.xex.original"))
                        ctx.log("Había otro default.xex: se guardó como default.xex.original", "warn")
                    shutil.copy2(os.path.join(assets, os.path.basename(src)), target)
                    ctx.log(f"{os.path.basename(src)} → default.xex", "warn")
            else:
                n, total = copy_tree(src, assets, ctx)
            ctx.log(f"{n} archivos · {human_size(total)} copiados a assets", "ok")

        def do_extras(ctx):
            # DLC, contenido del disco 2, actualización y otros discos junto al juego: se instalan solos
            if mode not in ("iso", "pkg") or not src:
                return
            from .extra_content import install_extras
            try:
                done = install_extras(root, src, lambda m, *_a: ctx.log(m),
                                      progress=lambda d, t: ctx.progress(int(d * 1000 / max(t, 1)), 1000),
                                      cancelled=ctx.cancelled, main_package=src)
            except Exception as e:      # noqa: BLE001 — el juego base sigue sirviendo
                ctx.log(f"Contenido extra no instalado: {e}", "warn")
                return
            if any(done.values()):
                ctx.log("✔ Contenido extra: " + " · ".join(x for x in (
                    f"{done['discs']} disco(s) más" if done["discs"] else "",
                    f"{done['dlc']} paquete(s) de contenido/DLC" if done["dlc"] else "",
                    f"actualización {done['update']}" if done["update"] else "") if x), "ok")
            else:
                ctx.log("Sin discos extra, DLC ni actualización junto al juego.", "dim")

        def do_verify(ctx):
            if not os.path.isdir(assets):
                raise RuntimeError(f"No existe la carpeta {assets}")
            entries = os.listdir(assets)
            match = [f for f in entries if f.lower() == "default.xex"]
            if match and match[0] != "default.xex":
                os.rename(os.path.join(assets, match[0]), os.path.join(assets, "default.xex"))
                ctx.log(f"Renombrado {match[0]} → default.xex", "warn")
            xex = os.path.join(assets, "default.xex")
            if not os.path.isfile(xex):
                subdirs = [d for d in entries if os.path.isdir(os.path.join(assets, d))]
                files = [f for f in entries if os.path.isfile(os.path.join(assets, f))
                         and f.lower() != ".gitkeep"]
                if len(subdirs) == 1 and not files and \
                        os.path.isfile(os.path.join(assets, subdirs[0], "default.xex")):
                    inner = os.path.join(assets, subdirs[0])
                    ctx.log(f"default.xex estaba dentro de «{subdirs[0]}»; moviendo contenido a assets/",
                            "warn")
                    for item in os.listdir(inner):
                        shutil.move(os.path.join(inner, item), os.path.join(assets, item))
                    os.rmdir(inner)
                else:
                    raise RuntimeError("No hay default.xex en la raíz de assets. Copia el contenido "
                                       "del juego (carpetas + default.xex) directamente en assets/.")
            info = read_xex_info(xex)
            self._result.update(info)
            ctx.log(f"default.xex · {human_size(os.path.getsize(xex))}")
            for k, lbl in (("title_id", "Title ID"), ("version", "Versión"), ("media_id", "Media ID"),
                           ("disc", "Disco"), ("original_name", "Nombre original")):
                if info.get(k):
                    ctx.log(f"  {lbl}: {info[k]}")
            folders = [d for d in os.listdir(assets) if os.path.isdir(os.path.join(assets, d))]
            ctx.log(f"  Carpetas del juego: {', '.join(folders) if folders else '(ninguna)'}")

        def do_clean(ctx):
            if os.path.isdir(build):
                ctx.log(f"Eliminando {build}")
                shutil.rmtree(build)

        def do_cache(ctx):
            why = game.cache_mismatch(cfg, build)
            ctx.log(f"Reconfigurando desde cero: {why}. Se borra la caché de CMake (no los archivos del juego).",
                    "warn")
            game.reset_cache(build)

        def init_skip():
            if os.path.isfile(os.path.join(root, "CMakeLists.txt")):
                return "el proyecto ya existe (CMakeLists.txt encontrado)"
            return None

        for key in keys:
            if key == "init":
                steps.append(Step(key, "Crear proyecto (rexglue init)",
                                  cmd=lambda: rexglue_init_cmd(cfg, name, root),
                                  cwd=os.path.dirname(root), env=env, skip_if=init_skip))
            elif key == "assets":
                steps.append(Step(key, {"iso": "Extraer juego en assets",
                                        "pkg": "Extraer paquete GOD/XBLA en assets",
                                        "xex": "Copiar juego (XEX) en assets"}.get(mode, "Copiar juego en assets"),
                                  func=do_assets))
            elif key == "verify":
                def verify_and_extras(ctx):
                    do_verify(ctx)
                    do_extras(ctx)
                steps.append(Step(key, "Verificar default.xex", func=verify_and_extras))
            elif key == "configure":
                steps.append(Step("sdkcheck", "Validar SDK compatible",
                                  func=lambda ctx: _validate_sdk(cfg, root, build, env, ctx)))
                if self.clean.isChecked():
                    steps.append(Step("clean", "Limpiar build", func=do_clean))
                else:
                    steps.append(Step("cache", "Revisar caché de CMake", func=do_cache,
                                      skip_if=lambda: None if game.cache_mismatch(cfg, build) else
                                      "la caché coincide con el compilador actual"))
                steps.append(Step(key, "Configurar CMake",
                                  cmd=lambda: cmake_configure_cmd(cfg, root, build), cwd=root, env=env))
            elif key == "codegen":
                steps.append(Step(key, "Generar código (codegen)",
                                  func=lambda ctx: game.codegen_with_autofix(cfg, root, build, name, env, ctx)))
            elif key == "build":
                # Codegen creates sources.cmake after the initial configure.
                # Refresh even for build-only retries of an existing project.
                steps.append(Step("hooks", "Preparar el proyecto (carpeta del juego, perfil y logros)",
                                  func=lambda ctx: prepare_project(root, ctx)))
                steps.append(Step("sdkcheck2", "Validar SDK compatible",
                                  func=lambda ctx: _validate_sdk(cfg, root, build, env, ctx)))
                steps.append(Step("reconfigure", "Actualizar CMake con las fuentes generadas",
                                  cmd=lambda: cmake_configure_cmd(cfg, root, build), cwd=root, env=env))
                steps.append(Step(key, "Compilar ejecutable",
                                  func=lambda ctx: game.build_with_ext_fallback(cfg, root, build, env, ctx),
                                  cwd=root, env=env))
        self._step_keys = [s.key for s in steps]
        return steps

    def _tracker_index(self, runner_index):
        key = self._step_keys[runner_index] if runner_index < len(self._step_keys) else ""
        if key in ("clean", "cache", "sdkcheck"):
            key = "configure"
        elif key in ("reconfigure", "hooks", "watch", "sdkcheck2"):
            key = "build"
        elif key == "declare":
            key = "codegen"
        for i, (k, _t, _s) in enumerate(STEP_DEFS):
            if k == key:
                return i
        return -1

    def _on_step_state(self, i, state):
        if not self.runner.running and state == "pending":
            return
        key = self._step_keys[i] if i < len(self._step_keys) else ""
        if key in ("clean", "cache", "reconfigure", "hooks", "declare", "watch") and state in ("done", "skipped"):
            return
        self.tracker.set_state(self._tracker_index(i), state)
        if state == "running":
            title = self.runner.steps[i].title
            self.status_lbl.setText(title)

    def _on_progress(self, v, m):
        self.progress.setRange(0, m)
        if m:
            self.progress.setValue(min(v, m))

    def _update_stats(self):
        self.stats_lbl.setText(f"⚠ {self.log.warnings}   ✖ {self.log.errors}")

    def _set_running(self, on):
        self.start_btn.setEnabled(not on)
        self.cancel_btn.setEnabled(on)
        for w in (self.mode, self.src, self.name, self.parent_dir, self.clean):
            w.setEnabled(not on)
        for cb in self.checks.values():
            cb.setEnabled(not on)
        if not on:
            self.src.setEnabled(self._mode_key() != "none")
        self.win.set_busy(on)

    def _on_finished(self, ok):
        self._set_running(False)
        self._stat_timer.stop()
        self._update_stats()
        p = self.current
        if p is None:
            return
        mode, self._mode = self._mode, "build"
        if mode == "play":
            self._after_watch(ok)
            return
        if self._result.get("title_id"):
            p.title_id = self._result["title_id"]
        outputs = []
        if ok and "build" in self._active_keys:
            exe = game.game_exe(p.root, p.name)
            outputs = [exe] if exe else []
        if outputs:
            p.output = outputs[0]
            self.log.write(f"Ejecutable x64: {outputs[0]}", "ok")
            try:        # compilado sin errores = al día (aunque ninja no tuviera nada que enlazar)
                if game.rebuild_reason(p.root, outputs[0]):
                    os.utime(outputs[0])
            except OSError:
                pass
            try:
                game.prepare_game_runtime(self.win.cfg, outputs[0], p.root)
                bat = game.write_launcher(outputs[0], p.root, p.name)
                self.log.write(f"Lanzador: {bat}", "ok")
                from . import mnklayouts
                _layout, teclas = mnklayouts.configure(p.root, outputs[0], p.name)
                if teclas:
                    self.log.write(teclas, "ok")
                cfg_path = write_runtime_config(outputs[0], GameOptions.load(p.root))
                self.log.write(f"Opciones del juego: {cfg_path}", "ok")
            except (OSError, RuntimeError) as e:
                self.log.write(f"No se pudo preparar el lanzamiento: {e}", "warn")
            self.log.write("Pulsa «▶ Jugar» para ejecutarlo.", "ok")
        p.status = ("Compilado" if outputs else "Listo") if ok else "Error"
        self.win.lib.upsert(p)
        self.project_changed.emit()
        self.btn_out.setEnabled(bool(p.output and os.path.exists(p.output)))
        self._update_play()
        self.status_lbl.setText("¡Completado!" if ok else "Detenido")
        self._save_log(auto=True)
        if ok and outputs and self.open_after.isChecked() and mode != "repair":
            open_path(os.path.dirname(outputs[0]))
        if mode == "repair":
            self._after_watch(ok)
            return
        self.win.notify("Recompilación completada" if ok else "La recompilación se detuvo",
                        p.name)
        if self._play_after_build:
            self._play_after_build = False
            if ok and outputs:
                self.log.write("▶ Abriendo el juego con todo lo último…", "ok")
                QTimer.singleShot(800, lambda: self.play(auto=True))

    def _current_exe(self):
        p = self.current
        if not p:
            return ""
        if p.output and os.path.isfile(p.output):
            return p.output
        return game.game_exe(p.root, p.name)

    def _update_play(self):
        exe = self._current_exe()
        has = bool(exe)
        self.btn_play.setEnabled(has)
        self.btn_lnk.setEnabled(has)
        self.btn_opts.setEnabled(self.current is not None)
        self.btn_optim.setEnabled(self.current is not None)
        self.btn_upd.setEnabled(self.current is not None and not self.runner.running)
        self.btn_extra.setEnabled(self.current is not None and not self.runner.running)
        self.btn_cheats.setEnabled(self.current is not None and not self.runner.running)
        try:
            crashed = has and game.analyze_runtime_log(game.newest_log(exe))["kind"] == "unregistered"
        except Exception:
            crashed = False
        self.btn_fix.setEnabled(has)
        self.btn_sweep.setEnabled(has and not self.runner.running)
        self.btn_fix.setText("🔧  Reparar" if crashed else "🩺  Mantener")
        self.btn_fix.setToolTip("Repara el último fallo del juego (función no registrada)" if crashed else
                                "Mantenimiento completo: busca de una vez las funciones que faltan (análisis "
                                "profundo), aplica las correcciones del codegen, compila y prueba el juego; si "
                                "falla, sigue reparando solo.")

    def play(self, auto=False):
        p, exe = self.current, self._current_exe()
        if not exe:
            if auto:
                return
            return QMessageBox.information(self, "Sin ejecutable", "Primero compila el proyecto.")
        if self.runner.running:
            return
        o = GameOptions.load(p.root)
        reason = game.rebuild_reason(p.root, exe, self.win.cfg)
        if reason and o.auto_repair:
            # Nunca abrir un juego sin lo último: se recompila primero y se abre solo al terminar.
            self.log.write(f"↻ Antes de jugar se recompila: {reason}. El juego se abrirá solo al terminar.", "warn")
            self.rebuild_and_play()
            return
        if not auto and o.ask_engine_on_play:
            from .game_options_ui import LaunchDialog
            if LaunchDialog(self, self.win.cfg, p, exe).exec() != LaunchDialog.DialogCode.Accepted:
                return
        self._repair_round = 0
        self._repair_seen = set()
        self._session_timer.stop()
        self._session = None
        self._start_watch_only(p)

    def _watch_step(self, p):
        cfg = self.win.cfg

        def do_watch(ctx):
            exe = game.game_exe(p.root, p.name)
            if not exe:
                raise RuntimeError("No se encontró el ejecutable recompilado")
            from .autoconfig import apply as autoconfig
            line = autoconfig(p.root, exe)          # revisa el PC y escribe la configuración más rápida
            if line:
                ctx.log(f"⚙ Autoconfiguración: {line}", "ok")
            o = GameOptions.load(p.root)
            write_runtime_config(exe, o)
            # Optimización del código aún sin comprobar: un juego colgado también cuenta como fallo.
            hang = not o.codegen_opt_verified and o.codegen_level() != "off" \
                and o.reforge_ext
            res = game.launch_and_watch(cfg, exe, p.root, int(o.repair_watch_seconds), ctx, detect_hang=hang)
            self._watch_result = res
            if res["kind"] == "running":
                ctx.log(f"✔ El juego sigue abierto tras {o.repair_watch_seconds} s: arrancó correctamente.", "ok")
            elif res["kind"] == "unregistered":
                ctx.log(f"✖ El juego se cerró: llamada a una función no registrada en 0x{res['address']:08X}", "err")
            elif res["kind"] in ("crash", "guest_av"):
                ctx.log(f"✖ {game.crash_advice(res)} (tras {res.get('seconds')} s)", "err")
            elif res["kind"] == "hang":
                ctx.log("✖ El juego se quedó colgado (sin imagen) y se cerró.", "err")
            else:
                ctx.log(f"El juego se cerró (código {res.get('exit_code')}) tras {res.get('seconds')} s.", "warn")
            for ln in res.get("lines", []):
                ctx.log("   " + ln, "dim")
            if res.get("path"):
                ctx.log(f"Log del juego: {res['path']}", "dim")
        return Step("watch", "Probar el juego", func=do_watch)

    def _start_watch_only(self, p):
        self._mode = "play"
        self._watch_result = None
        self.log.write("━━━ ▶ Jugar (vigilando el arranque)", "head")
        self._set_running(True)
        self.status_lbl.setText("Probando el juego…")
        self._step_keys = ["watch"]
        self.runner.start([self._watch_step(p)], project_root=p.root)

    def full_sweep(self):
        """🔬 Barrido completo: todas las capas de una vez, correcciones, mantenimiento y prueba; informe al final."""
        p, exe = self.current, self._current_exe()
        if not p or not exe or self.runner.running:
            return
        from .sweep import format_report, run_static
        self.log.write("━━━ 🔬 Barrido completo · 1/2 revisión de todas las capas", "head")
        rows = run_static(self.win.cfg, p.root, exe)
        for ln in format_report(rows):
            self.log.write("   " + ln, "warn" if ln[0] in "⚠✖" else ("ok" if ln[0] in "✔🔧" else "dim"))
        if any(st == "fail" for _l, st, _t in rows):
            self.log.write("✖ Hay un problema que el Taller no puede corregir solo (arriba). Corrígelo y vuelve a "
                           "lanzar el barrido.", "err")
            return
        self.log.write("━━━ 🔬 Barrido completo · 2/2 mantenimiento: análisis profundo, correcciones del codegen, "
                       "compilar, probar el arranque y reparar en rondas", "head")
        self._sweep = True
        self._repair_round = 0
        self._repair_seen = set()
        self.repair_round(None)

    def _sweep_report(self, res):
        """Informe final del barrido (cuando el juego ya arranca)."""
        self._sweep = False
        p, exe = self.current, self._current_exe()
        if not p:
            return
        from .sweep import check_code, check_warnings, format_report
        rows = check_code(p.root, exe) + check_warnings(p.root)
        self.log.write("━━━ 🔬 Resultado del barrido completo", "head")
        self.log.write(f"   ✔ Arranque: el juego sigue abierto tras {GameOptions.load(p.root).repair_watch_seconds} s"
                       + (f" ({self._repair_round} ronda(s) de reparación)" if self._repair_round > 1 else "") + ".",
                       "ok")
        for ln in format_report(rows):
            self.log.write("   " + ln, "warn" if ln[0] in "⚠✖" else "ok")
        self.win.notify("ReForge Studio", f"Barrido completo de {p.name}: listo")

    def repair_from_log(self):
        p, exe = self.current, self._current_exe()
        if not exe or self.runner.running:
            return
        res = game.analyze_runtime_log(game.newest_log(exe))
        self._repair_round = 0
        self._repair_seen = set()
        # sin fallo pendiente: mantenimiento completo (análisis profundo, correcciones del codegen, compilar y
        # probar el juego; si falla, sigue la reparación automática)
        self.repair_round(res["address"] if res["kind"] == "unregistered" else None)

    def repair_round(self, address):
        p = self.current
        cfg = self.win.cfg
        o = GameOptions.load(p.root)
        self._session_timer.stop()
        self._session = None
        self._repair_round += 1
        if address is not None:
            self._repair_seen.add(address)
        root, build = p.root, os.path.join(p.root, "build")
        self._refresh_tools(root)       # cada arreglo de código se compila con las últimas herramientas
        env = cfg.environment()

        def do_declare(ctx):
            # Base de datos de problemas conocidos: remedios automáticos (p. ej. quitar funciones fuera del
            # módulo que dejan el juego sin arrancar) antes de recompilar a ciegas.
            try:
                from . import knownissues
                exe0 = self._current_exe()
                log0 = game.newest_log(exe0) if exe0 else ""
                info0 = game.analyze_runtime_log(log0) if log0 else {}
                msgs, _rec = knownissues.auto_heal(root, exe0, game._read_log_text(log0), info0)
                for m in msgs:
                    ctx.log(m, "ok")
            except Exception as e:      # noqa: BLE001
                ctx.log(f"Diagnóstico de problemas conocidos no disponible: {e}", "dim")
            if address is None:
                ctx.log("Mantenimiento: revisar entradas de función, regenerar con correcciones, compilar y probar.")
            elif game.declare_runtime_function(root, address):
                ctx.log(f"Declarada 0x{address:08X} en {game.FUNCTIONS_FILE}", "ok")
            else:
                ctx.log(f"0x{address:08X} ya estaba declarada", "warn")
            exe = self._current_exe()
            others = [a for a in game.unregistered_in_log(game.newest_log(exe)) if a != address] if exe else []
            more = game.declare_functions(root, others, "otro hilo falló a la vez al ejecutar el juego")
            if more:
                ctx.log(f"Declaradas también {len(more)} dirección(es) del mismo arranque", "ok")
            # análisis profundo: todas las entradas que faltan, de una vez (necesita la imagen que vuelca el juego)
            try:
                from .deepscan import deep_scan_project
                cands = deep_scan_project(root, exe, game.generated_dir(root))
            except Exception as e:      # noqa: BLE001
                cands = None
                ctx.log(f"Análisis profundo no disponible: {e}", "warn")
            if cands is None:
                ctx.log("Análisis profundo: el juego aún no volcó su imagen (se hará en el próximo arranque con "
                        "esta versión de ReForge).", "dim")
            else:
                deep = game.declare_functions(root, cands, "entrada encontrada por el análisis profundo")
                ctx.log(f"Análisis profundo: {len(deep)} entrada(s) de función nuevas declaradas de una vez "
                        f"(tablas de métodos virtuales y punteros a funciones)." if deep else
                        "Análisis profundo: no hay más entradas pendientes.", "ok")

        steps = [
            Step("declare", (f"Ronda {self._repair_round}/{o.repair_max_rounds}: declarar 0x{address:08X}"
                             if address is not None else "Mantenimiento: análisis profundo de funciones"),
                 func=do_declare),
            Step("codegen", "Generar código (codegen)",
                 func=lambda ctx: game.codegen_with_autofix(cfg, root, build, p.name, env, ctx)),
            Step("hooks", "Preparar el proyecto (carpeta del juego, perfil y logros)",
                 func=lambda ctx: prepare_project(root, ctx)),
            Step("reconfigure", "Actualizar CMake con las fuentes generadas",
                 cmd=lambda: cmake_configure_cmd(cfg, root, build), cwd=root, env=env),
            Step("build", "Compilar ejecutable",
                 func=lambda ctx: game.build_with_ext_fallback(cfg, root, build, env, ctx), cwd=root, env=env),
            self._watch_step(p),
        ]
        self._mode = "repair"
        self._watch_result = None
        self._active_keys = ["codegen", "build"]
        self._step_keys = [s.key for s in steps]
        self.tracker.reset([k in ("codegen", "build") for k, _t, _s in STEP_DEFS])
        self.log.write(f"━━━ 🔧 Reparación automática · ronda {self._repair_round}" if address is not None
                       else "━━━ 🩺 Mantenimiento completo del juego", "head")
        self._set_running(True)
        self.status_lbl.setText(f"Reparando arranque (ronda {self._repair_round})…")
        self._stat_timer.start()
        self.runner.start(steps, project_root=root)

    def _after_watch(self, ok):
        p = self.current
        res = self._watch_result
        self._update_play()
        if not ok or not res:
            self.status_lbl.setText("Detenido")
            return
        o = GameOptions.load(p.root)
        kind = res["kind"]
        if kind == "running":
            self._utf8_retries = 0          # arrancó: la cadena de reintentos del cierre intermitente termina
            if self._sweep:
                self._sweep_report(res)
            self.status_lbl.setText("✔ El juego arrancó · vigilando mientras juegas")
            self._session = (p, game.game_exe(p.root, p.name), res)
            self._session_timer.start()
            if self._repair_round:
                self.log.write(f"★ Arranque reparado en {self._repair_round} ronda(s). "
                               f"Funciones declaradas: {len(game.declared_functions(p.root))}.", "ok")
            self.win.notify("ReForge Studio", f"{p.name} arrancó y sigue abierto")
            p.status = "Jugable"
            self.win.lib.upsert(p)
            self.project_changed.emit()
            return
        self._handle_crash(res, o)

    def _poll_session(self):
        if not self._session or self.runner.running:
            return
        p, exe, res = self._session
        try:
            out = game.check_running_game(exe, res)
        except Exception as e:      # noqa: BLE001
            self.log.write(f"No se pudo vigilar el juego: {e}", "warn")
            out = {"kind": "nolog"}
        if out is None:
            self._show_live(exe, res)
            return
        self._session_timer.stop()
        self._session = None
        self._live = None
        if p is not self.current:
            return
        self.post_session(p, exe, out)

    def _show_live(self, exe, res):
        """Estado en vivo mientras se juega: tiempo, tirones, logros y avisos del log del juego."""
        from .perfdiag import LiveLog, live_text
        path = game._fresh_log(exe, res.get("before", {})) or res.get("path", "")
        if not path:
            return
        if self._live is None or self._live[0].path != path:
            self._live = (LiveLog(path), time.time())
        stats = self._live[0].feed()
        self.status_lbl.setText(live_text(stats, time.time() - self._live[1]))

    def post_session(self, p, exe, out, external=False):
        """Qué hacer al terminar una partida (vigilada aquí o lanzada por fuera): explicar, ajustar y reparar solo."""
        if out.get("path"):
            self.handled_logs.add(out["path"])
        try:   # con la partida recién cerrada ya hay imagen del juego: icono oficial aunque el XEX use LZX
            from .gameicon import ensure as ensure_icon
            msg = ensure_icon(exe, p.root, p.name)
            if msg and not msg.startswith("icono no aplicado"):
                self.log.write("🖼 " + msg[0].upper() + msg[1:] + ".", "dim")
        except Exception:      # noqa: BLE001
            pass
        if game.consume_restart_flag(exe):
            self.log.write("↻ El juego se reinició solo para cargar una ranura de partidas (menú Guía).", "dim")
            self.status_lbl.setText("Juego reiniciado (cargando partida)")
            return
        o = GameOptions.load(p.root)
        if external:
            self.log.write(f"━━━ Partida de {p.name} terminada (lanzada fuera del Taller)", "head")
        kind = out["kind"]
        if kind == "unregistered":
            self.log.write(f"━━━ El juego se cerró mientras jugabas: función no registrada en "
                           f"0x{out['address']:08X}", "head")
            for ln in out.get("lines", []):
                self.log.write("   " + ln, "dim")
            self._handle_crash(out, o)
            return
        if kind in ("crash", "guest_av", "fatal", "split"):
            if kind in ("fatal", "split"):
                self.log.write("El juego se cerró con un error:", "err")
            for ln in out.get("lines", []):
                self.log.write("   " + ln, "dim")
            self._handle_crash(out, o)          # explica y lanza el mantenimiento automático
            return
        self.log.write("Juego cerrado.", "dim")
        self.status_lbl.setText("Juego cerrado")
        played = 0
        try:
            from .perfdiag import play_fps
            played = len(play_fps(out.get("path") or game.newest_log(exe)))
        except Exception:      # noqa: BLE001
            pass
        if not o.codegen_opt_verified and o.codegen_level() != "off" and not game.codegen_opt_pending(p.root) \
                and played >= 24:          # 2 minutos jugando de verdad (FPS cada 5 s)
            o.codegen_opt_verified = True        # partida completa sin cierres con esta optimización
            o.save(p.root)
            self.log.write(f"✔ Optimización del código «{game.CODEGEN_LEVEL_TITLES[o.codegen_level()]}» comprobada: "
                           "el juego funcionó sin cierres.", "ok")
        tuned = self.show_perf_report(p, exe, out.get("path")) or []
        self._repair_round = 0
        try:        # ¿quedan entradas de función por declarar? (evita cierres futuros en otras zonas del juego)
            from .deepscan import deep_scan_project
            cands = deep_scan_project(p.root, exe, game.generated_dir(p.root)) or []
            pending = [a for a in cands if a not in game.declared_functions(p.root)]
        except Exception:      # noqa: BLE001
            pending = []
        if pending and o.auto_repair and o.auto_relaunch and p.root not in self._auto_maint:
            self._auto_maint.add(p.root)
            self.log.write(f"🩺 Mantenimiento automático: {len(pending)} entrada(s) de función que aún no están en el "
                           "código recompilado. Se añaden y se recompila ahora para evitar cierres en otras partes "
                           "del juego.", "warn")
            QTimer.singleShot(400, lambda: self.repair_round(None))
            return
        if pending:
            self.log.write(f"🩺 El análisis profundo encontró {len(pending)} entrada(s) de función que aún no "
                           "están en el código recompilado. Pulsa «🩺 Mantener» para añadirlas de una vez y "
                           "evitar cierres en otras partes del juego.", "warn")
        QTimer.singleShot(200, lambda: self._after_clean_session(p, exe, tuned))

    def _after_clean_session(self, p, exe, tuned):
        """Tras una partida sin fallos: mejoras para PC, recompilar si hace falta y volver a abrir el juego
        con los ajustes nuevos (el jugador no tiene que hacer nada)."""
        if self.runner.running or p is not self.current:
            return
        o = GameOptions.load(p.root)
        if self.offer_pc_enhancements(p, exe):
            # Reabrir el juego al terminar de recompilar SOLO si el jugador activó el relanzamiento automático.
            self._play_after_build = bool(o.auto_relaunch)
            if not o.auto_relaunch:
                self.log.write("Recompilando con las mejoras. Al terminar, pulsa «▶ Jugar» cuando quieras "
                               "(no se reabrirá solo).", "dim")
            return
        reason = game.rebuild_reason(p.root, exe, self.win.cfg)
        if reason and o.auto_repair:
            if o.auto_relaunch:
                self.log.write(f"↻ Recompilando para la próxima partida: {reason}. El juego se abrirá solo al "
                               "terminar.", "warn")
                self.rebuild_and_play()
            else:
                self.log.write(f"↻ Conviene recompilar para la próxima partida: {reason}. Se recompila ahora; "
                               "pulsa «▶ Jugar» cuando quieras (no se reabrirá solo).", "dim")
                self.rebuild_current()
            return
        if tuned and o.auto_tune:
            if o.auto_relaunch:
                self.relaunch_countdown(p, "ReForge ajustó el juego tras esta partida:\n\n• " + "\n• ".join(tuned))
            else:
                self.log.write("🔧 Ajustes aplicados para la próxima partida: " + "; ".join(tuned)
                               + ". Pulsa «▶ Jugar» cuando quieras.", "ok")

    def show_perf_report(self, p, exe, log_path):
        """Resumen de rendimiento de la partida y ajustes automáticos (la extensión anota los tirones)."""
        log_path = log_path or game.newest_log(exe)
        try:
            from .perfdiag import auto_tune, report
            o = GameOptions.load(p.root)
            diag = o.diagnostics
            lines, main = report(log_path, exe)
            tuned = auto_tune(p.root, exe, log_path)
        except Exception:      # noqa: BLE001
            return []
        o = GameOptions.load(p.root)        # ya con lo que haya reparado el ajuste automático
        if o.readback_resolve:
            lines.append("⚠ «Lecturas exactas» (readback) activadas: cada copia de la GPU a memoria obliga a esperarla → "
                         "latencia y bajones bruscos de FPS. Desactívalas en 🎮 Opciones → Compatibilidad si el juego "
                         "se ve bien sin ellas.")
        if not tuned and len(lines) <= 1 and not diag and "Sin tirones" in "".join(lines):
            return []
        self.log.write("━━━ 📈 Rendimiento de la partida" + (" (diagnóstico)" if diag else ""), "head")
        for ln in lines:
            self.log.write("   " + ln, "warn" if ("tirón" in ln or "⚠" in ln or "bajón" in ln) else "dim")
        for msg in tuned:
            self.log.write("   🔧 Reparado automáticamente: " + msg, "ok")
        if main == "shaders" and o.render_path == "rov":
            self.log.write("   → Prueba «Rápido + datos no válidos» en 🎮 Opciones (Compatibilidad): los shaders de la ruta "
                           "Preciso (ROV) son mucho más grandes y tardan más en compilarse.", "warn")
        return tuned

    def offer_pc_enhancements(self, p, exe):
        """Tras jugar (ya se conoce la versión exacta): ofrece FPS desbloqueados y correcciones de la base de datos."""
        from . import cheats, pc_enhance
        o = GameOptions.load(p.root)
        if o.pc_offer_dismissed or self.runner.running or p is not self.current:
            return
        if not cheats.db_info():
            if o.auto_tune and not getattr(self, "_db_downloading", False):
                # Se descarga sola (la base de datos de parches de Xenia Canary) y se vuelve a mirar.
                import threading
                self._db_downloading = True
                done = {}

                def work():
                    try:
                        cheats.download_db()
                        done["ok"] = True
                    except Exception as e:      # noqa: BLE001
                        done["err"] = str(e)
                threading.Thread(target=work, daemon=True).start()
                self.log.write("✨ Descargando la base de datos de parches de Xenia (FPS desbloqueados y "
                               "correcciones para cada juego)…", "dim")
                timer = QTimer(self)

                def check():
                    if not done:
                        return
                    timer.stop()
                    self._db_downloading = False
                    if done.get("ok"):
                        self.offer_pc_enhancements(p, exe)
                    else:
                        self.log.write(f"No se pudo descargar la base de datos de parches: {done.get('err')}", "warn")
                timer.timeout.connect(check)
                timer.start(1000)
                return False
            self.log.write("✨ Mejoras para PC: descarga la base de datos en 🎯 Trucos para ver si este juego tiene "
                           "parche de FPS desbloqueados y correcciones gráficas.", "dim")
            return
        try:
            avail = pc_enhance.available_for_exe(exe, p.title_id)
        except Exception:      # noqa: BLE001
            return
        active = set((cheats.cheats_state(p.root) or {}).get("patches", []))
        rec = [x for x in pc_enhance.recommended(avail, o.resolution_scale, o.frame_mode()) if x.name not in active]
        if not rec:
            return
        names = "\n".join("  • " + x.name for x in rec)
        if o.auto_tune:          # sin preguntar: FPS desbloqueados y correcciones probadas para tu versión
            self.log.write("✨ Mejoras para PC de la base de datos de Xenia para tu versión del juego: "
                           + ", ".join(x.name for x in rec) + f" ({pc_enhance.describe(rec)}). Se integran y se "
                           "recompila; el juego se abrirá solo al terminar.", "ok")
            r = QMessageBox.StandardButton.Yes
        else:
            r = QMessageBox.question(
                self, "Mejoras para PC",
                f"La base de datos de Xenia Canary tiene mejoras para tu versión de este juego:\n\n{names}\n\n"
                f"({pc_enhance.describe(rec)}). Se integran en el código del juego: hay que recompilar.\n\n"
                "¿Aplicarlas y recompilar ahora?")
        if r != QMessageBox.StandardButton.Yes:
            o.pc_offer_dismissed = True
            o.save(p.root)
            self.log.write("Mejoras para PC: puedes activarlas cuando quieras en 🎯 Trucos → ✨ Recomendadas.", "dim")
            return
        try:
            new, changed = pc_enhance.apply_recommended(p.root, exe, p.title_id)
        except Exception as e:      # noqa: BLE001
            return QMessageBox.warning(self, "Mejoras para PC", str(e))
        self.log.write("✨ Mejoras para PC activadas: " + ", ".join(x.name for x in new), "ok")
        if changed:
            return self.rebuild_current()
        return False

    def _codegen_step_down(self, p, o, res):
        """Un cierre con la optimización del código aún sin probar: se baja un nivel, se recompila y se prueba.
        Devuelve True si lo hizo."""
        if o.codegen_opt == "off" or o.codegen_opt_verified or res.get("hotplug") or not o.auto_repair:
            return False
        if o.codegen_opt_exonerated:      # ya se probó «Desactivada» y también se cerró: no es la optimización
            return False
        lvl = o.codegen_level()
        if lvl == "off":
            # El nivel más conservador también se cierra: la optimización queda descartada. Volver a «Segura»
            # no recompila ahora (se aplica en la próxima compilación) y deja de bajarse en cada cierre.
            o.codegen_opt_exonerated = True
            o.codegen_opt, o.codegen_opt_level = "auto", "safe"
            o.save(p.root)
            self.log.write("↺ Se cerró también con la optimización del código «Desactivada»: el fallo no viene de "
                           "ahí. Se vuelve a «Segura» para no perder rendimiento (se aplica en la próxima "
                           "compilación) y ya no se baja más de nivel por estos cierres.", "warn")
            return False
        nxt = game.CODEGEN_LEVELS[game.CODEGEN_LEVELS.index(lvl) + 1]
        o.codegen_opt, o.codegen_opt_level = "auto", nxt
        o.save(p.root)
        self.log.write({"fatal": "El juego se cerró con un error.", "hang": "El juego se quedó colgado al arrancar."}
                       .get(res["kind"]) or game.crash_advice(res), "err")
        self.log.write(f"↻ El juego se cerró con la optimización del código «{game.CODEGEN_LEVEL_TITLES[lvl]}» aún sin "
                       f"probar: puede que no respete la convención de llamadas. Se baja a "
                       f"«{game.CODEGEN_LEVEL_TITLES[nxt]}», se recompila y se vuelve a probar.", "warn")
        QTimer.singleShot(300, lambda: self.repair_round(None))
        return True

    def _handle_crash(self, res, o):
        p = self.current
        kind = res["kind"]
        if kind in ("crash", "guest_av", "fatal") and res.get("path") \
                and (game.known_runtime_race(game._read_log_text(res["path"])) or game.runtime_abort(res)):
            # Bug CONOCIDO del runtime precompilado del SDK (~1 de cada 2 arranques), no del juego ni de la
            # optimización: no se recompila ni se baja de nivel, solo se vuelve a abrir. Antes el diagnóstico
            # lo confundía con una optimización agresiva y la apagaba, perdiendo rendimiento sin motivo. El
            # mensaje de la excepción cambia («Invalid UTF-8», «Not enough space») y a veces el log no llega a
            # escribirlo: también cuenta el 0xC0000409 sin nada que señale al juego.
            tries = getattr(self, "_utf8_retries", 0)
            if tries < 2:
                self._utf8_retries = tries + 1
                self.status_lbl.setText("Reabriendo el juego (fallo intermitente del SDK)…")
                self.log.write("⚠ El juego se cerró por el fallo INTERMITENTE del runtime de rexglue "
                               "(una completion diferida del despachador: «Invalid UTF-8», «Not enough space»…): "
                               "es un bug conocido del SDK, no de tu juego ni de la optimización, y recompilar no "
                               "lo arregla.", "warn")
                self.log.write(f"↻ Se vuelve a abrir solo (intento {tries + 2} de 3)…", "warn")
                QTimer.singleShot(800, lambda: self.play(auto=True))
            else:
                self._utf8_retries = 0
                self.log.write("El fallo intermitente del SDK ha salido 3 veces seguidas. No se toca la "
                               "optimización ni se recompila: es una carrera interna del runtime; vuelve a "
                               "abrir el juego en un rato.", "warn")
            return
        if kind == "unregistered":
            addr = res["address"]
            self.btn_fix.setEnabled(True)
            if addr in self._repair_seen and o.auto_repair and addr not in getattr(self, "_maint_seen", set()) \
                    and self._repair_round < o.repair_max_rounds:
                # ya declarada y sigue fallando: mantenimiento completo (funciones partidas o cortadas, análisis
                # profundo) antes de rendirse
                self._maint_seen = getattr(self, "_maint_seen", set()) | {addr}
                self.log.write(f"↻ 0x{addr:08X} ya estaba declarada: se revisan funciones partidas/cortadas y se "
                               "regenera todo.", "warn")
                QTimer.singleShot(300, lambda: self.repair_round(None))
                return
            if addr in self._repair_seen:
                self.status_lbl.setText("Requiere ajuste manual")
                self.log.write(f"0x{addr:08X} sigue fallando aunque ya está declarada. Puede estar dentro de otra "
                               "función: necesita 'parent' o 'size' a mano en reforge_functions.toml.", "err")
                return
            if self._repair_round >= o.repair_max_rounds:
                self.status_lbl.setText("Límite de rondas alcanzado")
                self.log.write(f"Se alcanzó el máximo de {o.repair_max_rounds} rondas. Puedes subirlo en "
                               "🎮 Opciones y pulsar 🔧 Reparar para continuar.", "warn")
                return
            if o.auto_repair:
                self.log.write(f"↻ Reparación automática: siguiente ronda con 0x{addr:08X}", "warn")
                QTimer.singleShot(300, lambda: self.repair_round(addr))
                return
            r = QMessageBox.question(self, "El juego se cerró",
                                     f"El juego llamó a una función que no se recompiló (0x{addr:08X}).\n\n"
                                     "¿Declararla, recompilar y volver a probar?")
            if r == QMessageBox.StandardButton.Yes:
                self.repair_round(addr)
            return
        self.status_lbl.setText("El juego se cerró")
        if kind in ("crash", "guest_av", "fatal", "hang") and p and o.path_trial == "rtv":
            # se estaba probando la ruta rápida porque ROV iba lento: con RTV falla → vuelve a ROV para siempre
            o.render_path, o.path_trial, o.rov_required = "rov", "", True
            o.save(p.root)
            self.log.write("↻ Con la ruta rápida (RTV) el juego falló: vuelve a la precisa (ROV), que queda fija para "
                           "este juego, y se abre de nuevo.", "warn")
            QTimer.singleShot(600, lambda: self.play(auto=True))
            return
        if kind == "split" and p:
            s_, t = res.get("branch", (0, 0))
            self.btn_fix.setEnabled(True)
            if self._repair_round >= o.repair_max_rounds:
                self.log.write(f"Se alcanzó el máximo de {o.repair_max_rounds} rondas.", "warn")
                return
            key = ("split", s_, t)
            if key in self._repair_seen:
                self.log.write(f"El salto 0x{s_:08X} → 0x{t:08X} sigue sin resolverse tras quitar las entradas que "
                               "partían la función.", "err")
                return
            self._repair_seen.add(key)
            self.log.write(f"El juego saltó de 0x{s_:08X} a 0x{t:08X}: una misma función quedó partida en dos. "
                           "↻ Reparación automática: se quitan las entradas que la parten, se regenera, se compila y "
                           "se vuelve a probar.", "warn")
            QTimer.singleShot(300, lambda: self.repair_round(None))
            return
        if kind in ("crash", "guest_av", "fatal") and p and o.auto_repair and not o.live_offline \
                and res.get("path"):
            online = game.online_crash(res["path"])
            if online:
                # con «Live simulado» el juego entra en su código online (funciones que el runtime no tiene) y lee
                # datos que nunca llegan: este juego se juega sin conexión (no hace falta recompilar)
                o.live_offline = True
                o.save(p.root)
                self.log.write(f"El juego cayó tras pedir servicios de Xbox Live que no existen ({', '.join(online[:3])}). "
                               "↻ Reparación automática: este juego pasa a jugarse sin conexión (Live simulado "
                               "desactivado solo aquí) y se vuelve a abrir.", "warn")
                QTimer.singleShot(600, lambda: self.play(auto=True))
                return
        if kind in ("crash", "guest_av", "fatal", "hang") and p and self._codegen_step_down(p, o, res):
            return
        if kind == "hang":
            self.log.write("El juego se quedó colgado al arrancar.", "err")
            return
        if kind in ("guest_av", "crash") and o.auto_repair and p and not game.exception_handlers_enabled(p.root) \
                and not res.get("hotplug") and game.enable_exception_handlers(p.root):
            # Muchos juegos capturan accesos inválidos con __try/__except (comprobar memoria, cargar datos
            # opcionales). Recompilado sin manejadores, ese acceso cierra el juego en vez de seguir. Un cierre
            # «crash» (0xC0000005 sin mensaje) suele ser justo eso: un acceso que el juego esperaba capturar.
            self.log.write(game.crash_advice(res), "err")
            self.log.write("↻ Reparación automática: se activan los manejadores de excepciones del juego "
                           "(__try/__except), se regenera, se compila y se vuelve a probar.", "warn")
            QTimer.singleShot(300, lambda: self.repair_round(None))
            return
        if kind in ("crash", "guest_av"):
            self.log.write(game.crash_advice(res), "err")
            # Mantenimiento automático (una vez por proyecto y sesión): análisis profundo, correcciones del codegen
            # (funciones cortadas, saltos sin función, setjmp/longjmp…), compilar y probar de nuevo.
            if o.auto_repair and not res.get("hotplug") and p and p.root not in self._auto_maint:
                self._auto_maint.add(p.root)
                self.log.write("↻ Mantenimiento automático: se revisa y recompila el juego con todas las correcciones "
                               "conocidas y se vuelve a probar.", "warn")
                QTimer.singleShot(300, lambda: self.repair_round(None))
                return
        elif kind == "fatal":
            self.log.write("El juego se cerró con un error que no es de funciones no registradas; "
                           "revisa las líneas de arriba del log del juego.", "err")

    def open_optimizer(self):
        p = self.current
        if not p:
            return QMessageBox.information(self, "Sin proyecto", "Abre o crea un proyecto primero.")
        from .optimizer_ui import OptimizeDialog
        OptimizeDialog(self, self.win.cfg, p.root, p.name, self._current_exe(), p.title_id).exec()

    def open_cheats(self):
        p = self.current
        if not p:
            return QMessageBox.information(self, "Sin proyecto", "Abre o crea un proyecto primero.")
        from .cheats_ui import CheatsDialog
        CheatsDialog(self, self.win.cfg, p.root, p.name, rebuild=lambda _root: self.rebuild_current()).exec()
        self._update_play()

    def rebuild_current(self):
        """Regenera el código y compila el proyecto actual (tras cambiar trucos o la actualización)."""
        p = self.current
        if not p or self.runner.running:
            return False
        game.invalidate_codegen(p.root)
        self.load_project(p)
        self.start()
        return True

    def rebuild_and_play(self):
        """Recompila con todo lo último y abre el juego solo al terminar."""
        self._play_after_build = self.rebuild_current() or self._play_after_build
        return self._play_after_build

    def relaunch_countdown(self, p, why, seconds=10):
        """Vuelve a abrir el juego con los ajustes nuevos tras una cuenta atrás (se puede cancelar)."""
        if self.runner.running or p is not self.current:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Volver a jugar")
        box.setIcon(QMessageBox.Icon.Information)
        go = box.addButton("▶ Jugar ahora", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("No, gracias", QMessageBox.ButtonRole.RejectRole)
        left = [seconds]

        def text():
            box.setText(f"{why}\n\nEl juego se abrirá de nuevo con los ajustes aplicados en {left[0]} s.")
        text()
        timer = QTimer(box)

        def tick():
            left[0] -= 1
            if left[0] <= 0:
                timer.stop()
                go.click()
            else:
                text()
        timer.timeout.connect(tick)
        timer.start(1000)
        box.setModal(False)

        def done(_r):
            timer.stop()
            if box.clickedButton() is go and not self.runner.running:
                self.play(auto=True)
        box.finished.connect(done)
        box.show()

    def open_extras(self):
        p = self.current
        if not p or self.runner.running:
            return
        from PySide6.QtWidgets import QFileDialog
        box = QMessageBox(self)
        box.setWindowTitle("Discos y DLC")
        box.setText("¿Dónde está el contenido extra del juego?\n\n"
                    "• Carpeta: la del juego en formato GOD/Content (la que tiene 00007000, 00000002, 000B0000) "
                    "o una carpeta con DLC.\n• Archivo: la ISO de otro disco o un paquete DLC suelto.\n\n"
                    "ReForge busca e instala todo lo que sea de este juego.")
        b_dir = box.addButton("📁 Carpeta…", QMessageBox.ButtonRole.AcceptRole)
        b_file = box.addButton("📄 Archivo…", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() == b_dir:
            src = QFileDialog.getExistingDirectory(self, "Carpeta con el contenido del juego")
        elif box.clickedButton() == b_file:
            src, _ = QFileDialog.getOpenFileName(self, "ISO de otro disco o paquete DLC", "",
                                                 "Discos y paquetes (*.iso *);;Todos (*)")
        else:
            return
        if not src:
            return
        root = p.root

        def work(ctx):
            from .extra_content import install_extras
            if os.path.isfile(src) and not src.lower().endswith(".iso"):
                from .extra_content import TYPE_DLC, _content_type, install_dlc, merge_disc
                if _content_type(src) == TYPE_DLC:
                    install_dlc(root, src, lambda m, *_a: ctx.log(m),
                                progress=lambda d, t: ctx.progress(int(d * 1000 / max(t, 1)), 1000))
                    return
                merge_disc(root, src, lambda m, *_a: ctx.log(m))
                return
            done = install_extras(root, src, lambda m, *_a: ctx.log(m),
                                  progress=lambda d, t: ctx.progress(int(d * 1000 / max(t, 1)), 1000),
                                  cancelled=ctx.cancelled)
            if os.path.isfile(src) and src.lower().endswith(".iso") and not done.get("discs"):
                from .extra_content import merge_disc
                merge_disc(root, src, lambda m, *_a: ctx.log(m))
                done["discs"] = 1
            if not any(done.values()):
                ctx.log("No se encontró contenido extra de este juego ahí (DLC, discos ni actualización).", "warn")
            else:
                ctx.log("✔ Listo. Pulsa ▶ Jugar: el juego verá el contenido nuevo.", "ok")

        self.log.write("━━━ 💿 Discos, DLC y actualización", "head")
        self.runner.start([Step("extras", "Instalar contenido extra", func=work)], project_root=root)

    def open_update(self):
        p = self.current
        if not p:
            return QMessageBox.information(self, "Sin proyecto", "Abre o crea un proyecto primero.")
        from .title_update_ui import open_update_dialog
        open_update_dialog(self, p)
        self._update_play()

    def open_options(self):
        p = self.current
        if not p:
            return QMessageBox.information(self, "Sin proyecto", "Abre o crea un proyecto primero.")
        from .game_options_ui import GameOptionsDialog
        GameOptionsDialog(self, self.win.cfg, p, self._current_exe()).exec()

    def make_shortcut(self):
        p, exe = self.current, self._current_exe()
        if not exe:
            return
        try:
            game.prepare_game_runtime(self.win.cfg, exe, p.root)
            lnk = game.desktop_shortcut(exe, p.root, p.name)
            self.log.write(f"Acceso directo creado: {lnk}", "ok")
        except Exception as e:
            QMessageBox.warning(self, "Acceso directo", str(e))

    def _open_output(self):
        p = self.current
        if p and p.output:
            open_path(os.path.dirname(p.output))

    def _save_log(self, auto=False):
        root = self._root()
        if not root or not os.path.isdir(root):
            return
        d = os.path.join(root, "logs")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"reforge-{datetime.datetime.now():%Y%m%d-%H%M%S}.log")
        self.log._flush()
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.log.toPlainText())
        if not auto:
            self.log.write(f"Log guardado en {path}", "ok")


# =============================================================================
#  BIBLIOTECA
# =============================================================================
class ProjectCard(QFrame):
    def __init__(self, page, p):
        super().__init__()
        self.setObjectName("Card")
        self.setFixedHeight(168)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 12)
        v.setSpacing(10)

        # --- fila superior: carátula + datos ---
        top = QHBoxLayout()
        top.setSpacing(14)
        cover = QLabel()
        cover.setPixmap(cover_pixmap(p.root, p.name, 78))
        cover.setFixedSize(78, 78)
        top.addWidget(cover, 0, Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(3)
        titrow = QHBoxLayout()
        titrow.setSpacing(8)
        name = label(p.name, "CardTitle")
        name.setToolTip(p.name)
        titrow.addWidget(name, 1)
        chip = label(p.status.upper(), "Chip")
        chip.setProperty("kind", {"Error": "err", "Compilando": "run"}.get(p.status, ""))
        titrow.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
        info.addLayout(titrow)
        info.addWidget(label(p.title_id and f"Title ID {p.title_id}" or "Sin Title ID", "Hint"))
        info.addWidget(label(p.updated or "—", "Hint"))
        if not os.path.isdir(p.root):
            info.addWidget(label("⚠ La carpeta ya no existe", "HintErr"))
        info.addStretch(1)
        top.addLayout(info, 1)
        v.addLayout(top, 1)
        self.setToolTip(p.root)

        # --- fila de acciones ---
        row = QHBoxLayout()
        row.setSpacing(8)
        b1 = QPushButton("⚒  Abrir en Taller")
        b1.setCursor(Qt.CursorShape.PointingHandCursor)
        b1.clicked.connect(lambda: page.win.open_project(p))
        b2 = QPushButton("📁")
        b2.setToolTip("Abrir carpeta")
        b2.clicked.connect(lambda: open_path(p.root))
        b3 = QPushButton("▶")
        b3.setEnabled(bool(p.output and os.path.isfile(p.output)))
        b3.setToolTip("Jugar (ejecuta el .exe x64 recompilado)")
        b3.clicked.connect(lambda: page.launch(p))
        b4 = QPushButton("✕")
        b4.setObjectName("Danger")
        b4.setToolTip("Quitar de la biblioteca (no borra archivos)")
        b4.clicked.connect(lambda: page.remove(p))
        row.addWidget(b1, 1)
        for b in (b2, b3, b4):
            b.setFixedWidth(42)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(b)
        v.addLayout(row)


class LibraryPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.setContentsMargins(36, 10, 36, 30)
        v.setSpacing(14)
        bar = QHBoxLayout()
        self.count_lbl = label("", "Hint")
        bar.addWidget(self.count_lbl, 1)
        add = QPushButton("＋  Agregar proyecto existente")
        add.clicked.connect(self.add_existing)
        new = QPushButton("⬢  Nuevo desde ISO")
        new.setObjectName("Primary")
        new.clicked.connect(win.new_from_iso)
        bar.addWidget(add)
        bar.addWidget(new)
        v.addLayout(bar)
        holder = QWidget()
        self.grid = QGridLayout(holder)
        self.grid.setSpacing(14)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        v.addWidget(scroll_wrap(holder), 1)

    def refresh(self):
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        projects = self.win.lib.projects
        self.count_lbl.setText(f"{len(projects)} proyecto(s)")
        if not projects:
            self.grid.addWidget(label("La biblioteca está vacía.", "Hint"), 0, 0)
        cols = 3
        for i, p in enumerate(projects):
            self.grid.addWidget(ProjectCard(self, p), i // cols, i % cols)
        for c in range(cols):
            self.grid.setColumnStretch(c, 1)
        self.grid.setRowStretch(len(projects) // cols + 1, 1)

    def add_existing(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "Carpeta raíz del proyecto rexglue",
                                             self.win.cfg.workspace)
        if not d:
            return
        if not os.path.isfile(os.path.join(d, "CMakeLists.txt")):
            QMessageBox.warning(self, "No parece un proyecto", "No se encontró CMakeLists.txt en esa carpeta.")
            return
        p = Project(name=sanitize_name(os.path.basename(os.path.normpath(d))), root=d, status="Importado")
        xex = os.path.join(d, "assets", "default.xex")
        if os.path.isfile(xex):
            try:
                p.title_id = read_xex_info(xex).get("title_id", "")
            except Exception:
                pass
        outs = find_outputs(os.path.join(d, "build"), p.name)
        if outs:
            p.output, p.status = outs[0], "Compilado"
        self.win.lib.upsert(p)
        self.win.refresh_all()

    def remove(self, p):
        r = QMessageBox.question(self, "Quitar proyecto",
                                 f"¿Quitar «{p.name}» de la biblioteca?\nLos archivos no se borran.")
        if r == QMessageBox.StandardButton.Yes:
            self.win.lib.remove(p.root)
            self.win.refresh_all()

    def launch(self, p):
        """▶ desde la Biblioteca: abre el proyecto en el Taller y lanza vigilado (repara si se cierra)."""
        exe = p.output if p.output and os.path.isfile(p.output) else game.game_exe(p.root, p.name)
        if not exe:
            return
        if self.win.workshop.runner.running:
            QMessageBox.information(self, "Ocupado", "Hay una tarea en curso en el Taller.")
            return
        self.win.open_project(p)
        self.win.workshop.play()


# =============================================================================
#  XENONRECOMP
# =============================================================================
TOML_TEMPLATE = """# Configuración de XenonRecomp generada por ReForge Studio
# Las rutas son relativas a la carpeta de este archivo.
[main]
file_path = "{xex}"
{patch}out_directory_path = "{out}"
switch_table_file_path = "{switch}"

# Optimizaciones: actívalas solo cuando la recompilación ya funcione.
skip_lr = false
skip_msr = false
ctr_as_local = false
xer_as_local = false
reserved_as_local = false
cr_as_local = false
non_argument_as_local = false
non_volatile_as_local = false

# Direcciones de las funciones de guardado/restauración de registros.
# Búscalas en el ejecutable por su patrón de bytes (ver README de XenonRecomp).
# restgprlr_14_address = 0x00000000   # e9 c1 ff 68
# savegprlr_14_address = 0x00000000   # f9 c1 ff 68
# restfpr_14_address   = 0x00000000   # c9 cc ff 70
# savefpr_14_address   = 0x00000000   # d9 cc ff 70
# restvmx_14_address   = 0x00000000   # 39 60 fe e0 7d cb 60 ce
# savevmx_14_address   = 0x00000000   # 39 60 fe e0 7d cb 61 ce
# restvmx_64_address   = 0x00000000   # 39 60 fc 00 10 0b 60 cb
# savevmx_64_address   = 0x00000000   # 39 60 fc 00 10 0b 61 cb

# longjmp_address = 0x00000000
# setjmp_address  = 0x00000000

# functions = [ {{ address = 0x00000000, size = 0x00 }} ]
# invalid_instructions = [ {{ data = 0x00000000, size = 4 }} ]
"""


def _rel(path, base):
    try:
        return os.path.relpath(path, base).replace("\\", "/")
    except ValueError:
        return path.replace("\\", "/")


class XenonPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.runner = PipelineRunner(self)
        root = QHBoxLayout(self)
        root.setContentsMargins(36, 10, 36, 30)
        root.setSpacing(20)

        form_w = QWidget()
        fv = QVBoxLayout(form_w)
        fv.setContentsMargins(0, 0, 8, 0)
        fv.setSpacing(14)
        p1, v1 = panel()
        v1.addWidget(label("ARCHIVOS", "Section"))
        f = QFormLayout()
        f.setVerticalSpacing(8)
        self.xex = PathField("file", "Ejecutables Xbox 360 (*.xex);;Todos (*)", "default.xex")
        self.xexp = PathField("file", "Parches (*.xexp);;Todos (*)", "Opcional: default.xexp (title update)")
        self.toml = PathField("save", "TOML (*.toml)", "config/juego.toml")
        self.out = PathField("dir", placeholder="Carpeta de salida del código C++ (ppc)")
        self.ctx = PathField("file", "Cabecera (*.h)", "XenonUtils/ppc_context.h")
        self.ctx.setText(win.cfg.ppc_context)
        f.addRow("XEX", self.xex)
        f.addRow("XEXP", self.xexp)
        f.addRow("TOML", self.toml)
        f.addRow("Salida", self.out)
        f.addRow("ppc_context.h", self.ctx)
        v1.addLayout(f)
        fill = QPushButton("Rellenar desde el proyecto actual")
        fill.clicked.connect(self.fill_from_project)
        v1.addWidget(fill)
        fv.addWidget(p1)

        p2, v2 = panel()
        v2.addWidget(label("ACCIONES", "Section"))
        b_tpl = QPushButton("📝  Generar TOML base")
        b_tpl.clicked.connect(self.make_toml)
        b_an = QPushButton("🔎  XenonAnalyse → tablas de salto")
        b_an.clicked.connect(self.analyse)
        b_rc = QPushButton("▶   Ejecutar XenonRecomp")
        b_rc.setObjectName("Primary")
        b_rc.clicked.connect(self.recomp)
        self.cancel = QPushButton("■  Cancelar")
        self.cancel.clicked.connect(self.runner.cancel)
        for b in (b_tpl, b_an, b_rc, self.cancel):
            v2.addWidget(b)
        v2.addWidget(label("XenonRecomp convierte el XEX a C++; necesita un runtime (como rexglue) "
                           "para que el juego funcione. Las direcciones de guardado/restauración "
                           "deben completarse en el TOML.", "Hint", wrap=True))
        fv.addWidget(p2)
        fv.addStretch(1)
        left = scroll_wrap(form_w)
        left.setFixedWidth(450)
        root.addWidget(left)

        rv = QVBoxLayout()
        self.progress = QProgressBar()
        self.progress.setFixedHeight(8)
        self.progress.setRange(0, 1)
        rv.addWidget(self.progress)
        self.log = LogView()
        rv.addWidget(self.log, 1)
        root.addLayout(rv, 1)
        self.runner.log.connect(self.log.write)
        self.runner.progress.connect(lambda v, m: (self.progress.setRange(0, m),
                                                   m and self.progress.setValue(min(v, m))))

    def fill_from_project(self):
        p = self.win.workshop.current
        if not p:
            return QMessageBox.information(self, "Sin proyecto", "Abre un proyecto en el Taller o la Biblioteca.")
        self.xex.setText(os.path.join(p.root, "assets", "default.xex"))
        xexp = os.path.join(p.root, "assets", "default.xexp")
        self.xexp.setText(xexp if os.path.isfile(xexp) else "")
        self.toml.setText(os.path.join(p.root, "xenon", f"{p.name}.toml"))
        self.out.setText(os.path.join(p.root, "xenon", "ppc"))

    def make_toml(self):
        toml, xex = self.toml.text(), self.xex.text()
        if not toml or not xex:
            return QMessageBox.warning(self, "Faltan datos", "Indica el XEX y la ruta del TOML.")
        base = os.path.dirname(os.path.abspath(toml))
        os.makedirs(base, exist_ok=True)
        out = self.out.text() or os.path.join(base, "ppc")
        os.makedirs(out, exist_ok=True)
        if os.path.exists(toml) and QMessageBox.question(
                self, "Sobrescribir", "El TOML ya existe. ¿Sobrescribir?") != QMessageBox.StandardButton.Yes:
            return
        patch = ""
        if self.xexp.text():
            stem = os.path.splitext(xex)[0]
            patch = (f'patch_file_path = "{_rel(self.xexp.text(), base)}"\n'
                     f'patched_file_path = "{_rel(stem + "_patched.xex", base)}"\n')
        name = os.path.splitext(os.path.basename(toml))[0]
        with open(toml, "w", encoding="utf-8") as f:
            f.write(TOML_TEMPLATE.format(xex=_rel(xex, base), out=_rel(out, base), patch=patch,
                                         switch=f"{name}_switch_tables.toml"))
        self.log.write(f"TOML creado: {toml}", "ok")
        open_path(toml)

    def analyse(self):
        xex, toml = self.xex.text(), self.toml.text()
        if not os.path.isfile(xex):
            return QMessageBox.warning(self, "Falta el XEX", "Selecciona un default.xex válido.")
        base = os.path.dirname(os.path.abspath(toml)) if toml else os.path.dirname(xex)
        name = os.path.splitext(os.path.basename(toml))[0] if toml else "game"
        os.makedirs(base, exist_ok=True)
        out = os.path.join(base, f"{name}_switch_tables.toml")
        cfg = self.win.cfg
        self.runner.start([Step("an", "XenonAnalyse", cmd=[cfg.tool("xenonanalyse"), xex, out],
                                cwd=base, env=cfg.environment())])

    def recomp(self):
        toml, ctx = self.toml.text(), self.ctx.text()
        if not os.path.isfile(toml):
            return QMessageBox.warning(self, "Falta el TOML", "Genera o selecciona el archivo TOML.")
        if not os.path.isfile(ctx):
            return QMessageBox.warning(self, "Falta ppc_context.h",
                                       "Indica la ruta a XenonUtils/ppc_context.h.")
        if self.out.text():
            os.makedirs(self.out.text(), exist_ok=True)
        cfg = self.win.cfg
        cfg.ppc_context = ctx
        cfg.save()
        self.runner.start([Step("rc", "XenonRecomp", cmd=[cfg.tool("xenonrecomp"), toml, ctx],
                                cwd=os.path.dirname(os.path.abspath(toml)), env=cfg.environment())])


# =============================================================================
#  AJUSTES
# =============================================================================
class SettingsPage(QWidget):
    accent_changed = Signal()

    def __init__(self, win):
        super().__init__()
        self.win = win
        cfg = win.cfg
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._save)
        self.runner = PipelineRunner(self)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(36, 10, 36, 30)
        outer.setSpacing(20)
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 8, 0)
        bv.setSpacing(14)

        p1, v1 = panel()
        v1.addWidget(label("HERRAMIENTAS", "Section"))
        f1 = QFormLayout()
        f1.setVerticalSpacing(8)
        exe = "Ejecutables (*.exe);;Todos (*)" if os.name == "nt" else ""
        self.fields = {}
        rows = [
            ("rexglue", "rexglue", "file", exe, "Vacío = buscar en PATH"),
            ("cmake", "CMake", "file", exe, "Vacío = buscar en PATH"),
            ("xenonrecomp", "XenonRecomp", "file", exe, "Opcional"),
            ("xenonanalyse", "XenonAnalyse", "file", exe, "Opcional"),
            ("ppc_context", "ppc_context.h", "file", "Cabecera (*.h)", "XenonUtils/ppc_context.h"),
            ("vcvars", "vcvars64.bat", "file", "Batch (*.bat)", "Solo Windows: entorno de Visual Studio"),
            ("workspace", "Proyectos", "dir", "", "Carpeta por defecto para proyectos"),
        ]
        for key, lbl, kind, filt, ph in rows:
            pf = PathField(kind, filt, ph)
            pf.setText(getattr(cfg, key))
            pf.changed.connect(lambda t, k=key: self._set(k, t.strip()))
            self.fields[key] = pf
            f1.addRow(lbl, pf)
        v1.addLayout(f1)
        h = QHBoxLayout()
        det = QPushButton("🔍  Detectar automáticamente")
        det.clicked.connect(self.detect)
        chk = QPushButton("🩺  Comprobar entorno")
        chk.clicked.connect(self.check_env)
        h.addWidget(det)
        h.addWidget(chk)
        h.addStretch(1)
        v1.addLayout(h)
        bv.addWidget(p1)

        p2, v2 = panel()
        v2.addWidget(label("COMPILACIÓN", "Section"))
        f2 = QFormLayout()
        f2.setVerticalSpacing(8)
        self.gen = QComboBox()
        self.gen.setEditable(True)
        self.gen.addItems(["", "Ninja", "Ninja Multi-Config", "Visual Studio 17 2022", "Unix Makefiles",
                           "MinGW Makefiles"])
        self.gen.setCurrentText(cfg.generator)
        self.gen.currentTextChanged.connect(lambda t: self._set("generator", t.strip()))
        self.gen.lineEdit().setPlaceholderText("(predeterminado de CMake)")
        self.btype = QComboBox()
        self.btype.addItems(["Release", "RelWithDebInfo", "Debug", "MinSizeRel"])
        self.btype.setCurrentText(cfg.build_type)
        self.btype.currentTextChanged.connect(lambda t: self._set("build_type", t))
        self.cc = QLineEdit(cfg.c_compiler)
        self.cc.setPlaceholderText("ej. clang-cl / clang")
        self.cc.textChanged.connect(lambda t: self._set("c_compiler", t.strip()))
        self.cxx = QLineEdit(cfg.cxx_compiler)
        self.cxx.setPlaceholderText("ej. clang-cl / clang++")
        self.cxx.textChanged.connect(lambda t: self._set("cxx_compiler", t.strip()))
        self.jobs = QSpinBox()
        self.jobs.setRange(1, 256)
        self.jobs.setValue(int(cfg.jobs))
        self.jobs.valueChanged.connect(lambda n: self._set("jobs", n))
        self.extra = QLineEdit(cfg.extra_cmake_args)
        self.extra.setPlaceholderText("Argumentos extra para cmake (ej. -DREX_FOO=ON)")
        self.extra.textChanged.connect(lambda t: self._set("extra_cmake_args", t))
        self.env = QPlainTextEdit(cfg.extra_env)
        self.env.setObjectName("Small")
        self.env.setFixedHeight(70)
        self.env.setPlaceholderText("Variables de entorno extra, una por línea: CLAVE=valor")
        self.env.textChanged.connect(lambda: self._set("extra_env", self.env.toPlainText()))
        f2.addRow("Generador", self.gen)
        f2.addRow("Tipo de build", self.btype)
        f2.addRow("Compilador C", self.cc)
        f2.addRow("Compilador C++", self.cxx)
        f2.addRow("Hilos (-j)", self.jobs)
        f2.addRow("Args CMake", self.extra)
        f2.addRow("Entorno", self.env)
        v2.addLayout(f2)
        bv.addWidget(p2)

        p3, v3 = panel()
        v3.addWidget(label("APARIENCIA", "Section"))
        self.accent = QComboBox()
        self.accent.addItems(list(ACCENTS))
        self.accent.setCurrentText(cfg.accent)
        self.accent.currentTextChanged.connect(self._accent)
        f3 = QFormLayout()
        f3.addRow("Color de acento", self.accent)
        v3.addLayout(f3)
        v3.addWidget(label("F11: pantalla completa (modo TV) · Ctrl+1…5: cambiar sección · "
                           "flechas + Enter para navegar los tiles.", "Hint", wrap=True))
        bv.addWidget(p3)

        p4, v4 = panel()
        v4.addWidget(label("JUEGOS", "Section"))
        self.watch = QCheckBox("Detectar el juego que tengas abierto y repararlo si falla")
        self.watch.setChecked(bool(getattr(cfg, "watch_games", True)))
        self.watch.toggled.connect(self._watch_toggled)
        v4.addWidget(self.watch)
        v4.addWidget(label("Mientras ReForge Studio esté abierto (aunque esté minimizado), vigila los juegos de tu "
                           "Biblioteca aunque los abras con el .bat, un acceso directo o doble clic en el .exe. Si uno "
                           "se cierra por una función no registrada, lo cierra y lo repara; si es un error gráfico, "
                           "te ofrece el asistente de imagen.", "Hint", wrap=True))
        bv.addWidget(p4)

        p5, v5 = panel()
        v5.addWidget(label("ACTUALIZACIONES", "Section"))
        from . import update as upd
        ucfg = upd.load_config()
        self.upd_auto = QCheckBox("Buscar actualizaciones de ReForge Studio automáticamente")
        self.upd_auto.setChecked(bool(ucfg.get("enabled", True)))
        self.upd_auto.toggled.connect(lambda on: upd.save_config(enabled=bool(on)))
        v5.addWidget(self.upd_auto)
        self.upd_silent = QCheckBox("Instalarlas sin preguntar (se reinicia el programa)")
        self.upd_silent.setChecked(bool(ucfg.get("auto_install", False)))
        self.upd_silent.toggled.connect(lambda on: upd.save_config(auto_install=bool(on)))
        v5.addWidget(self.upd_silent)
        self.upd_beta = QCheckBox("Incluir versiones de prueba")
        self.upd_beta.setChecked(bool(ucfg.get("prereleases", False)))
        self.upd_beta.toggled.connect(lambda on: upd.save_config(prereleases=bool(on)))
        v5.addWidget(self.upd_beta)
        f5 = QFormLayout()
        f5.setVerticalSpacing(8)
        self.upd_repo = QLineEdit(ucfg.get("repo") or upd.REPO)
        self.upd_repo.editingFinished.connect(
            lambda: upd.save_config(repo=self.upd_repo.text().strip() or upd.REPO, last_check=0))
        f5.addRow("Repositorio", self.upd_repo)
        self.upd_token = QLineEdit(ucfg.get("token") or "")
        self.upd_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.upd_token.setPlaceholderText("Solo si el repositorio es privado")
        self.upd_token.editingFinished.connect(
            lambda: upd.save_config(token=self.upd_token.text().strip(), last_check=0))
        f5.addRow("Token de GitHub", self.upd_token)
        v5.addLayout(f5)
        hu = QHBoxLayout()
        self.upd_btn = QPushButton("⟳  Buscar ahora")
        self.upd_btn.clicked.connect(self.check_updates)
        hu.addWidget(self.upd_btn)
        hu.addStretch(1)
        v5.addLayout(hu)
        self.upd_state = label(f"Tienes la versión {upd.current_version()}.", "Hint", wrap=True)
        v5.addWidget(self.upd_state)
        v5.addWidget(label("ReForge compara su versión con la última publicada en GitHub. Antes de instalar nada "
                           "comprueba el tamaño y el SHA-256 del instalador. Si el repositorio es privado, hace "
                           "falta un token personal con permiso de lectura.", "Hint", wrap=True))
        bv.addWidget(p5)

        bv.addStretch(1)
        left = scroll_wrap(body)
        left.setMinimumWidth(560)
        outer.addWidget(left, 3)
        self.log = LogView()
        outer.addWidget(self.log, 2)
        self.runner.log.connect(self.log.write)

    def check_updates(self):
        """Busca una versión nueva y, si la hay, ofrece instalarla."""
        from . import update as upd
        self.upd_btn.setEnabled(False)
        self.upd_state.setText("Preguntando a GitHub…")
        QApplication.processEvents()
        try:
            info = upd.check(force=True)
        except upd.UpdateError as e:
            self.upd_state.setText(str(e))
            self.upd_btn.setEnabled(True)
            return
        finally:
            self.upd_btn.setEnabled(True)
        if not info:
            self.upd_state.setText(f"ReForge Studio {upd.current_version()}: ya tienes la versión más reciente.")
            return
        self.upd_state.setText(f"Disponible la versión {info['version']}.")
        self.win.offer_update(info)

    def _set(self, key, value):
        setattr(self.win.cfg, key, value)
        self._save_timer.start()

    def _save(self):
        self.win.cfg.save()
        self.win.home.refresh()

    def _watch_toggled(self, on):
        self._set("watch_games", bool(on))
        w = getattr(self.win, "watcher", None)
        if w is not None:
            w.start() if on else w.stop()

    def _accent(self, name):
        self._set("accent", name)
        self.win.apply_theme()

    def detect(self):
        found = detect_tools()
        self.log.write("━━━ Detección de herramientas", "head")
        for k, v in found.items():
            self.log.write(f"{'✔' if v else '✖'} {k:<13} {v or 'no encontrado'}", "ok" if v else "warn")
            if v and k in self.fields and not self.fields[k].text():
                self.fields[k].setText(v)
        if os.name == "nt" and found.get("vcvars") and not self.fields["vcvars"].text():
            self.fields["vcvars"].setText(found["vcvars"])

    def check_env(self):
        cfg = self.win.cfg

        def run(ctx):
            env = cfg.environment()
            checks = [
                ("rexglue", [cfg.tool("rexglue"), "--help"]),
                ("CMake", [cfg.tool("cmake"), "--version"]),
                ("Ninja", ["ninja", "--version"]),
                ("Clang", [cfg.cxx_compiler or ("clang-cl" if os.name == "nt" else "clang++"), "--version"]),
            ]
            for name, cmd in checks:
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL, timeout=20, env=env,
                                       creationflags=NO_WINDOW)
                    first = (r.stdout or r.stderr).strip().splitlines()
                    ctx.log(f"✔ {name}: {first[0] if first else 'OK'}", "ok")
                except FileNotFoundError:
                    ctx.log(f"✖ {name}: no encontrado ({cmd[0]})", "err")
                except Exception as e:
                    ctx.log(f"⚠ {name}: {e}", "warn")
            ctx.log(f"Hilos: {cfg.jobs} · Generador: {cfg.generator or 'predeterminado'} · "
                    f"Build: {cfg.build_type}")
        self.runner.start([Step("env", "Comprobar entorno", func=run)])
