"""Diagnóstico de tirones (micro stuttering).

La extensión de ReForge mide el tiempo entre imágenes dentro del juego: cada tirón de más de 50 ms queda en el
log del juego con su hora («[ReForge] Tirón de N ms») y, con el diagnóstico activado, el tiempo de cada
fotograma en reforge_frametimes.csv. Con el diagnóstico, además, rexglue escribe en el log lo que hace por
dentro (log_level = debug): shaders nuevos, pipelines, texturas, lecturas de disco, audio…

Al cerrar el juego se cruza cada tirón con lo que rexglue anotó justo antes y se calcula la causa probable.
"""
import datetime
import os
import re

TS_RE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3})\]")
FPS_RE = re.compile(r"\[ReForge\] FPS (\d+) · peor (\d+) ms")
HITCH_RE = re.compile(r"\[ReForge\] Tir[oó]n de (\d+) ms")
FRAMETIMES_FILE = "reforge_frametimes.csv"
LOADING_MS = 700        # pausas más largas = pantallas de carga, no tirones
PLAY_FPS = 50           # el juego «ya está jugando» cuando un tramo de 5 s llega a estos FPS…
PLAY_AFTER_S = 60       # …o, si nunca llega (juego a 30), 60 s después del primer tramo
BURST_N, BURST_S = 4, 1.5   # 4 fotogramas lentos en 1,5 s = tramo a pocos FPS (vídeo, menú), no un tirón suelto

# Categorías: (clave, texto, regex sobre la línea del log)
CATEGORIES = [
    ("shaders", "compilación de shaders y pipelines nuevos (primera vez que aparece un efecto)",
     re.compile(r"Creating graphics pipeline|Generated .* shader|[Tt]ranslat\w* .*shader|shader .*translat|"
                r"ShaderTranslator|DXBC|pipeline", re.I)),
    ("textures", "carga de texturas nuevas",
     re.compile(r"texture with|TextureCache|xe_texture", re.I)),
    ("resolve", "copias de la GPU a memoria (resolve / memexport)",
     re.compile(r"Resolve|memexport|readback", re.I)),
    ("disk", "lecturas de disco",
     re.compile(r"NtReadFile|NtCreateFile|NtQueryFullAttributesFile|XFileRead|\.xxx|\.bik", re.I)),
    ("audio", "audio (XMA)",
     re.compile(r"\bXma|XMA|\[apu\]|audio", re.I)),
    ("threads", "sincronización de hilos",
     re.compile(r"KeWaitFor|NtWaitFor|KeSetEvent|KeDelayExecution|critical section|RtlEnterCriticalSection", re.I)),
]

ADVICE = {
    "shaders": ("La GPU del Xbox 360 usa shaders propios: cada efecto nuevo se traduce y compila la primera vez que "
                "aparece y se guarda (la próxima vez va fluido). Con la ruta «Rápido» (RTV) los shaders son "
                "mucho más pequeños y se compilan varias veces más rápido que con «Preciso» (ROV)."),
    "textures": ("Se cargan texturas nuevas: sube la caché de texturas (Optimizador «Fluido») o reduce la escala "
                 "de resolución."),
    "resolve": ("El juego copia imágenes de la GPU a memoria: desactiva «lecturas exactas» (readback) si lo "
                "activaste; esas copias obligan a esperar a la GPU."),
    "disk": ("El juego lee de disco en ese momento: copia el proyecto a un SSD si está en un disco duro."),
    "audio": "Coincide con audio XMA nuevo (decodificación).",
    "threads": "Coincide con esperas entre hilos del juego (no hay ajuste directo).",
}


def _ts(line):
    m = TS_RE.match(line)
    if not m:
        return None
    try:
        return datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None


def play_start(stamped):
    """Hora en que empieza el juego de verdad (tras logos, vídeos y menú) según los FPS que anota la extensión;
    None si el log no trae FPS (extensión anterior a la 1.18)."""
    first = None
    for t, ln in stamped:
        m = FPS_RE.search(ln)
        if not m:
            continue
        first = first or t
        if int(m.group(1)) >= PLAY_FPS or (t - first).total_seconds() >= PLAY_AFTER_S:
            return t - datetime.timedelta(seconds=5)
    return None


def analyze_log(path, before_ms=400):
    """{'hitches': [(hora, ms, {cat: n})] (solo tirones sueltos mientras se juega), 'causes': {cat: n},
    'debug': bool, 'loads': n, 'startup': n (arranque: logos, vídeos, menú), 'slow': n (tramos a pocos FPS),
    'minutes': minutos jugados}"""
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return {"hitches": [], "causes": {}, "debug": False, "loads": 0, "startup": 0, "slow": 0, "minutes": 0.0}
    stamped = [(t, ln) for ln in lines if (t := _ts(ln)) is not None]
    debug = any("] [debug] [" in ln or "] [trace] [" in ln for _t, ln in stamped)
    start = play_start(stamped)
    hitch_ts = [t for t, ln in stamped if (m := HITCH_RE.search(ln)) and int(m.group(1)) < LOADING_MS]
    burst = set()
    k = 0
    for i, t in enumerate(hitch_ts):          # ráfagas: muchos fotogramas lentos seguidos
        while (t - hitch_ts[k]).total_seconds() > BURST_S:
            k += 1
        if i - k + 1 >= BURST_N:
            burst.update(hitch_ts[k:i + 1])
    t0 = start or (stamped[0][0] if stamped else None)
    minutes = ((stamped[-1][0] - t0).total_seconds() / 60.0) if stamped and t0 else 0.0
    hitches, causes = [], {}
    loads = startup = slow = 0
    j0 = 0
    for i, (t, ln) in enumerate(stamped):
        m = HITCH_RE.search(ln)
        if not m:
            continue
        ms = int(m.group(1))
        if ms >= LOADING_MS:          # pantalla de carga: el juego deja de dibujar a propósito
            loads += 1
            continue
        if start is not None and t < start:
            startup += 1
            continue
        if t in burst:
            slow += 1
            continue
        start = t - datetime.timedelta(milliseconds=ms + before_ms)
        while j0 < i and stamped[j0][0] < start:
            j0 += 1
        counts = {}
        for _t2, ln2 in stamped[j0:i]:
            if HITCH_RE.search(ln2):
                continue
            for key, _txt, rx in CATEGORIES:
                if rx.search(ln2):
                    counts[key] = counts.get(key, 0) + 1
                    break
        hitches.append((t, ms, counts))
        if counts:
            top = max(counts, key=counts.get)
            causes[top] = causes.get(top, 0) + 1
        else:
            causes["unknown"] = causes.get("unknown", 0) + 1
    return {"hitches": hitches, "causes": causes, "debug": debug, "loads": loads, "startup": startup,
            "slow": slow, "minutes": max(0.0, minutes)}


def frame_stats(csv_path):
    """{'frames', 'avg_fps', 'low1_fps', 'over33', 'over100'} de reforge_frametimes.csv (None si no hay)."""
    try:
        vals = [float(x) for x in open(csv_path, encoding="utf-8").read().split()[1:] if x]
    except (OSError, ValueError):
        return None
    vals = [v for v in vals if 0 < v < LOADING_MS]      # sin pantallas de carga
    if len(vals) < 30:
        return None
    total = sum(vals)
    worst = sorted(vals, reverse=True)[:max(1, len(vals) // 100)]
    return {"frames": len(vals), "avg_fps": len(vals) * 1000.0 / total,
            "low1_fps": 1000.0 / (sum(worst) / len(worst)),
            "over33": sum(v > 33.4 for v in vals), "over100": sum(v > 100 for v in vals)}


def _fresh_csv(exe, log_path):
    """reforge_frametimes.csv de ESTA partida (no la de un diagnóstico anterior) o ''."""
    if not exe:
        return ""
    csv = os.path.join(os.path.dirname(exe), FRAMETIMES_FILE)
    try:
        if log_path and abs(os.path.getmtime(csv) - os.path.getmtime(log_path)) > 180:
            return ""
        return csv
    except OSError:
        return ""


def pacing_misses(log_path, exe, rate, skip_s=30.0):
    """¿Aguanta el juego el ritmo `rate`? Devuelve (fracción_de_fallos, 'frames'|'windows') o None.
    Con los tiempos de cada fotograma: fotogramas que tardaron 1,5× o más el intervalo (al fallar un vblank el
    juego espera al siguiente: 82,5 → 41 FPS de golpe = «bajón brusco»). Sin ellos: tramos de 5 s por debajo
    del 90 % del ritmo. Se saltan los primeros 30 s (carga)."""
    csv = _fresh_csv(exe, log_path)
    if csv:
        try:
            vals = [float(x) for x in open(csv, encoding="utf-8").read().split()[1:] if x]
        except (OSError, ValueError):
            vals = []
        t, rest = 0.0, []
        for v in vals:
            t += v
            if t >= skip_s * 1000 and 0 < v < LOADING_MS:
                rest.append(v)
        if len(rest) >= 600:
            limit = 1.5 * 1000.0 / rate
            return sum(v > limit for v in rest) / len(rest), "frames"
    fps = [int(m.group(1)) for m in FPS_RE.finditer(_read_text(log_path))][int(skip_s // 5):]
    if len(fps) >= 6:
        return sum(v < 0.9 * rate for v in fps) / len(fps), "windows"
    return None


def play_fps(log_path):
    """FPS de cada tramo de 5 s desde que se juega (sin logos, vídeos ni menú)."""
    stamped = [(t, ln) for ln in _read_text(log_path).splitlines() if (t := _ts(ln)) is not None]
    start = play_start(stamped)
    return [int(m.group(1)) for t, ln in stamped if (m := FPS_RE.search(ln)) and (start is None or t >= start)]


def own_frame_cap(exe, fps, target, title_id=None):
    """¿El juego tiene su propio tope de FPS y los está cumpliendo (30 planos de un título frame-locked)?

    Un juego con candado de framerate entrega un FPS plano (29-30) aunque la ventana refresque a 60: no está
    limitado por la GPU, así que bajarle la resolución interna no le da fluidez, solo la pierde. Sin esto, el
    ajuste automático leía «30 de 60» como «GPU lenta» y apagaba la resolución alta tras cada partida.
    """
    if not fps or not target or len(fps) < 4:
        return False
    ordered = sorted(fps)
    med = ordered[len(ordered) // 2]
    if med >= 0.9 * target:
        return False                      # llega al refresco: no hay tope propio que valga
    if ordered[-1] > max(med + 1, med * 1.1):
        return False                      # hay subidas por encima del tope: GPU limitada, no candado
    try:
        if title_id is None:
            from .game_options import title_id_for_exe
            title_id = title_id_for_exe(exe) or ""
        from . import gamedb
        return bool((gamedb.frame_lock(title_id) or {}).get("locked"))
    except Exception:      # noqa: BLE001
        return False


def _read_text(path):
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except (OSError, TypeError):
        return ""


WARM_RE = re.compile(r"Created (\d+) graphics pipelines .*from the storage in (\d+) milliseconds")
WARM_SH_RE = re.compile(r"Translated (\d+) shaders from the storage")


def shader_warmup(log_path):
    """(shaders, pipelines, ms) precompilados al arrancar desde el almacén del juego (como SCSKiller, pero
    de rexglue: lo que el juego usó en partidas anteriores se compila antes de jugar)."""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            head = f.read(4 << 20)
    except OSError:
        return None
    m = WARM_RE.search(head)
    if not m:
        return None
    sh = WARM_SH_RE.search(head)
    return (int(sh.group(1)) if sh else 0, int(m.group(1)), int(m.group(2)))


def report(log_path, exe=None):
    """Texto para el jugador (lista de líneas) y la causa principal ('' si no hay tirones)."""
    a = analyze_log(log_path)
    out = []
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            guard = [ln.split("[ReForge] ", 1)[1].strip() for ln in f if "[ReForge] Guardián:" in ln]
    except OSError:
        guard = []
    for g in guard[-3:]:
        out.append("🛡 " + g + (" (se usará desde el arranque en las próximas partidas)" if "→" in g else ""))
    warm = shader_warmup(log_path)
    if warm and warm[1]:
        out.append(f"🧊 Shaders precompilados al arrancar: {warm[0]} shaders y {warm[1]} pipelines de partidas "
                   f"anteriores ({warm[2]} ms) — no causan tirones al jugar.")
    csv = _fresh_csv(exe, log_path)
    st = frame_stats(csv) if csv else None
    if st:
        out.append(f"Fotogramas: {st['frames']} · media {st['avg_fps']:.0f} FPS · 1% más lentos {st['low1_fps']:.0f} FPS · "
                   f"{st['over33']} por encima de 33 ms · {st['over100']} por encima de 100 ms")
    fps = play_fps(log_path)
    if len(fps) >= 2:
        med = sorted(fps)[len(fps) // 2]
        drops = sum(1 for v in fps if v < med * 0.75)
        out.append(f"FPS del juego cada 5 s: mediana {med} · mínimo {min(fps)}" +
                   (f" · {drops} bajón(es) por debajo del 75 %" if drops else ""))
    if a["startup"]:
        out.append(f"Arranque (logos, vídeos y menú): {a['startup']} fotograma(s) lento(s) — normal, no cuentan.")
    if a["slow"]:
        out.append(f"{a['slow']} fotograma(s) lento(s) seguidos en vídeos, menús o zonas pesadas (no son tirones sueltos).")
    h = a["hitches"]
    mins = a["minutes"]
    if not h:
        out.append("Sin tirones mientras jugabas." if a["startup"] or a["slow"] else
                   "Sin tirones de más de 50 ms en esta partida.")
        return out, ""
    worst = max(ms for _t, ms, _c in h)
    rate = f" en {mins:.0f} min de juego ({len(h) / mins:.1f} por minuto)" if mins >= 1 else ""
    out.append(f"{len(h)} tirón(es) de más de 50 ms mientras jugabas{rate} (el mayor, {worst} ms).")
    if not a["debug"]:
        return out, ""          # sin log detallado no se sabe la causa: el Taller decide solo si diagnosticar
    names = {k: txt for k, txt, _rx in CATEGORIES}
    names["unknown"] = "sin actividad anotada justo antes (el juego o el driver)"
    ranked = sorted(a["causes"].items(), key=lambda kv: -kv[1])
    for k, n in ranked:
        out.append(f"  · {n} × {names.get(k, k)}")
    main = ranked[0][0] if ranked and a["debug"] else ""
    if main in ADVICE:
        out.append(ADVICE[main])
    return out, main


UNDERRUN_RE = re.compile(r"no frames queued|underrun|buffer starv", re.I)


def audio_underruns(log_path):
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            return sum(1 for ln in f if UNDERRUN_RE.search(ln))
    except OSError:
        return 0


DIAG_COOLDOWN = 5      # partidas normales entre dos diagnósticos automáticos
DIAG_PER_MIN = 1.0     # tirones sueltos por minuto de juego a partir de los cuales se diagnostica


def auto_tune(root, exe, log_path):
    """El Taller se ajusta solo tras cada partida. Devuelve los cambios hechos (textos) — se aplican la
    próxima vez que se abra el juego:
    * audio que se queda sin datos (sonido entrecortado/estático) → más audio en cola;
    * muchos tirones sin saber la causa → diagnóstico detallado en la próxima partida;
    * diagnóstico ya hecho → se apaga (consume rendimiento) y queda el informe;
    * tirones por texturas → optimizador «Fluido» (más caché de texturas)."""
    from .game_options import GameOptions
    o = GameOptions.load(root)
    if not o.auto_tune or not log_path:
        return []
    a = analyze_log(log_path)
    changes = []
    dirty = False
    # Ruta de render: ROV (precisa) cuesta mucho más que RTV (rápida) en GPU y al compilar pipelines, y en algunos
    # juegos da la imagen sobreexpuesta (COD AW). Si un juego en ROV va lento o el guardián vio la imagen blanca,
    # se prueba RTV en la próxima partida; si con RTV se cierra o se cuelga, vuelve a ROV y queda anotado.
    fps_play = play_fps(log_path)
    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            washed = "[ReForge] Guardián: imagen sobreexpuesta" in fh.read()
    except OSError:
        washed = False
    med = sorted(fps_play)[len(fps_play) // 2] if len(fps_play) >= 6 else 0
    target = 0.0
    try:
        from .pc_enhance import frame_values
        target = float(frame_values(o.frame_mode(), o.fps_unlocked, cap=o.fps_cap).get("video_mode_refresh_rate", 0))
    except Exception:      # noqa: BLE001
        pass
    # Un juego con tope propio (30 FPS planos) no va «lento»: no se le baja la resolución ni se le cambia la ruta.
    own_cap = own_frame_cap(exe, fps_play, target)
    if o.path_trial == "rtv" and o.render_path == "rtv":
        if med or not washed:
            o.path_trial = ""
            dirty = True
            changes.append("Ruta rápida (RTV) confirmada para este juego" + (f" ({med} FPS)." if med else "."))
    elif o.render_path == "rov" and not o.rov_required and ((med and med < 50 and not own_cap) or washed):
        o.render_path, o.path_trial = "rtv", "rtv"
        dirty = True
        why = f"iba a {med} FPS" if med and med < 50 else "la imagen salía sobreexpuesta"
        changes.append(f"En la ruta precisa (ROV) {why}: en la próxima partida se prueba la ruta rápida (RTV); si el "
                       "juego falla con ella, ReForge vuelve solo a ROV.")
    under = audio_underruns(log_path)
    if under >= 3 and (o.audio_queue or 32) < 64:
        o.audio_queue = min(64, (o.audio_queue or 32) * 2)
        changes.append(f"El audio se quedó sin datos {under} veces (sonido entrecortado): ahora hay {o.audio_queue} "
                       "fotogramas de audio en cola.")
    n = len(a["hitches"])
    ranked = sorted(a["causes"].items(), key=lambda kv: -kv[1])
    main = ranked[0][0] if ranked else ""
    capped = False
    # Ritmo: si el juego no aguanta el ritmo automático (p. ej. 82,5 en 165 Hz), cada vblank que falla lo baja de
    # golpe a la mitad (bajón brusco + latencia). Mejor 60 constantes.
    if o.frame_mode() == "auto" and o.fps_unlocked and not o.fps_cap:
        from .pc_enhance import monitor_hz, paced_rate
        rate = paced_rate(monitor_hz(), True)
        res = pacing_misses(log_path, exe, rate) if rate > 61 else None
        if res and res[0] >= (0.05 if res[1] == "frames" else 0.25):
            o.fps_cap = 60.0
            capped = True
            changes.append(f"El juego no aguanta {rate:g} FPS estables ({res[0] * 100:.0f} % de "
                           f"{'fotogramas' if res[1] == 'frames' else 'tramos'} por debajo): cada fallo lo bajaba "
                           "de golpe a la mitad. Ahora va a 60 FPS constantes (sin bajones bruscos, menos latencia).")
    per_min = n / a["minutes"] if a["minutes"] >= 1 else float(n >= 5) * 99
    if a["debug"] and o.diagnostics:
        o.diagnostics = False
        o.diag_cooldown = DIAG_COOLDOWN
        changes.append("Diagnóstico completado: se desactiva el log detallado (consume rendimiento). Se repetirá "
                       f"solo si los tirones siguen, como mínimo dentro de {DIAG_COOLDOWN} partidas.")
    elif not a["debug"] and not o.diagnostics:
        if o.diag_cooldown > 0:
            o.diag_cooldown -= 1
            dirty = True
        elif n >= 5 and per_min >= DIAG_PER_MIN and not capped:
            o.diagnostics = True
            changes.append(f"{n} tirones mientras jugabas: la próxima partida se analiza en detalle para saber la "
                           "causa (el log detallado consume algo de rendimiento; se apaga solo al cerrar).")
    # ---- reparaciones según la causa (solo con el log detallado se sabe la causa de cada tirón)
    known = {k: v for k, v in a["causes"].items() if k != "unknown"}
    cause = max(known, key=known.get) if known else ""
    if cause and (known[cause] < 3 or known[cause] < 0.25 * max(1, n)):
        cause = ""
    fps = fps_play
    slow_gpu = bool(fps and target and sorted(fps)[len(fps) // 2] < 0.9 * target and not own_cap)
    if o.readback_resolve and (n >= 3 or slow_gpu or cause == "resolve"):
        o.readback_resolve = False
        changes.append("«Lecturas exactas» (readback) desactivadas: obligaban a esperar a la GPU en cada copia → "
                       "latencia y bajones. Si ves algún efecto raro, vuelve a activarlas en 🎮 Opciones.")
    if cause == "shaders" and o.render_path != "rtv":
        o.render_path, o.allow_invalid_fetch = "rtv", True
        changes.append("Tirones al compilar shaders: ruta de render «Rápido» (shaders varias veces más pequeños y "
                       "rápidos de compilar). Los ya compilados se guardan: cada efecto tira solo la primera vez.")
    if cause == "textures":
        if o.perf_mode != "fluido":
            o.perf_mode = "fluido"
            changes.append("Tirones por carga de texturas: optimizador en «Fluido» (más caché de texturas).")
        elif int(o.resolution_scale or 1) > 1:
            o.resolution_scale = int(o.resolution_scale) - 1
            o.scale_ceiling = o.resolution_scale
            changes.append(f"Tirones por texturas con la caché ya al máximo: resolución interna a {o.resolution_scale}× "
                           "(texturas y destinos de render más ligeros).")
    elif slow_gpu and int(o.resolution_scale or 1) > 1:
        o.resolution_scale = int(o.resolution_scale) - 1
        o.scale_ceiling = o.resolution_scale
        changes.append(f"El juego no llegaba a {target:g} FPS mientras jugabas: resolución interna a "
                       f"{o.resolution_scale}× para recuperar fluidez.")
    changes += _after_play(root, exe, log_path, o)
    if changes or dirty:
        o.save(root)
    return changes


def _after_play(root, exe, log_path, o):
    """Lo que se guarda o se arregla al terminar la partida: caché de shaders y montón del juego."""
    changes = []
    try:        # la caché de shaders que acaba de crecer se guarda dentro del proyecto
        from . import shadercache
        from .game_options import title_id_for_exe
        tid = title_id_for_exe(exe) or ""
        saved = shadercache.backup(root, exe, tid)
        if saved > (1 << 20):
            changes.append(f"Shaders guardados en el proyecto ({saved / (1 << 20):.1f} MB): si vuelves a "
                           "compilar este juego, no habrá que traducirlos otra vez.")
    except Exception:      # noqa: BLE001
        pass
    try:        # el juego se quedó sin montón: se sube para la próxima partida
        from . import hostcheck
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        if hostcheck.heap_exhausted(text):
            nxt = hostcheck.next_heap_size(getattr(o, "heap_size_mb", 0))
            if nxt:
                o.heap_size_mb = nxt
                changes.append(f"Al juego se le acabó la memoria de su montón: se sube a {nxt} MB para la "
                               "próxima partida.")
    except Exception:      # noqa: BLE001
        pass
    return changes


ACHIEVEMENT_RE = re.compile(r"Achievement unlocked: ([0-9A-Fa-f]{8})")
DISCONNECT_RE = re.compile(r"Controller disconnected")


class LiveLog:
    """Lee el log del juego mientras se juega (solo lo nuevo en cada llamada) y lleva la cuenta en vivo."""

    def __init__(self, path):
        self.path = path
        self.pos = 0
        self.playing = False         # ya pasó el arranque (logos, vídeos, menú)
        self._first_fps = None
        self._recent = []
        self.stats = {"hitches": 0, "worst": 0, "loads": 0, "errors": 0, "fatal": False,
                      "achievements": 0, "disconnects": 0, "last_error": "", "fps": 0, "fps_min": 0, "drops": 0}

    def feed(self):
        try:
            with open(self.path, encoding="utf-8", errors="replace") as f:
                f.seek(self.pos)
                chunk = f.read()
                self.pos = f.tell()
        except OSError:
            return self.stats
        from .game import HARMLESS_ERROR_RE
        s = self.stats
        for ln in chunk.splitlines():
            f = FPS_RE.search(ln)
            if f:
                fps = int(f.group(1))
                t = _ts(ln)
                if t and self._first_fps is None:
                    self._first_fps = t
                    s["hitches"] = s["worst"] = 0      # lo anterior era el arranque (logos, vídeos, menú)
                if fps >= PLAY_FPS or (t and (t - self._first_fps).total_seconds() >= PLAY_AFTER_S):
                    if not self.playing:
                        self.playing = True
                        s["fps_min"] = 0          # el mínimo cuenta desde que se juega (no logos ni menú)
                        s["hitches"] = s["worst"] = 0
                if not self.playing:
                    s["fps"] = fps
                    continue
                if s["fps"] and fps < s["fps"] * 0.75:
                    s["drops"] += 1
                s["fps"] = fps
                s["fps_min"] = fps if not s["fps_min"] else min(s["fps_min"], fps)
                continue
            m = HITCH_RE.search(ln)
            if m:
                ms = int(m.group(1))
                if ms >= LOADING_MS:
                    s["loads"] += 1
                elif self.playing or self._first_fps is None:   # sin FPS en el log (extensión anterior): todo cuenta
                    t = _ts(ln)
                    self._recent = [x for x in self._recent if t and (t - x[0]).total_seconds() <= BURST_S]
                    self._recent.append((t, False))
                    if len(self._recent) >= BURST_N:      # ráfaga (vídeo, menú, zona pesada): no son tirones sueltos
                        s["hitches"] -= sum(1 for _x, burst in self._recent[:-1] if not burst)
                        self._recent = [(x, True) for x, _b in self._recent]
                    else:
                        s["hitches"] += 1
                        s["worst"] = max(s["worst"], ms)
            elif "[FATAL]" in ln:
                s["fatal"] = True
                s["last_error"] = ln[-160:]
            elif ("] [error] [" in ln or "] [critical] [" in ln) and not HARMLESS_ERROR_RE.search(ln):
                s["errors"] += 1
                s["last_error"] = ln[-160:]
            elif ACHIEVEMENT_RE.search(ln):
                s["achievements"] += 1
            elif DISCONNECT_RE.search(ln):
                s["disconnects"] += 1
        return s


def live_text(stats, seconds):
    """Línea de estado en vivo: «🎮 12:04 · 3 tirones (peor 180 ms) · 1 logro»."""
    m, sec = divmod(int(seconds), 60)
    parts = [f"🎮 Jugando {m:02d}:{sec:02d}"]
    if stats.get("fps"):
        parts.append(f"{stats['fps']} FPS (mín. {stats['fps_min']})")
    h = stats.get("hitches", 0)
    parts.append("sin tirones" if not h else f"{h} tirón(es) (peor {stats.get('worst', 0)} ms)")
    if stats.get("achievements"):
        parts.append(f"{stats['achievements']} logro(s)")
    if stats.get("errors"):
        parts.append(f"{stats['errors']} aviso(s) de error")
    return " · ".join(parts)
