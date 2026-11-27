# Parche de traza del despachador — runtime de diagnóstico

Objetivo: que `rexruntime.dll` diga **quién encoló** la tarea diferida que lanza `Invalid UTF-8`, **en qué fase**
falló (`pre`/`work`/`complete`/`post`) y **qué id** tenía la tarea activa, para distinguir dos tareas que
reutilizan la misma dirección `overlapped`.

Se instrumenta **solo** `src/kernel/dispatcher.cpp` (sin cambiar firmas de interfaz). Las líneas salen a nivel
**WARN** (`REXSYS_WARN`, verificado que existe en `include/rex/logging/log_category.h`) para que aparezcan aunque
el log no esté en modo debug. ReForge las lee con `reforge/deferred_trace.py`.

## Qué añade al log

```
[warning] [deferred] enqueue id=<n> ra=<hex> thread=<hex> overlapped=<hex>   ← al encolar (ra = quién la encoló)
[warning] [deferred] run id=<n> overlapped=<hex>                             ← al empezar a ejecutarla
[warning] [deferred] done id=<n> result=<hex>                               ← si terminó bien
[critical] [FATAL] Dispatch thread: deferred completion (task <n> phase=<fase> ra=<hex>) threw '<msg>'
```

`ra` es la dirección de retorno del llamador de `CompleteDeferred` (`__builtin_return_address`, Clang). Se
simboliza restando la base de `rexruntime.dll` (que el ZIP incluye en `modules.txt`) y buscando el RVA con el
`.pdb`/`.map` o `llvm-symbolizer`.

## El id activo se mantiene durante pre → work → complete → post

El lambda encolado fija `rf_active_deferred = {id, ra, overlapped, "pre"}` al entrar y actualiza `phase` antes de
cada etapa (`"work"` antes de `work()`, `"complete"` tras ella, `"post"` dentro de `if (post)`), y se limpia al
final. Así, **una excepción en `post` deja el fatal con el id correcto y `phase=post`** (y lo mismo para `work`).

## Los 4 cambios en `src/kernel/dispatcher.cpp` (anclas únicas, verificadas x1)

1. **Estado de traza** antes de `void Dispatcher::CompleteDeferred(u32 overlapped, rex::MoveOnlyFunction<void()> work,`:
   ```cpp
   #include <cstdint>
   namespace {
   struct RfDeferredTag { uint64_t id = 0; const void* ra = nullptr; uint32_t overlapped = 0; const char* phase = "idle"; };
   thread_local RfDeferredTag rf_active_deferred{};
   thread_local const void* rf_enqueue_ra = nullptr;
   std::atomic<uint64_t> rf_deferred_counter{1};
   }  // namespace
   #define RF_RETURN_ADDRESS() __builtin_return_address(0)
   ```
2. **ra real en la primera sobrecarga** (la de `void()` work): `rf_enqueue_ra = RF_RETURN_ADDRESS();` justo tras
   `rex::MoveOnlyFunction<void()> post) {` y antes de `CompleteDeferred(`.
3. **Lambda instrumentado**: se sustituye el bloque `dispatch_queue_.push_back(...)` completo por la versión que
   calcula `rf_task_id`/`rf_ra`, registra `enqueue`, captura `rf_task_id, rf_ra` en el lambda, fija
   `rf_active_deferred` con la fase, registra `run`/`done` y limpia al final.
4. **Fatal con id y fase**: se sustituye
   `REXSYS_FATAL("Dispatch thread: deferred completion threw '{}'", e.what());` por la versión con
   `(task {} phase={} ra={:016X})`.

El texto exacto de cada cambio está en `build_diag_runtime.ps1`, que los aplica **verificando que cada ancla
aparece exactamente una vez** (y aborta si no).

## Qué se probó realmente (en Windows, por Claude, vía puente)

- **Aplicación del parche** sobre tu `dispatcher.cpp` real: los 4 cambios se aplican **1 vez cada uno** y las 5
  marcas quedan exactamente una vez (`patch_apply`). Anclas confirmadas únicas; `REXSYS_WARN` existe; la variante
  `-fsr` = `REXGLUE_ENABLE_FIDELITYFX=ON`.
- **Mecanismo C++** (`dispatcher_trace_selftest.cpp`, compilado con tu `clang++` y ejecutado): **5/5**. Dos tareas
  en la misma dirección `41F0FF50` (una termina, otra lanza en `post`) → el fatal culpa a la **#2** con
  `phase=post`; una excepción en `work` → `phase=work`. Esta es la **prueba del despachador C++ instrumentado**.
- **ZIP por lista explícita**: incluye solo los 10 archivos de diagnóstico y **excluye** juego, DLL, TU, partidas
  y `run\`.

**Lo que NO se ha probado en tu equipo** (y corre al ejecutar el script): la **compilación completa** de
`rexruntime.dll` y el **arranque** del juego. Por eso el script comprueba el código de salida de cada `cmake` y,
si falla, entrega los logs **sin lanzar** el juego.

## Prueba del parser en ReForge

`tests/test_deferred_trace.py` (en el repo) reproduce la traza y comprueba la atribución (incluida la fase y el
descarte de la tarea que terminó bien). ReForge la muestra en el Taller cuando el cierre viene de un runtime
instrumentado.
