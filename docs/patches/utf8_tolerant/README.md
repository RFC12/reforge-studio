# Parche: UTF-8 tolerante (arregla el cierre/cuelgue `Invalid UTF-8` al enumerar contenido)

Arregla el fallo que ocurre en la pantalla **"Comprobando descargas de contenido…"** cuando hay
DLC / actualización (TU) / partidas cuyos nombres (o nombres de archivo internos del paquete)
traen **bytes UTF-8 inválidos**:

```
[critical] [core] [FATAL] Dispatch thread: deferred completion threw 'Invalid UTF-8'
```

## Causa raíz

`Invalid UTF-8` es el `what()` de `utf8::invalid_utf8` (utfcpp). En `src/core/utf8.cpp` (runtime
0.10.1 = commit `bd833a2a`) el procesamiento de cadenas usaba la API **checked** de utfcpp, que
**lanza** ante secuencias inválidas. La enumeración de contenido
(`xam_content_aggregate.cpp` → `IterateChildren` / `WildcardEngine` para emparejar nombres, y
`string::to_utf16(content_entry->name())` para el nombre visible) recorre esos nombres con
`utf8_citer` y los convierte con `to_utf16`. Un solo nombre con bytes inválidos hace que la
**completion diferida** lance → el bucle del hilo de despacho hace `REX_FATAL` → cierre.

Dos matices que obligan a una solución cuidadosa:

- **Iterador checked** (`utfcpp::iterator`): **lanza** → cierre `Invalid UTF-8`.
- **Iterador unchecked** (`utfcpp::unchecked::iterator`): **no lanza pero sobre-avanza** más allá
  del final en secuencias truncadas → lee fuera de rango → **cuelgue/crash silencioso** (el juego
  se queda en "Comprobando descargas de contenido…" renderizando el fondo pero sin avanzar, y el
  control no responde porque el juego no llega a estado jugable).

## El arreglo

`src/core/utf8.cpp` pasa a ser **tolerante** (ver `utf8_tolerant.diff`):

1. **Iterador `utf8_citer` propio, tolerante y acotado** (reemplaza a `utfcpp::iterator`): decodifica
   de forma leniente — una secuencia inválida o truncada produce `U+FFFD` (�) y **avanza solo los
   bytes disponibles, sin pasar nunca de `[start, end)`**. Nunca lanza y nunca entra en bucle. Es
   bidireccional (soporta `--`, `std::next`/`std::prev`, `std::find`/`std::equal`), así que cubre
   todas las funciones de `utf8.cpp` (split, find, lower, starts/ends_with, rutas, WildcardEngine).
2. **`to_utf16`** sanea con `utfcpp::replace_invalid(...)` (sustituye inválidos por `U+FFFD`) antes
   de convertir.
3. **`to_utf8`** envuelve la conversión checked en `try` con `catch(...)` que cae a
   `utfcpp::unchecked::utf16to8` (tolerante ante UTF-16 inválido / surrogates sueltos).
4. `#include <iterator>` para `std::back_inserter`.

Efecto: un nombre con bytes inválidos se muestra con `�` en lugar de tumbar el runtime. No cambia
ABI ni exports; es un reemplazo *drop-in* de `rexruntime.dll` (mismos imports que el original,
incluido `amd_fidelityfx_dx12.dll`).

## Build

`build_fix_runtime.ps1` reconstruye el árbol **0.10.1 offline** (superproyecto por
`git archive bd833a2a`, submódulos desde el working dir o el object store local — sin tocar el SDK
0.11), aplica `utf8_tolerant.diff` y compila `--target rexruntime`.

Variante **FSR** (drop-in idéntico): `-DREXGLUE_ENABLE_FIDELITYFX=ON`, que requiere una vez:

- **Vulkan SDK** (p. ej. 1.4.363.0) con `VULKAN_SDK` apuntándolo.
- **git en PATH** + `-DGIT_EXECUTABLE=<git>` para que `FetchContent` clone
  `github.com/rexglue/FidelityFX-SDK.git` (único acceso a red).
- Convertir `ffx-api/src/resource/ffx_api_dll.rc` de **UTF-16 LE a UTF-8** (el `llvm-rc` de Clang
  rechaza el BOM UTF-16).

## Integración en ReForge (persistencia a la recompilación)

El proyecto enlaza `rex::runtime` vía `find_package(rexglue 0.10.0 CONFIG)`, que resuelve al
**prebuilt** que ReForge Studio instala en:

```
%LocalAppData%\Programs\ReForge Studio\tools\rexglue-sdk\0.10.0.24-dev.gbd833a2-fsr\win-amd64\bin\rexruntime.dll
```

Para que el arreglo **persista a cada recompilación** se reemplaza ese prebuilt por el runtime
tolerante (con respaldo `rexruntime.dll.bak_reforge_<stamp>`). La lib de import
(`rexruntime.lib`) no cambia: los exports son idénticos. Una recompilación del juego (Taller →
Compilar) vuelve a copiar el runtime arreglado a `build\rexruntime.dll` automáticamente.

> El SDK de código `C:\ReForgeBuild\rexglue-sdk` (0.11) **no se toca**: se reconstruye 0.10.1 en
> una carpeta temporal y se parchea el prebuilt instalado por ReForge, no el árbol fuente.
>
> El string de versión del runtime queda `0.10.0.0-dev.unknown` (en vez de `.gbd833a2`) porque el
> árbol reconstruido no lleva los tags de git; es cosmético, no afecta ABI ni carga.

## Verificación (end-to-end en Windows, con DLC/TU reales)

Probado en el build real con los 5 DLC (Episode Pack IV, Episode 11.5/15.5, Lost Episode 1/2) y la
TU 0.0.1.5 activos — la condición que dispara el fallo. El juego **supera** la enumeración de
contenido (donde antes se caía con el iterador checked y se colgaba con el unchecked), llega a
gameplay y corre estable a **30 FPS**, con el control (DualSense, slot 0) detectado y **cero**
`Invalid UTF-8` / `FATAL` en el log. Tras reemplazar el prebuilt y reconstruir el proyecto,
`build\rexruntime.dll` queda con el runtime tolerante.

> Nota: los FPS bajos/inestables del primer arranque son el **prewarm de shaders** (≈2713 shaders),
> no el runtime; se estabilizan al calentar la caché.
