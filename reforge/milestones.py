"""Hitos de un juego recompilado: hasta dónde llega de verdad, por separado del «perfil visual».

La escalera va del binario a una escena jugable. El runtime del juego puede escribir su hito más alto en un
archivo junto al .exe (contrato abajo); ReForge también infiere hitos del log del juego y de la existencia del
.exe, así que hay una señal útil aunque el runtime todavía no escriba nada.

Contrato del archivo (lo escribe el runtime, opcional): `reforge_milestones.txt` junto al .exe, una línea por
hito alcanzado, `<ISO-8601>\t<CLAVE>` (p. ej. `2026-11-26T19:40:00\tFIRST_FRAME`). ReForge se queda con el más
alto. Claves válidas: las de LADDER.
"""
import os

# clave -> (nivel, etiqueta legible)
LADDER = [
    ("NONE", "sin binario"),
    ("EXE_BUILT", "ejecutable generado"),
    ("RUNTIME_INIT", "runtime inicializado"),
    ("FIRST_TITLE_FUNC", "primera función del título ejecutada"),
    ("FIRST_FRAME", "primer fotograma presentado"),
    ("INTERACTIVE_MENU", "menú interactivo"),
    ("PLAYABLE_SCENE", "escena jugable"),
]
KEY_LEVEL = {k: i for i, (k, _d) in enumerate(LADDER)}
LEVEL_DESC = {i: d for i, (_k, d) in enumerate(LADDER)}


def describe(level):
    return LEVEL_DESC.get(int(level or 0), "sin datos")


def milestones_path(exe):
    return os.path.join(os.path.dirname(exe), "reforge_milestones.txt") if exe else ""


def read(exe):
    """{clave: marca_de_tiempo} de los hitos que el runtime haya escrito junto al .exe."""
    out = {}
    path = milestones_path(exe)
    if not path or not os.path.isfile(path):
        return out
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2 and parts[1] in KEY_LEVEL:
                    out[parts[1]] = parts[0]
                elif len(parts) == 1 and parts[0] in KEY_LEVEL:
                    out[parts[0]] = ""
    except OSError:
        pass
    return out


def record(exe, key):
    """Anota un hito junto al .exe (idempotente por línea). Para el runtime o para el propio launcher."""
    if key not in KEY_LEVEL or not exe:
        return False
    import datetime
    path = milestones_path(exe)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')}\t{key}\n")
        return True
    except OSError:
        return False


def _log_text(exe):
    try:
        from . import game
        path = game.newest_log(exe)
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
    except Exception:      # noqa: BLE001
        pass
    return ""


def infer_from_log(text):
    """Nivel inferido del log del juego (conservador). 0 si no hay señales."""
    if not text:
        return 0
    low = text.lower()
    level = KEY_LEVEL["RUNTIME_INIT"] if ("rexglue" in low or "runtime" in low or "init" in low) else 0
    # señales de presentación / fotogramas
    if any(s in low for s in ("present", "swapchain", "frame ", "fps", "vsync", "d3d12", "vulkan")):
        level = max(level, KEY_LEVEL["FIRST_FRAME"])
    # señales de juego en marcha (diagnóstico de tirones, tiempos de fotograma sostenidos)
    if any(s in low for s in ("tirón", "frame time", "frametime", "stutter", "gameplay")):
        level = max(level, KEY_LEVEL["PLAYABLE_SCENE"])
    return level


def level_for(root, exe=""):
    """El hito más alto alcanzado: por el .exe existente, por lo que el runtime haya escrito y por el log."""
    level = 0
    if exe and os.path.isfile(exe):
        level = KEY_LEVEL["EXE_BUILT"]
    for key in read(exe):
        level = max(level, KEY_LEVEL[key])
    level = max(level, infer_from_log(_log_text(exe)))
    return level


def record_from_run(exe, outcome):
    """Tras una partida, anota el hito que demuestra el resultado (lo usa el launcher). `outcome` es el dict de
    game.check_running_game. Devuelve el nivel anotado o 0."""
    if not exe:
        return 0
    kind = (outcome or {}).get("kind", "")
    text = _log_text(exe)
    level = infer_from_log(text)
    # un cierre limpio tras presentar frames es, al menos, juego en marcha
    if kind == "clean" and level >= KEY_LEVEL["FIRST_FRAME"]:
        level = max(level, KEY_LEVEL["PLAYABLE_SCENE"])
    if level:
        record(exe, LADDER[level][0])
    return level
