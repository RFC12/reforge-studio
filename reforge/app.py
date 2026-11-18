"""Ventana principal de ReForge Studio."""
import datetime
import getpass
import json
import os
import sys

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QKeySequence, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QMainWindow,
                               QMessageBox, QProgressDialog, QPushButton, QStackedWidget, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

from . import APP_NAME, SUPPORTED_APIS, __version__
from . import stdlib_bundle  # noqa: F401  (módulos disponibles para parches en el .exe)
from .core import AppConfig, Library
from .env_page import EnvPage
from .pages import HomePage, LibraryPage, SettingsPage, WorkshopPage, XenonPage
from .patches import PATCH_EXT, PatchError, PatchManager, vtuple
from .patches_page import PatchesPage
from .plugin_api import PluginAPI
from .theme import accent_color, build_qss
from .widgets import Logo, label, logo_pixmap

CORE_NAV = [
    ("home", "⌂   Inicio", "Inicio"),
    ("workshop", "⚒   Taller", "Taller de recompilación"),
    ("env", "⚡   Entorno", "Entorno de compilación"),
    ("library", "▦   Biblioteca", "Biblioteca"),
    ("xenon", "⟁   XenonRecomp", "XenonRecomp"),
]
TAIL_NAV = [
    ("profile", "☺   Perfil", "Perfil de jugador"),
    ("patches", "⬡   Parches", "Parches y versión"),
    ("settings", "⚙   Ajustes", "Ajustes"),
]
SERVER_NAME = f"ReForgeStudio-{getpass.getuser()}"
# Parches cuya función ya forma parte del núcleo: se retiran solos.
OBSOLETE_PATCHES = {"rexglue-env": "integrado en ReForge Studio 1.2 (sección Entorno)"}


def bundled_patch_dirs():
    dirs = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        dirs.append(os.path.join(meipass, "bundled_patches"))
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else \
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dirs.append(os.path.join(base, "bundled_patches"))
    return [d for d in dirs if os.path.isdir(d)]


def parse_args(argv):
    args = {"safe_mode": False, "install_patch": "", "launcher": "", "repair": None, "open_project": "",
            "rebuild": ""}
    it = iter(argv[1:])
    for a in it:
        if a == "--safe-mode":
            args["safe_mode"] = True
        elif a == "--launcher":
            args["launcher"] = next(it, "")
        elif a == "--open-project":
            args["open_project"] = next(it, "")
        elif a == "--rebuild":
            args["rebuild"] = next(it, "")
        elif a == "--repair":
            root, addr = next(it, ""), next(it, "")
            try:
                args["repair"] = [root, int(addr, 16)]
            except ValueError:
                args["open_project"] = root
        elif a == "--install-patch":
            args["install_patch"] = next(it, "")
        elif a.lower().endswith(PATCH_EXT) and os.path.isfile(a):
            args["install_patch"] = a
    return args


class MainWindow(QMainWindow):
    def __init__(self, args=None):
        super().__init__()
        self.args = args or {"safe_mode": False, "install_patch": ""}
        self.cfg = AppConfig.load()
        self.lib = Library.load()
        self.patches = PatchManager(__version__, SUPPORTED_APIS)
        self.setWindowTitle(APP_NAME)
        self.resize(1440, 880)
        self.setMinimumSize(1180, 740)
        self.server = None
        self.tray = None

        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # ---------------- barra lateral ----------------
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(240)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 24, 0, 18)
        sv.setSpacing(2)
        brand = QHBoxLayout()
        brand.setContentsMargins(20, 0, 16, 26)
        self.logo = Logo(44)
        brand.addWidget(self.logo)
        bt = QVBoxLayout()
        bt.setSpacing(0)
        bt.addWidget(label("ReForge", "Brand"))
        bt.addWidget(label("RECOMP STUDIO", "BrandSub"))
        brand.addLayout(bt, 1)
        sv.addLayout(brand)
        self.nav_layout = QVBoxLayout()
        self.nav_layout.setSpacing(2)
        sv.addLayout(self.nav_layout)
        sv.addStretch(1)
        from .profile_page import ProfileChip
        self.profile_chip = ProfileChip()
        self.profile_chip.clicked.connect(lambda: self.go("profile"))
        sv.addWidget(self.profile_chip)
        self.busy_lbl = label("", "Hint")
        self.busy_lbl.setContentsMargins(22, 0, 12, 6)
        sv.addWidget(self.busy_lbl)
        self.ver_lbl = label("", "Version")
        self.ver_lbl.setContentsMargins(22, 0, 12, 0)
        self.ver_lbl.setWordWrap(True)
        sv.addWidget(self.ver_lbl)
        h.addWidget(side)

        # ---------------- contenido ----------------
        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(36, 26, 36, 14)
        self.title_lbl = label("", "PageTitle")
        top.addWidget(self.title_lbl, 1)
        self.clock = label("", "Clock")
        top.addWidget(self.clock)
        main.addLayout(top)
        self.stack = QStackedWidget()
        main.addWidget(self.stack, 1)
        h.addLayout(main, 1)

        self.nav_group = QButtonGroup(self)
        self.nav = {}           # key -> dict(button, title, widget, owner)
        self.nav_order = []

        self.home = HomePage(self)
        self.workshop = WorkshopPage(self)
        self.env = EnvPage(self)
        self.library = LibraryPage(self)
        self.xenon = XenonPage(self)
        self.settings = SettingsPage(self)
        core_pages = {"home": self.home, "workshop": self.workshop, "env": self.env,
                      "library": self.library, "xenon": self.xenon}
        for key, text, title in CORE_NAV:
            self.add_page(key, text, title, core_pages[key])
        self._tail_index = len(self.nav_order)   # los parches se insertan antes de este punto
        from .profile_page import ProfilePage
        self.profile_page = ProfilePage(self)
        self.profile_page.changed.connect(lambda: self.profile_chip.refresh())
        self.add_page("profile", TAIL_NAV[0][1], TAIL_NAV[0][2], self.profile_page, tail=True)
        self.patches_page = PatchesPage(self)
        self.add_page("patches", TAIL_NAV[1][1], TAIL_NAV[1][2], self.patches_page, tail=True)
        self.add_page("settings", TAIL_NAV[2][1], TAIL_NAV[2][2], self.settings, tail=True)
        self.workshop.project_changed.connect(self.refresh_all)

        for i in range(1, 10):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self, activated=lambda n=i: self._go_index(n - 1))
        QShortcut(QKeySequence("F11"), self, activated=self.toggle_fullscreen)
        QShortcut(QKeySequence("Escape"), self, activated=lambda: self.isFullScreen() and self.showNormal())

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._update_clock)
        self._tick.start(1000)
        self._update_clock()
        self.apply_theme()

        # ---------------- parches ----------------
        crashed = self.patches.check_crash_guard()
        self.patch_notices = self.sync_bundled_patches()
        safe = self.args.get("safe_mode") or bool(
            QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        self.patches.load_all(lambda info: PluginAPI(self, info, self.patches.data_root), safe_mode=safe)
        self.patches_page.refresh()
        self.update_patch_badge()
        self.refresh_all()
        self.go("home")
        self._setup_watcher()
        if crashed:
            QTimer.singleShot(400, lambda: QMessageBox.warning(
                self, "Parche desactivado",
                f"La última vez ReForge Studio se cerró inesperadamente al cargar el parche «{crashed}».\n"
                "Se desactivó para proteger la aplicación. Puedes revisarlo en Parches."))
        if self.patch_notices:
            self.patches_page.notices = self.patch_notices
            self.patches_page.refresh()
        if self.args.get("install_patch"):
            QTimer.singleShot(300, lambda: self.install_patch(self.args["install_patch"]))
        self._handle_project_args(self.args, 400)
        QTimer.singleShot(3000, self.check_updates_quietly)

    # ---------------------------------------------------------------- actualizaciones
    def check_updates_quietly(self):
        """Pregunta a GitHub en segundo plano (como mucho una vez al día) y avisa si hay versión nueva."""
        from threading import Thread

        from . import update as upd

        def work():
            try:
                info = upd.check()
            except Exception:      # noqa: BLE001 — una actualización nunca debe molestar al arrancar
                info = None
            if info:
                QTimer.singleShot(0, lambda: self.offer_update(info))

        Thread(target=work, daemon=True).start()

    def offer_update(self, info):
        """Ofrece instalar la versión nueva (o la instala sola si así está configurado)."""
        from . import update as upd
        cfg = upd.load_config()
        if not cfg.get("auto_install"):
            box = QMessageBox(self)
            box.setWindowTitle("Hay una versión nueva")
            box.setText(f"ReForge Studio {info['version']} está disponible (tienes la {upd.current_version()}).")
            if info.get("notes"):
                box.setDetailedText(info["notes"][:4000])
            now = box.addButton("Actualizar ahora", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Más tarde", QMessageBox.ButtonRole.RejectRole)
            skip = box.addButton("Omitir esta versión", QMessageBox.ButtonRole.DestructiveRole)
            box.exec()
            if box.clickedButton() is skip:
                upd.save_config(skip=info["version"])
                return
            if box.clickedButton() is not now:
                return
        self._download_update(info, silent=bool(cfg.get("auto_install")))

    def _download_update(self, info, silent=False):
        from . import update as upd
        cfg = upd.load_config()
        dlg = QProgressDialog(f"Descargando ReForge Studio {info['version']}…", "Cancelar", 0, 1000, self)
        dlg.setWindowTitle("Actualización")
        dlg.setMinimumDuration(0)
        state = {"path": "", "error": ""}

        def work(ctx):
            state["path"] = upd.download(
                info, progress=lambda d, t: ctx.progress(int(d * 1000 / t), 1000),
                cancelled=ctx.cancelled, token=cfg.get("token") or "")

        def done(ok, err):
            dlg.close()
            if not ok:
                QMessageBox.warning(self, "Actualización", f"No se pudo descargar: {err}")
                return
            upd.cleanup(keep=state["path"])
            try:
                upd.install(state["path"], silent=silent)
            except upd.UpdateError as e:
                QMessageBox.warning(self, "Actualización", str(e))
                return
            QApplication.quit()

        from .runner import run_in_thread
        th = run_in_thread(work, done)
        th.progress_signal.connect(lambda v, m: dlg.setValue(v))
        dlg.canceled.connect(lambda: th.cancel_event.set())

    # ---------------------------------------------------------------- páginas
    def add_page(self, key, nav_text, title, widget, owner="", tail=False):
        if key in self.nav:
            raise ValueError(f"La página «{key}» ya existe")
        b = QPushButton(nav_text)
        b.setObjectName("NavButton")
        b.setCheckable(True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda _c=False, k=key: self.go(k))
        self.nav_group.addButton(b)
        if tail or not hasattr(self, "_tail_index"):
            pos = len(self.nav_order)
        else:
            pos = self._tail_index
            self._tail_index += 1
        self.nav_layout.insertWidget(pos, b)
        self.nav_order.insert(pos, key)
        self.stack.addWidget(widget)
        self.nav[key] = {"button": b, "title": title, "widget": widget, "owner": owner}

    def remove_page(self, key):
        entry = self.nav.pop(key, None)
        if not entry:
            return
        if key in self.nav_order:
            idx = self.nav_order.index(key)
            self.nav_order.remove(key)
            if hasattr(self, "_tail_index") and idx < self._tail_index:
                self._tail_index -= 1
        self.nav_group.removeButton(entry["button"])
        self.nav_layout.removeWidget(entry["button"])
        entry["button"].hide()
        entry["button"].setParent(None)
        entry["button"].deleteLater()
        self.stack.removeWidget(entry["widget"])
        entry["widget"].hide()
        entry["widget"].setParent(None)
        entry["widget"].deleteLater()

    def go(self, key):
        if key not in self.nav:
            return
        e = self.nav[key]
        self.stack.setCurrentWidget(e["widget"])
        e["button"].setChecked(True)
        self.title_lbl.setText(e["title"])
        if key == "home":
            self.home.hero.setFocus()
        elif key == "patches":
            self.patches_page.refresh()

    def _go_index(self, i):
        if 0 <= i < len(self.nav_order):
            self.go(self.nav_order[i])

    def open_project(self, p):
        if self.workshop.runner.running:
            QMessageBox.information(self, "Ocupado", "Hay una recompilación en curso.")
            return
        self.workshop.load_project(p)
        self.go("workshop")

    def new_from_iso(self):
        self.go("workshop")
        if not self.workshop.runner.running:
            self.workshop.new_from_iso()

    def refresh_all(self):
        self.home.refresh()
        self.library.refresh()

    def update_patch_badge(self):
        items = list(self.patches.patches.values())
        active = sum(1 for i in items if i.status == "activo")
        problems = sum(1 for i in items if i.status in ("error", "incompatible"))
        txt = f"v{__version__}"
        if items:
            txt += f" · {active} parche(s)"
        if problems:
            txt += f" · ⚠ {problems}"
        if self.patches.safe_mode:
            txt += " · 🛡 modo seguro"
        self.ver_lbl.setText(txt)
        b = self.nav["patches"]["button"]
        b.setText(dict((k, t) for k, t, _ in TAIL_NAV)["patches"] + (f"  ({len(items)})" if items else ""))

    # ---------------------------------------------------------------- parches incluidos
    def _bundled_state_path(self):
        return os.path.join(self.patches.base, "bundled.json")

    def bundled_declined(self):
        try:
            with open(self._bundled_state_path(), encoding="utf-8") as f:
                return set(json.load(f).get("declined", []))
        except Exception:
            return set()

    def set_bundled_declined(self, pid, declined=True):
        d = self.bundled_declined()
        (d.add if declined else d.discard)(pid)
        with open(self._bundled_state_path(), "w", encoding="utf-8") as f:
            json.dump({"declined": sorted(d)}, f)

    def sync_bundled_patches(self):
        """Retira parches obsoletos e instala/actualiza los parches que vienen con el programa."""
        notices = []
        self.patches.scan()
        for pid, why in OBSOLETE_PATCHES.items():
            if pid in self.patches.patches:
                self.patches.uninstall(pid, keep_data=False)
                notices.append(f"Se retiró el parche «{pid}»: {why}.")
        declined = self.bundled_declined()
        for d in bundled_patch_dirs():
            for fn in sorted(os.listdir(d)):
                if not fn.lower().endswith(PATCH_EXT):
                    continue
                path = os.path.join(d, fn)
                try:
                    new, old, incompat = self.patches.inspect(path)
                except (PatchError, Exception):
                    continue
                if incompat or new.id in declined or new.id in OBSOLETE_PATCHES:
                    continue
                if old is None or vtuple(new.version) > vtuple(old.version):
                    try:
                        self.patches.install(path)
                        notices.append(f"{'Actualizado' if old else 'Instalado'} el parche incluido "
                                       f"«{new.name}» v{new.version}.")
                    except Exception as e:
                        notices.append(f"No se pudo instalar el parche incluido «{new.name}»: {e}")
        return notices

    def update_env_status(self, missing):
        e = self.nav.get("env")
        if e:
            e["button"].setText(CORE_NAV[2][1] + (f"  ⚠ {len(missing)}" if missing else "  ✔"))
        self.home.set_env_status(missing)

    def install_patch(self, path):
        self.go("patches")
        self.raise_()
        self.activateWindow()
        self.patches_page.install_file(path)

    def set_busy(self, on):
        self.busy_lbl.setText("● Recompilando…" if on else "")

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _update_clock(self):
        self.clock.setText(datetime.datetime.now().strftime("%H:%M"))

    # ---------------------------------------------------------------- reinicio
    def restart(self, safe_mode=False):
        if self.workshop.runner.running:
            QMessageBox.information(self, "Ocupado", "Espera a que termine la recompilación.")
            return
        extra = ["--safe-mode"] if safe_mode else []
        if getattr(sys, "frozen", False):
            prog, args = sys.executable, extra
        else:
            prog, args = sys.executable, [os.path.abspath(sys.argv[0])] + extra
        if self.server is not None:
            self.server.close()
            self.server = None
        QProcess.startDetached(prog, args)
        self._restarting = True
        self.close()

    # ---------------------------------------------------------------- instancia única
    def start_server(self):
        QLocalServer.removeServer(SERVER_NAME)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_connection)
        self.server.listen(SERVER_NAME)

    def _on_connection(self):
        sock = self.server.nextPendingConnection()
        if sock is None:
            return
        sock.waitForReadyRead(1000)
        try:
            args = json.loads(bytes(sock.readAll()).decode("utf-8"))
        except Exception:
            args = {}
        sock.disconnectFromServer()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()
        if args.get("install_patch"):
            QTimer.singleShot(100, lambda: self.install_patch(args["install_patch"]))
        self._handle_project_args(args, 100)

    # ---------------------------------------------------------------- vigilante de juegos
    def _setup_watcher(self):
        from .watcher import GameWatcher
        self._outdated_asked = set()
        self.watcher = GameWatcher(lambda: list(self.lib.projects), self._project_busy)
        self.watcher.detected.connect(self._game_detected)
        self.watcher.finished.connect(self._game_finished)
        self.watcher.crashed.connect(self._game_crashed)
        self.watcher.stats.connect(self._game_stats)
        self.watcher.ended.connect(self._game_ended)
        if self.cfg.watch_games:
            self.watcher.start()

    def _project_busy(self, project):
        ws = self.workshop
        same = ws.current is not None and os.path.abspath(ws.current.root) == os.path.abspath(project.root)
        return same and (ws.runner.running or ws._session is not None)

    def _game_detected(self, project, exe):
        self.busy_lbl.setText(f"🎮 Jugando: {project.name}")
        self.notify("ReForge Studio", f"Juego detectado: {project.name}. Se vigila por si falla.")
        QTimer.singleShot(1500, lambda: self._check_outdated_game(project, exe))

    def _check_outdated_game(self, project, exe):
        """El juego abierto se compiló sin lo último de ReForge: ofrecer cerrarlo, recompilar y abrirlo de nuevo."""
        from . import game
        from .game_options import GameOptions
        from .watcher import kill_by_exe
        ws = self.workshop
        if ws.runner.running or ws._session is not None:
            return
        try:
            reason = game.rebuild_reason(project.root, exe, self.cfg)
            o = GameOptions.load(project.root)
        except Exception:      # noqa: BLE001
            return
        key = (os.path.abspath(exe), round(os.path.getmtime(exe)) if os.path.exists(exe) else 0)
        if not reason or not o.auto_repair or key in self._outdated_asked:
            return
        self._outdated_asked.add(key)
        r = QMessageBox.question(
            self, "Juego sin las últimas correcciones",
            f"{project.name} está abierto, pero {reason}.\n\n¿Cerrar el juego ahora, recompilarlo con todo lo "
            "último y volver a abrirlo solo? (Guarda tu partida antes si estás jugando.)")
        if r != QMessageBox.StandardButton.Yes:
            return
        p = self._project_for(project.root)
        ws.restarting.add(os.path.abspath(p.root))
        kill_by_exe(exe)
        if ws.current is None or os.path.abspath(ws.current.root) != os.path.abspath(p.root):
            ws.load_project(p)
        ws.log.write(f"━━━ ↻ {p.name}: se cerró para recompilar ({reason}) y se abrirá de nuevo", "head")
        QTimer.singleShot(2500, ws.rebuild_and_play)

    def _game_stats(self, project, exe, stats, seconds):
        """Estado en vivo del juego abierto (da igual cómo se lanzó)."""
        from .perfdiag import live_text
        txt = f"{live_text(stats, seconds)} · {project.name}"
        self.busy_lbl.setText(txt)
        ws = self.workshop
        if ws.current is not None and os.path.abspath(ws.current.root) == os.path.abspath(project.root) \
                and not ws.runner.running:
            ws.status_lbl.setText(live_text(stats, seconds))

    def _game_ended(self, project, exe, info):
        """Partida terminada que no vigilaba el Taller ni el lanzador: el Taller la analiza y la mantiene."""
        ws = self.workshop
        if os.path.abspath(project.root) in ws.restarting:
            ws.restarting.discard(os.path.abspath(project.root))
            return
        if info.get("path") and info["path"] in ws.handled_logs:
            return
        if ws.runner.running:
            return
        p = self._project_for(project.root)
        if ws.current is None or os.path.abspath(ws.current.root) != os.path.abspath(p.root):
            ws.load_project(p)
        self.notify("ReForge Studio", f"Partida de {p.name} terminada: revisando el juego…")
        ws.post_session(p, exe, info, external=True)

    def _game_finished(self, project):
        if self.busy_lbl.text().startswith("🎮"):
            self.busy_lbl.setText("")

    def _game_crashed(self, project, exe, info):
        from .game_options import GameOptions
        from .watcher import kill_by_exe
        self.busy_lbl.setText("")
        kill_by_exe(exe)
        lines = "\n".join(info.get("lines", [])[-4:])
        if info["kind"] == "unregistered":
            addr = info["address"]
            if GameOptions.load(project.root).auto_repair:
                self.notify("ReForge Studio", f"{project.name} se cerró (0x{addr:08X}). Reparando…")
                self._handle_project_args({"repair": [project.root, addr]}, 200)
                return
            r = QMessageBox.question(self, "El juego se cerró",
                                     f"{project.name} llamó a una función que no se recompiló (0x{addr:08X}).\n\n"
                                     "¿Declararla, recompilar y volver a probar?")
            if r == QMessageBox.StandardButton.Yes:
                self._handle_project_args({"repair": [project.root, addr]}, 0)
            return
        self.showNormal()
        self.raise_()
        if info["kind"] == "gpu":
            box = QMessageBox(self)
            box.setWindowTitle("Error gráfico")
            box.setText(f"{project.name} se cerró por un error de la GPU:\n\n{lines}\n\nSuele arreglarse con otro "
                        "modo de imagen.")
            fix = box.addButton("⚡  Abrir el asistente de imagen", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Cerrar", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is fix:
                self.open_project(self._project_for(project.root))
                self.workshop.open_optimizer()
            return
        QMessageBox.warning(self, "El juego se cerró", f"{project.name} se cerró con un error:\n\n{lines or '(sin detalles)'}")

    def _project_for(self, root):
        from .core import Project
        root = os.path.abspath(root)
        p = self.lib.get(root)
        if p is None:
            from .game import manifest_project_name
            p = self.lib.upsert(Project(name=manifest_project_name(root) or os.path.basename(root), root=root))
        return p

    def _handle_project_args(self, args, delay):
        """--open-project <raíz> y --repair <raíz> <0xDIRECCIÓN> (los envía el lanzador del juego)."""
        root = (args.get("repair") or [None])[0] or args.get("open_project") or args.get("rebuild")
        if not root or not os.path.isdir(root):
            return

        def go():
            if self.workshop.runner.running:
                QMessageBox.information(self, "Ocupado", "Hay una tarea en curso en el Taller.")
                return
            self.open_project(self._project_for(root))
            self.showNormal()
            self.raise_()
            self.activateWindow()
            if args.get("repair"):
                ws = self.workshop
                ws._repair_round, ws._repair_seen = 0, set()
                ws.log.write("━━━ Reparación pedida desde el lanzador del juego", "head")
                ws.repair_round(int(args["repair"][1]))
            elif args.get("rebuild"):
                ws = self.workshop
                ws.log.write("━━━ Recompilación pedida desde el lanzador del juego (trucos)", "head")
                ws.rebuild_current()
        QTimer.singleShot(delay, go)

    # ---------------------------------------------------------------- tema
    def apply_theme(self):
        accent = accent_color(self.cfg.accent)
        app = QApplication.instance()
        app.setProperty("accent", accent)
        app.setStyleSheet(build_qss(accent))
        icon = QIcon(logo_pixmap(256, accent))
        self.setWindowIcon(icon)
        app.setWindowIcon(icon)
        self.logo.update()

    def cfg_accent_hex(self):
        c = QColor(accent_color(self.cfg.accent))
        return c.name()[1:].upper()

    def notify(self, title, msg):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        if self.tray is None:
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
            self.tray.show()
        if not self.isActiveWindow():
            self.tray.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 6000)

    def closeEvent(self, e):
        if self.workshop.runner.running:
            r = QMessageBox.question(self, "Recompilación en curso",
                                     "Hay una recompilación en curso. ¿Cancelarla y salir?")
            if r != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            # Keep the event loop alive until the worker and its child processes stop.
            self.workshop.runner.finished.connect(lambda _ok: self.close())
            self.workshop.runner.cancel()
            e.ignore()
            return
        self.patches.shutdown()
        self.cfg.save()
        e.accept()


def _forward_to_running(args):
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(400):
        return False
    sock.write(json.dumps(args).encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ReForge.Studio")
        except Exception:
            pass
    args = parse_args(sys.argv)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("ReForge")
    if args["launcher"]:
        from .launcher import run_launcher
        sys.exit(run_launcher(args["launcher"]))
    if not args["safe_mode"] and _forward_to_running(args):
        return 0
    from .runner import wait_threads
    app.aboutToQuit.connect(wait_threads)
    w = MainWindow(args)
    w.start_server()
    w.show()
    sys.exit(app.exec())
