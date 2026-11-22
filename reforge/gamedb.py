"""Base de datos de compatibilidad por juego (Title ID) para la recompilación nativa.

Idea: por cada juego guardamos SOLO los parámetros que de verdad mapean al motor nativo de rexglue
(ruta de imagen ROV/RTV, gamma, lectura de resolves, alpha, guardas de fetch, comportamiento de FPS) más
una guía y la fuente del dato. Con eso el Taller aplica la configuración idónea automáticamente al preparar
el proyecto, y para un juego que no esté en la base usa el heurístico seguro de siempre.

Tres capas, de menor a mayor prioridad:
  1. Semilla verificada  → los registros de `optimizer` (RENDER_HINTS / GFX_HINTS), ya probados.
  2. Curada              → `CURATED` de este módulo (ampliable con el tiempo).
  3. De usuario          → `gamedb_user.json` en la carpeta de configuración: lo que el propio PC va
                           aprendiendo (`remember`) y comparte (`export_db` / `import_db`).

Lo que NO hacemos: importar a ciegas la base de Xenia. Xenia es otro motor (un emulador) y sus ajustes no
se trasladan 1:1 a un `.exe` nativo. Sí ofrecemos su ficha como REFERENCIA informativa (estado y notas), con
el enlace para verificar, sin tocar la configuración con ella.
"""
import json
import os

from .core import config_dir

# --------------------------------------------------------------------------- claves que persistimos
# Banderas gráficas (fuera de la tríada de la ruta de imagen, que va por «preset») que tiene sentido recordar
# por juego. image_guard viene activo por defecto: solo se guarda si se desactivó.
GFX_KEYS = ("gfx_gamma_unorm16", "gfx_fuzzy_alpha", "image_guard", "readback_mode", "smooth_motion")


# --------------------------------------------------------------------------- capa curada (ampliable)
# Registros nativos de la base (los que no vienen ya de optimizer). Cada uno:
#   preset:  clave de modo de imagen de RENDER_LADDER ("rtv", "rov_inv", …) o "" si no se fija.
#   flags:   {atributo de GameOptions: valor} para banderas gráficas concretas.
#   guide:   explicación corta para la ficha.
#   source:  de dónde sale el dato (captura propia, prueba del usuario, …).
#   conf:    "verificado" | "probado" | "referencia".
CURATED = {
    # (vacío de serie: la semilla verificada vive en optimizer. Aquí se van añadiendo casos nuevos.)
}

# Juegos con candado de framerate (animación/física/QTE atadas al ritmo de fotogramas).
#
# Cómo lo "detectamos": NO del binario (eso no es fiable), sino del catálogo de parches de la comunidad de
# Xenia (xenia-canary/game-patches). Que exista un parche «Unlock FPS» para un juego es la señal fiable de que
# ese juego es frame-locked: alguien ya localizó dónde fija el tope y, a menudo, deja anotado qué se acelera.
#
# OJO (honestidad técnica): la dirección del parche es una escritura de MEMORIA GUEST de Xenia (0x8xxxxxxx).
# Xenia reinterpreta el código al vuelo, por eso allí basta escribir un `nop` sobre la instrucción. En la
# recompilación NATIVA el código ya está traducido a C++, así que esa escritura en runtime NO surte efecto:
# para portar un desbloqueo de FPS habría que parchear la imagen PPC ANTES de generar el código. Por eso aquí
# el parche se guarda solo como REFERENCIA; no se aplica solo.
FRAME_LOCKED = {
    "43430817": {
        "locked": True,
        "note": "Asura's Wrath: los QTE de machaque de botones van atados al framerate; desbloquear los FPS "
                "acelera cinemáticas y QTEs.",
        "source": "xenia-canary/game-patches (boma): parche «Unlock FPS»",
        "patch": [{"type": "be32", "address": "0x824d7130", "value": "0x60000000"},
                  {"type": "be8", "address": "0x8299a70f", "value": "0x01"}],
    },
}


# Notas por motor: NO se aplican solas (no fabricamos arreglos por juego sin verificar); se muestran como
# guía para quien prepara un juego de ese motor y quiere saber por dónde empezar.
ENGINE_NOTES = {
    "ue3": "Unreal Engine 3: es habitual que el menú o algunas escenas salgan lavados/sobreexpuestos. Si pasa, "
           "prueba «gamma del render target a UNORM16». Los efectos aditivos suelen ir mejor en ROV que en RTV.",
    "mtframework": "MT Framework (Capcom): efectos y transparencias pueden fallar en RTV; ROV los compone con "
                   "más precisión. Vigila el gamma en cinemáticas.",
    "unity": "Unity: suele recompilar limpio. Si hay parpadeo de sombras, prueba ROV.",
}


# --------------------------------------------------------------------------- utilidades
def title_id_of(root):
    """Title ID en mayúsculas del proyecto, o "" si no se puede leer."""
    try:
        from .xex import read_xex_info
        return read_xex_info(os.path.join(root, "assets", "default.xex")).get("title_id", "").upper()
    except Exception:      # noqa: BLE001
        return ""


def _user_path():
    return os.path.join(config_dir(), "gamedb_user.json")


def _load_user():
    try:
        with open(_user_path(), encoding="utf-8") as f:
            data = json.load(f)
        return {str(k).upper(): v for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception:      # noqa: BLE001
        return {}


def _save_user(db):
    try:
        os.makedirs(config_dir(), exist_ok=True)
        with open(_user_path(), "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False


def _preset_label(key):
    from .optimizer import RENDER_LADDER
    return dict((k, t) for k, t, *_r in RENDER_LADDER).get(key, key)


def _seed_record(tid):
    """Registro derivado de la semilla verificada de optimizer (RENDER_HINTS + GFX_HINTS), o None."""
    from . import optimizer
    preset = optimizer.RENDER_HINTS.get(tid)
    gfx = optimizer.GFX_HINTS.get(tid)
    if not preset and not gfx:
        return None
    rec = {"preset": "", "flags": {}, "guide": "", "source": "semilla verificada de ReForge", "conf": "verificado"}
    if preset:
        rec["preset"] = preset[0]
        rec["guide"] = preset[1]
    if gfx:
        rec["flags"] = dict(gfx[0])
        rec["guide"] = (rec["guide"] + " · " if rec["guide"] else "") + gfx[1]
    return rec


# --------------------------------------------------------------------------- consulta
def record(tid):
    """Ficha fusionada del juego (semilla < curada < usuario), o None si no hay nada."""
    tid = (tid or "").upper()
    if not tid:
        return None
    merged = None
    for layer in (_seed_record(tid), CURATED.get(tid), _load_user().get(tid)):
        if not layer:
            continue
        if merged is None:
            merged = {"preset": "", "flags": {}, "guide": "", "source": "", "conf": "referencia", "name": ""}
        if layer.get("preset"):
            merged["preset"] = layer["preset"]
        if layer.get("flags"):
            merged["flags"] = {**merged["flags"], **layer["flags"]}
        for k in ("guide", "source", "name", "conf"):
            if layer.get(k):
                merged[k] = layer[k]
    return merged


def record_for(root):
    return title_id_of(root), record(title_id_of(root))


def frame_lock(tid):
    """{'locked','note','source','patch'} si el juego tiene candado de framerate conocido, o None.

    Combina el catálogo (semilla de la comunidad de Xenia) con lo que la base de usuario haya anotado.
    """
    tid = (tid or "").upper()
    seed = FRAME_LOCKED.get(tid)
    uf = (_load_user().get(tid) or {}).get("frame_lock")
    if uf:
        return {**(seed or {}), **uf}
    return seed


def frame_advice(root):
    """(frame_locked, mensaje) para el juego del proyecto. El mensaje recomienda Movimiento Suave y avisa si el
    desbloqueo de FPS está activo en un juego con animación atada al framerate."""
    fl = frame_lock(title_id_of(root))
    if not fl or not fl.get("locked"):
        return False, ""
    msg = ("Juego con candado de 30 FPS: la animación y los QTE van atados al framerate ("
           + fl.get("source", "catálogo de la comunidad") + "). Para más fluidez SIN acelerar las cinemáticas, "
           "usa Movimiento Suave (mantiene el ritmo real e interpola); desbloquear los FPS a secas las acelera.")
    try:
        from .game_options import GameOptions
        o = GameOptions.load(root)
        if getattr(o, "fps_unlocked", False) and not getattr(o, "smooth_motion", False):
            msg = "⚠ Tienes el desbloqueo de FPS activo. " + msg
    except Exception:      # noqa: BLE001
        pass
    return True, msg


def all_games():
    """[(title_id, ficha)] de todo lo que hay en la base, ordenado por nombre/Title ID."""
    from . import optimizer
    tids = set(optimizer.RENDER_HINTS) | set(optimizer.GFX_HINTS) | set(CURATED) | set(_load_user())
    out = [(t, record(t)) for t in tids]
    out.sort(key=lambda x: ((x[1] or {}).get("name") or x[0]))
    return out


def summary():
    """Texto corto con cuántos juegos hay y de qué nivel de confianza."""
    games = all_games()
    por = {"verificado": 0, "probado": 0, "referencia": 0}
    for _t, r in games:
        por[(r or {}).get("conf", "referencia")] = por.get((r or {}).get("conf", "referencia"), 0) + 1
    return (f"{len(games)} juego(s) en la base de compatibilidad: {por['verificado']} verificados, "
            f"{por['probado']} probados, {por['referencia']} de referencia.")


# --------------------------------------------------------------------------- aplicar al proyecto
def apply(root, log=None):
    """Aplica la configuración idónea del juego al preparar el proyecto. Devuelve la lista de avisos.

    Primero la semilla verificada (vía optimizer, que ya respeta lo elegido a mano), luego la capa curada y la
    de usuario. Solo toca lo que siga en su valor por defecto para no pisar ajustes del usuario.
    """
    from . import optimizer
    msgs = []
    m = optimizer.apply_title_hint(root)
    if m:
        msgs.append(m)
    m = optimizer.apply_gfx_hint(root)
    if m:
        msgs.append(m)
    tid = title_id_of(root)
    extra = CURATED.get(tid) or _load_user().get(tid)
    if extra:
        # _apply_record solo toca lo que siga por defecto y el preset solo si está en automático, así que no
        # repite lo que la semilla ya dejó puesto arriba.
        msgs += _apply_record(root, extra)
    _locked, adv = frame_advice(root)
    if adv:
        msgs.append(adv)
    if log:
        for m in msgs:
            log(m, "ok")
    return msgs


def _apply_record(root, rec):
    from .game_options import GameOptions
    o = GameOptions.load(root)
    defaults = GameOptions()
    msgs = []
    changed = False
    preset = rec.get("preset")
    if preset and o.preset() == "auto":
        o.apply_preset(preset)
        if o.render_path == "rov":
            o.rov_required = True
        changed = True
        nombre = rec.get("name") or "este juego"
        msgs.append(f"Modo de imagen idóneo para {nombre}: {_preset_label(preset)}"
                    + (f" ({rec['guide']})" if rec.get("guide") else "") + ".")
    applied = []
    for k, v in (rec.get("flags") or {}).items():
        if hasattr(o, k) and getattr(o, k) == getattr(defaults, k, None) and getattr(o, k) != v:
            setattr(o, k, v)
            changed = True
            applied.append(k)
    if applied:
        msgs.append(f"Ajustes gráficos idóneos aplicados ({', '.join(applied)}) — "
                    f"{rec.get('guide') or rec.get('source') or 'base de datos de compatibilidad'}.")
    if changed:
        o.save(root)
    return msgs


# --------------------------------------------------------------------------- aprender / compartir
def remember(root, guide="", source="probado por el usuario"):
    """Guarda en la base de usuario la config actual del juego (ruta de imagen + banderas gráficas no estándar).

    Así la base crece con cada juego que confirmas que va bien, y se puede exportar y compartir.
    """
    tid = title_id_of(root)
    if not tid:
        return False
    from .game_options import GameOptions
    o = GameOptions.load(root)
    defaults = GameOptions()
    flags = {}
    for k in GFX_KEYS:
        if hasattr(o, k) and getattr(o, k) != getattr(defaults, k):
            flags[k] = getattr(o, k)
    pr = o.preset()
    try:
        from .game import display_name
        name = display_name(os.path.basename(root.rstrip("/\\")))
    except Exception:      # noqa: BLE001
        name = os.path.basename(root.rstrip("/\\"))
    rec = {"name": name,
           "preset": pr if pr not in ("auto", "custom") else "",
           "flags": flags,
           "guide": guide,
           "source": source,
           "conf": "probado"}
    db = _load_user()
    db[tid] = rec
    return _save_user(db)


def forget(tid):
    """Quita un juego de la base de usuario. Devuelve True si existía."""
    tid = (tid or "").upper()
    db = _load_user()
    if tid in db:
        del db[tid]
        _save_user(db)
        return True
    return False


def export_db(path):
    """Vuelca la base de usuario a un archivo JSON (para compartir). Devuelve cuántos juegos escribió."""
    db = _load_user()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    return len(db)


def import_db(path, overwrite=False):
    """Mezcla una base de usuario externa. Devuelve cuántos juegos añadió o actualizó."""
    with open(path, encoding="utf-8") as f:
        incoming = json.load(f)
    if not isinstance(incoming, dict):
        return 0
    db = _load_user()
    n = 0
    for k, v in incoming.items():
        k = str(k).upper()
        if overwrite or k not in db:
            db[k] = v
            n += 1
    _save_user(db)
    return n


# --------------------------------------------------------------------------- referencia de Xenia y guía
def xenia_reference_url(tid):
    """Enlace a la ficha de compatibilidad de Xenia para ese Title ID (referencia informativa, a verificar)."""
    tid = (tid or "").upper()
    if not tid:
        return "https://github.com/xenia-project/game-compatibility/issues"
    return ("https://github.com/xenia-project/game-compatibility/issues?q="
            f"is%3Aissue+{tid}")


def guide(root):
    """Guía de compatibilidad en texto para el juego del proyecto: config conocida + referencia Xenia + consejos."""
    tid = title_id_of(root)
    rec = record(tid)
    lineas = []
    if tid:
        lineas.append(f"Title ID: {tid}")
    if rec:
        conf = {"verificado": "verificado", "probado": "probado", "referencia": "referencia"}.get(rec.get("conf"), "")
        if rec.get("preset"):
            lineas.append(f"Modo de imagen idóneo: {_preset_label(rec['preset'])}"
                          + (f" — {rec['guide']}" if rec.get("guide") else ""))
        if rec.get("flags"):
            lineas.append("Ajustes gráficos: " + ", ".join(f"{k}={v}" for k, v in rec["flags"].items()))
        if rec.get("source"):
            lineas.append(f"Fuente: {rec['source']}" + (f" ({conf})" if conf else ""))
    else:
        lineas.append("Sin ficha propia todavía: se usará el heurístico seguro (ruta de imagen automática). "
                      "Cuando confirmes que va bien, guárdalo para que quede en la base.")
    fl = frame_lock(tid)
    if fl and fl.get("locked"):
        lineas.append("Candado de framerate: SÍ — " + fl.get("note", "animación atada al framerate")
                      + " → usa Movimiento Suave en vez de desbloquear los FPS.")
    lineas.append("Referencia de Xenia (emulador, a verificar — no se aplica sola): " + xenia_reference_url(tid))
    return "\n".join(lineas)
