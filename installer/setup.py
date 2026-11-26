"""Instalador / actualizador de ReForge Studio.

* Detecta la versión instalada (registro de Windows HKCU\\Software\\ReForgeStudio).
* Instala, actualiza, repara o (con confirmación) vuelve a una versión anterior.
* Actualización atómica: carpeta nueva → intercambio → si falla, restaura la anterior.
* Nunca toca tus datos: proyectos, ajustes y parches viven en %APPDATA%\\ReForgeStudio.
* Crea acceso directo en el Escritorio y en el menú Inicio, asocia los archivos .rfpatch
  y registra la desinstalación en «Aplicaciones instaladas».

* 1.2: elige la carpeta de proyectos, descarga el SDK de rexglue dentro del programa
  (o usa un rexglue-sdk-*.zip que esté junto al instalador) y deja ReForge configurado.
  La carpeta tools (SDK) se conserva al actualizar.

Uso silencioso:
  ReForgeStudio-Setup.exe --silent [--dir RUTA] [--workspace RUTA] [--sdk] [--sdk-zip ZIP]
                          [--no-desktop] [--force]
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import threading
import zipfile

APP = "ReForge Studio"
APP_KEY = "ReForgeStudio"
EXE = "ReForgeStudio.exe" if os.name == "nt" else "ReForgeStudio"
PATCH_EXT = ".rfpatch"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # para «from reforge import toolchain» desde el código
from reforge import toolchain  # noqa: E402


def resource(name):
    base = getattr(sys, "_MEIPASS", "") or os.environ.get("REFORGE_SETUP_RES") or HERE
    return os.path.join(base, name)


def setup_dir():
    """Carpeta donde está el instalador (para buscar un zip del SDK junto a él)."""
    return os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))


def find_local_sdk_zip():
    tag = toolchain.platform_tag()
    cands = []
    for d in {setup_dir(), os.getcwd()}:
        try:
            cands += [os.path.join(d, f) for f in os.listdir(d)
                      if f.startswith("rexglue-sdk-") and f.endswith(f"-{tag}.zip")]
        except OSError:
            pass
    # el SDK compilado con FSR/CAS (copia de respaldo de ReForge) tiene preferencia
    return sorted(cands, key=lambda c: ("-fsr-" in os.path.basename(c), os.path.basename(c)))[-1] if cands else ""


def user_config_path():
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_KEY, "config.json")


def read_user_config():
    try:
        with open(user_config_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_user_config(updates):
    cfg = read_user_config()
    cfg.update({k: v for k, v in updates.items() if v is not None})
    path = user_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def default_workspace():
    return read_user_config().get("workspace") or os.path.join(os.path.expanduser("~"), "ReForgeProjects")


def existing_sdk_ok():
    exe = read_user_config().get("rexglue", "")
    return bool(exe and os.path.isfile(exe))


class _Ctx:
    def __init__(self, progress=None, log=print, lo=0.0, hi=1.0):
        self._p, self._log, self.lo, self.hi = progress, log, lo, hi

    def progress(self, v, m):
        if self._p and m:
            self._p(self.lo + (self.hi - self.lo) * v / m)

    def cancelled(self):
        return False

    def log(self, text, level="info"):
        self._log(text)


def install_sdk(target_dir, zip_path="", progress=None, log=print, lo=0.0, hi=1.0):
    """Instala el SDK de rexglue en <programa>/tools/rexglue-sdk/<versión>. Devuelve (prefijo, exe)."""
    os.environ["REFORGE_TOOLS_DIR"] = os.path.join(target_dir, "tools")
    ctx = _Ctx(progress, log, lo, hi)
    if zip_path:
        log(f"Instalando SDK desde {os.path.basename(zip_path)}…")
        return toolchain.install_zip(zip_path, toolchain.version_from_zip_name(zip_path), ctx)
    log("Buscando la última versión de rexglue en GitHub…")
    rel = toolchain.list_releases()[0]
    log(f"Descargando rexglue {rel['version']}…")
    return toolchain.download_and_install(rel, ctx)


def vtuple(v):
    parts = [int(x) for x in str(v).split(".") if x.isdigit()]
    return tuple(parts + [0] * (4 - len(parts)))


def payload_info():
    with open(resource("payload.json"), encoding="utf-8") as f:
        return json.load(f)


def default_dir():
    if os.name == "nt":
        return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs", APP)
    return os.path.join(os.path.expanduser("~"), ".local", "share", APP_KEY)


# ================================================================ registro
class Registry:
    """HKCU en Windows; archivo JSON en otros sistemas (para pruebas)."""

    def __init__(self):
        self.win = os.name == "nt"
        if not self.win:
            base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
            self.path = os.path.join(base, APP_KEY, "install.json")

    def read(self):
        if self.win:
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\{APP_KEY}") as k:
                    return {"dir": winreg.QueryValueEx(k, "InstallDir")[0],
                            "version": winreg.QueryValueEx(k, "Version")[0]}
            except OSError:
                return None
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def write(self, install_dir, version):
        if not self.win:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"dir": install_dir, "version": version}, f)
            return
        import winreg
        exe = os.path.join(install_dir, EXE)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\{APP_KEY}") as k:
            winreg.SetValueEx(k, "InstallDir", 0, winreg.REG_SZ, install_dir)
            winreg.SetValueEx(k, "Version", 0, winreg.REG_SZ, version)
        unk = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_KEY}"
        size_kb = sum(os.path.getsize(os.path.join(dp, f)) for dp, _d, fn in os.walk(install_dir) for f in fn) // 1024
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, unk) as k:
            for name, val in (("DisplayName", APP), ("DisplayVersion", version), ("Publisher", "ReForge"),
                              ("DisplayIcon", exe), ("InstallLocation", install_dir),
                              ("UninstallString", f'cmd.exe /c "{os.path.join(install_dir, "uninstall.cmd")}"')):
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
            winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, int(size_kb))
            winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)

    def associate(self, install_dir):
        if not self.win:
            return
        import winreg
        exe = os.path.join(install_dir, EXE)
        cls = "ReForgeStudio.Patch"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PATCH_EXT}") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cls)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{cls}") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Parche de ReForge Studio")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{cls}\DefaultIcon") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f"{exe},0")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{cls}\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{exe}" --install-patch "%1"')
        try:
            import ctypes
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
        except Exception:
            pass


# ================================================================ accesos directos
def _ps(script):
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                   capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL, timeout=60, creationflags=NO_WINDOW)


def special_folder(name):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", f"[Environment]::GetFolderPath('{name}')"],
                       capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL, timeout=30, creationflags=NO_WINDOW)
    return r.stdout.strip()


def make_shortcut(lnk, target, workdir):
    os.makedirs(os.path.dirname(lnk), exist_ok=True)
    esc = lambda s: s.replace("'", "''")  # noqa: E731
    _ps(f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{esc(lnk)}');"
        f"$s.TargetPath='{esc(target)}';$s.WorkingDirectory='{esc(workdir)}';"
        f"$s.IconLocation='{esc(target)},0';$s.Description='{APP}';$s.Save()")


def shortcut_paths():
    if os.name != "nt":
        return []
    desktop = special_folder("Desktop")
    programs = special_folder("Programs")
    return [os.path.join(desktop, f"{APP}.lnk"), os.path.join(programs, f"{APP}.lnk")]


UNINSTALL_CMD = r"""@echo off
setlocal
if not "%~1"=="--run" (
  copy /y "%~f0" "%TEMP%\reforge_uninstall.cmd" >nul
  start "" "%TEMP%\reforge_uninstall.cmd" --run "%~dp0."
  exit /b
)
set "DIR=%~f2"
echo Desinstalando ReForge Studio...
taskkill /im ReForgeStudio.exe /f >nul 2>&1
timeout /t 2 /nobreak >nul
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do del /q "%%D\ReForge Studio.lnk" >nul 2>&1
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Programs')"`) do del /q "%%D\ReForge Studio.lnk" >nul 2>&1
reg delete "HKCU\Software\ReForgeStudio" /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\ReForgeStudio" /f >nul 2>&1
reg delete "HKCU\Software\Classes\.rfpatch" /f >nul 2>&1
reg delete "HKCU\Software\Classes\ReForgeStudio.Patch" /f >nul 2>&1
rd /s /q "%DIR%" >nul 2>&1
echo Listo. Tus proyectos, ajustes y parches siguen en %APPDATA%\ReForgeStudio
timeout /t 4 >nul
(goto) 2>nul & del "%~f0"
"""


# ================================================================ instalación
def log_path():
    return os.path.join(os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp", "ReForgeStudio-setup.log")


def _filelog(text):
    try:
        with open(log_path(), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%H:%M:%S}] {text}\n")
    except OSError:
        pass


def is_running():
    if os.name != "nt":
        return False
    try:
        r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/NH"], capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL,
                           creationflags=NO_WINDOW, timeout=30)
    except Exception as e:          # nunca bloquear el botón por esto
        _filelog(f"tasklist falló: {e!r}")
        return False
    return EXE.lower() in (r.stdout or "").lower()


def close_running(install_dir=None):
    """Cierra ReForge Studio y cualquier programa que se esté ejecutando DESDE la carpeta del programa
    (rexglue, cmake, ninja, clang… de tools). Sin esto Windows no deja reemplazar los archivos."""
    if os.name != "nt":
        return
    subprocess.run(["taskkill", "/IM", EXE, "/F", "/T"], capture_output=True, creationflags=NO_WINDOW)
    if install_dir:
        d = os.path.abspath(install_dir).replace("'", "''")
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Get-Process | Where-Object {{ $_.Path -and $_.Path.StartsWith('{d}\\', "
                        "[StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force"],
                       capture_output=True, timeout=60, creationflags=NO_WINDOW)
    import time
    time.sleep(1.0)


def _retry(fn, *args, tries=20, delay=0.5):
    """Windows Defender u otro antivirus bloquean unos segundos los archivos recién extraídos:
    se reintenta en vez de abandonar la actualización."""
    import time
    for i in range(tries):
        try:
            return fn(*args)
        except PermissionError:
            if i == tries - 1:
                raise
        except OSError as e:
            if getattr(e, "winerror", None) not in (5, 32, 33) or i == tries - 1:
                raise
        time.sleep(delay)


def installed_version(install_dir):
    try:
        with open(os.path.join(install_dir, "version.json"), encoding="utf-8") as f:
            return json.load(f).get("version")
    except Exception:
        return None


def plan(target_dir=None):
    """Devuelve dict con la situación actual: acción, versiones y carpeta."""
    new = payload_info()["version"]
    reg = Registry().read() or {}
    folder = target_dir or reg.get("dir") or default_dir()
    # version.json de la carpeta es la verdad (el registro puede haberse quedado atrás)
    old = installed_version(folder) or reg.get("version")
    if not old and os.path.isfile(os.path.join(folder, EXE)):
        old = "0.0.0"
    if not old:
        action = "install"
    elif vtuple(new) > vtuple(old):
        action = "update"
    elif vtuple(new) == vtuple(old):
        action = "repair"
    else:
        action = "downgrade"
    return {"new": new, "old": old, "dir": folder, "action": action}


def _swap_in(staging, target_dir, backup, log):
    """Reemplaza, elemento a elemento, los archivos del programa. La carpeta tools (SDK y
    herramientas) y cualquier otra cosa que no venga en el paquete NO se toca."""
    os.makedirs(target_dir, exist_ok=True)
    os.makedirs(backup, exist_ok=True)
    done = []           # (nombre, había_anterior)
    try:
        for name in sorted(os.listdir(staging)):
            if name == "tools":
                continue
            dst, src, bak = (os.path.join(target_dir, name), os.path.join(staging, name),
                             os.path.join(backup, name))
            had = os.path.lexists(dst)
            if had:
                _retry(os.replace, dst, bak)
            try:
                _retry(os.replace, src, dst)
            except Exception:
                if had:
                    _retry(os.replace, bak, dst)
                raise
            done.append((name, had))
            _filelog(f"reemplazado {name}")
    except Exception as e:
        log("Restaurando la versión anterior…")
        _filelog(f"ERROR al reemplazar: {e!r}; revirtiendo {len(done)} elementos")
        for name, had in reversed(done):
            dst = os.path.join(target_dir, name)
            try:
                if os.path.isdir(dst) and not os.path.islink(dst):
                    shutil.rmtree(dst, ignore_errors=True)
                elif os.path.lexists(dst):
                    os.remove(dst)
                if had:
                    _retry(os.replace, os.path.join(backup, name), dst)
            except Exception as e2:
                _filelog(f"no se pudo restaurar {name}: {e2!r}")
        raise


def _locked_hint(e):
    if isinstance(e, PermissionError) or getattr(e, "winerror", None) in (5, 32, 33):
        return ("\n\nWindows no dejó reemplazar un archivo porque está en uso. Cierra ReForge Studio, el juego "
                "recompilado, cualquier ventana del Explorador abierta en la carpeta del programa y vuelve a "
                "intentarlo. Si persiste, reinicia el PC o pausa unos minutos el antivirus.")
    return ""


def install(target_dir, desktop=True, startmenu=True, associate=True, progress=None, log=print,
            workspace=None, sdk=False, sdk_zip=""):
    info = payload_info()
    version = info["version"]
    target_dir = os.path.abspath(target_dir)
    parent = os.path.dirname(target_dir)
    os.makedirs(parent, exist_ok=True)
    staging = target_dir + ".new"
    backup = target_dir + ".old"
    _filelog(f"=== instalar v{version} en {target_dir} (anterior: {installed_version(target_dir)}) ===")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)

    log(f"Preparando {APP} v{version}…")
    with zipfile.ZipFile(resource("payload.zip")) as z:
        members = [m for m in z.infolist() if not m.is_dir()]
        total = sum(m.file_size for m in members) or 1
        done = 0
        for m in members:
            dest = os.path.realpath(os.path.join(staging, m.filename))
            if not dest.startswith(os.path.realpath(staging) + os.sep):
                raise RuntimeError(f"Ruta no válida en el paquete: {m.filename}")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(m) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            mode = (m.external_attr >> 16) & 0o777
            if os.name != "nt" and mode:
                os.chmod(dest, mode)
            done += m.file_size
            if progress:
                progress(done / total * (0.55 if (sdk or sdk_zip) else 0.85))
    if not os.path.isfile(os.path.join(staging, EXE)):
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError("El paquete no contiene el ejecutable principal")
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(os.path.join(staging, "version.json"), "w", encoding="utf-8") as f:
        json.dump({"version": version, "installed_at": stamp, "install_dir": target_dir,
                   "channel": info.get("channel", "stable"), "build": info.get("build", "")}, f, indent=2)
    if os.name == "nt":
        with open(os.path.join(staging, "uninstall.cmd"), "w", encoding="ascii", errors="ignore") as f:
            f.write(UNINSTALL_CMD.replace("\n", "\r\n"))
    _filelog(f"extraídos {len(members)} archivos")

    log("Cerrando programas que usan la carpeta…")
    close_running(target_dir)
    log("Instalando archivos…")
    try:
        _swap_in(staging, target_dir, backup, log)
    except Exception as e:
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError(f"{e}{_locked_hint(e)}") from e
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    got = installed_version(target_dir)
    if got != version:
        raise RuntimeError(f"Tras copiar, la carpeta indica v{got} en vez de v{version}.")
    _filelog(f"archivos de v{version} en su sitio")
    if progress:
        progress(0.92)

    warnings = []
    reg = Registry()
    try:
        reg.write(target_dir, version)
    except Exception as e:
        warnings.append(f"registro: {e}")
    exe = os.path.join(target_dir, EXE)
    if os.name == "nt":
        try:
            paths = shortcut_paths()
            if desktop and paths:
                log("Creando acceso directo en el Escritorio…")
                make_shortcut(paths[0], exe, target_dir)
            if startmenu and len(paths) > 1:
                make_shortcut(paths[1], exe, target_dir)
        except Exception as e:
            warnings.append(f"accesos directos: {e}")
        if associate:
            try:
                reg.associate(target_dir)
            except Exception as e:
                warnings.append(f".rfpatch: {e}")
    updates = {}
    if workspace:
        os.makedirs(workspace, exist_ok=True)
        updates["workspace"] = workspace
    if sdk or sdk_zip:
        try:
            prefix, rex = install_sdk(target_dir, sdk_zip, progress, log, 0.6, 0.98)
            updates.update(rexglue=rex, rexglue_sdk=prefix, cli_flavor="")
            log(f"✔ rexglue SDK listo en {prefix}")
        except Exception as e:
            log(f"⚠ No se pudo instalar el SDK de rexglue ({e}). Podrás hacerlo desde Entorno.")
            warnings.append(f"SDK: {e}")
    if updates:
        write_user_config(updates)
    for w in warnings:
        _filelog("aviso: " + w)
    if progress:
        progress(1.0)
    log(f"✔ {APP} v{version} instalado en {target_dir}")
    _filelog("terminado")
    return exe


# ================================================================ interfaz
def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    BG, PANEL, TEXT, MUTED, ACCENT = "#0b0d10", "#151a21", "#e8ecf1", "#8b96a5", "#19d3a2"
    _filelog(f"--- instalador abierto · Python {sys.version.split()[0]} · {sys.executable}")
    p = plan()
    _filelog(f"plan: {p}")
    root = tk.Tk()

    def on_tk_error(exc, val, tb):
        # sin consola, un error dentro de un clic desaparecería en silencio: se muestra y se registra
        import traceback
        _filelog("ERROR en la interfaz:\n" + "".join(traceback.format_exception(exc, val, tb)))
        try:
            go.configure(state="normal")
        except Exception:
            pass
        messagebox.showerror(APP, f"Error inesperado: {val}\n\nDetalles: {log_path()}")
    root.report_callback_exception = on_tk_error
    root.title(f"Instalar {APP}")
    root.configure(bg=BG)
    root.geometry("660x700")
    root.resizable(False, False)
    try:
        root.iconbitmap(resource("icon.ico"))
    except Exception:
        pass
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("A.Horizontal.TProgressbar", troughcolor=PANEL, background=ACCENT, bordercolor=PANEL,
                    lightcolor=ACCENT, darkcolor=ACCENT)

    def lbl(text, size=10, color=TEXT, bold=False, pady=0, wrap=560):
        w = tk.Label(root, text=text, bg=BG, fg=color, font=("Segoe UI", size, "bold" if bold else "normal"),
                     anchor="w", justify="left", wraplength=wrap)
        w.pack(fill="x", padx=36, pady=pady)
        return w

    lbl("REFORGE STUDIO", 9, ACCENT, True, (30, 0))
    titles = {"install": "Instalar", "update": "Actualizar", "repair": "Reparar",
              "downgrade": "Volver a una versión anterior"}
    lbl(f"{titles[p['action']]} · v{p['new']}", 22, TEXT, False, (2, 4))
    if p["old"]:
        status = {"update": f"Tienes instalada la v{p['old']}. Se actualizará a la v{p['new']}.",
                  "repair": f"Ya tienes la v{p['old']}. Se reinstalarán los archivos del programa.",
                  "downgrade": f"⚠ Tienes una versión MÁS NUEVA (v{p['old']}). Instalar la v{p['new']} es una "
                               "vuelta atrás y algunos parches podrían quedar incompatibles."}[p["action"]]
    else:
        status = "No se encontró una instalación anterior."
    lbl(status, 10, "#e3b341" if p["action"] == "downgrade" else MUTED, pady=(0, 6))
    lbl("Tus proyectos, ajustes y parches se conservan (están en %APPDATA%\\ReForgeStudio).", 9, MUTED,
        pady=(0, 14))

    frm = tk.Frame(root, bg=BG)
    frm.pack(fill="x", padx=36)
    dir_var = tk.StringVar(value=p["dir"])
    tk.Label(frm, text="Carpeta", bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
    row = tk.Frame(frm, bg=BG)
    row.pack(fill="x", pady=(2, 10))
    ent = tk.Entry(row, textvariable=dir_var, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief="flat",
                   font=("Segoe UI", 10))
    ent.pack(side="left", fill="x", expand=True, ipady=6)

    def browse():
        d = filedialog.askdirectory(initialdir=os.path.dirname(dir_var.get()))
        if d:
            dir_var.set(os.path.join(os.path.normpath(d), APP))
    bbtn = tk.Button(row, text="…", command=browse, bg=PANEL, fg=TEXT, relief="flat", width=4)
    bbtn.pack(side="left", padx=(6, 0))
    if p["old"]:
        ent.configure(state="disabled")
        bbtn.configure(state="disabled")

    tk.Label(frm, text="Carpeta de proyectos (juegos recompilados)", bg=BG, fg=MUTED,
             font=("Segoe UI", 9)).pack(anchor="w")
    ws_var = tk.StringVar(value=default_workspace())
    row2 = tk.Frame(frm, bg=BG)
    row2.pack(fill="x", pady=(2, 10))
    tk.Entry(row2, textvariable=ws_var, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief="flat",
             font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True, ipady=6)

    def browse_ws():
        d = filedialog.askdirectory(initialdir=ws_var.get())
        if d:
            ws_var.set(os.path.normpath(d))
    tk.Button(row2, text="…", command=browse_ws, bg=PANEL, fg=TEXT, relief="flat", width=4).pack(
        side="left", padx=(6, 0))

    local_zip = find_local_sdk_zip()
    if local_zip:
        sdk_text = f"Instalar rexglue SDK desde {os.path.basename(local_zip)} (sin conexión)"
    elif existing_sdk_ok():
        sdk_text = "Descargar la última versión de rexglue SDK (ya tienes uno configurado)"
    else:
        sdk_text = "Descargar e instalar rexglue SDK (≈45 MB, recomendado)"
    sdk_var = tk.BooleanVar(value=bool(local_zip) or not existing_sdk_ok())
    tk.Checkbutton(frm, text=sdk_text, variable=sdk_var, bg=BG, fg=ACCENT, selectcolor=PANEL,
                   activebackground=BG, activeforeground=ACCENT, font=("Segoe UI", 10, "bold"),
                   anchor="w").pack(fill="x", pady=(0, 6))

    opts = {}
    for key, text in (("desktop", "Crear acceso directo en el Escritorio"),
                      ("startmenu", "Agregar al menú Inicio"),
                      ("assoc", f"Abrir archivos {PATCH_EXT} con ReForge Studio"),
                      ("launch", "Abrir ReForge Studio al terminar")):
        v = tk.BooleanVar(value=True)
        tk.Checkbutton(frm, text=text, variable=v, bg=BG, fg=TEXT, selectcolor=PANEL, activebackground=BG,
                       activeforeground=TEXT, font=("Segoe UI", 10), anchor="w").pack(fill="x")
        opts[key] = v

    pb = ttk.Progressbar(root, style="A.Horizontal.TProgressbar", maximum=1.0)
    pb.pack(fill="x", padx=36, pady=(16, 4))
    msg = lbl("", 9, MUTED)
    btns = tk.Frame(root, bg=BG)
    btns.pack(fill="x", padx=36, pady=14, side="bottom")
    go = tk.Button(btns, text=titles[p["action"]], bg=ACCENT, fg="#04130e", relief="flat",
                   font=("Segoe UI", 11, "bold"), padx=20, pady=6)
    go.pack(side="right")
    tk.Button(btns, text="Cancelar", command=root.destroy, bg=PANEL, fg=TEXT, relief="flat",
              font=("Segoe UI", 10), padx=14, pady=6).pack(side="right", padx=8)

    import queue
    events = queue.Queue()      # el hilo de instalación NUNCA toca Tk: solo deja eventos aquí

    def pump():
        last = None
        try:
            while True:
                kind, val = events.get_nowait()
                if kind == "progress":
                    last = val
                elif kind == "log":
                    msg.configure(text=val)
                elif kind == "error":
                    go.configure(state="normal")
                    msg.configure(text="✖ No se completó", fg="#ff6b6b")
                    messagebox.showerror(APP, f"La instalación no se completó.\n\n{val}\n\n"
                                              f"Detalles: {log_path()}")
                elif kind == "done":
                    pb.configure(value=1.0)
                    msg.configure(text=f"✔ Listo: v{p['new']} instalada", fg=ACCENT)
                    if opts["launch"].get():
                        try:
                            subprocess.Popen([val], cwd=os.path.dirname(val))
                        except OSError as e:
                            messagebox.showwarning(APP, f"Instalado, pero no se pudo abrir: {e}")
                    root.after(1200, root.destroy)
                    return
        except queue.Empty:
            pass
        if last is not None:
            pb.configure(value=last)
        root.after(60, pump)

    def worker():
        try:
            want_sdk = sdk_var.get()
            exe = install(dir_var.get(), opts["desktop"].get(), opts["startmenu"].get(), opts["assoc"].get(),
                          progress=lambda f: events.put(("progress", f)),
                          log=lambda t: events.put(("log", t)),
                          workspace=ws_var.get().strip() or None,
                          sdk=want_sdk and not local_zip, sdk_zip=local_zip if want_sdk else "")
        except BaseException as e:      # noqa: BLE001 — cualquier fallo se muestra, nunca en silencio
            import traceback
            _filelog(traceback.format_exc())
            events.put(("error", str(e) or e.__class__.__name__))
            return
        events.put(("done", exe))

    def start():
        _filelog("clic en " + titles[p["action"]])
        if p["action"] == "downgrade" and not messagebox.askyesno(
                APP, f"Vas a reemplazar la v{p['old']} por la v{p['new']} (más antigua). ¿Continuar?"):
            return
        if is_running():
            if not messagebox.askyesno(APP, "ReForge Studio está abierto. ¿Cerrarlo para continuar?"):
                return
        go.configure(state="disabled")
        msg.configure(text="Iniciando…", fg=MUTED)
        threading.Thread(target=worker, daemon=True).start()
        root.after(60, pump)
    go.configure(command=start)
    root.mainloop()


def main():
    args = sys.argv[1:]
    if "--silent" in args:
        target = args[args.index("--dir") + 1] if "--dir" in args else None
        p = plan(target)
        if p["action"] == "downgrade" and "--force" not in args:
            print(f"Ya está instalada la v{p['old']} (más nueva que v{p['new']}). Usa --force para continuar.")
            return 2
        print(f"Acción: {p['action']} · {p['old'] or '—'} → {p['new']} · {p['dir']}")
        opt = lambda k: args[args.index(k) + 1] if k in args else None  # noqa: E731
        exe = install(p["dir"], desktop="--no-desktop" not in args, workspace=opt("--workspace"),
                      sdk="--sdk" in args, sdk_zip=opt("--sdk-zip") or "")
        if "--relaunch" in args and exe and os.path.isfile(exe):
            # Reabrir ReForge automáticamente tras actualizar, para no tener que abrirlo a mano.
            try:
                subprocess.Popen([exe], cwd=os.path.dirname(exe),
                                 creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
                                 close_fds=True)
            except OSError:
                pass
        return 0
    if "--info" in args:
        print(json.dumps(plan(), indent=2))
        return 0
    run_gui()
    return 0


if __name__ == "__main__":
    sys.exit(main())
