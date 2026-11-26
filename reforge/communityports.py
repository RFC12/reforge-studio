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
import os
import subprocess

from .core import config_dir


class CommunityPort:
    """Un puerto de la comunidad y cómo construirlo."""

    def __init__(self, pid, name, title_id, author, repo, engine, game_files, build="installer",
                 notes="", license="", branch="", releases_url=""):
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
