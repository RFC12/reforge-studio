"""Base de datos de problemas conocidos al recompilar y ejecutar juegos con rexglue.

Cada entrada reconoce un fallo por su huella en el log (o por el código de salida del proceso), explica en
palabras qué pasó y, cuando se puede, trae un remedio que ReForge aplica solo durante el mantenimiento.

La idea no es «arreglar cualquier cosa» —eso no existe para un recompilador—, sino acumular aquí cada
problema que se ha visto de verdad con su causa y su solución, para que el siguiente que lo sufra no empiece
de cero: el mantenimiento consulta esta tabla antes de recompilar a ciegas.

Un remedio es una función `(root, exe, log_text, info) -> (cambiado: bool, descripcion: str)`. `cambiado`
True significa que tocó el proyecto y conviene recompilar. `info` es el dict de `game.analyze_runtime_log`.

Para añadir un problema nuevo: una entrada más en `ISSUES`. `match` decide si es este caso; `recompila`
indica si su remedio deja algo que haya que volver a compilar.
"""
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Issue:
    id: str
    titulo: str
    sintomas: str                      # qué ve el jugador / qué pone el log
    causa: str                         # por qué pasa
    match: Callable                    # (log_text, info) -> bool
    remedio: Optional[Callable] = None  # (root, exe, log_text, info) -> (bool, str)
    consejo: str = ""                  # qué puede hacer el jugador si no hay remedio automático
    recompila: bool = False            # su remedio deja cambios que hay que recompilar

    def aplica(self, log_text, info):
        try:
            return bool(self.match(log_text or "", info or {}))
        except Exception:      # noqa: BLE001
            return False


# ---------------------------------------------------------------- remedios
def _fix_funcs_fuera(root, exe, log_text, info):
    from . import game
    quitadas = game.prune_bad_functions(root)
    if not quitadas:
        return False, ""
    lista = ", ".join(f"0x{a:08X}" for a in quitadas[:4]) + (" …" if len(quitadas) > 4 else "")
    return True, (f"Quitadas {len(quitadas)} dirección(es) fuera del módulo del juego ({lista}) que impedían "
                  "arrancar. Eran saltos a punteros dañados que ReForge había declarado por error como "
                  "funciones; el runtime rechazaba toda la tabla y el juego ni abría.")


def _fix_heap(root, exe, log_text, info):
    from . import hostcheck
    from .game_options import GameOptions
    o = GameOptions.load(root)
    actual = int(getattr(o, "heap_size_mb", 0) or 0)
    nuevo = hostcheck.next_heap_size(actual)
    if not nuevo or nuevo <= actual:
        return False, ""
    o.heap_size_mb = nuevo
    o.save(root)
    return True, (f"Se amplía el montón del CRT del juego a {nuevo} MB (estaba en "
                  f"{actual or 'el valor por defecto'}): se quedó sin memoria para sus reservas.")


def _fix_shaders(root, exe, log_text, info):
    from . import shadercache
    from .game_options import GameOptions
    tid = GameOptions.load(root).title_id if hasattr(GameOptions.load(root), "title_id") else ""
    try:
        n = shadercache.clear(exe, tid)
    except Exception:      # noqa: BLE001
        n = 0
    if not n:
        return False, ""
    return True, (f"Se vació la caché de shaders dañada ({n} archivo(s)); se vuelve a crear limpia en el "
                  "próximo arranque. No hay que recompilar.")


# ---------------------------------------------------------------- firmas
def _tiene(*trozos):
    def f(log_text, info):
        return any(t in log_text for t in trozos)
    return f


ISSUES = [
    Issue(
        id="funcs_fuera_del_modulo",
        titulo="Una función declarada cae fuera del juego",
        sintomas="El juego ni siquiera abre: se cierra al instante. En el log, «func_mappings entries "
                 "rejected» y «SetFunction: address … outside all registered module ranges».",
        causa="El juego saltó a una dirección a través de un puntero dañado y ReForge la declaró como si "
              "fuera una función. Como está fuera del módulo, el runtime rechaza toda la tabla de funciones "
              "al arrancar y aborta (C0000001). Basta una entrada así para tumbar el juego entero.",
        match=_tiene("func_mappings entries rejected", "outside all registered module ranges"),
        remedio=_fix_funcs_fuera,
        recompila=True,
    ),
    Issue(
        id="heap_agotado",
        titulo="El montón del CRT del juego se quedó corto",
        sintomas="Cierre al poco de empezar, con «rexcrt_heap: virtual heap allocation … failed» o "
                 "«o1heapInit failed» en el log.",
        causa="El juego pidió más memoria de su propio montón de la reservada.",
        match=lambda log, info: __import__("reforge.hostcheck", fromlist=["heap_exhausted"]).heap_exhausted(log),
        remedio=_fix_heap,
        recompila=False,
    ),
    Issue(
        id="cache_shaders_danada",
        titulo="La caché de shaders quedó dañada",
        sintomas="«Failed to initialize the graphics pipeline cache» en el log, a veces con parpadeos o un "
                 "cierre al cargar.",
        causa="La caché de shaders de un arranque anterior quedó a medias (un cierre forzado, un cambio de "
              "driver) y rexglue no puede leerla.",
        match=_tiene("Failed to initialize the graphics pipeline cache"),
        remedio=_fix_shaders,
        recompila=False,
    ),
    Issue(
        id="ejecuta_fuera_del_modulo",
        titulo="El juego salta a un puntero sin resolver",
        sintomas="Tras arrancar bien, el juego se cierra con «Execute(…): function not in function table» o "
                 "«Call to invalid or unregistered function» con una dirección muy por encima del módulo "
                 "(por ejemplo 0x8805xxxx).",
        causa="El juego llamó a través de un puntero de función que nunca recibió un valor válido: suele ser "
              "un import del motor que esta versión de rexglue todavía no implementa, o un patrón de código "
              "que no se recompiló bien. No es una función que falte declarar (declararla rompería el "
              "arranque), así que ReForge no puede añadirla sola.",
        match=lambda log, info: _ejecuta_fuera(log, info),
        consejo="Es un problema de compatibilidad de ese juego con esta versión del SDK, no de tu equipo. "
                "Prueba a recompilar con la optimización del código en «Conservadora» (Opciones del juego), "
                "y revisa si hay una versión más nueva de rexglue en Entorno. Algunos títulos aún no corren "
                "enteros.",
        recompila=False,
    ),
    Issue(
        id="mando_reconectado",
        titulo="El mando se desconectó y reconectó",
        sintomas="Cierre justo después de que el mando parpadee o se reconecte; «Controller disconnected "
                 "from slot» en el log.",
        causa="El controlador SDL de rexglue 0.10 daña la memoria cuando un mando se reconecta en caliente.",
        match=lambda log, info: bool(info.get("hotplug")),
        consejo="Con mandos de Xbox, usa «XInput» en Opciones del juego → Controles («Automático» ya lo "
                "elige) y revisa el cable o el receptor para que no se corte la conexión.",
        recompila=False,
    ),
    Issue(
        id="llamada_fuera_rango",
        titulo="El juego llamó a una dirección imposible",
        sintomas="«Call to invalid or unregistered function» con una dirección muy lejos del juego (fuera "
                 "de su módulo).",
        causa="El código del juego saltó a través de un puntero que aún no tenía un valor válido. No es una "
              "función que falte declarar: es un error de ejecución, a menudo síntoma de otra cosa que se "
              "recompiló mal antes.",
        match=lambda log, info: (info.get("kind") == "unregistered" and info.get("address") is not None
                                 and not _addr_en_modulo(info)),
        consejo="El análisis profundo no puede añadir esta dirección (no es una función). Si el juego fallaba "
                "siempre en el mismo punto, prueba a recompilarlo con la optimización del código en "
                "«Conservadora» desde Opciones del juego.",
        recompila=False,
    ),
]


EXECUTE_RE = re.compile(r"Execute\((?:0x)?([0-9A-Fa-f]{8})\): function not in function table")


def _ejecuta_fuera(log_text, info):
    """True si el log tiene un Execute()/llamada a una dirección fuera del módulo del juego."""
    root = info.get("root")
    direcciones = [int(m.group(1), 16) for m in EXECUTE_RE.finditer(log_text or "")]
    a = info.get("address")
    if a is not None:
        direcciones.append(a)
    if not direcciones:
        return False
    if not root:
        # sin proyecto a mano: una dirección así de alta casi siempre está fuera de un módulo de 360
        return any(d >= 0x84000000 for d in direcciones)
    from . import game
    return any(not game.in_module(root, d) for d in direcciones)


def _addr_en_modulo(info):
    """True si la dirección del fallo cae dentro del módulo del juego (necesita info['root'])."""
    root = info.get("root")
    a = info.get("address")
    if not root or a is None:
        return True
    from . import game
    return game.in_module(root, a)


def diagnose(log_text, info=None):
    """El primer problema conocido que encaja, o None."""
    info = info or {}
    for issue in ISSUES:
        if issue.aplica(log_text, info):
            return issue
    return None


def auto_heal(root, exe, log_text, info=None):
    """Aplica los remedios automáticos que encajen. Devuelve (mensajes, hay_que_recompilar).

    Recorre toda la tabla porque pueden coincidir varios a la vez (p. ej. caché de shaders y montón).
    """
    info = dict(info or {})
    info.setdefault("root", root)
    mensajes, recompila = [], False
    for issue in ISSUES:
        if not issue.remedio or not issue.aplica(log_text, info):
            continue
        try:
            cambiado, texto = issue.remedio(root, exe, log_text, info)
        except Exception as e:      # noqa: BLE001
            cambiado, texto = False, f"No se pudo aplicar «{issue.titulo}»: {e}"
        if cambiado:
            mensajes.append(texto)
            recompila = recompila or issue.recompila
        elif texto:
            mensajes.append(texto)
    return mensajes, recompila
