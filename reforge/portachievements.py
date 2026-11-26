"""Conexión de ReForge con puertos de la comunidad que tienen su PROPIO runtime.

Un puerto (Pinyon Shift para Forza Horizon, Crash OTT de VitoMiguelF) recompila el MISMO juego de Xbox 360:
mismo Title ID, así que su base de datos de logros, sus saltos y su código son los del juego original. Lo que
ReForge aporta no es un runtime nuevo, sino la IDENTIDAD: el mismo Gamertag, idioma, color de acento, sonido y
notificación de logros que usa en los juegos que recompila por dentro.

Este módulo deja esa identidad junto al .exe del puerto —`reforge_ext.ini` y los sidecars del perfil (avatar,
logo, sonido)—, que es EXACTAMENTE lo que ReForge escribe para sus propios juegos. Como los puertos de esta
familia (ShiftGlue es un fork de rexglue) leen ese `reforge_ext.ini`, el runtime del puerto muestra tus logros
con tu perfil, tu idioma y tu notificación, igual que un juego recompilado dentro de ReForge.

Lo que este módulo NO hace: inventar definiciones de logros. Los nombres, puntos e iconos viven dentro del
juego y los enseña el runtime del puerto al jugar (lee el XDBF del propio juego). ReForge sí lee, si existe, el
estado de guardado del puerto para enseñar un progreso aproximado en la Biblioteca.
"""
import json
import os


def link_profile(exe, options=None, profile=None):
    """Escribe la identidad de ReForge (reforge_ext.ini + sidecars) junto al .exe del puerto.

    Es la misma función que ReForge usa para sus propios juegos, así que el puerto, al arrancar, encuentra tu
    Gamertag, idioma, acento, sonido y ajustes de notificación. Devuelve la ruta del .ini o '' si no se pudo.
    """
    if not exe or not os.path.isfile(exe):
        return ""
    try:
        from .profile import write_ext_ini
        return write_ext_ini(exe, options=options, profile=profile)
    except Exception:      # noqa: BLE001 — la identidad es un extra; nunca debe impedir jugar
        return ""


def _state_dirs(exe):
    """Carpetas candidatas donde un puerto guarda su progreso (logros/partida), junto al .exe."""
    base = os.path.dirname(exe)
    names = ("userdata", "savegame", "savegames", "saves", "save", "profile", "pinyon_shift_state",
             "crashrecomp_state", "state")
    out = []
    for n in names:
        p = os.path.join(base, n)
        if os.path.isdir(p):
            out.append(p)
    return out


def progress(port, exe):
    """Progreso aproximado del puerto leyendo su estado de guardado, si existe. Devuelve un dict o None.

    No es la lista de logros (esa la enseña el runtime del puerto); es solo una señal para la Biblioteca:
    `{'played': bool, 'unlocked': int|None, 'total': int|None, 'where': ruta}`.
    """
    if not exe or not os.path.isfile(exe):
        return None
    dirs = _state_dirs(exe)
    if not dirs:
        return None
    where = dirs[0]
    unlocked = total = None
    # Formatos conocidos: un JSON del puerto con logros desbloqueados.
    for name in ("achievements.json", "logros.json", "progress.json", "state.json"):
        p = os.path.join(where, name)
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
                unlocked, total = _count_from(data)
            except (OSError, ValueError):
                pass
            break
    return {"played": True, "unlocked": unlocked, "total": total, "where": where}


def _count_from(data):
    """Intenta sacar (desbloqueados, total) de un JSON de progreso de un puerto, con tolerancia a formatos."""
    if isinstance(data, dict):
        if "unlocked" in data and isinstance(data["unlocked"], (list, int)):
            u = data["unlocked"]
            unlocked = len(u) if isinstance(u, list) else int(u)
            total = int(data["total"]) if isinstance(data.get("total"), int) else None
            return unlocked, total
        ach = data.get("achievements")
        if isinstance(ach, dict):
            vals = list(ach.values())
            return sum(1 for v in vals if v), len(vals)
        if isinstance(ach, list):
            return sum(1 for v in ach if isinstance(v, dict) and v.get("unlocked")), len(ach)
    if isinstance(data, list):
        return sum(1 for v in data if isinstance(v, dict) and v.get("unlocked")), len(data)
    return None, None


def connect(port, exe, game_root=None, options=None, profile=None, lib=None):
    """Conecta un puerto ya construido con ReForge: deja la identidad del perfil junto a su .exe y devuelve un
    resumen legible del estado. No arranca nada."""
    ini = link_profile(exe, options=options, profile=profile)
    prog = progress(port, exe)
    parts = []
    if ini:
        parts.append("Perfil de ReForge enlazado (Gamertag, idioma, acento, notificación de logros).")
    else:
        parts.append("No se pudo escribir la identidad del perfil junto al puerto (se puede jugar igual).")
    if prog and prog.get("unlocked") is not None:
        tot = f"/{prog['total']}" if prog.get("total") else ""
        parts.append(f"Progreso detectado: {prog['unlocked']}{tot} logros.")
    parts.append(f"Logros del juego (Title ID {port.title_id}): los muestra el runtime del puerto al jugar, "
                 "con tu perfil.")
    return {"ini": ini, "progress": prog, "summary": "  ".join(parts)}
