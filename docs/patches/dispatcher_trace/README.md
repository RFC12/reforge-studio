# Parche de traza del despachador — runtime de diagnóstico

Objetivo: que `rexruntime.dll` diga **quién encoló** la tarea diferida que lanza `Invalid UTF-8` y **qué id** tenía
la tarea activa en el fatal, para distinguir dos tareas que reutilizan la misma dirección `overlapped`.

Se instrumenta **solo** `src/kernel/dispatcher.cpp` (sin cambiar firmas de interfaz). Las líneas salen a nivel
**WARN** para que aparezcan aunque el log no esté en modo debug. ReForge las lee con `reforge/deferred_trace.py`.

## Qué añade al log

```
[warning] [deferred] enqueue id=<n> ra=<hex> thread=<hex> overlapped=<hex>   ← al encolar (ra = quién la encoló)
[warning] [deferred] run id=<n> overlapped=<hex>                             ← al empezar a ejecutarla
[warning] [deferred] done id=<n> result=<hex>                               ← si terminó bien
[critical] [FATAL] Dispatch thread: deferred completion (task <n> ra=<hex>) threw '<msg>'   ← la que falló
```

`ra` es la dirección de retorno del llamador de `CompleteDeferred` (`__builtin_return_address`, Clang). Se
simboliza restando la base de `rexruntime.dll` (que el ZIP de diagnóstico incluye) y buscando el RVA en el `.map`
o con `llvm-symbolizer`/`cdb`.

## Los tres cambios en `src/kernel/dispatcher.cpp`

### 1. Estado de traza (añadir una vez, cerca de la cabecera del archivo, tras los `#include`)

```cpp
#include <cstdint>
namespace {
struct RfDeferredTag { uint64_t id = 0; const void* ra = nullptr; uint32_t overlapped = 0; };
thread_local RfDeferredTag rf_active_deferred{};
thread_local const void* rf_enqueue_ra = nullptr;
std::atomic<uint64_t> rf_deferred_counter{1};
}  // namespace
#define RF_RETURN_ADDRESS() __builtin_return_address(0)
```

### 2. En `CompleteDeferred` (la sobrecarga que ENCOLA, la de `MoveOnlyFunction<CompletionOptions()> work`)

**Antes:**
```cpp
  REXSYS_DEBUG("CompleteDeferred: queuing for overlapped {:08X}", overlapped);
  auto ptr = StateOf(runtime_).GetAddressSpace()->TranslateVirtual(overlapped);
  XOverlappedSetResult(ptr, X_ERROR_IO_PENDING);
  XOverlappedSetContext(ptr, KernelThread::GetCurrentThreadHandle());
  std::lock_guard lock(dispatch_mutex_);
  dispatch_queue_.push_back([this, work = std::move(work), overlapped, pre = std::move(pre),
                             post = std::move(post)]() mutable {
    REXSYS_DEBUG("Deferred overlapped {:08X}: running pre", overlapped);
```
**Después:**
```cpp
  const uint64_t rf_task_id = rf_deferred_counter.fetch_add(1);
  const void* rf_ra = rf_enqueue_ra ? rf_enqueue_ra : RF_RETURN_ADDRESS();
  rf_enqueue_ra = nullptr;
  REXSYS_WARN("[deferred] enqueue id={} ra={:016X} thread={:08X} overlapped={:08X}", rf_task_id,
              reinterpret_cast<uintptr_t>(rf_ra),
              static_cast<uint32_t>(reinterpret_cast<uintptr_t>(KernelThread::GetCurrentThreadHandle())),
              overlapped);
  REXSYS_DEBUG("CompleteDeferred: queuing for overlapped {:08X}", overlapped);
  auto ptr = StateOf(runtime_).GetAddressSpace()->TranslateVirtual(overlapped);
  XOverlappedSetResult(ptr, X_ERROR_IO_PENDING);
  XOverlappedSetContext(ptr, KernelThread::GetCurrentThreadHandle());
  std::lock_guard lock(dispatch_mutex_);
  dispatch_queue_.push_back([this, work = std::move(work), overlapped, pre = std::move(pre),
                             post = std::move(post), rf_task_id, rf_ra]() mutable {
    rf_active_deferred = RfDeferredTag{rf_task_id, rf_ra, overlapped};
    REXSYS_WARN("[deferred] run id={} overlapped={:08X}", rf_task_id, overlapped);
    REXSYS_DEBUG("Deferred overlapped {:08X}: running pre", overlapped);
```

Y tras `CompleteOverlappedEx(overlapped, options.result, ExtendedError(options), Length(options));` (dentro del
mismo lambda):

**Antes:**
```cpp
    CompleteOverlappedEx(overlapped, options.result, ExtendedError(options), Length(options));
    if (post) {
```
**Después:**
```cpp
    CompleteOverlappedEx(overlapped, options.result, ExtendedError(options), Length(options));
    REXSYS_WARN("[deferred] done id={} result={:08X}", rf_task_id, options.result);
    rf_active_deferred = RfDeferredTag{};
    if (post) {
```

### 3. En la primera sobrecarga de `CompleteDeferred` (la de `MoveOnlyFunction<void()> work`), marca el ra real

**Antes:**
```cpp
                                  rex::MoveOnlyFunction<void()> post) {
  CompleteDeferred(
      overlapped,
```
**Después:**
```cpp
                                  rex::MoveOnlyFunction<void()> post) {
  rf_enqueue_ra = RF_RETURN_ADDRESS();
  CompleteDeferred(
      overlapped,
```

### 4. En el `catch` del hilo despachador (`Dispatcher::Start`), nombra la tarea activa

**Antes:**
```cpp
      } catch (const std::exception& e) {
        REXSYS_FATAL("Dispatch thread: deferred completion threw '{}'", e.what());
```
**Después:**
```cpp
      } catch (const std::exception& e) {
        REXSYS_FATAL("Dispatch thread: deferred completion (task {} ra={:016X}) threw '{}'",
                     rf_active_deferred.id, reinterpret_cast<uintptr_t>(rf_active_deferred.ra), e.what());
```

## Autoprueba del mecanismo (dos tareas, misma dirección)

La atribución (una tarea termina en `41F0FF50`, otra lanza en la misma dirección → se culpa a la segunda) está
**probada en ReForge** con `tests/test_deferred_trace.py` sobre una traza sintética idéntica a la del 121. En la
DLL, el mismo patrón produce `enqueue id=1 … done id=1` y `enqueue id=2 … FATAL task=2`, y ReForge lo atribuye a
la #2. (Si quieres la prueba dentro del SDK, añade un test que encole dos tareas con el mismo `overlapped`, una
que retorne y otra que `throw std::runtime_error("x")`, y comprueba que el fatal lleva `task=2`.)

Construcción y captura: `build_diag_runtime.ps1` (en esta carpeta).
