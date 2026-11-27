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

## Estado (verificado end-to-end en Windows)

El script se corrió completo en el PC: reconstruye 0.10.1 offline (22 submódulos desde objetos locales), aplica
los 7 cambios ×1 sobre el `kernel_state.cpp` real, compila `rexruntime` **y** `rexgpu-xenos` (sin sufijo, con
símbolos), los planta en una carpeta aislada y **arranca el juego con el runtime instrumentado**. El juego llega
a menú/gameplay y la traza `[deferred] enqueue/run/done` sale correctamente.

**Encoladores identificados** (ra simbolizado contra el `.pdb`, en `symbols.txt`):

- `xeXamEnumerate` (`src/kernel/xam/xam_enum.cpp:66`) — encola la mayoría de las tareas diferidas (enumeración).
- `xeXamContentCreate` (`src/kernel/xam/xam_content.cpp:231`).
- `KernelState::CompleteOverlappedDeferred` (wrapper interno; el origen XAM real está un frame arriba).

Es decir, las tareas diferidas que lanzan `Invalid UTF-8` las encolan las rutas de **enumeración/creación de
contenido** (XAM), que es donde se parsea el nombre/metadatos del contenido (DLC/partida/TU).

**Pendiente**: en la corrida de validación el cierre `Invalid UTF-8` **no se reprodujo** (las tareas completaron
`done result=0` y el juego corrió >2,5 min). Para capturar el fatal `(task N phase=X ra=Y)` hay que ejecutar la
build instrumentada **bajo la condición que lo dispara** (la TU/el contenido con el campo UTF-8 inválido aplicado).
El script deja la build lista y simboliza automáticamente; con el fatal presente, `deferred_trace.py` ata la tarea
a su encolador y `symbols.txt` da la función exacta.

## Prueba del parser en ReForge

`tests/test_deferred_trace.py` reproduce la traza y comprueba la atribución (incluida la fase y el descarte de la
tarea que terminó bien). ReForge la muestra en el Taller cuando el cierre viene de un runtime instrumentado.
