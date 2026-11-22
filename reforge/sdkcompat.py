"""Compatibilidad entre el SDK seleccionado y el proyecto generado.

El problema que esto evita: un proyecto se genera con un SDK (p. ej. rexglue 0.10, que expone el target
`rex::runtime`); si luego se instala/selecciona un SDK de otra familia (0.11 renombró ese target), el CMake del
proyecto falla con «Target ... links to rex::runtime but the target was not found» y la recompilación se rompe
sin que el usuario haya tocado el proyecto.

Aquí se valida, antes de configurar, que el SDK seleccionado provee los targets `rex::*` que el proyecto
necesita. Si no, se busca un SDK instalado que sí los provea y se cambia a él automáticamente (dejando copia de
la configuración anterior), para que la recompilación «vuelva a la normalidad» sola. Si no hay ninguno
compatible, se detiene con un mensaje claro en vez de un error de CMake incomprensible.
"""
import glob
import os
import re
import shutil

# Targets tipo rex::runtime / rexglue::runtime que aparecen en el CMake generado o que define un SDK.
_REX = re.compile(r"\b(rex(?:glue)?::[A-Za-z0-9_]+)")


def _version_key(ver):
    """Clave numérica para ordenar versiones de SDK (p. ej. «0.10.0.24-dev.gbd833a2-fsr» → (0,10,0,24))."""
    nums = re.findall(r"\d+", str(ver).split("-")[0])
    return tuple(int(n) for n in nums[:4]) + (0,) * (4 - len(nums[:4]))


def _read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def needed_targets(root):
    """Targets rex::* que el proyecto ya generado necesita del SDK. Vacío si aún no se ha generado nada."""
    needed = set()
    for rel in ("generated/rexglue.cmake", "generated/sources.cmake", "CMakeLists.txt"):
        needed |= set(_REX.findall(_read(os.path.join(root, *rel.split("/")))))
    return needed


def provided_targets(prefix):
    """Targets rex::* que define un SDK (por sus archivos de CMake). Set vacío = no se pudo leer (no concluir)."""
    d = os.path.join(prefix, "lib", "cmake", "rexglue")
    found = set()
    for f in glob.glob(os.path.join(d, "*.cmake")):
        txt = _read(f)
        # add_library(rex::runtime SHARED IMPORTED) y add_library(rex::foo ALIAS ...)
        for m in re.finditer(r"add_library\(\s*(rex(?:glue)?::[A-Za-z0-9_]+)", txt):
            found.add(m.group(1))
    return found


def sdk_covers(prefix, needed):
    """¿El SDK en `prefix` provee todos los targets `needed`? Si no se pueden leer sus targets, no se bloquea."""
    if not needed:
        return True
    provided = provided_targets(prefix)
    if not provided:          # no se pudo leer el SDK: mejor no concluir incompatibilidad
        return True
    return needed <= provided


def check(cfg, root):
    """(ok, needed, prefix_actual). ok=True si el SDK seleccionado sirve para este proyecto o no hay nada que validar."""
    needed = needed_targets(root)
    prefix = cfg.sdk_prefix()
    if not needed or not prefix:
        return True, needed, prefix
    return sdk_covers(prefix, needed), needed, prefix


def _backup_config(cfg):
    try:
        p = cfg.path()
        if os.path.isfile(p):
            shutil.copyfile(p, p + ".bak_sdk")
    except Exception:      # noqa: BLE001
        pass


def ensure_compatible(cfg, root, build, env, ctx):
    """Valida el SDK contra el proyecto antes de configurar. Si no encaja, cambia solo a un SDK instalado
    compatible (con copia de respaldo de la config) y limpia la caché de CMake; si no hay ninguno, se detiene
    con un mensaje claro. Pensado para correr como paso previo a «Configurar CMake»."""
    ok, needed, prefix = check(cfg, root)
    if ok:
        return
    pedido = ", ".join(sorted(needed))
    from .toolchain import installed_sdks
    # Entre los SDK instalados que SÍ sirven para este proyecto, elegir el mejor: versión más alta y, a igualdad,
    # la variante con FSR/CAS (mejores componentes). Así el Taller no solo evita el error: escoge lo óptimo.
    compatibles = [(ver, pfx, exe) for ver, pfx, exe in installed_sdks()
                   if pfx != prefix and sdk_covers(pfx, needed)]
    compatibles.sort(key=lambda c: (_version_key(c[0]), c[0].endswith("-fsr")), reverse=True)
    if compatibles:
        ver, pfx, exe = compatibles[0]
        _backup_config(cfg)
        cfg.rexglue = exe
        cfg.rexglue_sdk = pfx
        try:
            cfg.save()
        except Exception:      # noqa: BLE001
            pass
        # recalcular el entorno in situ para que el configure use el SDK nuevo
        env.clear()
        env.update(cfg.environment())
        # la caché de CMake tiene cacheado el SDK viejo: se borra para forzar un configure limpio
        cache = os.path.join(build, "CMakeCache.txt")
        try:
            if os.path.isfile(cache):
                os.remove(cache)
        except OSError:
            pass
        ctx.log(f"⚠ El SDK seleccionado no era compatible con este proyecto (necesita {pedido}, que ese SDK ya "
                f"no provee). Cambiado automáticamente al mejor SDK compatible instalado ({ver}) y limpiada la "
                "caché de CMake para que la recompilación no se rompa. La selección anterior quedó respaldada.", "warn")
        return
    raise RuntimeError(
        f"El SDK seleccionado no es compatible con este proyecto: se generó usando {pedido}, que este SDK ya "
        "no provee (p. ej. al pasar de rexglue 0.10 a 0.11 cambió el nombre del target). Soluciones: en "
        "Entorno selecciona un SDK de la familia con la que generaste el proyecto (p. ej. 0.10.x), o pulsa "
        "«Limpiar build» para regenerar el proyecto desde cero con el SDK nuevo.")
