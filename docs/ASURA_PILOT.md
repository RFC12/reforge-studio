# Piloto de perfiles por título — Asura's Wrath

Esta versión añade la **infraestructura de perfiles**: elegir un juego produce su propia experiencia (tema,
opciones y estado), y el launcher de PC se adapta a cada título. Asura's Wrath (Title ID **43430817**) es el
primer perfil a medida.

## Qué se implementó (en el repo, con pruebas)

- **`reforge/titleprofiles.py`** — sistema de perfiles por título y variante:
  - `TitleProfile` + `OptionSpec`: cada opción declara **quién la aplica** (launcher/runtime/codegen), **cuándo**
    (al instante / al reiniciar / al recompilar) y **cómo se comprueba el valor efectivo** (`verify`). Es una sola
    definición, compartida por el launcher y el menú dentro del juego.
  - **Perfil de Asura** (tema carbón `#17120E` + cobre `#C8793C` + rojo `#7A1E12`), con sus adaptaciones
    verificadas (SEH 210/210; reintento del cierre intermitente hasta 8 veces). FPS alto y ultrapanorámica están
    **definidas pero sin verificar** → no se ofrecen como listas hasta comprobarlas.
  - **Perfil genérico utilizable** para cualquier otro juego (nombre, recursos locales, opciones generales), y
    `resolve(root)` que elige a medida por Title ID o genérico. Añadir un perfil a `PROFILES` basta para
    personalizar el siguiente juego: **ningún hook de Asura se activa para otro ejecutable** (probado).
  - `status(root)` devuelve **los dos resultados por separado**: «perfil visual» (a medida/básico, siempre
    creado) y «compatibilidad jugable» (hasta dónde llega el juego).
- **`reforge/milestones.py`** — escalera de hitos: `EXE_BUILT → RUNTIME_INIT → FIRST_TITLE_FUNC → FIRST_FRAME →
  INTERACTIVE_MENU → PLAYABLE_SCENE`. El launcher anota el hito tras cada partida (infiriéndolo del log) y el
  runtime puede escribir el suyo en `reforge_milestones.txt` junto al `.exe` (contrato al principio del archivo).
- **`reforge/launcher.py`** — el launcher resuelve el perfil al abrir, aplica su tema, muestra nombre + los dos
  estados y registra el hito jugable tras cada partida. La vista rápida conserva los controles útiles; la
  avanzada vive en «⚙ Más opciones».

## Cómo abrir el launcher de Asura's Wrath

Cualquiera de estas tres (todas acaban en el mismo launcher temático):

```powershell
# 1) Directo, desde la carpeta de ReForge instalada:
& "$env:LOCALAPPDATA\Programs\ReForge Studio\ReForgeStudio.exe" --launcher "C:\Users\roger\ReForgeProjects\asura_s_wrath"

# 2) El .bat que deja ReForge junto al .exe del juego:
& "C:\Users\roger\ReForgeProjects\asura_s_wrath\build\Jugar Asura's Wrath.bat"

# 3) Desde el Taller: abre el proyecto asura_s_wrath y pulsa «🖥 Escritorio» (crea el acceso directo) o «▶ Jugar».
```

Verás el fondo carbón con acentos cobre, el nombre del juego, **Perfil visual: a medida** y **Compatibilidad
jugable: <hito>**.

## El recorrido piloto (lo que pediste primero)

**Seleccionar Asura → abrir su launcher → cambiar un ajuste → ejecutar el binario → comprobar el efecto o
diagnosticar** ya es un recorrido completo:

1. Abre el launcher (arriba).
2. Cambia, por ejemplo, **Resolución interna** a 2× o **Pantalla completa**.
3. Pulsa **▶ JUGAR**. El launcher escribe la config del runtime, lanza el binario del Taller y lo vigila.
4. Al cerrarse, el launcher **registra el hito** alcanzado y actualiza «Compatibilidad jugable», o **diagnostica**
   el fallo (función no registrada → «Reparar ahora»; cierre intermitente → reintenta solo).

## Último hito jugable realmente comprobado (por mí, sin tu PC)

- **`EXE_BUILT` (ejecutable generado)** — el antecedente del 210/210 (enlace completo con SEH resuelto) está en el
  historial. **Lo que ocurre después del enlace** (runtime init, primer fotograma, escena jugable) depende de
  ejecutar el binario en tu PC. Al jugar desde el launcher, esos hitos se anotan solos en
  `reforge_milestones.txt` y aparecen en «Compatibilidad jugable».

## Verificar en tu PC lo que necesita el juego / la RTX

### A. Hitos después del enlace
```powershell
cd "C:\Users\roger\ReForgeProjects\asura_s_wrath"
# Ejecuta el binario del Taller con los datos del juego y guarda el log:
& ".\build\asuraswrath.exe" "--game_data_root=.\assets" *> ".\logs\asura_manual.log"
# Mira hasta dónde llegó (hitos inferidos + los que escriba el runtime):
Get-Content ".\logs\asura_manual.log" -Tail 40
Get-Content ".\build\reforge_milestones.txt" -ErrorAction SilentlyContinue
```
Busca en el log: líneas de `present`/`swapchain`/`d3d12`/`vulkan` (primer fotograma) y de tiempos de fotograma
(escena jugable). Pásame el log y te digo el primer fallo reproducible y su causa.

### B. QTE / secuencia de acción rápida (antes de ofrecer 60 FPS)
1. Juega a 60 FPS base y a la configuración del juego **la misma secuencia QTE**.
2. Comprueba: el botón mostrado = la entrada configurada; **una pulsación = una acción** (no doble); audio y
   escena en sincronía.
3. Compara la **duración de la secuencia** y la **ventana de entrada** entre ambas. Solo si no cambian, se
   habilita el FPS alto por variante (hoy `fps_mode.verified = False` en el perfil).

### C. DLSS (necesita RTX y seguir un fotograma hasta la presentación)
Sigue la [guía de NVIDIA](https://github.com/NVIDIA-RTX/Streamline/blob/main/docs/ProgrammingGuideDLSS.md).
Localiza en el backend real de Asura: **color de escena, profundidad, vectores de movimiento, jitter de cámara,
composición del HUD**. Comprueba los vectores moviendo la cámara y moviendo un personaje con la cámara fija.
- Si están todos y el equipo es compatible → se integra DLSS y se verifica que corre.
- Si falta alguno → se registra **cuál falta, en qué etapa y qué trabajo lo obtendría**, conservando una ruta de
  render funcional. En la interfaz se distinguirá **disponible / seleccionado / activo**.

## Cierre «Invalid UTF-8» al añadir la actualización (TU)

Evidencia tuya: Title ID 43430817, Media ID 11DFADD6, XEX actualizado de 0.0.0.5 → 0.0.0.6; cierres a ~34 s /
~39 s / ~31 s; `[FATAL] Dispatch thread: deferred completion threw 'Invalid UTF-8'`; y **falla al añadir la TU
`TU_11K620N_..._0000000000085`**.

### Los dos puntos exactos del código (confirmado leyendo el SDK)

1. **Quién cierra el juego (runtime):** `rexglue-sdk/src/kernel/dispatcher.cpp:333-336`. El hilo despachador
   ejecuta las *deferred completions*; si una lanza una excepción, hace
   `REXSYS_FATAL("Dispatch thread: deferred completion threw '{}'", e.what())`, que llama a `abort()`. Eso
   produce el `[FATAL]` y, cuando Windows no alcanza a volcar la línea, el **0xC0000409** (el intento 105).
2. **De dónde sale «Invalid UTF-8»:** `rexglue-sdk/include/rex/string/text.h`. La conversión UTF-8 **estricta**
   (utf8cpp `checked.h`) lanza `invalid_utf8` cuyo `what()` es exactamente «Invalid UTF-8». Nota importante:
   `ToWideString`/`ToUTF8(wstring)` del MISMO archivo son **tolerantes** (documentan «Invalid UTF-8 becomes
   U+FFFD»); el que lanza es el camino UTF-8→UTF-16 estricto. Es decir, una completion diferida convierte un
   texto del juego (muy probablemente un nombre/metadato que entra con la TU y **no** es UTF-8, p. ej. UTF-16BE
   del contenedor del contenido) con la versión estricta → excepción → FATAL.

**Atribución corregida:** ReForge decía «es una carrera interna del runtime, vuelve a abrir». Con tu evidencia es
**reproducible** (ocurre al añadir la TU), no una carrera de 1-de-2. El defecto es del **SDK** (conversión
estricta en una op diferida), no de tu recompilación: recompilar o bajar la optimización no lo arregla.

**Qué binarios carga tu `asuraswrath.exe` (verificado):** `rexruntime.dll` (marca 0.10.0.24),
`rexgpu-xenos.dll`, `amd_fidelityfx_dx12.dll` → confirman la variante **-fsr** del SDK que CMake encontró
(0.10.0.24-dev.gbd833a2-fsr). Coincide.

**El supervisor de ReForge SÍ cierra el proceso** al ver `[FATAL]` (`game.launch_and_watch` →
`_kill_tree`). Por eso el código de salida tras un `[FATAL]` es del cierre forzado, no del juego. Esto ya se
registra (`killed`) y cambia la interpretación del código de salida, como pediste.

### Lo que corregí en ReForge (verificado con pruebas)

- Un cierre con `[FATAL]` **ya no se clasifica como `clean`** (antes `[FATAL]` no estaba en `RUNTIME_BAD_RE`, solo
  `[critical]`/`[error]`, y si el log traía además una línea de cierre pasaba por éxito → ✔/★). El `[FATAL]`
  manda siempre.
- El paso «Probar el juego» **figura como ✖** cuando el juego falla, conserva el **primer error** de la sesión y
  distingue los **tres casos**: «el juego terminó», «el supervisor cerró el proceso» y «causa pendiente de
  confirmar» (0xC0000409 sin `[FATAL]`, como el intento 105, que se mantiene **aparte**).
- Prueba de regresión `tests/test_crash_signatures.py` con las firmas de los intentos **104, 105 y 106**.
- La partida «lanzada fuera del Taller» (resumen de FPS) queda separada: ReForge solo clasifica los intentos que
  vigila.

### Lo que falta reproducir en TU PC (necesito esto)

El campo exacto y la operación diferida que lanza requieren símbolos + la propia TU. Corre **un solo intento**
(sin reintentos) con este bloque, que **conserva tus partidas** y reúne el log:

```powershell
# --- Diagnóstico de UN intento de Asura's Wrath (no toca tus guardados) ---
$proj = "C:\Users\roger\ReForgeProjects\asura_s_wrath"
$exe  = Join-Path $proj "build\asuraswrath.exe"
$out  = Join-Path $proj ("diag_asura_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
New-Item -ItemType Directory -Force -Path $out | Out-Null
$before = Get-ChildItem (Join-Path $proj "build\logs\*.log") -ErrorAction SilentlyContinue | Select -Expand FullName
# Arranque directo (mismo .exe, directorio y datos; SIN el supervisor de ReForge, así no hay reintentos):
$p = Start-Process -FilePath $exe -ArgumentList '--game_data_root=.\assets' -WorkingDirectory (Join-Path $proj "build") -PassThru
$p.WaitForExit()
"PID=$($p.Id)  exit=0x{0:X8}  hora={1}" -f $p.ExitCode, (Get-Date) | Tee-Object (Join-Path $out "resultado.txt")
# El log nuevo de ESTE intento:
$after = Get-ChildItem (Join-Path $proj "build\logs\*.log") | Sort LastWriteTime -desc | Select -First 1
Copy-Item $after.FullName (Join-Path $out "asura_diag.log")
Select-String -Path $after.FullName -Pattern 'FATAL|Invalid UTF-8|deferred completion|present|swapchain|\[render\]' |
  Select -Last 40 | ForEach-Object { $_.Line } | Tee-Object (Join-Path $out "resumen.txt")
"Carpeta a devolverme: $out"
```

**Devuélveme la carpeta `diag_asura_*`** (tiene `asura_diag.log`, `resultado.txt` y `resumen.txt`). Con el
código de salida y las líneas alrededor del `[FATAL]` confirmo si cayó **antes del código del juego**, **al
preparar el renderer** o **después de presentar una imagen**, y preparo el parche del SDK en la frontera correcta
(decodificar el campo con su codificación real o, como hace Xenia/`ToWideString`, con U+FFFD en el nombre de
presentación — nunca sustituyendo texto del juego a ciegas). **Prueba clave:** quita la TU y arranca; si deja de
cerrarse, confirma que el disparador es un texto no-UTF-8 que entra con la TU.

## Cierre UTF-8 en una operación diferida — avance con los logs (121 y 123–125)

> Nota: el evento visible justo antes del fatal **cambia** entre ejecuciones (en el 121 fue `XamContentCreateEnumerator`;
> en 123/124/125 fue `XNetLogonGetTitleID`), y siempre cae en un hilo distinto del que lanza. Es decir, **no
> identifica la operación**. El campo y el origen están **pendientes** hasta tener la pila (ver más abajo).

Leí tu `build\logs\asuraswrath_121.log` completo (18 914 líneas). La secuencia exacta del fatal:

```
23:40:35.928 [krnl] XamContentCreateEnumerator: added 5 items to enumerator
23:40:35.928 [sys]  CompleteOverlappedDeferredEx: queuing for overlapped 41F0FF50
23:40:36.028 [sys]  Deferred overlapped 41F0FF50: completing with result 00000000   (1ª completion OK)
23:40:36.060 [sys]  CompleteOverlappedDeferredEx: queuing for overlapped 41F0FF50   (se reencola)
23:40:36.160 [sys]  Deferred overlapped 41F0FF50: running completion
23:40:36.160 [critical] [FATAL] Dispatch thread: deferred completion threw 'Invalid UTF-8'
```

- **Operación (confirmada):** una *deferred completion* de la **enumeración de contenido** (`XamContentCreateEnumerator`,
  5 ítems: TU/DLC/guardados del Title ID). Ocurrió **a los ~45 s**, ya pasada la ventana de vigilancia — por eso
  el Taller había dicho «arrancó» (ver el arreglo del seguimiento abajo).
- **Por qué el log pierde la operación:** `rexglue-sdk/src/kernel/dispatcher.cpp:331` saca un `fn()` sin nombre de
  la cola y, al lanzar, hace `REXSYS_FATAL("…threw '{}'", e.what())`. Solo queda `e.what()` = «Invalid UTF-8».
- **De dónde NO sale:** la conversión propia del SDK (`ToUTF16`/`DecodeUTF8` en `src/base/utf8.cpp` +
  `utf8_codec.h`) ya es **tolerante** (sustituye el byte inválido por U+FFFD, **no** lanza). Tampoco hay uso
  directo de `utf8::` en el SDK. Es decir, «Invalid UTF-8» viene de una **validación estricta de una librería**
  (toml++/utfcpp, que sí lanzan ese texto) al **leer un archivo o campo** del contenido durante la enumeración.
  Pinchar el campo exacto necesita la **pila del lanzamiento**, que el log no guarda.

**¿Qué archivo seleccionó ReForge? (verificado con hashes en tu PC):**
- Paquete TU adjunto: 626 688 bytes · SHA-256 `43914d51…`.
- `default.xexp` que ReForge **extrajo y aplicó** (en `assets\` y `update\`): **573 440 bytes** ·
  SHA-256 `918cdee90389f27dee0bfe1bdfd758bc52cc4148666dcae1e35a1c0297f2005c`. Es el XEX-patch **interno** del
  contenedor TU, no el contenedor. (La discrepancia `0.0.0.6` del 117 vs `0.0.1.5` del 121 es del generador
  —módulo cacheado vs 414 archivos regenerados— y queda para la traza del generador.)
- **Binarios que carga el proceso:** `rexruntime.dll` (0.10.0.24), `rexgpu-xenos.dll`, `amd_fidelityfx_dx12.dll`
  → variante **-fsr**.

### Opción preferida: runtime de diagnóstico instrumentado (identifica quién encola)

Como el log pierde la operación (el despachador ejecuta un `fn()` sin nombre), la vía más directa es un
`rexruntime.dll` **instrumentado**: asigna un **id único** a cada tarea diferida y registra, a nivel WARN,
`enqueue id/ra/overlapped`, `run id`, `done id/result`, y el **id de la tarea activa en el fatal**. Así se
distinguen dos tareas que reutilizan la misma dirección `overlapped` (como las dos sobre `41F0FF50` del 121) y se
sabe **quién encoló** la que lanza (`ra` = dirección de retorno del llamador, se simboliza con el `.map`).

- Parche y pasos: `docs/patches/dispatcher_trace/README.md`.
- Un solo comando que aplica el parche, compila el runtime con símbolos, lo pone en una carpeta aparte (sin tocar
  tu instalación/TU/partidas), hace **un intento** y arma el ZIP: `docs/patches/dispatcher_trace/build_diag_runtime.ps1`.
- El **mecanismo de atribución ya está probado** en ReForge: `tests/test_deferred_trace.py` reproduce las dos
  tareas sobre la misma dirección (una termina, otra lanza) y comprueba que se culpa a la segunda. Y ReForge lee
  esa traza automáticamente: cuando el cierre venga de un runtime instrumentado, el Taller mostrará
  «▶ Runtime instrumentado: Tarea diferida #N (encolada desde ra=…) lanzó «Invalid UTF-8»…».

**Devuélveme el `diag_asura_*.zip`** que genera ese script (trae `task_trace.txt` con las líneas `[deferred]`,
`modules.txt` con las bases para simbolizar el `ra`, el hash de la DLL y el log del intento). Con eso simbolizo el
`ra`, nombro la función que encola y corrijo esa frontera con una prueba de regresión.

### Alternativa SIN recompilar (first-chance con cdb)

Esto detiene la ejecución **cuando se lanza** la excepción C++ (antes de que el despachador la convierta en un
fatal genérico) y vuelca la pila real. Necesita las *Debugging Tools for Windows* (cdb). Un solo intento, no toca
guardados:

```powershell
# --- Captura first-chance de UN intento (no toca tus guardados) ---
$proj = "C:\Users\roger\ReForgeProjects\asura_s_wrath"
$exe  = Join-Path $proj "build\asuraswrath.exe"
$cdb  = "C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe"
$out  = Join-Path $proj ("diag_asura_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
New-Item -ItemType Directory -Force -Path $out | Out-Null
# Hashes y versiones (sin incluir juego/TU/guardados):
Get-FileHash $exe -Algorithm SHA256 | Tee-Object (Join-Path $out "exe.sha256.txt")
Get-FileHash (Join-Path $proj "build\rexruntime.dll") -Algorithm SHA256 | Tee-Object (Join-Path $out "runtime.sha256.txt")
if (Test-Path $cdb) {
  # Rompe en la 1ª excepción C++ (0xE06D7363), imprime pila y los 32 bytes del dato, y sigue hasta el fatal:
  & $cdb -g -G -c "sxe -c `"kc 40; .echo ---; db @rdx L20; gN`" e06d7363; g; q" `
        -o $exe "--game_data_root=$proj\assets" *> (Join-Path $out "cdb.txt")
} else {
  "cdb no encontrado; ejecución directa (sin pila). Instala Debugging Tools for Windows para la pila." |
    Tee-Object (Join-Path $out "cdb.txt")
  Push-Location (Join-Path $proj "build"); $p = Start-Process $exe -ArgumentList "--game_data_root=$proj\assets" -PassThru; $p.WaitForExit(); Pop-Location
}
# El log de ESTA sesión:
$log = Get-ChildItem (Join-Path $proj "build\logs\*.log") | Sort LastWriteTime -desc | Select -First 1
Copy-Item $log.FullName (Join-Path $out "session.log")
Select-String $log.FullName -Pattern 'XamContent|overlapped|Invalid UTF-8|deferred completion|\[render\]|present' |
  Select -Last 60 | % { $_.Line } | Tee-Object (Join-Path $out "resumen.txt")
Compress-Archive -Path "$out\*" -DestinationPath "$out.zip" -Force
"Devuélveme: $out.zip   (contiene cdb.txt con la pila, session.log y los hashes; sin juego, TU ni guardados)"
```

**Devuélveme `diag_asura_*.zip`.** Con la pila de `cdb.txt` veré qué función de contenido y qué archivo/campo
dispara la validación, y corrijo esa frontera (decodificar con la codificación real del campo o, como ya hace el
propio SDK en otras rutas, con U+FFFD — sin tocar nombres/rutas/texto válidos). Si prefieres no instalar cdb,
mándame directamente `build\logs\asuraswrath_121.log`: ya lo tengo leído, pero con uno nuevo tras un arranque
limpio confirmo que la secuencia es idéntica.

### Intentos 123/124/125 — leídos completos (actualización)

Los tres llegaron al **menú del título jugando a 30 FPS** (cargando `D:\BCGame\Movies\…`, `TitleMenu_Bg00`) y
cerraron con el mismo fatal UTF-8. La secuencia **común** en los tres, ~1–1,5 s antes del fatal:

```
… [ReForge] FPS 30 …
[krnl] [tXXXXX] __imp__XNetLogonGetTitleID STUB          ← Xbox LIVE (logon), en un hilo de kernel
[core] [tYYYYY] [ReForge] Guardián: imagen normal con readback_resolve=full
[critical] [core] [tZZZZZ] [FATAL] Dispatch thread: deferred completion threw 'Invalid UTF-8'   ← otro hilo
```

- En el **121** el evento visible anterior era `XamContentCreateEnumerator`; en **123/124/125** es
  `__imp__XNetLogonGetTitleID` (Live). **Conclusión honesta:** el evento visible anterior cae en un **hilo
  distinto** del hilo del despachador que lanza, así que **no prueba** quién encoló la tarea. Mi resumen anterior
  atribuía «XamContent/nombre de contenido» por arrastre del 121 — era una suposición. Corregido: la interfaz
  ahora muestra un **único** mensaje, «Excepción `Invalid UTF-8` en una operación diferida. Campo y origen
  pendientes de identificar», y la línea fatal se muestra **una sola vez** por sesión (los tres intentos siguen
  contando como tres fallos independientes).
- No aparece `ResolvePath(UPDATE:\)` ni `XamContent` en la ventana de 123/124/125 (sí en el 121). El denominador
  común es: **una completion diferida en el hilo del despachador, cerca del logon de Live, tras llegar al menú**.

### Lo que ya está descartado (verificado en tu PC)

Tu `reforge_game.json` tiene **`live_offline: true`** — Xbox Live simulado ya está DESACTIVADO — y aun así el
juego llama a `__imp__XNetLogonGetTitleID` (un stub que solo escribe en el log) y cierra con el UTF-8. Por tanto
el logon de Live **no es la causa**: ese `XNetLogon` es ruido en otro hilo, no el que encola la tarea que lanza.
El origen real sigue **sin identificar** y por eso necesito la **pila del lanzamiento** (el bloque `cdb` de
arriba), que es lo único que señala la función y el dato exactos sin suponer.

### Arreglo del falso éxito (ya en el código, con prueba)

Tu intento 121 arrancó, el Taller dijo «arrancó correctamente / Proceso completado», y **38 s después** llegó el
fatal. Corregido:
- A los 45 s con el proceso vivo, el Taller muestra **«▶ En ejecución · seguimiento activo»** (no «Proceso
  completado»). La sesión queda atada a su PID.
- Si llega un fatal más tarde, se actualiza **esa misma sesión como fallida**, conservando por separado el caso,
  el primer error, el código de salida y si **intervino el supervisor**.
- Regresión `tests/test_session_tracking.py`: proceso que supera el umbral y falla después, cierre limpio, y un
  segundo arranque con su propio log.

## Capturas del launcher (piloto)

Vista rápida y avanzada, mismas opciones (una sola definición), navegables con mando/teclado/ratón, con foco
visible y ayuda por opción: `docs/img/launcher_asura_rapida.png` y `docs/img/launcher_asura_avanzada.png`.

## Cómo añadir el perfil del siguiente juego

1. Averigua su **Title ID** (lo muestra el Taller al abrir el proyecto, o en `projects.json`).
2. En `reforge/titleprofiles.py`, crea un `TitleProfile` nuevo (tema, `options` = `_common_options()` + las que
   verifiques, `adaptations`) y añádelo a `PROFILES`.
3. Nada más: `resolve()` ya lo usará para ese Title ID; el resto de juegos siguen con su perfil genérico y no se
   ven afectados. (Si una revisión concreta necesita direcciones/hooks distintos, usa `variants` con su
   `media_id`/`version`.)

Mientras no haya perfil a medida, el juego usa el **genérico utilizable** automáticamente.
