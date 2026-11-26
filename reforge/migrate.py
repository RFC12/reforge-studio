"""Actualización inteligente y REVERSIBLE de un proyecto a los componentes de recompilación más nuevos.

Idea: llevar un juego hecho con un SDK antiguo (p. ej. 0.10) a la versión más nueva instalada (0.11…),
regenerándolo con ella y re-aplicando las adaptaciones de ReForge (ext del SDK, encabezado SEH, hints), pero
SIN dejar nunca al usuario peor: antes de tocar nada se respalda el proyecto, y si la versión nueva no compila
o el juego se cierra al arrancar, se REVIERTE sola a la que funcionaba.

Este módulo es la parte segura y comprobable (respaldo, reversión, plan, detección de cierre). La orquestación
—regenerar, compilar y la prueba de arranque— la hace el Taller reutilizando su pipeline, llamando a estas
piezas para el respaldo/reversión y para decidir si la actualización salió bien.
"""
import os
import shutil

from . import toolchain

BACKUP_DIR = ".reforge_upgrade_backup"

# Lo que define cómo se genera y compila el proyecto. Se respalda esto (no la carpeta build entera, que es
# enorme y se regenera): con esto se puede reconstruir la versión anterior exactamente.
_BACKUP_ITEMS = (
    "reforge_game.json",
    "reforge_functions.toml",
    "CMakeLists.txt",
    "src",
    "generated",
)
# Los *_manifest.toml se respaldan aparte (nombre variable).


def _sdk_key(ver):
    return toolchain._sdk_key(ver)


def project_sdk(cfg):
    """Versión del SDK con que está configurado el proyecto ahora (p. ej. '0.10.0.24-dev...-fsr') o ''."""
    return toolchain.sdk_version(cfg)


def newest_installed_sdk():
    """(version, prefix, exe) del SDK instalado más nuevo (FSR preferido a igualdad), o None."""
    sdks = list(toolchain.installed_sdks())
    if not sdks:
        return None
    sdks.sort(key=lambda c: (_sdk_key(c[0]), c[0].endswith("-fsr")), reverse=True)
    return sdks[0]


def plan(cfg, root):
    """Qué actualización es posible para este proyecto.

    Devuelve {'from','to','prefix','exe','available','same_family'}:
      available  → hay un SDK instalado MÁS NUEVO que el del proyecto.
      same_family→ el nuevo es de la misma familia mayor.menor (p. ej. 0.10.x→0.10.y): actualización de bajo
                   riesgo (no cambian los targets del CMake). Distinta familia (0.10→0.11) es de mayor riesgo.
    """
    cur = project_sdk(cfg)
    newest = newest_installed_sdk()
    if not newest:
        return {"from": cur, "to": "", "available": False, "same_family": False, "prefix": "", "exe": ""}
    ver, pfx, exe = newest
    available = bool(cur) and _sdk_key(ver) > _sdk_key(cur)
    same_family = _family(ver) == _family(cur) if cur else False
    return {"from": cur, "to": ver, "prefix": pfx, "exe": exe,
            "available": available, "same_family": same_family}


def _family(ver):
    # '0.11.0.13-dev...' → '0.11'
    parts = (ver or "").split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else (ver or "")


# --------------------------------------------------------------------------- respaldo / reversión
def backup_path(root):
    return os.path.join(root, BACKUP_DIR)


def has_backup(root):
    return os.path.isfile(os.path.join(backup_path(root), ".ok"))


def backup(root, note=""):
    """Respalda lo que define el proyecto (config + código generado) para poder revertir. Devuelve True."""
    dst = backup_path(root)
    try:
        if os.path.isdir(dst):
            shutil.rmtree(dst, ignore_errors=True)
        os.makedirs(dst, exist_ok=True)
        for name in _BACKUP_ITEMS:
            src = os.path.join(root, name)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(dst, name), dirs_exist_ok=True)
            elif os.path.isfile(src):
                shutil.copyfile(src, os.path.join(dst, name))
        for man in _manifests(root):
            shutil.copyfile(man, os.path.join(dst, os.path.basename(man)))
        with open(os.path.join(dst, ".ok"), "w", encoding="utf-8") as f:
            f.write(note or "respaldo de actualización")
        return True
    except Exception:      # noqa: BLE001
        return False


def restore(root):
    """Revierte el proyecto al respaldo (la versión que funcionaba). Devuelve True si había respaldo y se restauró."""
    dst = backup_path(root)
    if not has_backup(root):
        return False
    try:
        for name in _BACKUP_ITEMS:
            saved = os.path.join(dst, name)
            live = os.path.join(root, name)
            if os.path.isdir(saved):
                if os.path.isdir(live):
                    shutil.rmtree(live, ignore_errors=True)
                shutil.copytree(saved, live, dirs_exist_ok=True)
            elif os.path.isfile(saved):
                shutil.copyfile(saved, live)
        for man in os.listdir(dst):
            if man.endswith("_manifest.toml"):
                shutil.copyfile(os.path.join(dst, man), os.path.join(root, man))
        return True
    except Exception:      # noqa: BLE001
        return False


def clear_backup(root):
    shutil.rmtree(backup_path(root), ignore_errors=True)


def _manifests(root):
    try:
        return [os.path.join(root, f) for f in os.listdir(root) if f.endswith("_manifest.toml")]
    except OSError:
        return []


# --------------------------------------------------------------------------- prueba de arranque
# Señales de que el juego se CERRÓ por un fallo (no un cierre normal del jugador).
CRASH_SIGNS = ("crash report", "ACCESS_VIOLATION", "[FATAL]", "unhandled title read",
               "deferred completion threw", "SEH exception caught")


def crashed_after(exe, since_mtime):
    """Revisa el log de juego más nuevo (posterior a since_mtime) y devuelve la señal de cierre encontrada, o ''.

    Sirve de prueba de arranque: tras lanzar el .exe actualizado unos segundos, si el log trae una señal de
    cierre, la actualización empeoró las cosas y hay que revertir.
    """
    logdir = os.path.join(os.path.dirname(exe), "logs")
    try:
        logs = [os.path.join(logdir, f) for f in os.listdir(logdir) if f.endswith(".log")]
    except OSError:
        return ""
    logs = [p for p in logs if os.path.getmtime(p) >= since_mtime - 1]
    if not logs:
        return ""
    newest = max(logs, key=os.path.getmtime)
    try:
        with open(newest, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return ""
    for sign in CRASH_SIGNS:
        if sign in text:
            return sign
    return ""
