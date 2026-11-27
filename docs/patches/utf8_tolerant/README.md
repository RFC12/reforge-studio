# Parche: conversiones UTF-8 tolerantes (arregla el cierre `Invalid UTF-8`)

Arregla el cierre fatal que ocurre al enumerar contenido (DLC / partidas / TU) cuyo nombre
tiene **bytes UTF-8 inválidos**:

```
[critical] [core] [FATAL] Dispatch thread: deferred completion threw 'Invalid UTF-8'
```

## Causa raíz

`Invalid UTF-8` es el `what()` de la excepción `utf8::invalid_utf8` de **utfcpp**. En
`src/core/utf8.cpp` (runtime 0.10.1 = commit `bd833a2a`) las conversiones usaban la API
**checked** de utfcpp, que **lanza** ante secuencias inválidas:

- `to_utf16()` → `utfcpp::utf8to16()` (checked).
- `to_utf8()` → `utfcpp::utf16to8()` (checked).
- `utf8_citer` = `utfcpp::iterator<…>` (checked; su `operator*` llama a `utf8::next`, que valida).

La enumeración de contenido llama, en una **completion diferida** (hilo de despacho), a
`item->set_display_name(string::to_utf16(content_entry->name()))`
(`src/kernel/xam/xam_content_aggregate.cpp:73`). Si el nombre del contenido trae bytes
inválidos, `to_utf16` lanza → la completion diferida lanza → el bucle del hilo de despacho
hace `REX_FATAL` (`src/system/kernel_state.cpp`) → cierre.

El mismo `to_utf16` se usa también en `xam_user.cpp` (perfiles/logros), `xam_ui.cpp` y
`content_manager.cpp`, así que el fallo podía dispararse por cualquier metadato con bytes
inválidos, no solo por un DLC concreto.

## El arreglo (6 cambios en `src/core/utf8.cpp`, ver `utf8_tolerant.diff`)

Las conversiones pasan a ser **tolerantes**: en vez de lanzar, reemplazan lo inválido por
`U+FFFD` (�) y siguen.

1. `#include <iterator>` (para `std::back_inserter`).
2. `utf8_citer` → `utfcpp::unchecked::iterator<…>` (su `operator*` no valida; no lanza).
3. `to_utf16()` → sanea con `utfcpp::replace_invalid(...)` (sustituye inválidos por U+FFFD)
   y luego convierte.
4. `to_utf8()` → `try` con la versión checked y `catch(...)` que cae a `utfcpp::unchecked::utf16to8`.
5. y 6. `make_citer()` (ambas sobrecargas): el iterador *unchecked* solo tiene constructor de
   1 argumento (no rastrea rango), así que se construyen con 1 arg en lugar de 3.

Efecto: un nombre con bytes inválidos se muestra con `�` en lugar de tumbar el runtime.
No cambia ABI ni exports; es un reemplazo *drop-in* del `rexruntime.dll`.

## Reconstrucción y build

`build_fix_runtime.ps1` reconstruye el árbol **0.10.1 offline** (igual que el parche de
diagnóstico: superproyecto por `git archive bd833a2a`, submódulos desde el working dir o el
object store local), aplica los 6 cambios **verificando que cada ancla aparece 1 vez**, y
compila `--target rexruntime`.

### Variante desplegada (conserva FSR)

El `rexruntime.dll` que trae el juego importa `amd_fidelityfx_dx12.dll` (escalado FidelityFX
/ FSR). Para un drop-in idéntico se compiló con **`-DREXGLUE_ENABLE_FIDELITYFX=ON`**, lo que
requiere (una vez):

- **Vulkan SDK** (presente: 1.4.363.0) y `VULKAN_SDK` apuntándolo.
- **git en el PATH** y `-DGIT_EXECUTABLE=<git>` para que `FetchContent` clone
  `github.com/rexglue/FidelityFX-SDK.git` (único acceso a red del proceso).
- Convertir el recurso `ffx-api/src/resource/ffx_api_dll.rc` de **UTF-16 LE a UTF-8**: el
  `llvm-rc` de Clang rechaza el BOM UTF-16.

El DLL resultante tiene **el mismo conjunto de imports que el original** (incluido
`amd_fidelityfx_dx12.dll`) más el arreglo de UTF-8.

> El string de versión del runtime queda `0.10.0.0-dev.unknown` (en vez de `.gbd833a2`)
> porque el árbol reconstruido no lleva los tags de git; es cosmético, no afecta ABI ni carga.

## Verificación (end-to-end en Windows)

Probado en carpeta **aislada** (copia del juego, sin tocar el build real): el juego supera el
punto donde antes caía (`__imp__XNetLogonGetTitleID`, menú de título) y corre >200 s hasta
gameplay con **cero** `Invalid UTF-8` / `FATAL` / excepciones en el log. Despliegue con
respaldo del `rexruntime.dll` original (`rexruntime.dll.bak_<stamp>`).
