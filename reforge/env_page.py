"""Página «Entorno»: detecta, descarga y configura rexglue, CMake, Ninja, Clang y Visual Studio."""
import os
import shutil
import subprocess
import sys
import tempfile
import types

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QMessageBox, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from . import toolchain as detect
from . import toolchain as sdk
from .pages import panel, scroll_wrap
from .runner import PipelineRunner, Step
from .widgets import LogView, StepTracker, label, repolish


class _CfgSettings:
    """Ajustes del entorno guardados directamente en la configuración de la app."""
    MAP = {"sdk_exe": "rexglue", "sdk_prefix": "rexglue_sdk", "cli_flavor": "cli_flavor"}

    def __init__(self, cfg):
        self.cfg = cfg

    def get(self, key, default=None):
        if key == "path_dirs":
            return [d for d in (self.cfg.path_dirs or "").split(os.pathsep) if d]
        return getattr(self.cfg, self.MAP.get(key, key), default) or default

    def set(self, key, value):
        if key == "path_dirs":
            self.cfg.path_dirs = os.pathsep.join(value or [])
        else:
            setattr(self.cfg, self.MAP.get(key, key), value)
        self.cfg.save()


class _CoreAPI:
    def __init__(self, win):
        self.main_window = win
        self.app_config = win.cfg
        self.settings = _CfgSettings(win.cfg)
        self.ui = types.SimpleNamespace(label=label, panel=panel, scroll_wrap=scroll_wrap, LogView=LogView,
                                        StepTracker=StepTracker, repolish=repolish)
        self.runner = types.SimpleNamespace(PipelineRunner=PipelineRunner, Step=Step)

    def notify(self, title, msg):
        self.main_window.notify(title, msg)

    def go(self, key):
        self.main_window.go("env" if key == "main" else key)

WIN = sys.platform == "win32"
VS_OVERRIDE = ("--passive --wait --add Microsoft.VisualStudio.Workload.VCTools "
               "--add Microsoft.VisualStudio.Component.VC.CMake.Project "
               "--add Microsoft.VisualStudio.Component.VC.Llvm.Clang "
               "--add Microsoft.VisualStudio.Component.VC.Llvm.ClangToolset --includeRecommended")

COMPONENTS = [
    {"key": "rexglue", "name": "rexglue SDK", "need": "CLI rexglue + librerías del SDK",
     "url": "https://github.com/rexglue/rexglue-sdk/releases"},
    {"key": "vs", "name": "Visual Studio Build Tools (C++)", "need": "MSVC, Windows SDK y entorno vcvars64",
     "winget": ["--id", "Microsoft.VisualStudio.2022.BuildTools", "-e", "--override", VS_OVERRIDE],
     "url": "https://visualstudio.microsoft.com/visual-cpp-build-tools/", "win_only": True},
    {"key": "clang", "name": f"Clang {detect.CLANG_MIN}+", "need": "Compilador que exige rexglue",
     "winget": ["--id", "LLVM.LLVM", "-e"], "url": "https://github.com/llvm/llvm-project/releases",
     "apt": "sudo apt install clang-20"},
    {"key": "cmake", "name": "CMake 3.25+", "need": "Configura y compila el proyecto",
     "winget": ["--id", "Kitware.CMake", "-e"], "url": "https://cmake.org/download/", "apt": "sudo apt install cmake"},
    {"key": "ninja", "name": "Ninja", "need": "Generador que usan los presets de rexglue",
     "winget": ["--id", "Ninja-build.Ninja", "-e"], "url": "https://github.com/ninja-build/ninja/releases",
     "apt": "sudo apt install ninja-build"},
]
VCREDIST = {"key": "vcredist", "name": "Visual C++ Redistributable x64",
            "winget": ["--id", "Microsoft.VCRedist.2015+.x64", "-e"],
            "url": "https://aka.ms/vs/17/release/vc_redist.x64.exe"}


def short_path(p, keep=3):
    if not p:
        return ""
    parts = p.replace("\\", "/").split("/")
    return p if len(parts) <= keep + 1 else "…/" + "/".join(parts[-keep:])


class EnvPage(QWidget):
    def __init__(self, win):
        super().__init__()
        api = _CoreAPI(win)
        self.api = api
        self.s = api.settings
        self.cfg = api.app_config
        ui = api.ui
        self.ui = ui
        self.state = {}
        self.releases = []
        self.after = None
        self.runner = api.runner.PipelineRunner(self)

        root = QHBoxLayout(self)
        root.setContentsMargins(36, 10, 36, 30)
        root.setSpacing(20)
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 8, 0)
        bv.setSpacing(12)

        hero, hv = ui.panel()
        hv.addWidget(ui.label("ESTADO DEL ENTORNO", "Section"))
        self.summary = ui.label("Pulsa «Detectar» para revisar tu PC.", "BigNumber", wrap=True)
        hv.addWidget(self.summary)
        self.summary_hint = ui.label("", "Hint", wrap=True)
        self.summary_hint.setMinimumWidth(10)
        hv.addWidget(self.summary_hint)
        row = QHBoxLayout()
        self.b_auto = QPushButton("✨  Preparar todo automáticamente")
        self.b_auto.setObjectName("Primary")
        self.b_auto.clicked.connect(self.prepare_all)
        self.b_detect = QPushButton("⟳  Detectar")
        self.b_detect.clicked.connect(lambda: self.detect())
        self.b_apply = QPushButton("✔  Aplicar configuración")
        self.b_apply.setToolTip("Guarda en Ajustes las rutas detectadas (rexglue, CMake, Ninja, Clang, vcvars)")
        self.b_apply.clicked.connect(lambda: self.apply_config(verbose=True))
        for b in (self.b_auto, self.b_detect, self.b_apply):
            row.addWidget(b)
        row.addStretch(1)
        hv.addLayout(row)
        bv.addWidget(hero)

        bv.addWidget(ui.label("COMPONENTES", "Section"))
        self.cards_box = QVBoxLayout()
        self.cards_box.setSpacing(10)
        bv.addLayout(self.cards_box)

        sp, sv = ui.panel()
        sv.addWidget(ui.label("SDK DE REXGLUE", "Section"))
        r1 = QHBoxLayout()
        self.rel_combo = QComboBox()
        self.rel_combo.setMinimumWidth(200)
        self.rel_combo.addItem("Pulsa «Buscar versiones»")
        b_list = QPushButton("Buscar versiones")
        b_list.clicked.connect(self.fetch_releases)
        self.b_dl = QPushButton("⬇  Descargar e instalar")
        self.b_dl.clicked.connect(self.download_selected)
        r1.addWidget(self.rel_combo, 1)
        sv.addLayout(r1)
        r1b = QHBoxLayout()
        r1b.addWidget(b_list)
        r1b.addWidget(self.b_dl)
        r1b.addStretch(1)
        sv.addLayout(r1b)
        r2 = QHBoxLayout()
        self.inst_combo = QComboBox()
        b_use = QPushButton("Usar esta versión")
        b_use.clicked.connect(self.use_installed)
        b_pick = QPushButton("Usar un SDK existente…")
        b_pick.clicked.connect(self.pick_sdk)
        b_zip = QPushButton("Instalar desde .zip…")
        b_zip.setToolTip("Si ya descargaste rexglue-sdk-…-win-amd64.zip desde GitHub")
        b_zip.clicked.connect(self.install_from_zip)
        r2.addWidget(self.inst_combo, 1)
        sv.addLayout(r2)
        r2b = QHBoxLayout()
        for b in (b_use, b_pick, b_zip):
            r2b.addWidget(b)
        r2b.addStretch(1)
        sv.addLayout(r2b)
        r3 = QHBoxLayout()
        self.b_fsr = QPushButton("⚡  Compilar con FSR / CAS (AMD FidelityFX)")
        self.b_fsr.setToolTip("Compila una vez la misma versión de rexglue con AMD FidelityFX: los juegos ganan FSR "
                              "y CAS en «Escalado / nitidez». Tarda (todo rexglue) y deja una copia de respaldo.")
        self.b_fsr.clicked.connect(self.build_fsr_sdk)
        r3.addWidget(self.b_fsr)
        r3.addStretch(1)
        sv.addLayout(r3)
        where = ui.label(f"Se instalan en {short_path(sdk.tools_root(), 4)} · plataforma {sdk.platform_tag()}",
                         "Hint", wrap=True)
        where.setToolTip(sdk.tools_root())
        where.setMinimumWidth(10)
        sv.addWidget(where)
        bv.addWidget(sp)
        bv.addStretch(1)
        left = ui.scroll_wrap(body)
        from PySide6.QtCore import Qt
        left.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(left, 5)

        rv = QVBoxLayout()
        self.status = ui.label("Listo", "CardTitle")
        rv.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(8)
        self.progress.setRange(0, 1)
        rv.addWidget(self.progress)
        self.log = ui.LogView()
        rv.addWidget(self.log, 1)
        root.addLayout(rv, 3)

        self.runner.log.connect(self.log.write)
        self.runner.progress.connect(self._progress)
        self.runner.finished.connect(self._finished)
        self.busy = [self.b_auto, self.b_detect, self.b_apply, self.b_dl, self.b_fsr]
        self._refresh_installed()
        self.detect(quiet=True, after=lambda _ok: self._auto_configure())

    # ================================================================ ejecución
    def _progress(self, v, m):
        self.progress.setRange(0, m)
        if m:
            self.progress.setValue(min(v, m))

    def _run(self, title, func, after=None):
        if self.runner.running:
            return
        self.after = after
        self.status.setText(title)
        for b in self.busy:
            b.setEnabled(False)
        self.runner.start([self.api.runner.Step("op", title, func=func)])

    def _finished(self, ok):
        for b in self.busy:
            b.setEnabled(True)
        self.status.setText("Listo" if ok else "Detenido")
        cb, self.after = self.after, None
        if cb:
            cb(ok)

    # ================================================================ detección
    def _detect_work(self, ctx):
        st = {}
        vs = detect.visual_studio()
        st["vs"] = vs
        st["vcvars"] = detect.find_vcvars(vs)
        st["cmake"] = detect.find_cmake(vs, self.cfg.cmake if os.path.isfile(self.cfg.cmake) else "")
        st["ninja"] = detect.find_ninja(vs)
        st["clang"] = detect.find_clang(vs)
        st["winget"] = bool(WIN and shutil.which("winget"))
        cands = [self.cfg.rexglue, self.s.get("sdk_exe", "")] + [e for _v, _p, e in sdk.installed_sdks()] + \
                [shutil.which("rexglue") or ""]
        rex = {"exe": "", "version": "", "error": "", "code": None}
        for c in cands:
            if c and os.path.isfile(c):
                ok, line, code = detect.run_version(c)
                if ok:
                    rex = {"exe": c, "version": line, "error": "", "code": 0}
                    break
                rex = {"exe": c, "version": "", "error": detect.explain_exit(code) or line, "code": code}
        if rex["exe"] and not rex["error"]:
            rex["flavor"] = detect.rexglue_cli_flavor(rex["exe"])
            rex["prefix"] = detect.sdk_prefix_from_exe(rex["exe"])
        st["rexglue"] = rex
        self.state = st
        ctx.log("━━━ Detección", "head")
        for line, lvl in self.describe():
            ctx.log(line, lvl)

    def describe(self):
        st = self.state
        out = []
        r = st.get("rexglue", {})
        if r.get("exe") and not r.get("error"):
            out.append((f"✔ rexglue {r['version']} · CLI {'actual' if r.get('flavor') == 'project' else 'antigua'} · {r['exe']}", "ok"))
        elif r.get("exe"):
            out.append((f"✖ rexglue no arranca: {r['error']} ({r['exe']})", "err"))
        else:
            out.append(("✖ rexglue: no instalado", "err"))
        if WIN:
            out.append((f"✔ Visual Studio C++: {st.get('vs')}" if st.get("vcvars") else
                        "✖ Visual Studio Build Tools (C++): no encontrado", "ok" if st.get("vcvars") else "err"))
        cc, _cxx, ver, origin = st.get("clang", ("", "", "", ""))
        if cc:
            good = self._clang_ok()
            out.append((f"{'✔' if good else '⚠'} Clang {ver} ({origin}){'' if good else f' — se necesita {detect.CLANG_MIN}+'} · {cc}",
                        "ok" if good else "warn"))
        else:
            out.append(("✖ Clang: no encontrado", "err"))
        cm, cver = st.get("cmake", ("", ""))
        out.append((f"✔ CMake {cver} · {cm}" if cm and self._cmake_ok() else
                    (f"⚠ CMake {cver} — se necesita 3.25+" if cm else "✖ CMake: no encontrado"),
                    "ok" if cm and self._cmake_ok() else ("warn" if cm else "err")))
        nj, nver = st.get("ninja", ("", ""))
        out.append((f"✔ Ninja {nver} · {nj}" if nj else "✖ Ninja: no encontrado", "ok" if nj else "err"))
        return out

    def _clang_ok(self):
        ver = self.state.get("clang", ("", "", "", ""))[2]
        try:
            return int(ver.split(".")[0]) >= detect.CLANG_MIN
        except Exception:
            return False

    def _cmake_ok(self):
        ver = self.state.get("cmake", ("", ""))[1]
        try:
            return tuple(int(x) for x in ver.split(".")[:2]) >= detect.CMAKE_MIN
        except Exception:
            return False

    def missing(self):
        st = self.state
        miss = []
        r = st.get("rexglue", {})
        if not r.get("exe") or r.get("error"):
            miss.append("rexglue")
            if r.get("code") in (-1073741515, 3221225781):
                miss.append("vcredist")
        if WIN and not st.get("vcvars"):
            miss.append("vs")
        if not self._clang_ok():
            miss.append("clang")
        if not (st.get("cmake", ("",))[0] and self._cmake_ok()):
            miss.append("cmake")
        if not st.get("ninja", ("",))[0]:
            miss.append("ninja")
        return miss

    def is_ready(self):
        return bool(self.state) and not self.missing()

    def _auto_configure(self):
        """Primer arranque o configuración incompleta: guarda lo detectado sin preguntar."""
        cfg = self.cfg
        incomplete = not (cfg.rexglue and os.path.isfile(cfg.rexglue)) or not cfg.cmake or not cfg.generator
        if incomplete and (self.state.get("rexglue", {}).get("exe") or self.state.get("cmake", ("",))[0]):
            self.apply_config()
        try:
            self.api.main_window.update_env_status(self.missing())
        except Exception:
            pass

    def detect(self, quiet=False, after=None):
        def done(ok):
            self.render()
            if after:
                after(ok)
        self._run("Detectando herramientas…", self._detect_work, done)

    # ================================================================ vista
    def render(self):
        while self.cards_box.count():
            it = self.cards_box.takeAt(0)
            w = it.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        miss = self.missing()
        comps = [c for c in COMPONENTS if WIN or not c.get("win_only")]
        if "vcredist" in miss:
            comps.insert(1, VCREDIST)
        for c in comps:
            ok = c["key"] not in miss
            card, cv = self.ui.panel()
            card.setObjectName("Card")
            top = QHBoxLayout()
            top.addWidget(self.ui.label(c["name"], "CardTitle"), 1)
            chip = self.ui.label("LISTO" if ok else "FALTA", "Chip")
            chip.setProperty("kind", "" if ok else "err")
            top.addWidget(chip)
            cv.addLayout(top)
            full = self._detail(c["key"])
            det = self.ui.label(self._short_detail(full) or c.get("need", ""), "Hint", wrap=True)
            det.setToolTip(full)
            det.setMinimumWidth(10)
            cv.addWidget(det)
            if not ok:
                row = QHBoxLayout()
                if c["key"] == "rexglue":
                    b = QPushButton("⬇ Descargar la última versión")
                    b.setObjectName("Primary")
                    b.clicked.connect(self.download_latest)
                    row.addWidget(b)
                elif WIN and c.get("winget") and self.state.get("winget"):
                    b = QPushButton("Instalar con winget")
                    b.setObjectName("Primary")
                    b.clicked.connect(lambda _c=False, cc=c: self.winget(cc))
                    row.addWidget(b)
                elif not WIN and c.get("apt"):
                    row.addWidget(self.ui.label(f"Terminal: {c['apt']}", "Hint"))
                if c.get("url"):
                    w = QPushButton("Página de descarga")
                    w.clicked.connect(lambda _c=False, u=c["url"]: QDesktopServices.openUrl(QUrl(u)))
                    row.addWidget(w)
                row.addStretch(1)
                cv.addLayout(row)
            self.cards_box.addWidget(card)
        try:
            self.api.main_window.update_env_status(miss)
        except Exception:
            pass
        if not miss:
            self.summary.setText("✔ Listo para recompilar")
            self.summary_hint.setText("Pulsa «Aplicar configuración» si aún no lo hiciste, y vuelve al Taller.")
        else:
            self.summary.setText(f"Faltan {len(miss)} componente(s)")
            self.summary_hint.setText("«Preparar todo» descarga rexglue y configura ReForge Studio. "
                                      "Lo que se instala con winget abre una ventana aparte; al terminar pulsa «Detectar».")
        self._refresh_installed()

    @staticmethod
    def _short_detail(text):
        if " · " in text:
            head, _sep, path = text.rpartition(" · ")
            return f"{head} · {short_path(path)}"
        return short_path(text) if ("/" in text or "\\" in text) else text

    def _detail(self, key):
        st = self.state
        if key == "rexglue":
            r = st.get("rexglue", {})
            if r.get("exe") and not r.get("error"):
                return f"v{r['version']} · {r['exe']}"
            return r.get("error") or ""
        if key == "vs":
            return st.get("vcvars", "")
        if key == "clang":
            cc, _x, ver, origin = st.get("clang", ("", "", "", ""))
            return f"{ver} ({origin}) · {cc}" if cc else ""
        if key == "cmake":
            p, v = st.get("cmake", ("", ""))
            return f"{v} · {p}" if p else ""
        if key == "ninja":
            p, v = st.get("ninja", ("", ""))
            return f"{v} · {p}" if p else ""
        return ""

    # ================================================================ configuración
    def apply_config(self, verbose=False):
        st = self.state
        win = self.api.main_window
        settings_page = getattr(win, "settings", None)
        changes = []

        def set_field(key, value):
            if value and getattr(self.cfg, key) != value:
                setattr(self.cfg, key, value)
                changes.append(f"{key} = {value}")
                if settings_page and key in getattr(settings_page, "fields", {}):
                    settings_page.fields[key].setText(value)

        r = st.get("rexglue", {})
        if r.get("exe") and not r.get("error"):
            set_field("rexglue", r["exe"])
            self.s.set("sdk_exe", r["exe"])
            self.s.set("sdk_prefix", r.get("prefix", ""))
            self.s.set("cli_flavor", r.get("flavor", "") or "project")
        cm = st.get("cmake", ("", ""))[0]
        set_field("cmake", cm)
        set_field("ninja", st.get("ninja", ("",))[0])
        if WIN:
            set_field("vcvars", st.get("vcvars", ""))
        if self.cfg.generator != "Ninja":
            self.cfg.generator = "Ninja"
            changes.append("generador = Ninja")
            if settings_page:
                settings_page.gen.setCurrentText("Ninja")
        cc, cxx, _v, _o = st.get("clang", ("", "", "", ""))
        if cc and self._clang_ok():
            for key, val, w in (("c_compiler", cc, "cc"), ("cxx_compiler", cxx, "cxx")):
                if getattr(self.cfg, key) != val:
                    setattr(self.cfg, key, val)
                    changes.append(f"{key} = {val}")
                    if settings_page and hasattr(settings_page, w):
                        getattr(settings_page, w).setText(val)
        dirs = []
        for p in (st.get("ninja", ("",))[0], cc if self._clang_ok() else "", r.get("exe", "")):
            if p:
                d = os.path.dirname(p)
                if d not in dirs:
                    dirs.append(d)
        self.s.set("path_dirs", dirs)
        self.cfg.save()
        try:
            win.home.refresh()
        except Exception:
            pass
        self.log.write("━━━ Configuración aplicada", "head")
        for c in changes or ["(sin cambios: ya estaba configurado)"]:
            self.log.write("  " + c, "ok")
        if dirs:
            self.log.write("  PATH de compilación + " + "; ".join(dirs), "dim")
        if self.s.get("sdk_prefix"):
            self.log.write(f"  CMAKE_PREFIX_PATH = {self.s.get('sdk_prefix')}", "dim")
        if verbose and not changes:
            QMessageBox.information(self, "Configuración", "Todo estaba ya configurado.")

    # ================================================================ SDK
    def _refresh_installed(self):
        self.inst_combo.clear()
        items = sdk.installed_sdks()
        for ver, _prefix, exe in items:
            self.inst_combo.addItem(f"v{ver}", exe)
        if not items:
            self.inst_combo.addItem("Ningún SDK instalado por ReForge", "")

    def fetch_releases(self, after=None):
        def work(ctx):
            ctx.log("Consultando GitHub Releases de rexglue/rexglue-sdk…")
            self.releases = sdk.list_releases()
            ctx.log(f"{len(self.releases)} versión(es) para {sdk.platform_tag()}", "ok")

        def done(ok):
            self.rel_combo.clear()
            for r in self.releases:
                tag = " (nightly)" if r["prerelease"] else ""
                self.rel_combo.addItem(f"v{r['version']}{tag} · {r['date']} · {r['size'] / 1e6:.0f} MB", r)
            if not self.releases:
                self.rel_combo.addItem("No se encontraron versiones")
            if after:
                after(ok)
        self._run("Buscando versiones…", work, done)

    def _install_release(self, rel, after=None):
        def work(ctx):
            prefix, exe = sdk.download_and_install(rel, ctx)
            ok, line, code = detect.run_version(exe)
            if ok:
                ctx.log(f"✔ rexglue {line} instalado en {prefix}", "ok")
            else:
                ctx.log(f"⚠ Instalado, pero rexglue no arranca: {detect.explain_exit(code) or line}", "warn")
            self.s.set("sdk_exe", exe)
            self.s.set("sdk_prefix", prefix)
            self.s.set("cli_flavor", "")
            self.cfg.rexglue = exe

        def done(ok):
            if ok:
                self.detect(after=lambda _o: (self.apply_config(), after and after(True)))
            elif after:
                after(False)
        self._run(f"Instalando rexglue v{rel['version']}…", work, done)

    def download_selected(self):
        rel = self.rel_combo.currentData()
        if not isinstance(rel, dict):
            return self.fetch_releases(after=lambda ok: ok and self.download_selected())
        self._install_release(rel)

    def download_latest(self, after=None):
        def got(ok):
            if ok and self.releases:
                self._install_release(self.releases[0], after)
            elif after:
                after(False)
        self.fetch_releases(after=got)

    def use_installed(self):
        exe = self.inst_combo.currentData()
        if not exe:
            return
        self.cfg.rexglue = exe
        self.s.set("sdk_exe", exe)
        self.s.set("sdk_prefix", detect.sdk_prefix_from_exe(exe))
        self.s.set("cli_flavor", "")
        self.detect(after=lambda _o: self.apply_config())

    def install_from_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, "Zip del SDK de rexglue", "",
                                              "SDK de rexglue (rexglue-sdk-*.zip);;Zip (*.zip)")
        if path:
            self._install_zip(path)

    def _install_zip(self, path, after=None):
        version = sdk.version_from_zip_name(path)

        def work(ctx):
            ctx.log(f"Instalando {os.path.basename(path)}…")
            prefix, exe = sdk.install_zip(path, version, ctx)
            ok, line, code = detect.run_version(exe)
            ctx.log(f"✔ rexglue {line} instalado en {prefix}" if ok else
                    f"⚠ Instalado, pero rexglue no arranca: {detect.explain_exit(code) or line}",
                    "ok" if ok else "warn")
            self.s.set("sdk_exe", exe)
            self.s.set("sdk_prefix", prefix)
            self.s.set("cli_flavor", "")
            self.cfg.rexglue = exe

        def done(ok):
            if ok:
                self.detect(after=lambda _o: (self.apply_config(), after and after(True)))
            elif after:
                after(False)
        self._run("Instalando SDK desde zip…", work, done)

    def build_fsr_sdk(self):
        from . import fidelityfx
        exe = self.cfg.rexglue
        prefix = detect.sdk_prefix_from_exe(exe) if exe else ""
        version = os.path.basename(os.path.dirname(prefix)) if prefix else ""
        if not version:
            return QMessageBox.information(self, "FSR / CAS", "Primero instala o elige un SDK de rexglue.")
        if fidelityfx.is_fsr_version(version):
            return QMessageBox.information(self, "FSR / CAS", f"Ya usas rexglue {version}, con FSR y CAS.")
        r = QMessageBox.question(
            self, "Compilar rexglue con FSR / CAS",
            f"Se compilará rexglue {version} con AMD FidelityFX (FSR 1 y CAS dentro de los juegos).\n\n"
            "• Una sola vez por PC: unos 20-40 minutos y unos 10 GB libres en el disco.\n"
            "• Necesita internet (código de rexglue, sus dependencias y FidelityFX).\n"
            "• Deja una copia en Documentos\\ReForgeStudio\\Respaldo para reinstalar sin compilar.\n\n"
            "Después, cada juego se recompila solo la próxima vez que pulses ▶ Jugar.\n\n¿Empezar?")
        if r != QMessageBox.StandardButton.Yes:
            return

        def work(ctx):
            new_prefix, new_exe, zpath = fidelityfx.build(self.cfg, version, ctx)
            self.s.set("sdk_exe", new_exe)
            self.s.set("sdk_prefix", new_prefix)
            self.s.set("cli_flavor", "")
            self.cfg.rexglue = new_exe
            ctx.log(f"Copia de respaldo: {zpath}", "ok")

        def done(ok):
            if ok:
                self.detect(after=lambda _o: self.apply_config())
                self.api.notify("ReForge Studio", "rexglue con FSR/CAS listo: recompila los juegos con ▶ Jugar")
        self._run("Compilando rexglue con FSR / CAS…", work, done)

    def pick_sdk(self):
        d = QFileDialog.getExistingDirectory(self, "Carpeta del SDK de rexglue (contiene bin/ y lib/)")
        if not d:
            return
        exe = sdk.find_exe(d)
        if not exe:
            QMessageBox.warning(self, "SDK no válido", "No se encontró bin/rexglue en esa carpeta.")
            return
        self.cfg.rexglue = exe
        self.s.set("sdk_exe", exe)
        self.s.set("sdk_prefix", detect.sdk_prefix_from_exe(exe))
        self.s.set("cli_flavor", "")
        self.detect(after=lambda _o: self.apply_config())

    # ================================================================ todo en uno
    def prepare_all(self):
        def after_detect(_ok):
            miss = self.missing()
            if "rexglue" in miss:
                self.download_latest(after=lambda _o: finish())
            else:
                self.apply_config()
                finish()

        def finish():
            miss = self.missing()
            self.render()
            if not miss:
                self.log.write("★ Entorno listo. Ya puedes recompilar desde el Taller.", "ok")
                self.api.notify("Entorno rexglue", "Todo listo para recompilar")
                return
            names = {c["key"]: c["name"] for c in COMPONENTS + [VCREDIST]}
            self.log.write("Todavía falta: " + ", ".join(names.get(m, m) for m in miss), "warn")
            if WIN and self.state.get("winget"):
                pend = [c for c in COMPONENTS + [VCREDIST] if c["key"] in miss and c.get("winget")]
                if pend and QMessageBox.question(
                        self, "Instalar componentes",
                        "Se abrirá una ventana de winget para instalar:\n\n• " +
                        "\n• ".join(c["name"] for c in pend) +
                        "\n\nWindows puede pedir permisos de administrador. Al terminar, pulsa «Detectar».") \
                        == QMessageBox.StandardButton.Yes:
                    self.winget_many(pend)
        self.detect(after=after_detect)

    # ================================================================ winget
    def winget(self, comp):
        self.winget_many([comp])

    def winget_many(self, comps):
        if not WIN:
            return
        lines = ["@echo off", "chcp 65001 >nul", "title ReForge Studio - instalando componentes"]
        for c in comps:
            args = " ".join(f'"{a}"' if " " in a else a for a in c["winget"])
            lines += ["echo.", f"echo === {c['name']} ===",
                      f"winget install {args} --accept-package-agreements --accept-source-agreements"]
        lines += ["echo.", "echo Terminado. Vuelve a ReForge Studio y pulsa Detectar.", "pause"]
        path = os.path.join(tempfile.gettempdir(), "reforge_winget.cmd")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\r\n".join(lines) + "\r\n")
        subprocess.Popen(["cmd.exe", "/c", path], creationflags=0x00000010)   # CREATE_NEW_CONSOLE
        self.log.write("Se abrió la instalación con winget: " + ", ".join(c["name"] for c in comps), "info")
