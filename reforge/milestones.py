"""Hitos de un juego recompilado: hasta dónde llega de verdad, con evidencia, por separado del «perfil visual».

La escalera va del binario a una escena jugable. El runtime del juego escribe su hito más alto (y datos del
render) junto al `.exe`; ReForge también los infiere del log, **de forma conservadora**: una línea de fallo
(`Vulkan initialization failed`, `swapchain creation failed`) NO confirma un fotograma, y activar un monitor
(`stutter monitoring enabled`) NO confirma una escena jugable. Para menú interactivo y escena jugable solo cuenta
una **señal específica** (marcador del runtime) o una **validación manual** marcada como tal.

Se distinguen: la **última sesión**, **cada intento** (con su primer error) y el **mejor resultado histórico**.

Contrato del archivo que escribe el runtime (opcional): `reforge_milestones.txt` junto al `.exe`, una línea por
hito, `<ISO-8601>\t<CLAVE>[\t<evidencia>]`. Claves válidas: las de LADDER. El launcher también puede anotar una
validación manual con evidencia `manual: ...`.
"""
import os
import re

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

# Palabras que marcan que una línea NO es un éxito (evita falsos positivos con «vulkan»/«swapchain»/«present»).
FAIL_WORDS = ("fail", "failed", "failure", "error", "could not", "couldn't", "cannot", "unable",
              "invalid", "not enough", "abort", "exception", "crash", "fatal", "denied", "missing",
              "no se pudo", "no device", "lost device", "timeout")


def describe(level):
    return LEVEL_DESC.get(int(level or 0), "sin datos")


def milestones_path(exe):
    return os.path.join(os.path.dirname(exe), "reforge_milestones.txt") if exe else ""


# --------------------------------------------------------------------------- archivo del runtime
def read(exe):
    """{clave: evidencia} de los hitos que el runtime (o una validación manual) haya escrito junto al .exe."""
    out = {}
    path = milestones_path(exe)
    if not path or not os.path.isfile(path):
        return out
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                key = parts[1] if len(parts) >= 2 else (parts[0] if parts else "")
                if key in KEY_LEVEL:
                    ev = parts[2] if len(parts) >= 3 else "marcador del runtime"
                    out[key] = ev
    except OSError:
        pass
    return out


def record(exe, key, evidence="marcador del runtime"):
    """Anota un hito junto al .exe. Para el runtime o para una validación manual (evidence='manual: ...')."""
    if key not in KEY_LEVEL or not exe:
        return False
    import datetime
    try:
        with open(milestones_path(exe), "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')}\t{key}\t{evidence}\n")
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- inferencia conservadora del log
def _is_fail(low):
    return any(w in low for w in FAIL_WORDS)


def _confirms_runtime_init(low):
    if _is_fail(low):
        return False
    return any(t in low for t in ("runtime initialized", "runtime ready", "rexglue ready", "init complete",
                                  "initialization complete", "runtime init ok"))


def _confirms_title_func(low):
    if _is_fail(low):
        return False
    return any(t in low for t in ("entering title", "title entry", "first title function", "guest main",
                                  "title code", "recompiled entry"))


def _confirms_frame(low):
    if _is_fail(low):
        return False
    return any(t in low for t in ("presented", "present ok", "first frame", "frame presented",
                                  "swapchain created", "displayed frame", "present succeeded"))


# Escena jugable: solo con tiempos de fotograma REALES (números), no con «stutter monitoring enabled».
_FRAMETIME_NUM = re.compile(r"frame\s*time\s*[:=]?\s*\d|\b\d+(\.\d+)?\s*ms\b.*\bfps\b|\bfps\s*[:=]?\s*\d{2,}")


def _confirms_scene(low):
    if _is_fail(low):
        return False
    if "playable" in low or "gameplay frame" in low:
        return True
    return bool(_FRAMETIME_NUM.search(low))


def _explicit_marker(low):
    """Un marcador explícito en el log: '[milestone] KEY' o 'milestone: KEY'. Devuelve la clave o ''."""
    m = re.search(r"milestone[\]:]?\s*[:=]?\s*([a-z_]+)", low)
    if m:
        key = m.group(1).upper()
        if key in KEY_LEVEL:
            return key
    return ""


def analyze_text(text):
    """Analiza UN intento (un log). Devuelve {level, confirmed:{clave:evidencia}, first_error}."""
    confirmed = {}
    first_error = ""
    if not text:
        return {"level": 0, "confirmed": {}, "first_error": ""}
    for raw in text.splitlines():
        low = raw.lower()
        if not first_error and _is_fail(low):
            first_error = raw.strip()[:200]
        mk = _explicit_marker(low)
        if mk:
            confirmed.setdefault(mk, "marcador en el log: " + raw.strip()[:120])
            continue
        if "RUNTIME_INIT" not in confirmed and _confirms_runtime_init(low):
            confirmed["RUNTIME_INIT"] = "log: " + raw.strip()[:120]
        if "FIRST_TITLE_FUNC" not in confirmed and _confirms_title_func(low):
            confirmed["FIRST_TITLE_FUNC"] = "log: " + raw.strip()[:120]
        if "FIRST_FRAME" not in confirmed and _confirms_frame(low):
            confirmed["FIRST_FRAME"] = "log: " + raw.strip()[:120]
        if "PLAYABLE_SCENE" not in confirmed and _confirms_scene(low):
            confirmed["PLAYABLE_SCENE"] = "log: " + raw.strip()[:120]
    level = max([KEY_LEVEL[k] for k in confirmed], default=0)
    return {"level": level, "confirmed": confirmed, "first_error": first_error}


# --------------------------------------------------------------------------- por intento / sesión / histórico
def _logs(exe):
    """Rutas de los logs del juego, de más viejo a más nuevo (cada uno es un intento)."""
    if not exe:
        return []
    import glob
    try:
        from . import game
        d = game.game_log_dir(exe)
    except Exception:      # noqa: BLE001
        d = os.path.join(os.path.dirname(exe), "logs")
    paths = glob.glob(os.path.join(d, "*.log"))
    return sorted(paths, key=lambda p: os.path.getmtime(p))


def _read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def attempts(exe):
    """Un análisis por intento (log), de más viejo a más nuevo, con su primer error conservado."""
    out = []
    for p in _logs(exe):
        a = analyze_text(_read(p))
        a["log"] = p
        out.append(a)
    return out


def last_session(exe):
    """El análisis del intento más reciente (último log)."""
    logs = _logs(exe)
    if not logs:
        return {"level": 0, "confirmed": {}, "first_error": "", "log": ""}
    a = analyze_text(_read(logs[-1]))
    a["log"] = logs[-1]
    return a


def best(exe):
    """Mejor resultado histórico: combina el .exe, los marcadores del runtime y todos los intentos. Devuelve
    {level, evidence:{clave:evidencia}}."""
    evidence = {}
    if exe and os.path.isfile(exe):
        evidence["EXE_BUILT"] = "el ejecutable existe"
    for k, ev in read(exe).items():         # marcadores del runtime / validación manual
        evidence[k] = ev
    for a in attempts(exe):
        for k, ev in a["confirmed"].items():
            evidence.setdefault(k, ev)
    level = max([KEY_LEVEL[k] for k in evidence], default=0)
    return {"level": level, "evidence": evidence}


def level_for(root, exe=""):
    """El hito más alto alcanzado (histórico). Compatibilidad con la versión anterior."""
    return best(exe)["level"]


def triage(exe):
    """Si hay pantalla negra, ¿dónde falló? Devuelve una de:
    'antes del código del juego' | 'al preparar el renderer' | 'después de presentar una imagen' | ''."""
    b = best(exe)
    lvl = b["level"]
    if lvl >= KEY_LEVEL["FIRST_FRAME"]:
        return "después de presentar una imagen"
    if lvl >= KEY_LEVEL["RUNTIME_INIT"]:
        # llegó al runtime/título pero no presentó: fallo al preparar el renderer
        return "al preparar el renderer"
    return "antes del código del juego"


_PRESENTED = re.compile(r"\[render\]\s*presented\s*(\d+)\s*[x×]\s*(\d+)", re.I)


def presented_dims(exe):
    """Dimensiones REALMENTE presentadas (lo que el runtime escribió como `[render] presented WxH`), del último
    intento que las tenga. Devuelve (w, h) o None. (El tamaño del render target interno necesita un hook del
    renderer; aquí se registra la imagen presentada y lo solicitado se conoce desde los ajustes.)"""
    for p in reversed(_logs(exe)):
        m = _PRESENTED.search(_read(p))
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def summary(exe):
    """Resumen estructurado para el launcher: última sesión, nº de intentos, primer error del último, mejor
    histórico con evidencia, y triaje de pantalla negra."""
    ls = last_session(exe)
    b = best(exe)
    top = max(b["evidence"], key=lambda k: KEY_LEVEL[k], default="")
    pres = presented_dims(exe)
    return {
        "presented": pres,
        "last_level": ls["level"],
        "last_desc": describe(ls["level"]),
        "last_first_error": ls["first_error"],
        "attempts": len(_logs(exe)),
        "best_level": b["level"],
        "best_desc": describe(b["level"]),
        "best_evidence": b["evidence"].get(top, "") if top else "",
        "best_key": top,
        "triage": triage(exe),
        "log": ls["log"],
    }


def record_from_run(exe, outcome):
    """Tras una partida, anota (histórico) el mejor hito demostrado por el ÚLTIMO intento. Devuelve el nivel."""
    if not exe:
        return 0
    a = last_session(exe)
    level = a["level"]
    kind = (outcome or {}).get("kind", "")
    # un cierre limpio tras presentar frames es, al menos, juego en marcha
    if kind == "clean" and level >= KEY_LEVEL["FIRST_FRAME"]:
        level = max(level, KEY_LEVEL["PLAYABLE_SCENE"])
    if level:
        record(exe, LADDER[level][0], a["confirmed"].get(LADDER[level][0], "inferido tras la partida"))
    return level
