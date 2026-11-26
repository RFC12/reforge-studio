"""Gestor de puertos de la comunidad (runtimes de otros autores).

Algunos juegos de Xbox 360 tienen puertos nativos a PC hechos por otros autores con su PROPIO runtime y motor
(normalmente sobre XenonRecomp), no sobre rexglue. Esos puertos resuelven cosas que rexglue no (p. ej. el
mapa de memoria del título, que hace que Crash of the Titans se cierre con un ACCESS_VIOLATION en rexglue pero
funcione en el puerto de VitoMiguelF). No se pueden «enchufar» a rexglue: son proyectos completos.

Este módulo es el soporte de ReForge para ESOS puertos: un registro de puertos conocidos (por Title ID), poder
clonarlos, ayudarte a apuntarlos a tu copia legal del juego, construirlos con su propio toolchain y añadir el
resultado a la Biblioteca. ReForge NO incluye ningún archivo de juego ni código recompilado: el puerto se
construye en tu PC a partir de tu propia copia, como hace el instalador del autor.
"""
import json
import os
import subprocess

from .core import config_dir


class CommunityPort:
    """Un puerto de la comunidad y cómo construirlo."""

    def __init__(self, pid, name, title_id, author, repo, engine, game_files, build="installer",
                 notes="", license="", branch="", releases_url="", play_name="", exe_base="",
                 known_dirs=None):
        self.id = pid
        self.name = name
        self.title_id = (title_id or "").upper()
        self.author = author
        self.repo = repo
        self.engine = engine
        self.game_files = list(game_files)
        self.build = build            # "installer" (trae su instalador/toolchain) o "source"
        self.notes = notes
        self.license = license
        self.branch = branch
        # Página de releases: el release trae todo para construir (código + toolchain). Es la vía recomendada.
        self.releases_url = releases_url or (repo.rstrip("/") + "/releases")
        # Nombre corto del juego para la Biblioteca y el icono (p. ej. «Forza Horizon»).
        self.play_name = play_name or name
        # Nombre de archivo al que ReForge renombra el .exe del puerto (p. ej. «Horizon»), sin extensión.
        self.exe_base = exe_base or "".join(c for c in self.play_name if c.isalnum() or c in " -_").strip()
        # Carpetas conocidas donde el toolchain del puerto deja el .exe construido (se amplía con el tiempo).
        self.known_dirs = list(known_dirs or [])

    def dir(self):
        return os.path.join(ports_dir(), self.id)

    def is_cloned(self):
        return os.path.isdir(os.path.join(self.dir(), ".git"))


# Registro de puertos conocidos. Se amplía con el tiempo; la clave es el Title ID del juego.
PORTS = [
    CommunityPort(
        pid="crashott",
        name="Crash of the Titans — Definitive Edition (PC)",
        title_id="565507E4",
        author="VitoMiguelF",
        repo="https://github.com/VitoMiguelF/crashott-pc",
        engine="XenonRecomp",
        game_files=["default.xex", "default.rcf"],
        build="installer",
        notes="Puerto nativo con runtime propio (mapa de memoria, imports del kernel, audio XMA, etc.). "
              "Recompila el juego desde TU copia retail (comprueba el SHA-256 del default.xex). Resuelve el "
              "cierre 0x701A0000 que rexglue no puede, porque usa su propio runtime.",
        license="Código del puerto: ver LICENSE y THIRD_PARTY_NOTICES del repo. Sin archivos de juego.",
        play_name="Crash of the Titans",
        exe_base="Crash of the Titans",
        known_dirs=[r"C:\ReForgeBuild\crashott-pc\out\build\win-amd64-release",
                    r"C:\ReForgeBuild\crashott\out\build\win-amd64-release"],
    ),
    CommunityPort(
        pid="pinyonshift",
        name="Forza Horizon — Pinyon Shift (PC)",
        title_id="4D5309C9",
        author="arcanite24",
        repo="https://github.com/arcanite24/pinyon-shift",
        engine="ShiftGlue",      # fork de rexglue: MISMA familia que ReForge → sus técnicas son más portables
        game_files=["default.xex"],
        build="installer",
        notes="Puerto nativo de Forza Horizon (disco USA retail, serial MS-2505). Construido sobre ShiftGlue, un "
              "fork de ReXGlue (la misma familia que ReForge), así que sus mejoras de compatibilidad y de "
              "renderizado son especialmente aprovechables para ReForge. Se construye desde tu propia copia.",
        license="Código del puerto: ver LICENSE y THIRD_PARTY_NOTICES del repo. Sin archivos de juego.",
        play_name="Forza Horizon",
        exe_base="Horizon",
        known_dirs=[r"C:\ReForgeBuild\pinyon-shift\out\build\win-amd64-release",
                    r"C:\ReForgeBuild\pinyon-shift\out\build\win-amd64-relwithdebinfo"],
    ),
]


def ports_dir():
    return os.path.join(config_dir(), "community_ports")


def all_ports():
    return list(PORTS)


def by_id(pid):
    for p in PORTS:
        if p.id == pid:
            return p
    return None


def for_title(title_id):
    """El puerto de la comunidad registrado para ese Title ID, o None."""
    tid = (title_id or "").upper()
    for p in PORTS:
        if p.title_id == tid:
            return p
    return None


def for_project(root):
    """Si el proyecto de ReForge tiene un puerto de la comunidad para su juego, lo devuelve (si no, None).

    Útil para sugerirlo cuando un juego no arranca en rexglue: p. ej. Crash of the Titans.
    """
    tid = _title_id_of(root)
    return for_title(tid) if tid else None


def _title_id_of(root):
    try:
        from .gameicon import title_id
        xex = os.path.join(root, "assets", "default.xex")
        return (title_id(xex) if os.path.isfile(xex) else "").upper()
    except Exception:      # noqa: BLE001
        return ""


# --------------------------------------------------------------------------- clonar
def clone(port, git="git", log=None):
    """Clona el repositorio del puerto en la carpeta de puertos de ReForge. Devuelve (ok, mensaje)."""
    dest = port.dir()
    if port.is_cloned():
        return True, f"El puerto «{port.name}» ya está clonado en {dest}."
    os.makedirs(ports_dir(), exist_ok=True)
    cmd = [git, "clone", "--depth", "1"]
    if port.branch:
        cmd += ["--branch", port.branch]
    cmd += [port.repo, dest]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"No se pudo clonar el puerto: {e}"
    if r.returncode != 0:
        return False, f"git clone falló: {(r.stderr or r.stdout or '').strip()[-300:]}"
    msg = f"Puerto «{port.name}» de {port.author} clonado en {dest}."
    if log:
        log(msg, "ok")
    return True, msg


def game_files_status(port, game_dir):
    """Comprueba qué archivos de juego requeridos están en game_dir. Devuelve {archivo: bool}."""
    out = {}
    for name in port.game_files:
        out[name] = bool(game_dir) and os.path.isfile(os.path.join(game_dir, name))
    return out


def ready_to_build(port, game_dir):
    """¿Están el puerto clonado y todos los archivos de juego presentes?"""
    return port.is_cloned() and all(game_files_status(port, game_dir).values())


# --------------------------------------------------------------------------- construir (vía el toolchain del puerto)
def build_plan(port):
    """Pasos, en orden, para construir el puerto en el PC del usuario. Cada puerto trae su propio toolchain e
    instalador; ReForge los orquesta y envuelve el resultado, no los recompila por dentro."""
    return [
        f"Descargar el release del puerto desde {port.releases_url} (trae su código y su toolchain).",
        f"Apuntarlo a tu copia LEGAL del juego: {', '.join(port.game_files)} (ReForge los copia desde tu "
        "proyecto si ya los tienes).",
        "Ejecutar el instalador/compilación del puerto: recompila el juego desde tu copia y construye el .exe "
        "(varios minutos; usa el toolchain del propio puerto).",
        "ReForge detecta el .exe resultante y le pone su lanzador temático, su icono y lo añade a la Biblioteca.",
    ]


SKIP_EXE = ("xenonrecomp", "cmake", "clang", "ninja", "python", "git", "ffmpeg", "dxc", "7z", "unzip",
            "vcredist", "setup", "installer", "uninstall", "_tests", "test", "crashpad", "dxcompiler")


# --------------------------------------------------------------------------- rutas recordadas
def _settings_path():
    return os.path.join(config_dir(), "community_ports.json")


def _load_settings():
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_settings(data):
    os.makedirs(config_dir(), exist_ok=True)
    tmp = _settings_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _settings_path())


def saved_exe(port):
    """La ruta del .exe que el usuario eligió/renombró antes para este puerto, si sigue existiendo."""
    p = (_load_settings().get(port.id, {}) or {}).get("exe", "")
    return p if p and os.path.isfile(p) else ""


def remember_exe(port, exe):
    """Recuerda la ruta del .exe construido del puerto para que «Jugar» funcione directo la próxima vez."""
    data = _load_settings()
    entry = data.get(port.id, {}) or {}
    entry["exe"] = exe
    data[port.id] = entry
    _save_settings(data)


def forget_exe(port):
    data = _load_settings()
    if port.id in data:
        data[port.id].pop("exe", None)
        _save_settings(data)


def _scan_dir_for_exe(base):
    """El .exe del juego más grande en `base` que no es una herramienta del toolchain. '' si no hay."""
    if not base or not os.path.isdir(base):
        return ""
    best, best_size = "", 0
    for root_dir, _dirs, files in os.walk(base):
        for f in files:
            low = f.lower()
            if not low.endswith(".exe") or any(s in low for s in SKIP_EXE):
                continue
            p = os.path.join(root_dir, f)
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            if sz > best_size:          # el ejecutable del juego es el más grande que no es una herramienta
                best, best_size = p, sz
    return best


def locate_built_exe(port):
    """Encuentra el .exe ya construido del puerto. Mira, en orden: la ruta recordada por el usuario, la carpeta
    del puerto clonado y las carpetas de salida conocidas del toolchain (p. ej. win-amd64-release). Devuelve la
    ruta o ''."""
    remembered = saved_exe(port)
    if remembered:
        return remembered
    found = _scan_dir_for_exe(port.dir())
    if found:
        return found
    for d in port.known_dirs:
        found = _scan_dir_for_exe(d)
        if found:
            return found
    return ""


def is_built(port):
    return bool(locate_built_exe(port))


def find_installed(port):
    """Busca el puerto ya instalado a mano (sin pasar por ReForge) en sus carpetas de salida conocidas y, si lo
    encuentra, lo recuerda. Devuelve la ruta o ''. Esto cubre «ya lo instalé por mi cuenta»."""
    found = _scan_dir_for_exe(port.dir())
    if not found:
        for d in port.known_dirs:
            found = _scan_dir_for_exe(d)
            if found:
                break
    if found:
        remember_exe(port, found)
    return found


# --------------------------------------------------------------------------- renombrar a Horizon / Crash
def rename_built(port, exe, new_base=""):
    """Renombra el .exe del puerto a un nombre bonito (p. ej. «Horizon.exe») en su misma carpeta y actualiza la
    ruta recordada. El icono va embebido en el .exe, así que sobrevive al renombrado. Devuelve (ok, nueva_ruta).
    """
    if not exe or not os.path.isfile(exe):
        return False, exe
    base = (new_base or port.exe_base or "").strip() or os.path.splitext(os.path.basename(exe))[0]
    base = "".join(c for c in base if c.isalnum() or c in " -_").strip() or "Juego"
    dst = os.path.join(os.path.dirname(exe), base + ".exe")
    if os.path.abspath(dst) == os.path.abspath(exe):
        remember_exe(port, exe)
        return True, exe
    try:
        if os.path.exists(dst):
            os.remove(dst)
        os.replace(exe, dst)
    except OSError:
        return False, exe
    remember_exe(port, dst)
    return True, dst


# --------------------------------------------------------------------------- instalar/construir desde ReForge
def _runnable_installer(port):
    """Un instalador o script de construcción ejecutable dentro del puerto clonado, o ''."""
    base = port.dir()
    if not os.path.isdir(base):
        return ""
    prefer = ("install.bat", "build.bat", "setup.bat", "install.cmd", "build.cmd", "make.bat")
    for name in prefer:
        p = os.path.join(base, name)
        if os.path.isfile(p):
            return p
    # un instalador .exe del release (no una herramienta del toolchain)
    for root_dir, _dirs, files in os.walk(base):
        for f in files:
            low = f.lower()
            if low.endswith(".exe") and ("setup" in low or "install" in low) \
                    and "uninstall" not in low:
                return os.path.join(root_dir, f)
    return ""


def install_build(port, game_dir="", log=None, launch=True):
    """Instala/construye el puerto desde ReForge: clona si falta, copia tus archivos de juego al puerto y lanza
    su propio instalador/compilación (su toolchain hace el trabajo pesado). Devuelve (ok, mensaje).

    ReForge NO recompila el puerto por dentro: orquesta el toolchain del autor desde tu copia legal del juego.
    Si no hay un instalador ejecutable en el puerto, devuelve el plan y la página de releases.
    """
    import shutil
    if not port.is_cloned():
        ok, msg = clone(port, log=log)
        if not ok:
            return False, msg
    if game_dir:
        for name in port.game_files:
            src = os.path.join(game_dir, name)
            if os.path.isfile(src):
                try:
                    shutil.copy2(src, os.path.join(port.dir(), name))
                except OSError as e:
                    return False, f"No se pudo copiar {name} al puerto: {e}"
    runner = _runnable_installer(port)
    if not runner:
        steps = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(build_plan(port)))
        return False, ("Este puerto no trae un instalador ejecutable que ReForge pueda lanzar solo. Descárgalo "
                       f"de su página de releases y sigue sus pasos:\n{steps}\n\nReleases: {port.releases_url}")
    if not launch:
        return True, f"Listo para construir con {os.path.basename(runner)} (no se lanzó)."
    try:
        subprocess.Popen([runner], cwd=port.dir())
    except OSError as e:
        return False, f"No se pudo lanzar el instalador del puerto: {e}"
    if log:
        log(f"Lanzado el instalador del puerto «{port.name}»: {os.path.basename(runner)}.", "ok")
    return True, (f"Se lanzó el instalador de «{port.name}». Cuando termine, pulsa «Buscar juego ya instalado» "
                  "y ReForge lo detecta, lo renombra y lo añade a la Biblioteca.")


# --------------------------------------------------------------------------- español latino (TU/GOD)
def apply_title_update(game_root, god_or_tu, log=None):
    """Aplica una actualización de título (GOD o archivo TU) al PROYECTO del juego en ReForge, para que, al
    reconstruir el puerto desde esos assets, el juego salga con el idioma/contenido de esa actualización (p. ej.
    el español latino de Forza Horizon). Devuelve el resumen de title_update.install_update.

    El puerto lee los assets del juego; aplicar aquí la TU es lo que hace que Horizon salga en español latino
    cuando lo reconstruyas. Requiere reconstruir el puerto después.
    """
    from . import title_update
    return title_update.install_update(game_root, god_or_tu, log=log)


def wrap_in_reforge(port, exe, game_root, lib=None, write_launcher=None, ensure_icon=None):
    """Envuelve el .exe construido del puerto con las comodidades de ReForge: lanzador temático, icono y
    entrada en la Biblioteca. Devuelve el Project creado (o None si no se pudo).

    `game_root` es la carpeta del proyecto del juego (de donde salen el icono del XEX y las rutas). Se pueden
    inyectar las funciones (para pruebas); por defecto usa las de ReForge.
    """
    if not exe or not os.path.isfile(exe):
        return None
    if write_launcher is None:
        from .game import write_launcher as _wl
        write_launcher = _wl
    if ensure_icon is None:
        from .gameicon import ensure as _ei
        ensure_icon = _ei
    title = port.play_name
    try:
        write_launcher(exe, game_root, title)
    except Exception:      # noqa: BLE001
        pass
    try:
        ensure_icon(exe, game_root, title, force=True)
    except Exception:      # noqa: BLE001
        pass
    remember_exe(port, exe)
    from .core import Project
    proj = Project(name=title, root=game_root, source=f"Puerto de {port.author} ({port.engine})",
                   title_id=port.title_id, status="Puerto de la comunidad", output=exe)
    if lib is None:
        try:
            from .core import Library
            lib = Library.load()
        except Exception:      # noqa: BLE001
            lib = None
    if lib is not None:
        try:
            lib.upsert(proj)
            lib.save()
        except Exception:      # noqa: BLE001
            pass
    return proj


def connect(port, exe, game_root=None, options=None, profile=None, lib=None):
    """Envuelve el puerto con las comodidades de ReForge y enlaza tu perfil/logros junto a su .exe. Devuelve el
    resumen de la conexión (ver portachievements.connect). `game_root` por defecto es la carpeta del puerto."""
    root = game_root or port.dir()
    try:
        wrap_in_reforge(port, exe, root, lib=lib)
    except Exception:      # noqa: BLE001
        pass
    from . import portachievements
    return portachievements.connect(port, exe, game_root=root, options=options, profile=profile, lib=lib)


def launch(port, exe=None):
    """Lanza el .exe del puerto (el construido, o el que se pase). Devuelve (ok, mensaje)."""
    exe = exe or locate_built_exe(port)
    if not exe or not os.path.isfile(exe):
        return False, "El puerto todavía no está construido (no encuentro su .exe)."
    try:
        subprocess.Popen([exe], cwd=os.path.dirname(exe))
        return True, f"Lanzando «{port.play_name}»."
    except OSError as e:
        return False, f"No se pudo lanzar el puerto: {e}"
