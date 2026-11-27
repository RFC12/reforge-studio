"""Atribución del cierre «Invalid UTF-8» con un runtime INSTRUMENTADO.

El parche `docs/patches/dispatcher_trace` hace que `rexruntime.dll` escriba, a nivel WARN (para que aparezca
aunque el log no esté en debug), una traza por cada tarea diferida:

    [deferred] enqueue id=<n> ra=<hex> thread=<hex> overlapped=<hex>
    [deferred] run id=<n> overlapped=<hex>
    [deferred] done id=<n> result=<hex>
    [FATAL] Dispatch thread: deferred completion (task <n> ra=<hex>) threw '<msg>'

`ra` es la dirección de retorno del ENCOLADOR (quién llamó a `CompleteDeferred`): se simboliza contra
`asuraswrath.map`/`rexruntime` restando la base del módulo (que el ZIP de diagnóstico incluye). El `id` único
permite distinguir DOS tareas que reutilizan la misma dirección `overlapped` (como las dos sobre `41F0FF50` del
121): el fatal nombra el `id` de la tarea ACTIVA, no el de la que ya terminó.

Este módulo lee esa traza y atribuye el fatal a su encolado. No necesita el símbolo: devuelve el `ra` y el `id`
para que ReForge (o tú) lo resuelva con el mapa.
"""
import re

_ENQ = re.compile(r"\[deferred\]\s*enqueue\s+id=(\d+)\s+ra=(0x[0-9A-Fa-f]+|[0-9A-Fa-f]+)\s+"
                  r"thread=(0x[0-9A-Fa-f]+|[0-9A-Fa-f]+)\s+overlapped=([0-9A-Fa-f]+)")
_RUN = re.compile(r"\[deferred\]\s*run\s+id=(\d+)\s+overlapped=([0-9A-Fa-f]+)")
_DONE = re.compile(r"\[deferred\]\s*done\s+id=(\d+)\s+result=([0-9A-Fa-f]+)")
_FATAL = re.compile(r"deferred completion \(task (\d+)\s+ra=(0x[0-9A-Fa-f]+|[0-9A-Fa-f]+)\) threw '([^']*)'")


def is_instrumented(log_text):
    """¿El log viene de un runtime con el parche de traza? (tiene líneas [deferred] con id)."""
    return bool(log_text) and "[deferred] enqueue id=" in log_text


def enqueues(log_text):
    """{id: {ra, thread, overlapped}} de cada tarea encolada (el id es único aunque se reuse el overlapped)."""
    out = {}
    for m in _ENQ.finditer(log_text or ""):
        out[int(m.group(1))] = {"ra": m.group(2), "thread": m.group(3), "overlapped": m.group(4)}
    return out


def attribute(log_text):
    """Atribuye el ÚLTIMO fatal a la tarea que lo lanzó. Devuelve None si no hay fatal instrumentado, o:
        {id, ra, overlapped, message, enqueue: {ra, thread, overlapped} | None, completed_same_overlapped: [ids]}
    `completed_same_overlapped` lista las tareas que terminaron bien en esa MISMA dirección (para no confundirlas
    con la que falló)."""
    if not log_text:
        return None
    fatals = list(_FATAL.finditer(log_text))
    if not fatals:
        return None
    m = fatals[-1]
    task_id = int(m.group(1))
    enq = enqueues(log_text)
    info = enq.get(task_id)
    overlapped = info["overlapped"] if info else None
    done_ids = {int(d.group(1)) for d in _DONE.finditer(log_text)}
    same = []
    if overlapped:
        for i, e in enq.items():
            if i != task_id and e["overlapped"].lower() == overlapped.lower() and i in done_ids:
                same.append(i)
    return {
        "id": task_id,
        "ra": m.group(2),
        "overlapped": overlapped,
        "message": m.group(3),
        "enqueue": info,
        "completed_same_overlapped": sorted(same),
    }


def summary(log_text):
    """Una línea legible para la interfaz, o '' si el log no está instrumentado / no hay fatal."""
    a = attribute(log_text)
    if not a:
        return ""
    base = (f"Tarea diferida #{a['id']} (encolada desde ra={a['ra']}"
            + (f", overlapped {a['overlapped']}" if a['overlapped'] else "")
            + f") lanzó «{a['message']}».")
    if a["completed_same_overlapped"]:
        base += (f" Otra(s) tarea(s) {a['completed_same_overlapped']} usaron esa misma dirección y terminaron "
                 "bien: no son la causa.")
    if not a["enqueue"]:
        base += " (No encontré su línea de encolado; manda el log completo de ese intento.)"
    else:
        base += " Simboliza ese ra contra el mapa para ver la función que la encoló."
    return base
