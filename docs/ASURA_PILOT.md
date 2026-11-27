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
