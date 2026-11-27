# Parche de traza del despachador — runtime de diagnóstico (0.10.1)

Objetivo: que `rexruntime.dll` diga **quién encoló** la tarea diferida que lanza `Invalid UTF-8`, **en qué fase**
falló (`pre`/`work`/`complete`/`post`) y **qué id** tenía la tarea activa, para distinguir dos tareas que
reutilizan la misma dirección `overlapped`.

## Versión correcta: 0.10.1, no 0.11

El juego (Asura's Wrath) carga un **`rexruntime.dll` monolítico de 0.10.0.24-dev.gbd833a2**, que corresponde al
commit **`bd833a2a`** (tag `v0.10.1`). En esa versión:

- El despachador diferido está en **`src/system/kernel_state.cpp`** (no en `src/kernel/dispatcher.cpp`, que es
  el layout de 0.11, donde el runtime se partió en `rexkernel`, `rexbase`, …).
- El fatal usa **`REX_FATAL`** (no `REXSYS_FATAL`).
- El encolador es **`KernelState::CompleteOverlappedDeferredEx`** con callbacks `pre_callback` / `completion_callback`
  / `post_callback` (`std::function`, no `rex::MoveOnlyFunction`).
- El bucle del hilo de despacho saca `fn` de `dispatch_queue_` y lo corre en `try/catch`.
- `REXSYS_WARN` / `REXSYS_DEBUG` existen; la traza sale a **WARN** para verse sin modo debug.
- El target de compilación **sí es `rexruntime`** y la opción **`REXGLUE_ENABLE_FIDELITYFX`** (variante `-fsr`)
  **existe** en este commit.

## Qué añade al log

```
[warning] [deferred] enqueue id=<n> ra=<hex> thread=<hex> overlapped=<hex>   ← al encolar (ra = quién la encoló)
[warning] [deferred] run id=<n> overlapped=<hex>                             ← al empezar a ejecutarla
[warning] [deferred] done id=<n> result=<hex>                               ← si terminó bien
[critical] [FATAL] Dispatch thread: deferred completion (task <n> phase=<fase> ra=<hex>) threw '<msg>'
```

`ra` es la dirección de retorno del llamador de `CompleteOverlappedDeferredEx` (`__builtin_return_address`, Clang).
Se simboliza restando la base de `rexruntime.dll` (que el ZIP incluye en `modules.txt`) y buscando el RVA con el
`.pdb`/`.map` o `llvm-symbolizer`.

## El id activo se mantiene durante pre → work → complete → post

El lambda encolado fija `rf_active_deferred = {id, ra, overlapped, "pre"}` al entrar y actualiza `phase` antes de
cada etapa (`"work"` tras el sleep, `"complete"` tras `completion_callback`, `"post"` dentro de `if (post_callback)`),
y se limpia al final. Así, **una excepción en `post` deja el fatal con el id correcto y `phase=post`** (y lo mismo
para `work`). ReForge lo lee con `reforge/deferred_trace.py`.

## Los 7 cambios en `src/system/kernel_state.cpp` (anclas únicas, verificadas x1)

1. **Estado de traza** (`RfDeferredTag` thread_local + contador atómico + `RF_RETURN_ADDRESS`) antes de la
   definición de `CompleteOverlappedDeferredEx(std::function<X_RESULT(uint32_t&, uint32_t&)> …)`.
2. **id/ra + log de encolado** justo antes de `dispatch_queue_.push_back(`.
3. **Captura** de `rf_task_id`/`rf_ra` en el lambda + fase `"pre"` + log `run`.
4. **Fase `"work"`** tras `rex::thread::Sleep(...)`.
5. **Fase `"complete"`** tras `completion_callback(...)`.
6. **Log `done` + fase `"post"` + limpieza** alrededor de `if (post_callback)` y al cierre del lambda.
7. **Fatal con id, fase y ra**: `REX_FATAL(...(task {} phase={} ra={:016X})...)`.

El texto exacto de cada cambio está en `build_diag_runtime.ps1`, que los aplica **verificando que cada ancla
aparece exactamente una vez** (y aborta si no). El formato del fatal coincide con el parser de
`reforge/deferred_trace.py` (no hace falta cambiar el parser).

## Cómo se obtiene un árbol 0.10.1 compilable sin red ni tocar tu SDK

Tu SDK (`C:\ReForgeBuild\rexglue-sdk`) está en **0.11** con cambios sin commit. El script **no lo toca**:
reconstruye el árbol de 0.10.1 en una carpeta temporal, **100% offline**, desde tus objetos git locales:

- **Superproyecto** 0.10.1: `git archive bd833a2a`.
- **Submódulos** (son submódulos de git): los que tu árbol principal ya tiene en el commit de 0.10.1 se copian de
  su working dir; los que difieren se extraen de su object store local (`.git/modules/<nombre>`). Se verificó que
  los commits de 0.10.1 de los 22 submódulos están presentes localmente, así que **no hace falta descargar nada**.

Luego configura con `-DREXGLUE_ENABLE_FIDELITYFX=ON -DCMAKE_BUILD_TYPE=RelWithDebInfo`, compila `--target rexruntime`,
ejecuta **un** intento en carpeta aparte con `run\logs` vacío, y arma el ZIP por lista explícita (sin juego, DLL,
TU, partidas ni `run\`).

## Estado

- **Verificado**: la reconstrucción offline del árbol 0.10.1 (superproyecto + 22 submódulos desde objetos locales),
  la resolución de `cmake`/`ninja` fuera del PATH, y que el script no aborta por los avisos de cmake en stderr
  (PS 5.1). El mecanismo de atribución id/fase lo cubre `tests/test_deferred_trace.py` y el self-test C++
  `dispatcher_trace_selftest.cpp`.
- **Pendiente de confirmar en tu equipo al ejecutarlo**: que el parche encaje x1 en tu `kernel_state.cpp` de
  0.10.1, la compilación completa de `rexruntime.dll` instrumentado y el arranque. Si la compilación falla, el
  script entrega los logs de CMake **sin lanzar** el juego.

## Prueba del parser en ReForge

`tests/test_deferred_trace.py` reproduce la traza y comprueba la atribución (incluida la fase y el descarte de la
tarea que terminó bien). ReForge la muestra en el Taller cuando el cierre viene de un runtime instrumentado.
