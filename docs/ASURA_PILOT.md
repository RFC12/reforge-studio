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

## Cómo añadir el perfil del siguiente juego

1. Averigua su **Title ID** (lo muestra el Taller al abrir el proyecto, o en `projects.json`).
2. En `reforge/titleprofiles.py`, crea un `TitleProfile` nuevo (tema, `options` = `_common_options()` + las que
   verifiques, `adaptations`) y añádelo a `PROFILES`.
3. Nada más: `resolve()` ya lo usará para ese Title ID; el resto de juegos siguen con su perfil genérico y no se
   ven afectados. (Si una revisión concreta necesita direcciones/hooks distintos, usa `variants` con su
   `media_id`/`version`.)

Mientras no haya perfil a medida, el juego usa el **genérico utilizable** automáticamente.
