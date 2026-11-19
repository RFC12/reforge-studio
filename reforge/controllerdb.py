"""Base de mapeos de mando (SDL gamecontrollerdb) que ReForge coloca junto a cada juego recompilado.

rexglue arranca su driver SDL leyendo «{carpeta_del_exe}/gamecontrollerdb.txt» (ajuste «mappings_file»).
Si no hay archivo, SDL usa solo su base interna; con mandos modernos (DualSense y DualSense Edge, DualShock 4,
Xbox Series, Switch Pro, 8BitDo…) eso a veces deja botones mal asignados. ReForge empaqueta una base SDL al
día (de mdqinc/SDL_GameControllerDB, licencia permisiva tipo zlib) y la deja al lado del juego.

Nunca pisa un archivo que hayas puesto tú: solo escribe si no hay ninguno, o si el que hay lo escribió ReForge
(lleva la cabecera REFORGE-GCDB) y la versión empaquetada es más nueva.
"""
import os
import re
import sys

MARKER = "REFORGE-GCDB"
_VER_RE = re.compile(r"REFORGE-GCDB\s+v(\d+)", re.I)


def bundled_path():
    """Ruta al gamecontrollerdb.txt empaquetado (frozen o desde código); '' si no está."""
    bases = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        bases.append(meipass)
    if getattr(sys, "frozen", False):
        bases.append(os.path.dirname(sys.executable))
    bases.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for base in bases:
        p = os.path.join(base, "assets", "gamecontrollerdb.txt")
        if os.path.isfile(p):
            return p
    return ""


def _version(text):
    """Número de versión REFORGE-GCDB de un contenido, o None si no lleva la cabecera de ReForge."""
    m = _VER_RE.search(text or "")
    return int(m.group(1)) if m else None


def place(dest_dir, src=None):
    """Deja gamecontrollerdb.txt en dest_dir sin pisar lo del usuario.

    Devuelve (colocado: bool, motivo: str). No lanza: ante cualquier problema de E/S devuelve (False, …),
    porque esto nunca debe impedir jugar.
    """
    src = src or bundled_path()
    if not src or not os.path.isfile(src):
        return False, "no hay base de mandos empaquetada"
    try:
        with open(src, encoding="utf-8") as f:
            nuevo = f.read()
    except OSError as e:
        return False, f"no se pudo leer la base empaquetada: {e}"
    nueva_ver = _version(nuevo)
    dst = os.path.join(dest_dir, "gamecontrollerdb.txt")
    if os.path.isfile(dst):
        try:
            with open(dst, encoding="utf-8", errors="replace") as f:
                actual = f.read()
        except OSError as e:
            return False, f"no se pudo leer el archivo existente: {e}"
        actual_ver = _version(actual)
        if actual_ver is None:
            return False, "ya hay un gamecontrollerdb.txt propio (no se toca)"
        if nueva_ver is not None and actual_ver >= nueva_ver and actual == nuevo:
            return False, "la base de mandos ya está al día"
        if nueva_ver is not None and actual_ver > nueva_ver:
            return False, "el archivo existente es más nuevo (no se toca)"
    try:
        os.makedirs(dest_dir, exist_ok=True)
        with open(dst, "w", encoding="utf-8", newline="\n") as f:
            f.write(nuevo)
    except OSError as e:
        return False, f"no se pudo escribir: {e}"
    return True, f"base de mandos SDL colocada (REFORGE-GCDB v{nueva_ver})"
