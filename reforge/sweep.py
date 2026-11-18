"""🔬 Barrido completo: revisa de una vez todas las capas donde suele fallar un juego recompilado (y las que no),
corrige lo que se puede corregir solo y deja un informe por capa. Después el Taller hace el mantenimiento
completo (análisis profundo, correcciones del codegen, compilar, probar el arranque y reparar en rondas).

Capas: compilación (modo Release y optimizaciones), XEX, archivos del juego (assets), código recompilado
(funciones, setjmp/longjmp, excepciones, optimización), avisos del compilador, mandos, rendimiento.
"""
import json
import os
import sys
import re

from . import game

OK, FIXED, WARN, FAIL = "ok", "fixed", "warn", "fail"
ICON = {OK: "✔", FIXED: "🔧", WARN: "⚠", FAIL: "✖"}

# Avisos de clang que pueden cambiar lo que hace el código (el resto son normales en código generado)
CRITICAL_WARNINGS = ("Wreturn-type", "Wuninitialized", "Wsometimes-uninitialized", "Wunsequenced",
                     "Wimplicit-function-declaration", "Wint-to-pointer-cast", "Winteger-overflow",
                     "Wshift-count-overflow", "Warray-bounds", "Wdangling", "Wreturn-stack-address",
                     "Wdivision-by-zero")
WARNING_RE = re.compile(r"warning: .*\[-(W[\w-]+)")
AUDIT_FILE = "reforge_build_audit.json"


def audit_build_warnings(lines, build):
    """Cuenta los avisos del compilador de la última compilación (separando los que importan) y lo guarda."""
    counts, critical, examples = {}, {}, []
    for ln in lines:
        m = WARNING_RE.search(ln)
        if not m:
            continue
        flag = m.group(1)
        counts[flag] = counts.get(flag, 0) + 1
        if flag in CRITICAL_WARNINGS:
            critical[flag] = critical.get(flag, 0) + 1
            if len(examples) < 5:
                examples.append(ln.strip()[:240])
    data = {"total": sum(counts.values()), "by_flag": counts, "critical": critical, "examples": examples}
    try:
        with open(os.path.join(build, AUDIT_FILE), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
    except OSError:
        pass
    return data


def _read_audit(build):
    try:
        with open(os.path.join(build, AUDIT_FILE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def check_build(cfg, root):
    out = []
    build = os.path.join(root, "build")
    bt = (getattr(cfg, "build_type", "") or "").strip()
    if bt.lower() != "release":
        cfg.build_type = "Release"
        try:
            cfg.save()
        except Exception:      # noqa: BLE001
            pass
        game.reset_cache(build)
        out.append(("Compilación", FIXED, f"Estaba en modo «{bt or '?'}»: ahora Release (optimizaciones de C++ "
                                          "activas: mucho más rendimiento). Se reconfigura y recompila."))
    else:
        cached = game.cache_value(build, "CMAKE_BUILD_TYPE")
        if cached and cached.lower() != "release":
            game.reset_cache(build)
            out.append(("Compilación", FIXED, f"El build se configuró en «{cached}»: se reconfigura en Release."))
        else:
            out.append(("Compilación", OK, "Modo Release (optimizaciones -O3 de clang activas)."))
    cxx = game.cache_value(build, "CMAKE_CXX_COMPILER") or getattr(cfg, "cxx_compiler", "")
    if cxx and not game.is_clang(cxx):
        out.append(("Compilación", WARN, f"El compilador no es clang ({os.path.basename(cxx)}): rexglue está pensado "
                                         "para clang; elige LLVM/Clang en Entorno."))
    return out


def check_cpu(root):
    """Instrucciones vectoriales: el Xbox 360 usa mucho VMX128; con -march=native clang usa AVX2 (y AVX-512 si
    tu procesador lo tiene) para traducirlas."""
    from .game_options import GameOptions
    from .optimizer import cached_hardware
    o = GameOptions.load(root)
    hw = cached_hardware()
    if o.cpu_native:
        return [("Procesador", OK, "Código compilado para tu CPU (-march=native: AVX2/AVX-512 para las "
                                   "instrucciones vectoriales VMX128 del Xbox 360).")]
    if hw.get("avx2"):
        o.cpu_native = True
        o.save(root)
        return [("Procesador", FIXED, "Activado -march=native: el código vectorial (VMX128) usa AVX2 de tu CPU. "
                                      "Ese .exe solo funcionará en procesadores como el tuyo (se desactiva en "
                                      "⚡ Optimizar).")]
    return [("Procesador", WARN, "Tu CPU no tiene AVX2: el código usa SSE4 (más lento en efectos vectoriales).")]


def check_stubs(exe):
    """Funciones del sistema del Xbox 360 que el runtime aún no implementa y que el juego llamó (último log)."""
    if not exe:
        return []
    log = game.newest_log(exe)
    if not log:
        return [("Funciones del sistema", WARN, "Sin log del juego todavía (se revisan tras la prueba).")]
    names = {}
    rx = re.compile(r"(__imp__\w+)\s+STUB|Unimplemented (\w+ message|\w+)|(\w+) not implemented", re.I)
    try:
        for ln in open(log, encoding="utf-8", errors="replace"):
            m = rx.search(ln)
            if m:
                n = next(g for g in m.groups() if g)
                names[n] = names.get(n, 0) + 1
    except OSError:
        return []
    if not names:
        return [("Funciones del sistema", OK, "El juego no llamó a funciones sin implementar.")]
    harmless = re.compile(r"Net|XNet|Live|XLIVE|Xam(User|Content)?Show|Party|Session|Voice|Marketplace|Avatar",
                          re.I)
    risky = [n for n in names if not harmless.search(n)]
    lst = ", ".join(sorted(names, key=lambda k: -names[k])[:6])
    if risky:
        return [("Funciones del sistema", WARN, f"Sin implementar en el runtime: {lst}. Si el juego falla o algo "
                                                 "no funciona en ese momento, es por una de ellas.")]
    return [("Funciones del sistema", OK, f"Solo red/Live sin implementar ({lst}): normal sin Xbox Live.")]


def check_xex(root):
    xex = os.path.join(root, "assets", "default.xex")
    try:
        with open(xex, "rb") as f:
            head = f.read(4)
        size = os.path.getsize(xex)
    except OSError:
        return [("XEX", FAIL, "No hay assets/default.xex.")]
    if head != b"XEX2":
        return [("XEX", FAIL, "default.xex no es un ejecutable XEX2 válido (¿archivo dañado o de otra consola?).")]
    if size < 64 * 1024:
        return [("XEX", WARN, f"default.xex es muy pequeño ({size // 1024} KB): puede estar incompleto.")]
    from .xex import read_xex_info
    info = read_xex_info(xex)
    extra = []
    if os.path.isfile(os.path.join(root, "assets", "default.xexp")):
        extra.append("con actualización/mejoras (default.xexp)")
    return [("XEX", OK, f"XEX2 válido · Title ID {info.get('title_id') or '?'} · versión {info.get('version') or '?'}"
                        + (" · " + ", ".join(extra) if extra else ""))]


def check_assets(root, max_files=200000):
    """Archivos del juego: vacíos o ilegibles (extracción incompleta, nube sin descargar, disco dañado)."""
    assets = os.path.join(root, "assets")
    n = total = 0
    empty, broken = [], []
    for dp, _dn, fs in os.walk(assets):
        for f in fs:
            n += 1
            if n > max_files:
                break
            p = os.path.join(dp, f)
            try:
                size = os.path.getsize(p)
                total += size
                if size == 0 and not f.lower().endswith((".gitkeep", ".txt")):
                    empty.append(os.path.relpath(p, assets))
                    continue
                with open(p, "rb") as fh:      # primer y último byte: detecta archivos sin descargar o dañados
                    fh.read(1)
                    if size > 1:
                        fh.seek(size - 1)
                        fh.read(1)
            except OSError:
                broken.append(os.path.relpath(p, assets))
    if not n:
        return [("Archivos del juego", FAIL, "La carpeta assets está vacía.")]
    out = []
    if broken:
        out.append(("Archivos del juego", FAIL, f"{len(broken)} archivo(s) no se pueden leer (dañados o sin "
                                                f"descargar): {', '.join(broken[:4])}{'…' if len(broken) > 4 else ''}. "
                                                "Vuelve a extraer el juego desde tu ISO/XEX."))
    if empty:
        out.append(("Archivos del juego", WARN, f"{len(empty)} archivo(s) vacíos: {', '.join(empty[:4])}"
                                                f"{'…' if len(empty) > 4 else ''}. Si el juego falla al cargar una "
                                                "zona, vuelve a extraerlo."))
    isos = [f for f in os.listdir(assets) if f.lower().endswith((".iso", ".god", ".zar", ".7z", ".zip", ".rar"))]
    if isos:
        out.append(("Archivos del juego", WARN, f"Hay imágenes o comprimidos dentro de assets ({', '.join(isos[:3])}): "
                                                "el juego debe estar extraído en carpetas; bórralos de assets para "
                                                "no ocupar espacio."))
    if not out:
        out.append(("Archivos del juego", OK, f"{n} archivos · {total / 1e9:.2f} GB · todos legibles."))
    return out


def check_code(root, exe=""):
    from .game_options import GameOptions
    o = GameOptions.load(root)
    out = []
    n = len(game.declared_functions(root))
    out.append(("Código recompilado", OK, f"{n} función(es) declaradas por las reparaciones automáticas."))
    path = game.manifest_path(root)
    txt = open(path, encoding="utf-8").read() if path else ""
    if re.search(r"^\s*setjmp_address\s*=", txt, re.M):
        out.append(("Código recompilado", OK, "setjmp/longjmp declarados (recuperación de errores del juego)."))
    seh = game.exception_handlers_enabled(root)
    out.append(("Código recompilado", OK, "Manejadores de excepciones (__try/__except): "
                                          + ("activados." if seh else "no hacen falta por ahora (se activan solos "
                                                                     "si el juego se cierra por un acceso inválido).")))
    lvl = game.CODEGEN_LEVEL_TITLES.get(o.codegen_level(), "")
    out.append(("Código recompilado", OK if o.codegen_opt_verified or o.codegen_level() == "off" else WARN,
                f"Optimización del código «{lvl}»" + (" comprobada." if o.codegen_opt_verified else
                                                      " aún sin comprobar: el barrido la prueba.")))
    try:
        from .deepscan import deep_scan_project
        cands = deep_scan_project(root, exe, game.generated_dir(root)) if exe else None
    except Exception:      # noqa: BLE001
        cands = None
    if cands is not None:
        pending = [a for a in cands if a not in game.declared_functions(root)]
        out.append(("Código recompilado", WARN if pending else OK,
                    f"Análisis profundo: {len(pending)} entrada(s) de función pendientes (se añaden ahora)."
                    if pending else "Análisis profundo: no faltan entradas de función."))
    return out


def check_warnings(root):
    a = _read_audit(os.path.join(root, "build"))
    if a is None:
        return [("Avisos del compilador", WARN, "Sin datos de la última compilación (se revisan en esta).")]
    crit = a.get("critical") or {}
    if crit:
        detail = ", ".join(f"{k} ×{v}" for k, v in sorted(crit.items(), key=lambda kv: -kv[1]))
        return [("Avisos del compilador", WARN, f"{sum(crit.values())} aviso(s) que pueden cambiar lo que hace el "
                                                f"código: {detail}. Si el juego falla en esa zona, el log lo dirá.")]
    return [("Avisos del compilador", OK, f"{a.get('total', 0)} aviso(s), ninguno crítico (normales en código "
                                          "generado).")]


def check_input(root):
    from .game_options import GameOptions, resolve_input_backend
    o = GameOptions.load(root)
    backend = resolve_input_backend(o.input_backend)
    txt = {"xinput": "XInput nativo de Windows (sin capas intermedias: mínima latencia)",
           "sdl": "SDL (mandos de PlayStation, Switch y genéricos)"}.get(backend, backend)
    return [("Mandos", OK, f"{txt}" + (" · menú Guía activado." if o.guide_menu else "."))]


def check_perf(root, exe):
    if not exe:
        return []
    from .autoconfig import apply
    line = apply(root, exe)
    return [("Rendimiento", OK, line)] if line else []


def check_icon(root, exe):
    """Icono del .exe: el oficial del juego (XDBF del XEX) en vez del genérico de Windows."""
    if not exe or not os.path.isfile(exe):
        return []
    from . import gameicon
    msg = gameicon.ensure(exe, root)
    src = gameicon._read_mark(exe).get("source", "")
    if msg.startswith("icono no aplicado") or (not src and sys.platform == "win32"):
        return [("Icono", WARN, msg or "No se pudo poner el icono al .exe.")]
    if msg:
        return [("Icono", FIXED, msg[0].upper() + msg[1:] + ".")]
    if src == "iniciales":
        return [("Icono", OK, "El juego no trae imagen propia (o usa compresión LZX): icono con sus iniciales; "
                              "se cambia solo por el oficial tras la primera partida.")]
    return [("Icono", OK, "El .exe ya tiene el icono oficial del juego.")] if src else []


def check_host():
    """El PC tal y como está: RAM libre y ajustes de Windows que cambian el rendimiento en Direct3D 12."""
    from . import hostcheck
    out = []
    for state, txt in hostcheck.report():
        out.append(("Tu PC", {hostcheck.OK: OK, hostcheck.WARN: WARN}.get(state, OK), txt))
    return out


def check_shaders(root, exe):
    """Caché de shaders: que no haya que volver a traducirlos en cada partida."""
    from . import shadercache
    from .game_options import GameOptions, title_id_for_exe
    tid = title_id_for_exe(exe) or ""
    o = GameOptions.load(root)
    st = shadercache.status(exe, tid, getattr(o, "render_path", "") or "rtv")
    if not st["exists"]:
        others = shadercache.other_caches(exe, tid)
        if others:
            return [("Shaders", FIXED, "Hay shaders ya traducidos de otro proyecto de este juego: se "
                                       "reaprovechan al jugar, así la primera partida no dará tirones.")]
        return [("Shaders", OK, "Sin caché todavía: la primera partida la crea y las siguientes cargan sin "
                                "tirones.")]
    state = WARN if st["cold"] else OK
    return [("Shaders", state, shadercache.describe(st))]


def run_static(cfg, root, exe):
    """Todas las capas que se revisan sin abrir el juego. Devuelve [(capa, estado, texto)]."""
    out = []
    for fn in (lambda: check_build(cfg, root), lambda: check_cpu(root), lambda: check_xex(root),
               lambda: check_assets(root), lambda: check_stubs(exe),
               lambda: check_code(root, exe), lambda: check_warnings(root), lambda: check_input(root),
               lambda: check_perf(root, exe), lambda: check_icon(root, exe),
               lambda: check_shaders(root, exe), check_host):
        try:
            out += fn()
        except Exception as e:      # noqa: BLE001
            out.append(("Revisión", WARN, f"No se pudo revisar una capa: {e}"))
    return out


def format_report(rows):
    return [f"{ICON.get(st, '·')} {layer}: {txt}" for layer, st, txt in rows]
