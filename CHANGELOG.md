# Historial de versiones — ReForge Studio

> El README muestra solo lo esencial. Aquí está el detalle de cada versión.

## 1.55.0 — Asura: diagnóstico del cierre UTF-8 unificado y honesto (sin atribuir el campo sin la pila)

- **Un solo mensaje para el cierre UTF-8** (`game.UTF8_DEFERRED_MSG`): «Excepción `Invalid UTF-8` en una
  operación diferida. Campo y origen pendientes de identificar.» Se elimina la atribución inconsistente (antes la
  ruta temprana decía «XamContent/nombre de contenido» y otras «nombres de la TU») — eran suposiciones: leído el
  log, el evento visible antes del fatal **cambia** entre ejecuciones (121 → `XamContentCreateEnumerator`;
  123/124/125 → `XNetLogonGetTitleID`) y siempre cae en un **hilo distinto** del que lanza, así que no identifica
  la operación. Mismo mensaje en el Taller, el seguimiento tardío y el diagnóstico de reintentos.
- **La línea `[FATAL]` se muestra una sola vez** por sesión: casa con `RUNTIME_FATAL_RE` y con `RUNTIME_BAD_RE`
  (`[critical]`), así que se deduplica en `analyze_runtime_log`. Los tres intentos siguen contando como **tres
  fallos independientes**.
- **Investigación con los logs reales (123/124/125, vía puente):** los tres llegan al **menú del título a 30 FPS**
  y cierran igual; verificado que `live_offline` ya está en `true` (Live simulado OFF) y aun así ocurre, de modo
  que el logon de Live **queda descartado** como causa. El origen real necesita la **pila del lanzamiento**.
- **Guía** (`docs/ASURA_PILOT.md`): secuencia común de los tres intentos, lo descartado, y la captura
  **first-chance (cdb)** de un solo intento (sin recompilar, sin supervisor, conservando TU y guardados) con el
  ZIP a devolver. Regresión ampliada en `tests/test_crash_signatures.py` (dedup + mensaje unificado). Suite 69/69.

## 1.54.0 — Asura: fin del falso éxito (fatal tardío) y avance de la causa del cierre UTF-8

- **Fin del falso éxito del Taller.** Si el juego sigue abierto pasada la ventana de vigilancia (p. ej. a los
  45 s), el resumen ya **no** dice «Proceso completado»: muestra **«▶ En ejecución · seguimiento activo»** y la
  sesión queda atada a su PID. Si llega un `[FATAL]` más tarde (como el UTF-8 a los ~45 s del intento 121), se
  actualiza **esa misma sesión como fallida**, conservando por separado el **caso**, el **primer error**, el
  **código de salida** y si **intervino el supervisor**. (`runner.on_complete_text`, `WorkshopPage._completion_text`,
  `post_session`.)
- **Regresión independiente del juego** (`tests/test_session_tracking.py`): proceso que supera el umbral y falla
  después, cierre limpio, y un segundo arranque con su propio log.
- **Causa del cierre UTF-8 — avance con el log real.** Leído `asuraswrath_121.log`: el fatal es una *deferred
  completion* de la **enumeración de contenido** (`XamContentCreateEnumerator`, 5 ítems), a los ~45 s. El log
  pierde la operación porque `dispatcher.cpp` ejecuta un `fn()` sin nombre y solo guarda `e.what()`. La conversión
  propia del SDK (`ToUTF16`/`DecodeUTF8`) ya es **tolerante** (U+FFFD), así que «Invalid UTF-8» viene de una
  validación estricta de librería (toml++/utfcpp) al leer un archivo/campo del contenido. Verificado además que
  el `default.xexp` aplicado (573 440 B, `918cdee9…`) es el XEX-patch **interno** del contenedor TU (626 688 B,
  `43914d51…`), y que el proceso carga la variante **-fsr**.
- **Diagnóstico sin recompilar** (`docs/ASURA_PILOT.md`): bloque PowerShell de **un solo intento** con captura
  **first-chance** (cdb) que vuelca la pila y los bytes cuando se lanza la excepción, y arma un ZIP (sin juego, TU
  ni guardados) a devolver. Suite **69/69**.

## 1.53.0 — Piloto de Asura's Wrath: hitos desde el runtime, dos vistas, y arreglo del cierre «Invalid UTF-8»

- **Hitos sin falsos positivos, con intentos y evidencia** (`reforge/milestones.py`). `Vulkan initialization
  failed`, `swapchain creation failed` o `stutter monitoring enabled` ya **no** confirman un fotograma ni una
  escena (filtro consciente de fallos; la escena jugable exige tiempos de fotograma reales, no la palabra
  «stutter»). Se separan **última sesión**, **cada intento** (con su primer error) y **mejor histórico**, cada
  hito con su **evidencia**. Dimensiones **presentadas** leídas del runtime (`[render] presented WxH`).
- **Instrumentación C++ del ejecutable** (`ext_cpp.py`/`ext11.py`): el overlay escribe al log `RUNTIME_INIT`,
  `FIRST_TITLE_FUNC` y `FIRST_FRAME` (si el overlay se dibuja, el juego presentó una imagen) y `INTERACTIVE_MENU`
  al abrir el menú; el launcher muestra **cuál fue la evidencia**. Para escena jugable, validación manual
  identificada como tal.
- **Dos vistas del launcher desde UNA definición de opciones** (`reforge/launcher_views.py`): rápida y avanzada
  (Juego/Pantalla/Gráficos/Audio/Controles), navegables con mando/teclado/ratón, **foco visible**, **ayuda por
  opción** (con quién la aplica, cuándo y cómo se comprueba), y se conserva la selección al alternar. Capturas
  reales en `docs/img/`.
- **Huella del XEX + adaptaciones por variante** (`titleprofiles.py`): dos revisiones con el mismo Title ID
  comparten **tema** pero cada una recibe solo **sus** adaptaciones compatibles (probado).
- **Ajuste de resolución y persistencia**: salida vs render interno modelados; los ajustes se cargan por la ruta
  del proyecto y la config del runtime vive junto al `.exe` (ruta absoluta), así que **abrir el `.exe` desde otro
  directorio conserva ajustes y datos** (probado).
- **Triaje de pantalla negra**: «antes del código del juego» / «al preparar el renderer» / «después de presentar
  una imagen».
- **Cierre «Invalid UTF-8» al añadir la TU — etiquetado corregido.** Un `[FATAL]` ya **no** se clasifica como
  `clean` (antes `[FATAL]` no estaba en `RUNTIME_BAD_RE`): el paso «Probar el juego» **figura como ✖**, conserva
  el **primer error** y distingue **el juego terminó / el supervisor cerró el proceso / causa pendiente de
  confirmar** (0xC0000409 sin `[FATAL]`, mantenido aparte). Se corrige la atribución: no es «una carrera benigna,
  vuelve a abrir», es reproducible y del runtime/SDK (localizado en `dispatcher.cpp:334` + la conversión UTF-8
  estricta de `string/text.h`). Regresión `tests/test_crash_signatures.py` con las firmas 104/105/106.
- Guía `docs/ASURA_PILOT.md`: causa confirmada, binarios que carga el `.exe` (variante -fsr), y un bloque
  PowerShell de **un solo intento** que conserva guardados y reúne el log a devolver. Suite **68/68**.

## 1.52.0 — Perfiles por título: cada juego con su launcher, opciones y estado (piloto: Asura's Wrath)

- **Elegir un juego produce su propia experiencia.** Nueva infraestructura `reforge/titleprofiles.py`: un
  **perfil por título (y variante)** define el **tema** visual, las **opciones** disponibles y las
  **adaptaciones** verificadas. Cada opción declara **quién la aplica** (launcher/runtime/codegen), **cuándo**
  (al instante / al reiniciar / al recompilar) y **cómo se comprueba el valor efectivo** — una sola definición
  compartida por el launcher y el menú del juego. Se resuelve por **Title ID**, y las revisiones por la huella
  del XEX (`media_id`/`version`).
- **Asura's Wrath** (Title ID `43430817`) es el **primer perfil a medida**: launcher con fondo **carbón** y
  acentos **cobre/rojo**, sus adaptaciones (SEH 210/210; reintento del cierre intermitente hasta 8 veces), y las
  mejoras de **FPS alto** y **ultrapanorámica** definidas pero **sin verificar** (no se ofrecen como listas hasta
  comprobar QTE, cámara/HUD/vídeos).
- **Perfil genérico utilizable** para cualquier otro juego (nombre, recursos locales, opciones generales). Añadir
  un perfil a `PROFILES` basta para personalizar el siguiente juego, **sin que ningún hook de Asura se active
  para otro ejecutable** (probado). Se muestran **dos estados por separado**: «perfil visual» (a medida/básico,
  siempre creado) y «compatibilidad jugable».
- **Hitos del juego** (`reforge/milestones.py`): escalera `ejecutable generado → runtime iniciado → primera
  función del título → primer fotograma → menú interactivo → escena jugable`. El launcher **anota el hito** tras
  cada partida (lo infiere del log) y muestra «Compatibilidad jugable»; el runtime puede escribir el suyo en
  `reforge_milestones.txt` junto al `.exe`.
- **Launcher conectado al perfil** (`reforge/launcher.py`): resuelve el perfil al abrir, aplica su tema, muestra
  nombre + los dos estados y registra el hito jugable. «Ports de la comunidad» se mantiene como puente a los
  runtimes originales.
- Guía del piloto en `docs/ASURA_PILOT.md` (cómo abrir el launcher de Asura, verificar hitos/QTE/DLSS en tu PC
  con comandos exactos, y añadir el perfil del siguiente juego). Suite 66/66.

## 1.51.3 — Botón «Cancelar compilación» a mano, y «Ports de la comunidad» como puente simple

- **Cancelar compilación siempre visible.** El botón de cancelar vivía en el formulario de la izquierda, que en
  ventana estrecha —o cuando la recompilación la pide el lanzador del juego («Reparación pedida desde el
  lanzador»)— queda fuera de vista. Ahora hay un **«■ Cancelar compilación» junto al log**, visible y activo solo
  mientras se compila (oculta «▶ Jugar» para no estorbar). Detiene de verdad: mata el árbol de procesos del
  codegen/compilación en curso.
- **«Ports de la comunidad» es ahora un puente, sin complicaciones.** Pediste que ReForge solo haga de puente:
  - **➕ Agregar puerto desde GitHub…** — pega la URL del repo (y, opcional, su Title ID) y queda en la lista.
  - **📂 Elegir runtime…** — apunta a su .exe o lanzador **original** (el que deja su autor/instalador).
  - **▶ Abrir runtime original** — lo abre **tal cual**, sin que ReForge le añada nada; cada puerto usa su propio
    runtime, su propio menú (en Forza/Pinyon Shift, **Back + Start**) y sus propios logros (del mismo juego,
    mismo Title ID).
  - **🗑** quita de la lista los puertos que agregaste. Crash y Forza siguen preconfigurados.
  Se retiran del apartado las acciones que intentaban recompilar/renombrar/envolver: no eran necesarias para un
  puente y complicaban el flujo.
- Suite 64/64.

## 1.51.1 — Arreglo: «Jugar» un puerto lanzaba el .exe sin `--game_data_root` (Forza se cerraba)

- **Causa del cierre de Forza Horizon.** El botón «Jugar» ejecutaba `Horizon.exe` **pelado**, y su runtime
  (ReXGlue/ShiftGlue) **exige** `--game_data_root`; por eso salía *«--game_data_root was not provided»* y el
  juego se cerraba sobre una pantalla negra. Ahora «Jugar» usa el **lanzador que ReForge ya genera**
  (`Jugar <Nombre>.bat`), que lleva `--game_data_root=…\<proyecto>\assets`, el reintento automático y el puente
  con ReForge. Si aún no existe el lanzador, ReForge arma el `--game_data_root` desde el proyecto del juego con
  el mismo Title ID; si no encuentra ese proyecto, lo avisa en vez de lanzar algo que se cerrará.
- **El menú del juego en estos puertos no es el Guía de ReForge.** Cada puerto trae su PROPIO menú. En Forza
  (Pinyon Shift) se abre con el mando manteniendo **BACK + START** a la vez (Select+Start; en PlayStation,
  Share/Create + Options) y ya incluye **Perfil, Logros (del propio juego, mismo Title ID), Trucos, Gráficos y
  copias de guardado**. ReForge ahora lo dice en la tarjeta del puerto y al lanzarlo, para que sepas dónde ver
  tus logros. (ReForge no puede inyectar su overlay en un .exe de terceros ya compilado; el puente real es:
  lanzarlo bien, mostrarlo en la Biblioteca con su carátula y aplicar tu TU de idioma.)
- Suite 64/64.

## 1.51.0 — Puertos: instalación/detección interna, logros y español; autoreinicio; logros 0.11 como 0.10

- **Instalar el puerto desde ReForge.** «⬇ Instalar en ReForge» clona el puerto, copia tu `default.xex` desde
  el proyecto del juego y lanza su propio instalador/compilación (su toolchain hace el trabajo pesado; ReForge
  lo orquesta). Si el puerto no trae un instalador ejecutable, enseña el plan y su página de releases en vez de
  fingir éxito.
- **«🔍 Buscar juego ya instalado».** Si lo instalaste a mano, ReForge lo detecta en las carpetas de salida
  conocidas (p. ej. `C:\ReForgeBuild\pinyon-shift\out\build\win-amd64-release`), lo recuerda, lo renombra y lo
  conecta. También puedes **«Elegir .exe construido…»** para una ruta cualquiera; ReForge la recuerda para
  «Jugar».
- **Renombrado al nombre bonito.** «✏ Renombrar» deja `pinyon_shift.exe` como **`Horizon.exe`** (y Crash como
  `Crash of the Titans.exe`). El icono va embebido en el .exe, así que sobrevive al renombrado; en la Biblioteca
  aparece con la **carátula real** del juego (misma del XEX, mismo Title ID).
- **Conexión de tu perfil y logros.** Al jugar un puerto, ReForge deja junto a su .exe la MISMA identidad que
  usa en sus juegos recompilados (`reforge_ext.ini` + sidecars del perfil: Gamertag, idioma, color de acento,
  sonido y notificación de logros). Como estos puertos son de la familia rexglue, su runtime la lee y muestra
  tus logros con tu perfil. La base de datos de logros/saltos/código es la del juego de Xbox 360 (mismo Title
  ID): ReForge no inventa definiciones, solo aporta la identidad y lee el progreso guardado si existe.
- **Español latino a Forza Horizon.** «🌐 Español latino (TU/GOD)» aplica tu actualización de título (p. ej.
  `FHL-DLC-TU-GOD`) al proyecto del juego; al reconstruir el puerto desde esos assets, Horizon sale en español
  latino.
- **ReForge se reabre solo tras actualizar.** La actualización automática ahora pasa `--relaunch` al instalador,
  que vuelve a abrir ReForge al terminar: ya no hay que abrirlo a mano para ver la versión nueva (se puede
  desactivar con `auto_relaunch`).
- **Menú Guía del SDK 0.11 con la vista de logros cómoda de 0.10.** La pestaña Logros gana barra de progreso,
  panel de detalle con los puntos y la fecha del logro elegido, y trato de **logros secretos/bloqueados**
  (candado y «se revela al conseguirlo»), igual que la Guía de 0.10. *(Requiere reconstruir el juego 0.11 para
  verlo.)*
- Suite 64/64 (tests nuevos: conexión de perfil/logros de puertos y autoreinicio tras actualizar).

## 1.50.0 — Gestor de puertos de la comunidad con las comodidades de ReForge

- **Nuevo: «Ports de la comunidad»** (tile en Inicio). Lista los puertos nativos hechos por otros autores (con
  su propio runtime), con su estado, y permite **obtenerlos, elegir el .exe ya construido y jugarlos envueltos
  con las comodidades de ReForge**: lanzador temático, icono del juego y entrada en la Biblioteca. Registrados:
  **Crash of the Titans** (VitoMiguelF) y **Forza Horizon — Pinyon Shift** (arcanite24).
- **Honesto sobre el build:** cada puerto trae su PROPIO toolchain e instalador (descargas grandes, compilación
  de minutos), que recompila el juego desde TU copia legal. ReForge **orquesta y envuelve** el resultado; no
  recompila el puerto por dentro ni incluye ningún archivo de juego. «Obtener» abre su página de releases;
  «Elegir .exe construido» apunta al ejecutable que deja su instalador, y ReForge le pone sus comodidades.
- Núcleo probado (detección del .exe del juego ignorando herramientas del toolchain, envoltura con
  lanzador/icono/Biblioteca, lanzamiento). Suite 62/62.

## 1.49.0 — Precisión de punto flotante de ShiftGlue y base de puertos de la comunidad

- **Mejora extraída de Pinyon Shift / ShiftGlue (beneficia a TODOS los juegos):** el código recompilado ahora
  se compila con **`-ffp-contract=off`**, que evita que clang fusione `a*b+c` en una instrucción FMA. Esa fusión
  cambia el resultado respecto al Xbox 360; desactivarla hace que el **punto flotante coincida con el original**,
  así física, animaciones y render salen más fieles. Va activado siempre y prácticamente no cuesta rendimiento.
- **Niveles de CPU al compilar** (⚡ Optimizar): además de «solo para este PC» (`-march=native`), ahora hay
  **«CPU moderna» (x86-64-v3 + AVX2/FMA)** — más rápido que el modo compatible y portable a cualquier PC de ~2015
  en adelante. La opción antigua sigue funcionando.
- **Base del gestor de puertos de la comunidad** (`communityports.py`): registro de puertos nativos de otros
  autores (con su propio runtime), buscables por Title ID. Registrados: **Crash of the Titans** (VitoMiguelF,
  motor XenonRecomp) y **Forza Horizon — Pinyon Shift** (arcanite24, motor ShiftGlue). Primer paso del gestor
  completo; ningún archivo de juego se incluye.
- Motores internos nuevos (probados): actualización reversible al SDK más nuevo y conversor de datos de
  recompilación de puertos de la familia XenonRecomp al formato de rexglue.

## 1.48.15 — Estabilidad: recompilar vuelve a funcionar (SEH) y el mando ya no falla (Numpad)

- **Arreglo crítico de recompilación (SEH):** desde hace unas versiones, recompilar cualquier juego con
  manejadores de excepciones (p. ej. Asura's Wrath) fallaba con «use of undeclared identifier 'SEH_TRY'». Causa:
  el encabezado `reforge_seh.h` había dejado de incluir `<rex/platform/exceptions.h>` del SDK (ahí se definen
  `SEH_TRY`/`SEH_CATCH`/`SEH_END`). Ahora se incluye de nuevo, protegido con `__has_include` para que siga
  funcionando aunque una versión del SDK mueva ese encabezado. Verificado: Asura's Wrath recompila entero
  (210/210) sin errores.
- **Mando / controles (Numpad):** las plantillas de teclado-y-ratón usaban nombres de tecla `Keypad4/6/8/2` que
  el runtime no reconoce («no key named 'Keypad4'»), así que el stick derecho mapeado al teclado numérico no
  respondía. El nombre correcto del SDK es `Numpad4…`; corregido en todas las plantillas.
- Pruebas internas al día (iconos y relanzamiento) y suite completa en verde (57/57).

## 1.48.14 — ReForge ya no declara funciones que caen a mitad de otra (Crash of the Titans)

- **Causa encontrada en Crash of the Titans.** Cuando rexglue avisaba de un salto que no podía resolver
  («Unresolved b target 0x…»), el arreglo automático declaraba el destino como función. Si ese destino es una
  **cola compartida** de otra función —en este juego, 0x823E8D70 salta a 0x823E9C10, que está dentro de
  0x823E9C04—, el código generado empieza a mitad de la función, sin su prólogo, y el juego moría en el
  primer fotograma con «unhandled title read of 0x701A0000» (leía con la pila sin montar). Ahora esas
  direcciones se reconocen por un dato exacto: su valor aparece en el código generado como regreso de una
  llamada (`ctx.lr = 0x…`). No se declaran, quedan anotadas en `reforge_not_functions.txt` y, si ya estaban,
  se quitan antes de recompilar.
- **Base de datos de problemas:** entrada nueva «El juego salta a la cola de otra función» (reconoce el aviso
  `Unresolved call from … to …` y el `SEH exception caught in …` + `unhandled title read`), con su remedio
  automático y la explicación de por qué declararla empeora el fallo.
- Prueba nueva `tests/test_midfunc.py`.
- **Estado de Crash of the Titans:** al declararlo bien, el juego ya no se cae en la función mal partida, pero
  sigue parándose en el primer milisegundo dentro de su propio código: usa la pila con `r1 = 0x701A0010` y la
  página `0x701A0000` no está mapeada («unhandled title read of 0x701A0008»). Es la colocación de la pila del
  hilo principal del runtime, no el código recompilado (se comprobó también sin manejadores SEH: mismo fallo).
  ReForge lo reconoce en el log y lo explica; necesita arreglo en rexglue.

## 1.48.13 — LB/RB dejan de ir acelerados y el menú Guía de 0.11 usa la imagen de jugador del perfil

- **LB/RB ya no saltan varias pestañas de golpe.** El estado del pad es un nivel (lo que está pulsado), no un
evento, y se estaba sumando en cada fotograma mientras el botón seguía pulsado: las pestañas cambiaban sin
control. Ahora solo cuenta el flanco (lo que acaba de pulsarse) y además hay 250 ms de espera entre cambio y
cambio, aunque el botón repita o llegue por las dos vías (ImGui y el pad).
- **La imagen de jugador del perfil llega al menú.** ReForge escribe en `reforge_ext.ini` la figura y los
colores de «Perfil → Imagen de jugador» (`avatar_style`, `avatar_fg`, `avatar_bg`) y el menú de 0.11 dibuja la
misma imagen (hexágono, rayo, estrella, diana, rombo, onda, mando o corona) con sus colores; con una foto
propia, como el 0.11 no da texturas al proyecto, se queda el trofeo sobre el color de acento, igual que hacía
0.10 cuando no había avatar.
- **Texto de ayuda sin solaparse** en las pestañas del menú (se dibujaba en dos líneas encima de sí mismo).

## 1.48.12 — El .exe de los juegos del SDK 0.11 arranca sin el .bat, y los manejadores de excepciones compilan

- **El ejecutable del juego arranca con doble clic.** En los proyectos del SDK 0.11 solo funcionaba el `.bat`:
el `.exe` se cerraba con «title failed: --game_data_root was not provided» porque nadie le decía dónde estaba
la carpeta `assets`. Ahora ReForge añade a `src/main.cpp` un `OnConfigure` que da por defecto `title.game_root`
(la carpeta del juego junto al `.exe`, o junto al proyecto) y `title.update_root` si hay una actualización
instalada; si alguien pasa `--game_data_root`, manda el suyo. Comprobado con Resident Evil Zero: el `.exe`
abierto sin argumentos entra al juego igual que con el `.bat`.
- **La reparación con manejadores de excepciones ya no rompe la compilación.** El código generado usa
`REX_SEH_TRY`/`REX_SEH_CATCH`, que en Windows necesitan `GetExceptionCode`/`GetExceptionInformation`, y con
clang-cl no venían definidos: el build fallaba con «use of undeclared identifier 'GetExceptionCode'» y
ReForge bajaba la optimización sin arreglarlo. Ahora se genera `src/reforge_seh.h` (definiendo esos dos
intrínsecos, lo que hace `<excpt.h>` de MSVC) y se añade al precompilado de **todos** los destinos del código
recompilado (`_recomp`, `_recompiled`…), borrando los `.pch` viejos. Verificado con **Crash of the Titans**:
compila y enlaza con los manejadores activos.
- Pequeño ajuste del .toml de 0.11 a los nombres nuevos del SDK (`gpu.xenos.*`, `gpu.d3d12.*`) para que el log
no avise de renombrados.

## 1.48.11 — Se acabó la recompilación en bucle y el menú Guía de 0.11 ya funciona con mando

- **Bucle de recompilación arreglado.** El Taller comparaba la carpeta del SDK que había en la caché de CMake
  con la que tiene configurada ReForge. En un proyecto del SDK 0.11 con ReForge apuntando al 0.10, CMake
  resolvía el 0.11 (por el entorno), la comparación fallaba, se borraba la caché… y la siguiente pasada volvía
  a fallar: recompilación completa una y otra vez, sin final. Ahora se comparan **versiones**: si el SDK de la
  caché cumple la que pide el proyecto (`find_package(rexglue 0.11.0)`), no se toca nada; y si de verdad hay
  que reconfigurar, se hace **una sola vez** (queda anotado en `build/reforge_sdk.txt`), nunca en bucle.
- **El menú Guía de 0.11 funciona con el mando.** La navegación se lee por ImGui, que es por donde el SDK
  manda el pad (antes se leía el estado del juego, que queda neutral mientras el menú lo bloquea: el mando «no
  respondía»). Y se pide el botón Guía del mando, que 0.11 filtra salvo que se active.
- **Mismo aspecto que el menú de 0.10**: panel lateral deslizante con barra de acento, cabecera con gamertag,
  puntos y hora, «Jugando / Total / FPS», pestañas Gráficos · Logros · Ajustes, filas con el valor a la derecha
  y pies con los iconos de los botones (A / B / Guía, estilo Xbox o PlayStation), aviso flotante al cambiar y
  lista de logros con trofeo, puntos, fecha y descripción.
- Comprobado con **Resident Evil Zero**: compila y enlaza el menú nuevo y el juego arranca y se mantiene
  abierto sin errores en el log.

## 1.48.10 — El idioma (y el resto de opciones) ya llegan de verdad a los juegos del SDK 0.11

- **El idioma elegido no cambiaba nada en los juegos recompilados con el SDK 0.11.** Ese SDK renombró todos los
  ajustes a «grupo.nombre» y el `.toml` recibía `user_language = 5`, que el runtime descartaba con
  `unknown setting 'user_language' from Config`: el juego seguía en inglés aunque en Opciones estuviera
  «Español (México / Latinoamérica)». Ahora se escribe `kernel.user_language` / `kernel.user_country` (y
  `apu.mute`, `hid.*`, `ui.*`, `gpu.*`, `xenos.*` para el resto), y no se escriben los ajustes que 0.11 ya no
  tiene (escala de resolución, `present_effect`, `gpu_plugin`…), que solo llenaban el log de avisos.
- Comprobado con **Resident Evil Zero**: el runtime acepta ya `kernel.user_language = 5` y
  `kernel.user_country = 71` (sin ningún «unknown setting» en el log) y el juego arranca y se mantiene abierto.
  El idioma lo lee el juego al cargar, así que se aplica al abrirlo desde ReForge (no en caliente).
- Los proyectos del SDK 0.10 escriben exactamente lo mismo que antes.

## 1.48.9 — El menú Guía también en los proyectos del SDK 0.11

- **Menú Guía propio para la familia del SDK 0.11** (`rex::app::TitleApp`), que no tiene la clase `ReXApp` de
  0.10: se genera `src/reforge_menu.cpp` y se monta en `OnTitleLaunch` del proyecto. Se abre con el **botón
  Guía (PS/Xbox)** del mando o la tecla **Inicio**, y trae pestañas **Gráficos** (fotogramas 30/60/sin límite,
  escala de resolución, contador de FPS), **Ajustes** (silenciar el juego —se aplica al momento con
  `SetAudioPaused`— e idioma del juego) y **Logros** (catálogo con los desbloqueados y su puntuación).
- Guarda lo elegido en `reforge_menu.ini`, el mismo formato que la extensión de 0.10, así que ReForge lo aplica
  al siguiente arranque (`reforge_ext.ini`/`.toml`) sin código especial: fotogramas, escala, silencio e idioma
  funcionan en los dos SDK. Lo que el runtime no cambia en caliente se avisa como «se aplica al reiniciar».
- Comprobado compilando y lanzando **Resident Evil Zero** (SDK 0.11): enlaza y arranca sin errores.

## 1.48.8 — El Taller dice en qué proyectos el menú Guía aún no se puede montar

- Los proyectos creados con el **SDK 0.11** usan otra API de aplicación (`rex::app::TitleApp`, sin la clase
  `ReXApp` ni los diálogos de ImGui de 0.10), así que la extensión del menú Guía no se puede generar ahí: el
  juego se recompila y abre, pero sin menú. El Taller ahora lo dice con esas palabras al preparar el proyecto
  (antes no se avisaba de nada) y no le mete archivos a medias. Con un proyecto del SDK 0.10 el menú sí sale.

## 1.48.7 — Menú Guía en todos los proyectos, idioma dentro del menú y base de datos de iconos

- **El menú Guía (botón Xbox/PS o Inicio del teclado) queda en todos los juegos recompilados.** La extensión
  ReForge se regenera también al preparar cualquier proyecto y antes de cada partida, no solo al compilar en el
  Taller: los proyectos hechos antes de que existiera el menú lo reciben en cuanto se recompilan (y se avisa).
- **Idioma del juego desde la pestaña Ajustes del menú Guía.** Nueva fila «Idioma del juego» que recorre
  English, 日本語, Deutsch, Français, Español, Italiano… y cambia `XGetLanguage` **al momento** (sin reiniciar):
  las pantallas que lean textos ya salen en el idioma elegido. Se recuerda en `reforge_menu.ini` y pasa a
  `reforge_ext.ini` y al `.toml` (`user_language`) en el siguiente arranque.
- **Base de datos de iconos por Title ID.** Cada vez que se aplica el icono oficial de un juego se guarda en la
  carpeta de ajustes de ReForge (`icons/<TITLEID>.png`) y se reutiliza en cualquier otro proyecto del mismo
  juego o tras borrar el build, sin volver a extraerlo. El orden es: base de datos → XEX → imagen capturada de
  la partida (`reforge_image.bin`) → iniciales. También sirve para poner un icono propio: basta con dejar el PNG
  con el nombre del Title ID en esa carpeta.

## 1.48.6 — El cierre por textos no UTF-8 dice qué revisar en Windows

- Cuando el juego se cierra con `Dispatch thread: deferred completion threw 'Invalid UTF-8'` y el sistema **no**
  está en UTF-8, ReForge lo explica en el aviso: su Windows está en una página de códigos ANSI (1252/850), así
  que los textos del juego llegan en ANSI y el runtime, que valida UTF-8 estricto, los rechaza. Incluye la ruta
  exacta del ajuste de Windows (Región → Administrativo → «Beta: Usar Unicode UTF-8…») y avisa si la carpeta
  del proyecto tiene tildes, ñ o símbolos, que también lo empeoran. Sin esos casos el aviso no cambia.

## 1.48.5 — Los juegos con SDK 0.11 abren, y la caché de compilación ya no se borra sola

- **«command line failed: unknown option '--gpu_plugin=xenos'»** al pulsar Jugar: en el SDK 0.11 el cargador de la
  GPU ya no se elige por línea de comandos (solo por la cvar del `.toml`, que ReForge ya escribía). Se deja de
  pasar; funciona igual en 0.10 y en 0.11. Con 0.11 tampoco se pasan `--gpu.driver`/`--gpu_plugin` a los
  lanzadores (los rechaza el cargador). Comprobado con Resident Evil Zero: el juego arranca y presenta.
- **La base de compilación ya no se tira por cambiar la ruta de Ninja.** Bastaba con que Ninja estuviera en otra
  carpeta (BuildTools → Community, ambas 1.13) para borrar la caché de CMake y recompilar el juego entero (194
  archivos, minutos). Ahora solo se reconfigura desde cero si cambia la VERSIÓN de Ninja (o el compilador/
  generador/SDK), que es cuando de verdad hace falta.
- **Arranque de Asura's Wrath sin cerrar y abrir a mano.** El cierre intermitente del runtime del SDK (track
  distinto cada vez, `'Invalid UTF-8'` en una completion diferida) necesitó hasta 8 intentos seguidos en una
  sesión: el lanzador reintenta solo hasta 8 veces (antes 3) y en 0,4 s en vez de 1 s. Sigue siendo un fallo del
  runtime precompilado del SDK: no se arregla recompilando.

## 1.48.4 — Lo que cambias en el menú Guía se guarda, y botón para silenciar el juego

- **Los cambios del menú Guía se perdían.** Lo elegido jugando (fotogramas, escala de resolución) se escribía en
  el `.toml` del juego y se borraba del `.ini` del menú, pero las opciones del proyecto seguían con lo de antes: al
  volver a pulsar **Jugar**, ReForge regeneraba el `.toml` desde esas opciones y el cambio se revertía (por eso
  parecía que el menú «no hacía nada»). Ahora lo elegido jugando pasa también a `reforge_game.json` y se queda:
  cada arranque posterior mantiene el ritmo de fotogramas, la escala de resolución y el silencio.
- **Botón «Silenciar el juego» en el menú Guía** (pestaña Ajustes, con el botón Xbox/PS o Inicio). Corta el sonido
  al momento (el runtime lee el silencio en cada envío de audio, sin reiniciar), se recuerda en
  `reforge_menu.ini` y pasa al `.toml` y a las opciones del juego en el siguiente arranque, así que también se ve
  la casilla marcada en ReForge → Opciones del juego.

## 1.48.3 — El diagnóstico de cierres dice qué pasó, y la optimización no se queda apagada sin motivo

- **El diagnóstico lee el volcado de Windows.** Antes, un 0xC0000005 sin línea en el log se resumía en «sin mensaje
  en el log». Ahora se abre el `.dmp` de `%LOCALAPPDATA%\CrashDumps` (solo las cabeceras, milisegundos) y se dice
  qué intentó hacer el proceso, dónde y desde qué código: «escritura en la dirección 0x20D559000 desde
  VCRUNTIME140.dll+0xF88B». Con eso se distingue una copia de memoria que se pasa de largo de un puntero nulo, y
  se puede buscar el módulo y el desplazamiento exactos en el log del juego.
- **La optimización del código vuelve a «Segura» cuando se descarta.** Si el juego se cierra también con
  «Desactivada», el fallo no viene de la optimización: antes se quedaba apagada para siempre y el juego perdía
  rendimiento por un problema que no era suyo. Ahora se vuelve a «Segura» (se aplica en la próxima compilación),
  se anota que la optimización queda descartada y no se vuelve a bajar de nivel en los cierres siguientes. Si
  eliges el nivel a mano en el optimizador, esa marca se borra y vuelve a decidir solo.

## 1.48.2 — La notificación de logros sale siempre que el juego desbloquea uno

- **El aviso flotante no aparecía aunque el logro sí se desbloqueaba.** El runtime guarda el desbloqueo y avisa por
  dos vías distintas: la del desbloqueo en sí (siempre se dispara) y la de «muéstralo en pantalla» (solo si el
  desbloqueo se pidió con aviso). La extensión solo escuchaba la segunda, así que los logros del juego (que llegan
  por la primera, la de XGI) contaban en el menú Guía y en `Documents\<juego>\achievements\<titleid>.toml`, pero no
  salía la notificación con el logo, el sonido y los puntos.
- **Ahora** la extensión se suscribe también al desbloqueo: el aviso sale siempre. Si el runtime además manda su
  notificación, se descarta el duplicado (mismo logro, misma cola).
- **Queda en el log** del juego una línea `[ReForge] Logro desbloqueado: <nombre> (<puntos>G)` cada vez que se pone
  el aviso, para poder comprobarlo sin esperar a verlo en pantalla.

## 1.48.1 — El cierre intermitente del SDK ya no apaga la optimización del código ni recompila

- **Se reconoce el mismo cierre con cualquier mensaje.** El despachador del runtime aborta cuando una completion
  diferida lanza una excepción, y el texto cambia: «Invalid UTF-8», «Not enough space»… y a veces Windows ni
  siquiera llega a escribir la línea `[FATAL]` (solo queda el 0xC0000409). Antes solo se reconocía «Invalid UTF-8»,
  así que el cierre con «Not enough space» se tomaba por un fallo de la optimización, se bajaba de «Segura» a
  «Desactivada» (perdiendo rendimiento) y se lanzaba un mantenimiento completo con recompilación.
- **Ahora** se reconocen `deferred completion threw` con cualquier texto y el `0xC0000409` sin nada en el log que
  señale al juego recompilado (sin acceso inválido del guest, sin función no registrada, sin excepción SEH): se
  reintenta el arranque hasta 3 veces y no se toca la optimización ni se recompila.
- Mismo criterio en el lanzador del juego (`.bat` / acceso directo) y en el aviso de problemas conocidos.
- Cubierto por `tests/test_runtime_race.py`: otro mensaje del SDK y el aborto sin línea en el log dejan la
  optimización en «Segura» y solo reabren el juego.

## 1.48.0 — 30 FPS con VSync para NVIDIA Smooth Motion y menú Gráficos dentro del juego

- **Nuevo ritmo «30 FPS con VSync»** (Opciones del juego → Fotogramas): el juego se queda a 30 FPS reales, que es la
  base que NVIDIA Smooth Motion (RTX 40/50) y AMD Fluid Motion duplican a 60. Antes el ritmo automático ponía 60 Hz
  de vblank y el driver tenía que interpolar desde 30 sin un ritmo declarado.
- El tope de 30 lo aplica la extensión de ReForge en `VdSwap` (`frame_cap` de `reforge_ext.ini`), una vez por
  fotograma del Xbox 360: no se baja el vblank a 30, porque los juegos que esperan dos vblancos por imagen (Asura's
  Wrath entre ellos) caerían a 15 FPS. Con el juego ya limitado a 30 no cambia nada; con uno de 60 lo deja en 30.
- **Menú Guía → pestaña Gráficos** (botón Xbox/PS del mando o tecla Inicio): fotogramas (30 · Smooth Motion, 60,
  sin límite), escala de resolución interna (1×/2×/3×) y contador de FPS, cambiables sin salir del juego. Usa las
  cvars de rexglue en caliente y avisa cuando algo se aplica al reiniciar.
- Lo elegido en el menú del juego se guarda en `reforge_menu.ini` y ReForge lo pasa al `.toml` y al `reforge_ext.ini`
  en el próximo arranque, así que sobrevive a cerrar el juego (guardar Opciones del juego vuelve a mandar).
- El ajuste automático no interpreta los 30 FPS elegidos a mano como «GPU lenta»: no baja resolución ni cambia la
  ruta de render.
- Cubierto por `tests/test_guide_graphics.py` y `tests/test_smooth_motion.py`.

## 1.47.1 — El ajuste automático ya no baja la resolución en juegos con tope propio de FPS

- **Diagnóstico corregido:** tras cada partida, `auto_tune` comparaba los FPS del juego con el refresco de la
  ventana. Un juego con candado de framerate (Asura's Wrath: 30 FPS) siempre «no llegaba» a 60, así que se
  interpretaba como GPU lenta y, tras cada sesión, bajaba la resolución interna a 1× y fijaba el techo en 1×
  (además de desactivar «Lecturas exactas» y probar la ruta rápida sin motivo).
- **Ahora** se reconoce un juego con tope propio (`gamedb.frame_lock` + FPS plano que no sube del tope): si está
  cumpliendo su propio tope no se toca la resolución, ni el readback, ni se cambia de ROV a RTV. Si el FPS varía
  por debajo del tope, se sigue bajando la resolución como antes: ahí el límite sí es la GPU.
- Cubierto por `tests/test_perfdiag.py`: 30 FPS planos de un juego frame-locked se quedan en 2× y en ROV; 18-26
  FPS variables siguen bajando la resolución interna.

## 1.47.0 — Cada recompilación usa las versiones más nuevas de VS, CMake, Ninja, Clang y el SDK

- **Selección automática de la última versión instalada** (`toolchain.upgrade_config`) antes de cada compilación y
  de cada ronda de reparación automática: Visual Studio/Build Tools, CMake, Ninja y Clang. Solo **sube** de versión:
  si la configurada ya es la más nueva, o no se puede ejecutar, se queda como está. Los cambios se explican en el log
  («↑ CMake 4.3.1 (la versión más nueva instalada)»).
- **Visual Studio:** se enumeran *todas* las instalaciones con C++ x64 con su versión (vswhere en JSON) y se usa la
  de mayor versión; antes se usaba la que vswhere marcaba como «reciente», que puede ser una 17 tras instalar una 18.
- **CMake, Ninja y Clang:** se elige la versión más alta que responde entre todas las copias instaladas (PATH,
  WinGet, Visual Studio, LLVM), no la primera que aparezca.
- **Ninja queda fijado en la caché de CMake** (`-DCMAKE_MAKE_PROGRAM`): ya no depende del PATH ni de la copia que
  traiga Visual Studio, y si aparece una versión más nueva se reconfigura solo (no se mezclan versiones).
- **SDK de rexglue:** `installed_sdks()` encuentra los SDK de la carpeta de instalación de ReForge (antes solo
  miraba `%LOCALAPPDATA%`), los ordena por versión **numérica** (0.11 > 0.10, no alfabética) y prefiere la variante
  FSR a igual versión. Un proyecto **nuevo** se crea con el SDK más nuevo; en un juego ya compilado **no se cambia
  solo** (obligaría a recompilar todo y una versión *dev* nueva puede no compilarlo), pero se avisa de que existe.
- La comprobación se repite en cada reparación de código, así que un arreglo no se recompila con herramientas viejas.

## 1.46.3 — Recompilación más fiable: el autofix siempre regenera y no oculta saltos rotos

- **El código generado ya no se reutiliza después de corregir la tabla de funciones.** Cuando el autofix cambia
  `reforge_functions.toml` (entradas que se solapan, el final real de una función cortada o direcciones nuevas por
  saltos sin resolver), se invalida la generación anterior para que la corrección entre de verdad en el `.exe`.
  Antes solo algunas ramas lo hacían y ninja podía dar el codegen por bueno con el código viejo.
- Lo mismo al recuperarse durante la compilación del error «use of undeclared label» de una función cortada.
- **Aviso honesto si quedan saltos rotos:** si tras regenerar el código generado todavía contiene
  `REX_FATAL("Unresolved …")` en direcciones que ya están declaradas (o marcadas como no-función), el Taller lo
  dice con las direcciones concretas en vez de terminar como si todo hubiera ido bien; el juego se cerraría al
  llegar ahí.
- **Errores más útiles:** el error final de llamadas sin resolver incluye las direcciones pendientes y qué hacer,
  y los fallos de codegen/compilación traducen los códigos de Windows (falta una DLL del sistema, arquitectura
  incorrecta) en lugar de mostrar solo el número.

## 1.46.2 — Reintento automático ante el cierre INTERMITENTE «Invalid UTF-8»

- **Corrección honesta:** el cierre «deferred completion threw 'Invalid UTF-8'» **no** era el logon de Live (el
  arreglo de 1.46.1 no lo evitaba). Diagnóstico real: es una **carrera** en una completion asíncrona de
  XOVERLAPPED del runtime de rexglue (UI/enumeración de contenido) que decodifica una cadena con un conversor
  UTF-8 que lanza, y el despachador la vuelve fatal. Es **intermitente** (~1 de cada 2 arranques) y vive en el
  runtime **precompilado** del SDK, así que no tiene arreglo por proyecto; recompilar no ayuda.
- **Mitigación universal:** el lanzador (la ventana de ReForge y el `.bat` directo) ahora **reintenta solo el
  arranque hasta 3 veces** cuando detecta este cierre. Como falla solo en parte de los arranques, el juego abre
  casi siempre sin que hagas nada.
- La ficha de la base de problemas se corrigió para describirlo con honestidad (bug del SDK, intermitente, sin
  recompilar) y recomendar reportarlo al autor de rexglue.

## 1.46.1 — Arreglo: cierre «Invalid UTF-8» en el inicio de sesión de Live (modo local tipo Xenia)

- **Nuevo problema conocido con arreglo automático** (`knownissues`): algunos juegos (p. ej. Asura's Wrath) se
  cerraban con «[FATAL] Dispatch thread: deferred completion threw 'Invalid UTF-8'» tras entrar en el inicio de
  sesión de Xbox Live. Causa: con el Live simulado ReForge decía que había conexión y sesión online, el juego
  intentaba el logon, y una tarea de red asíncrona devolvía texto con bytes no válidos que el runtime no podía
  decodificar. **Como hace Xenia por defecto**, ahora ReForge deja el perfil **firmado en LOCAL y sin conexión**
  cuando detecta este cierre: el juego no entra en el logon online que falla, y el gamertag y los logros siguen
  funcionando. Sin recompilar (se reescribe `reforge_ext.ini`); solo hay que volver a abrir el juego. También se
  puede activar a mano con «Live → local sin conexión».

## 1.46.0 — Base para el desbloqueo de FPS NATIVO (mid-asm hooks)

- **Framework de parches nativos a nivel de codegen** (`reforge/nativepatch.py`): genera *mid-asm hooks* reales de
  rexglue (`REX_MIDASM_BRANCH` + `REX_MIDASM_AT`, verificados en el SDK) para portar a nativo cosas como el
  desbloqueo de FPS. A diferencia de Xenia, rexglue no hace «pokes» de memoria en runtime: el cambio se hace al
  generar el código. Incluye **guarda de versión** (un parche del juego base NO se aplica si hay title update,
  porque las direcciones se desplazan), es **opt-in, reversible** (`apply`/`remove`) y **experimental**.
- **Catálogo**: la ficha de Asura's Wrath lleva el desbloqueo nativo portado de la dirección de boma
  (`xenia-canary/game-patches`), marcado **solo para el juego base** y con el aviso de que **acelera** lo atado
  al framerate (para fluidez sin acelerar: Movimiento Suave o un parche de *timestep* específico del juego).
- Todavía **no se engancha solo** al pipeline: no toca ninguna recompilación hasta validarlo por juego.

## 1.45.1 — Cerrar el juego ya no lo reabre solo + candado de FPS por juego

- **Arreglado: al cerrar un juego ya no se relanza solo.** Cerrar el juego nunca lo vuelve a abrir por su cuenta.
  Los ajustes automáticos y la recompilación recomendada se dejan **listos para la próxima vez** que pulses
  «▶ Jugar», y se avisa en el log. Se quitó la cuenta atrás que reabría el juego sola, y se gatearon todas las
  vías de reapertura tras una partida (mejoras de la base de datos, recompilación por cambios, ajustes de
  rendimiento y mantenimiento de funciones). Hay un interruptor nuevo en 🎮 Opciones → Reparación del arranque,
  **«Volver a abrir el juego solo al cerrarlo»** (desactivado por defecto) para quien sí quiera cerrar el ciclo.
- **Candado de framerate por juego** (`gamedb.frame_lock`): a partir del catálogo de parches de la comunidad de
  Xenia (xenia-canary/game-patches), ReForge sabe qué juegos tienen la animación/física/QTE atadas al ritmo de
  fotogramas (p. ej. Asura's Wrath, confirmado por el autor del parche «Unlock FPS»). En esos juegos recomienda
  **Movimiento Suave** en vez del desbloqueo crudo, que acelera las cinemáticas. La dirección del parche se
  guarda solo como **referencia**: es memoria *guest* de Xenia y en la recompilación nativa habría que aplicarla
  al generar el código, no en runtime.

## 1.45.0 — Base de datos de compatibilidad por juego

- **Base de datos de compatibilidad propia, por Title ID** (`reforge/gamedb.py`): por cada juego guarda solo los
  parámetros que de verdad mapean a la recompilación **nativa** (modo de imagen ROV/RTV, gamma, lectura de
  resolves, alpha, guardas de fetch, FPS) con su guía y su fuente. Al preparar el proyecto, el **Taller aplica
  la configuración idónea automáticamente**; para un juego que no está en la base, sigue usando el heurístico
  seguro de siempre. Respeta siempre lo que el usuario ya eligió a mano.
- **Tres capas**: semilla verificada (los arreglos ya probados, p. ej. el gamma de Asura's Wrath), capa curada
  ampliable y **base de usuario persistente** que el propio PC va aprendiendo: con `remember` queda guardada la
  config de un juego que confirmas que va bien, y se puede **exportar e importar** para compartirla.
- **Referencia de Xenia, no importación a ciegas**: Xenia es otro motor (un emulador) y sus ajustes no se
  trasladan 1:1 a un `.exe` nativo. La base enlaza la **ficha de compatibilidad de Xenia** de cada Title ID como
  referencia informativa (a verificar), sin aplicarla sola. También incluye **notas por motor** (UE3, MT
  Framework, Unity) como guía de por dónde empezar.

## 1.44.8 — Launcher claro y con la temática del juego

- **Los «Jugar ….bat» ahora son launchers claros y temáticos**: usan el **nombre real** del juego
  («asura_s_wrath» → «Asura's Wrath»), ponen ese nombre en el título de la ventana, **colorean la consola con
  el color característico del icono** del juego (el rojo de Asura, etc.) y muestran una cabecera limpia antes de
  arrancar. Además se genera un `.ico` del juego y el acceso directo del Escritorio usa el **icono del juego**,
  no el genérico. Se limpian los launchers antiguos para no dejar duplicados.

## 1.44.7 — Movimiento suave por driver (cinemáticas a velocidad correcta y fluidas)

- **Nueva opción «Movimiento suave por driver (NVIDIA Smooth Motion / AMD Fluid Motion)»** (🎮 Opciones →
  Gráficos). Resuelve el problema de las cinemáticas aceleradas al desbloquear los FPS: en los juegos de 30 FPS,
  en vez de desbloquear (que acelera cinemáticas y físicas porque atan su lógica al fotograma), el juego corre a
  su **velocidad real y estable** y es el **driver de la gráfica** quien interpola fotogramas para que *se vea*
  fluido a 60+. Al activarla, ReForge fija vsync y un ritmo base estable (sin «sin límite» ni tearing variable) e
  ignora el desbloqueo de FPS, y te guía a activar «Smooth Motion» (NVIDIA app, RTX 40/50) o «Fluid Motion
  Frames» (AMD Adrenalin) para tu `.exe`. Velocidad correcta + imagen fluida, sin trucos que rompan el juego.

## 1.44.6 — ReForge ya no se queda «No responde» al compilar (durante y al terminar)

Dos arreglos para que la ventana nunca se congele al recompilar:

- **Durante la compilación**: el árbol de compilación (cmake → ninja → clang) se lanza con prioridad por debajo
  de lo normal. Con `--parallel` usando todos los núcleos, a prioridad normal esos procesos ahogaban el hilo de
  la interfaz y Windows marcaba ReForge como «No responde». Ahora el sistema sigue dando tiempo a la UI y la
  ventana se mantiene fluida; apenas cambia el tiempo total, porque los núcleos siguen libres cuando la UI no
  los necesita.
- **Al terminar**: el log vuelca como mucho 600 líneas por tick. Antes, una compilación que soltaba miles de
  líneas las acumulaba y, al final, intentaba pintarlas todas de golpe en un solo `appendHtml` que bloqueaba la
  ventana varios minutos. Ahora se pintan por trozos y la UI nunca se congela, aunque el buffer esté lleno.

## 1.44.4 — el SDK incompatible entra en la base de datos de problemas conocidos

- **`knownissues` (la base de datos de problemas) ahora conoce el fallo de SDK incompatible**: reconoce el
  error de CMake «links to rex::runtime but the target was not found» y trae **remedio automático** — cambia al
  SDK instalado compatible (la misma lógica que el Taller) y pide recompilar. Así, este tipo de problema queda
  documentado con su causa y se corrige solo, como el resto de entradas de la base de datos.

## 1.44.3 — la validación de SDK reconoce el ejecutable de codegen y nunca bloquea

- **Corregida la falsa incompatibilidad**: el proyecto usa `rex::rexglue` (la herramienta de codegen, un
  `add_executable(rex::rexglue IMPORTED)` del SDK) además de `rex::runtime`. El detector solo miraba
  `add_library`, así que creía que ningún SDK proveía `rex::rexglue` y marcaba todo como incompatible, incluso
  el SDK correcto. Ahora reconoce bibliotecas **y** ejecutables importados (y nombres con guion como
  `rex::gpu-xenos`).
- **La validación ya no pone muros**: si no encuentra un SDK claramente compatible, avisa y **continúa** en vez
  de detener (que CMake decida); solo cambia de SDK cuando encuentra uno mejor. Automático de verdad.

## 1.44.2 — arreglo: la validación de SDK del Taller ya no crashea

- **Corregido el crash «No module named 'reforge.sdkcompat'»** al recompilar: el paso «Validar SDK compatible»
  importaba el módulo de forma dinámica (por string) y PyInstaller no lo incluía en la app empaquetada, así
  que el salvaguarda tumbaba justo la compilación que debía proteger. Ahora se importa de forma estática (y se
  añade como hidden-import), y el paso es **a prueba de fallos**: si por lo que sea la validación no está
  disponible, avisa y sigue en vez de detener el build; solo se detiene cuando el SDK es de verdad incompatible
  y no hay recambio.
- **El Taller elige el mejor SDK por sí mismo**: cuando un proyecto necesita un SDK distinto del seleccionado,
  cambia automáticamente al **mejor SDK compatible instalado** (versión más alta, con FSR/CAS si está), sin
  pasar por el Entorno. Así, aunque no entres a «Entorno», el Taller se encarga de elegir lo necesario para
  recompilar cualquier juego.

## 1.44.1 — recompilado resiliente, SDK a prueba de errores y arreglos gráficos

- **Aviso de actualización al abrir y mientras ReForge está abierto**: además del chequeo al arrancar, ReForge
  vuelve a mirar GitHub cada 3 h durante la sesión (la consulta real sigue limitada a una vez al día), así el
  aviso de versión nueva aparece aunque dejes el programa abierto. No apila ventanas si ya hay un aviso.
- **Recompilación automática resiliente** (`autorecompile.py`): la recompilación arranca con los mejores
  componentes (optimizador Fluido, AOT, auto-ajuste, arreglos por juego, SDK compatible) y, si la compilación
  falla con una optimización agresiva, **baja sola por una escalera de seguridad** (`max → safe → off`),
  regenerando y recompilando, hasta lograrlo. Junto con las recuperaciones que ya existían (encabezado SEH,
  funciones cortadas, «líneas vacías», compilar sin la extensión), hace que recompilar cualquier juego sea lo
  más a prueba de errores posible; solo si el nivel más seguro también falla se reporta, claro, que ese juego
  necesita trabajo específico. (No promete 0 % de errores: hay juegos aún no recompilables.)
- **Validación de SDK compatible al recompilar** (`sdkcompat.py`): antes de configurar se comprueba que el SDK
  seleccionado provee los targets `rex::*` que el proyecto generado necesita. Si no (p. ej. tras instalar o
  cambiar a un SDK de otra familia como rexglue 0.11, que renombró `rex::runtime`), ReForge **cambia solo a un
  SDK instalado compatible** —dejando una copia de respaldo de la configuración— y limpia la caché de CMake,
  para que la recompilación no se rompa; si no hay ninguno compatible, se detiene con un mensaje claro en vez
  de un error de CMake incomprensible. Así, actualizar o cambiar componentes ya no deja el proyecto roto.
- **Arreglos gráficos conocidos por juego** (registro `GFX_HINTS` por Title ID): se aplican solos al preparar
  el proyecto. Primer caso verificado: **Asura's Wrath** salía con el menú y varias escenas (incluida la
  pantalla de título) sobreexpuestos/lavados en blanco y con ruido verde; activar la gamma del render target
  a UNORM16 (`gfx_gamma_unorm16`) lo corrige. Verificado con capturas antes/después.
- **Precompilación de shaders (AOT) activada por defecto**: `shader_prewarm` pasa a estar encendido, así que
  al abrir un juego se precompilan los pipelines guardados antes del primer frame y desaparecen los tirones
  de transición en escenas ya vistas (la carga inicial es un poco más larga). Necesita que el SDK traiga el
  parche de prewarm, que ReForge aplica solo al compilar el SDK; si no lo trae, el ajuste se ignora sin romper
  nada. Se puede desactivar en 🎮 Opciones → Gráficos.

## 1.43.0 — actualizador integrado y Biblioteca con carátulas

- **Actualizador integrado y pulido**: ReForge compara tu versión con la última publicada en GitHub y, si hay
  una nueva, lo avisa con una ventana propia (logo, «tu versión → la nueva» y las novedades de la release
  renderizadas) y la descarga e instala sin que tengas que entrar a GitHub ni ejecutar el instalador a mano.
  La descarga se verifica por tamaño y SHA-256 antes de ejecutarse. La comprobación es automática (una vez al
  día) y se puede dejar en automático desde Ajustes.
- **Biblioteca con carátulas**: las fichas de la Biblioteca y de «Recientes» muestran la carátula real del
  juego (la imagen del título embebida en el XEX), con un respaldo generado cuando no hay arte. Fichas
  rediseñadas (carátula + título + estado + Title ID + acciones) para una vista más limpia y ordenada.
- README renovado con banner animado y capturas de la interfaz.

## 1.42.0 — inferir el final de las «líneas vacías» del functions.toml

Cuando rexglue no puede acotar una función deja `0xADDR = {}` en `reforge_functions.toml` y antes el
codegen se detenía pidiendo poner `end`/`parent` a mano. Ahora, en ese punto, ReForge **infiere el final**
= el inicio de la siguiente función conocida (como haría rexglue con el `.pdata`), con un tope de 32 KB para
no inventar tamaños enormes cuando hay datos en medio. Si queda mal, las siguientes rondas del autofix lo
corrigen; solo cae al aviso manual si tampoco se puede inferir (saltos a datos o fuera del módulo).

## Novedades 1.41.0 — precompilar shaders al cargar (AOT, estilo Pinyon)

Opciones del juego → Gráficos → **Precompilar shaders al cargar**. Lo que hace fluido a Forza Horizon en
Pinyon Shift no es Vulkan, es que **precompila todos los shaders antes de jugar** (AOT). rexglue ya guarda
los shaders que va viendo (`gpu.xenos.store_shaders`) y recrea sus pipelines al abrir el juego, pero lo hacía
**en segundo plano**, así que los primeros segundos aún daban tirones mientras terminaban de compilarse.

Ahora ReForge trae un parche de SDK que añade el cvar `gpu.xenos.shader_storage_blocking` y hace que, con la
opción activada, rexglue **compile por adelantado todos los pipelines guardados antes del primer frame**: la
carga inicial tarda un poco más, pero se acaban los tirones de «primera vez que aparece este efecto» en todo
lo que ya habías jugado. La caché se guarda sola al jugar; esta opción solo decide **cuándo** se compila.

Por defecto está desactivado (comportamiento de siempre). El cvar solo se escribe si el SDK del juego trae el
parche; si no, se ignora sin romper nada. Para la primera pasada por contenido nuevo sigue sin poder evitarse
compilar al vuelo (no hay un corpus de shaders prehecho como el que Pinyon capturó para Forza), pero a partir
de la segunda vez el juego va fluido desde el primer frame.

## Novedades 1.40.1 — el SDK compila el driver Vulkan (si tienes el Vulkan SDK)

El motivo por el que el renderer Vulkan nunca estaba disponible: ReForge compilaba el SDK con
`REXGLUE_USE_VULKAN=OFF` (el valor por defecto de rexglue). Ahora, al compilar el SDK en Entorno, ReForge
**activa Vulkan automáticamente si detecta el Vulkan SDK de LunarG** instalado (rexglue lo exige,
`find_package(Vulkan)` ≥ 1.4.313). Si no está, el SDK se compila solo con D3D12 como hasta ahora (sin
romperse) y ReForge avisa de que para Vulkan hay que instalar el Vulkan SDK y recompilar.

En resumen, para probar Vulkan: instala el Vulkan SDK de LunarG → recompila el SDK en Entorno → elige
«Vulkan» en Opciones del juego → Gráficos. Recuerda que es un experimento de fluidez, no una garantía.

## Novedades 1.40.0 — selector de renderer (D3D12 / Vulkan, experimental)

Opciones del juego → Gráficos → **Renderer**. rexglue trae dos renderers (el mismo linaje Xenia): **Direct3D 12**
(lo estable y probado, lo que usabas) y **Vulkan** (experimental). Ahora puedes elegirlo por juego; ReForge
pasa `--gpu.driver=` al lanzar y en los accesos directos.

Vulkan es un experimento para comparar fluidez, no una garantía de ir mejor: a veces va igual, mejor o peor
según el juego y el driver. Y **solo funciona si el SDK con el que compilaste el juego trae el driver Vulkan**
— los SDK de ReForge se han venido compilando solo con D3D12, así que para probar Vulkan hay que recompilar
el SDK con ese módulo. Si eliges Vulkan y el SDK no lo trae, ReForge lo detecta (`game.sdk_has_vulkan`) y te
avisa en vez de dejar que el juego no abra.

Nota de rendimiento: lo que hacía a Forza Horizon tan fluido en Pinyon Shift no era Vulkan en sí, sino
**precompilar todos los shaders antes de jugar** (AOT). Tus juegos en D3D12 ya compilan shaders en segundo
plano y guardan una caché persistente que rexglue precarga al arrancar, por eso la segunda partida va más
suave que la primera.

## Novedades 1.39.0 — lo mejor de ShiftGlue para mandos, teclado y ratón

[ShiftGlue](https://github.com/arcanite24/shiftglue-sdk) es el fork de rexglue (licencia BSD-3) donde el
proyecto [Pinyon Shift](https://github.com/arcanite24/pinyon-shift) metió los arreglos para que los juegos
corran bien en PC, portátiles, Mac y Android. De ahí se traen las mejoras **generales y portables** —sin
tocar el SDK ni atar nada a un juego concreto—:

**Base de mapeos de mando al día, junto a cada juego.** rexglue arranca su driver SDL leyendo
`{carpeta_del_exe}/gamecontrollerdb.txt`; si no hay archivo, usa solo su base interna y con mandos modernos
a veces deja botones mal asignados. ReForge ahora empaqueta una base SDL actualizada (2309 mandos:
DualSense y DualSense Edge, DualShock 4, Xbox Series, Switch Pro, 8BitDo…) y la coloca sola al compilar y
al lanzar. Nunca pisa un `gamecontrollerdb.txt` que hayas puesto tú (solo reescribe el suyo, marcado con
`REFORGE-GCDB`). Base de datos de [mdqinc/SDL_GameControllerDB](https://github.com/mdqinc/SDL_GameControllerDB).

**Aviso del DualSense (Opciones del juego → Controles).** Si hay un mando Sony conectado, ReForge avisa de
la causa número uno de «botones cambiados» en PC —la misma que detecta el driver de ShiftGlue—: **Steam
Input** se queda con el DualSense y se lo presenta al juego como un mando de Xbox. La solución (desactivar
Steam Input para ese juego) se explica ahí mismo.

**Diagnóstico de imports dinámicos sin resolver.** Cuando un juego se cierra con «GetProcAddress(…): ordinal
out of bounds» y una llamada a `0x88xxxxxx`, la base de problemas conocidos ahora lo reconoce: el juego
carga un módulo secundario en marcha y esta versión de rexglue no implementa esa carga (no es un fallo de
tu equipo; es rexglue [issue #448](https://github.com/rexglue/rexglue-sdk/issues/448)). Para **Forza
Horizon** (disco USA MS-2505) el camino que sí funciona es Pinyon Shift, que compila ese juego desde tu
propio disco con su motor a medida.

Lo que **no** se trajo, por honestidad: el audio XMA reescrito, el renderer a medida y la carga dinámica de
módulos de ShiftGlue están tan ligados a su fork que portarlos como parches de texto rompería la base. Eso
es justo lo que Pinyon Shift resuelve como motor aparte.

## Novedades 1.38.2 — reporte honesto de parches en SDK reorganizados

Afinando lo de la 1.38.1: rexglue 0.11 no solo movió el árbol de gráficos, reorganizó medio código
(`src/system`, `src/input`… cambiaron de sitio). Un parche cuyo archivo ya no está ahora se reporta como
**saltado** con su motivo, en vez de contarse como aplicado (que era engañoso). Un archivo ausente nunca
detiene la compilación —ni siquiera un parche imprescindible—, porque significa que esa versión reorganizó
el código y hay que re-anclar el parche, no que algo esté roto. Así, al compilar un SDK nuevo, el registro
dice la verdad de qué mejoras entraron y cuáles no.

Recomendación: para jugar, **sigue en rexglue 0.10.0.24** (el último 0.10, el que tienes). Las versiones
0.11.x son una reorganización en curso sin mejoras de juego todavía, y los parches de ReForge están
anclados al código de la 0.10.

## Novedades 1.38.1 — los parches del SDK no tumban una versión nueva

Al salir **rexglue v0.11.0**, que reorganizó el árbol de gráficos (`src/graphics/` → `src/gpu/xenos/`), se
vio que un parche de ReForge que no encajaba **abortaba toda la compilación del SDK**. Ya no: cada parche
busca sus archivos en las dos ubicaciones, y si aun así uno no encaja (porque una versión nueva cambió el
código), se **salta con un aviso** y el SDK se compila igual con los demás. Solo los parches imprescindibles
(que el arranque tolere funciones fuera del módulo) detienen la compilación si fallan. Así ReForge sigue
sirviendo con las versiones nuevas de rexglue en vez de romperse con cada actualización.

## Novedades 1.38.0 — compatibilidad gráfica y arreglos del SDK (hallazgos de la comunidad)

A partir de lo documentado en [fh1-recomp-findings](https://github.com/ItsNotPaths/fh1-recomp-findings),
se incorporan dos cosas:

**Compatibilidad gráfica** (🎮 Opciones del juego → Gráficos). Cuatro ajustes heredados de Xenia, apagados
de serie, para pelear un fallo concreto de imagen en un juego sin tocar a los demás (solo surten efecto si
el motor del juego los admite): desplazamiento de medio píxel (geometría/HUD temblorosos), transparencias
difusas (bordes que parpadean), acotar el rango de EDRAM al mínimo (restos en pantalla) e iluminación gamma
como UNORM16 (imagen muy oscura o lavada). Se prueban de uno en uno porque cada juego necesita unos u otros.

**Resolve vacío tolerante** (parche del SDK). Una región de *resolve* vacía ya no aborta el frame: se trata
como «nada que copiar», que es lo que hace Xenia. Solo afecta a los juegos que generan resolves vacíos
(FH1/FH2 y parecidos); los que ya van bien no entran nunca en ese caso. Entra al recompilar el SDK.

El selector de SDK en Entorno ya lista automáticamente las versiones nuevas de rexglue (incluida la v0.11.0,
que corrige casos límite de `fctid`, `srad/sraw` y `vcmpbfp` en el codegen); los parches de ReForge se
aplican sobre la versión que elijas.

## Novedades 1.37.0 — ningún juego se niega a abrir por una función fuera del módulo

La 1.36.0 evitaba que ReForge *añadiera* direcciones fuera del módulo, pero el propio recompilador de
rexglue también las encuentra en el XEX, así que el problema podía volver al recompilar. El arreglo de
raíz va en el SDK (`sdk_patch.apply_funcmap_tolerant`): si una función cae fuera del módulo del juego, el
runtime la **salta con un aviso** en vez de abortar todo el arranque. Una dirección así nunca se puede
llamar de forma válida, de modo que saltarla es más seguro que negarse a abrir; si el juego la llega a
llamar de verdad, fallará solo en esa llamada en lugar de no arrancar.

Entra al recompilar el SDK (Entorno → rexglue con FidelityFX), junto al parche de puntería del ratón.

También: un cierre por **acceso inválido sin mensaje en el log** (0xC0000005) ahora activa solo los
manejadores de excepciones del juego (`__try/__except`) y recompila, igual que ya se hacía con los
«guest access violation». Muchos cierres de ese tipo son accesos que el juego esperaba capturar.

## Novedades 1.36.0 — base de datos de problemas y un bug que impedía arrancar

Al recompilar juegos grandes, ReForge aprende funciones mirando el juego en marcha. Pero cuando un juego
salta a través de un **puntero dañado**, esa «dirección» cae fuera de su propio módulo, y ReForge la
declaraba como si fuera una función. El resultado: el runtime de rexglue rechaza *toda* la tabla de
funciones al arrancar («func_mappings entries rejected») y el juego **ni siquiera abre**. Le pasaba a
Forza Horizon (`0x88050388`, 80 MB por encima del módulo).

Arreglado en tres frentes:

* **Guardarraíl:** ReForge ya nunca declara una dirección fuera del módulo del juego. Si el juego saltó
  ahí, se anota como «no es función» y no se reintenta.
* **Autocuración:** los proyectos que ya quedaron rotos se arreglan solos en el mantenimiento — se quita
  la dirección mala de `reforge_functions.toml` y se recompila. Probado con el Forza real: pasa de «no
  arranca» a iniciarse del todo.
* **Base de datos de problemas conocidos** (`reforge/knownissues.py`): una tabla que reconoce cada fallo
  por su huella en el log, explica la causa y, cuando se puede, trae el remedio que el mantenimiento
  aplica solo. De momento cubre: función fuera del módulo, montón del CRT agotado, caché de shaders
  dañada, mando reconectado (el bug del SDL) y salto a un puntero sin resolver. Es ampliable: cada
  problema nuevo que se diagnostica se añade aquí para que el siguiente no empiece de cero.

Nota honesta sobre Forza: con esto **arranca** (antes no), pero todavía se cierra un instante después
porque el juego llama a un puntero que esta versión de rexglue no resuelve (un import del motor). Eso es
compatibilidad del título con el SDK, no algo que una base de datos pueda inventar; queda diagnosticado
con su consejo en vez de fingir un arreglo.

## Novedades 1.35.0 — panorámica de verdad, sin parchear el juego

Quitar las bandas negras estirando la imagen la deforma, y los parches de aspecto de
la base de Xenia solo existen para unos pocos juegos. Resulta que hay una tercera vía,
y es la buena: rexglue ya trae los cvars **`video_mode_width` y `video_mode_height`**,
que son el modo de vídeo que el juego cree tener delante.

Así que ReForge mira tu monitor y, si es más ancho que 16:9, le dice al juego que la
pantalla es de esa forma (en tu caso 1712×720 para un 21:9). Los juegos que calculan
su proyección a partir del modo de vídeo —la mayoría de los de esta época, Unreal
Engine 3 incluido— **dibujan ellos mismos más campo de visión a lo ancho**: imagen
llena, geometría correcta, sin estirar y sin parche. Los que llevan 1280×720 a fuego
lo ignoran y se quedan como estaban, sin romperse.

Se mantiene la altura en 720 para no encarecer el dibujado: lo que crece es el ancho,
y el supermuestreo del optimizador sigue multiplicando encima. El ancho se redondea a
múltiplo de 16 (los mosaicos del Xenos), lo que deja la forma a menos del 1 % de la de
tu pantalla.

Esto va además de lo de la 1.32.0: si el juego tiene parche de aspecto en la base de
Xenia, se sigue aplicando.

## Novedades 1.34.0 — puntería con el ratón de verdad

Subir la sensibilidad no arreglaba el ratón porque el problema no era el número, era
el método: rexglue convierte el ratón en **stick derecho**, y un stick manda
*velocidad de giro* mientras que un ratón manda *distancia*. Por eso lo lento no
registraba (se quedaba por debajo de la zona muerta del juego) y lo rápido pegaba un
salto (entraba de golpe en la parte alta de la curva de respuesta).

ReForge ya parchea el código de rexglue al compilar el SDK, así que el arreglo va
donde tiene que ir: `sdk_patch.apply_mouseaim()` cambia el driver de teclado y ratón
(`src/input/mnk/mnk_input_driver.cpp`) para que **acumule el recorrido del ratón y lo
gaste a lo largo de varios fotogramas**, siempre con una deflexión que supera la zona
muerta. El giro total sale proporcional a lo que has movido el ratón:

| Recorrido | Giro |
|---|---|
| 100 px | 4,88 |
| 200 px | 9,77 |
| 400 px | 19,53 |

Y los movimientos pequeños ya no se pierden: se guardan y se sueltan en cuanto suman
bastante, en vez de descartarse.

Además el parche añade **sensibilidad separada para X y para Y** (`mnk_sensitivity_x`
y `mnk_sensitivity_y`), que en el diálogo son dos barras; la vertical viene algo más
baja, como en cualquier juego de PC. Hay dos ajustes finos más por si hacen falta:
`mnk_aim_floor` (el empujón mínimo) y `mnk_aim_tail` (cuánto recorrido puede quedar
en cola, para que un gesto rápido no se sienta como inercia).

**Hay que recompilar el SDK una vez** (Entorno → rexglue con FidelityFX) para que el
parche entre en `rexruntime.dll`. Los juegos ya compilados lo heredan sin recompilarse,
porque ReForge copia el runtime junto a cada juego. Mientras tanto, el runtime sin
parchear sigue usando el valor único de siempre y ReForge se lo escribe ya subido.

Lo que no se puede arreglar: el giro máximo del juego pone un techo, así que un gesto
muy rápido no cabe en un fotograma y se reparte entre los siguientes. Un stick emulado
nunca llegará a ser un ratón nativo; esto lo deja suave y proporcional, que es lo que
faltaba.

## Novedades 1.33.2 — los diálogos caben en la pantalla

«Opciones del juego» había crecido tanto que en una pantalla de 1080 píxeles de alto
los botones Guardar y Cancelar quedaban por debajo del borde, fuera del alcance del
ratón. Ahora cada pestaña va dentro de una zona con barra de desplazamiento y el
diálogo nunca se abre más grande que la pantalla; lo mismo en Optimizar, Trucos,
Packs y el lanzador. Hay una prueba (`tests/test_dialogos.py`) que lo vigila, para
que no vuelva a pasar sin que nos enteremos.

La sensibilidad del ratón es ahora una **barra**, que se ajusta de un vistazo, con el
valor al lado.

## Novedades 1.33.1 — el ratón con sensibilidad que sirve

El reparto llegaba bien al juego pero la cámara no se movía. El motivo está en
`mnk_input_driver.cpp`: el ratón se convierte en stick derecho multiplicando los
píxeles por 200 y por la sensibilidad. Con la sensibilidad 1 que trae el SDK, un
gesto normal de ratón (unos 16 píxeles entre fotograma y fotograma a 60 FPS) da un
10 % de stick, **por debajo de la zona muerta de cualquier shooter**, así que el
juego lo descarta entero y parece que el ratón no funciona.

Los repartos con ratón vienen ahora en 5 (ese mismo gesto pasa al 49 %) y los
proyectos que ya estaban configurados se corrigen solos al abrirlos. El control del
diálogo llega hasta 10, que es el máximo que acepta rexglue.

## Novedades 1.33.0 — el teclado y el ratón ya vienen puestos

La 1.31.0 trajo los repartos por juego, pero los dejaba apagados mientras hubiera un
mando conectado, así que en la práctica no se usaban: Gears of War seguía arrancando
sin ratón para apuntar. Esa precaución sobraba. El SDK combina el estado de todos los
dispositivos en el mismo mando del juego (`src/input/state_merge.cpp`: los botones se
suman, los gatillos y los sticks se quedan con el valor más fuerte), y el teclado y el
ratón entran como un dispositivo más del jugador 1. **No hay que elegir**: el teclado y
el ratón quedan siempre disponibles y el mando sigue funcionando igual, a la vez, sin
cambiar nada en ninguna opción.

Qué cambia:

* **Al compilar un juego**, el Taller elige el reparto que le toca, enciende el ratón
  para la cámara y lo guarda en las opciones del proyecto. Sale escrito en el registro
  de la compilación, y las teclas quedan a la vista en 🎮 Opciones del juego →
  Controles por si quieres cambiar alguna. Al recompilar no se vuelven a pisar.
* **Los proyectos que ya tenías** se actualizan solos: al abrirlos se les enciende el
  teclado y el ratón y se les pone el reparto del juego, sin tener que recompilar.
* El teclado y el ratón vienen **activados de serie** en los proyectos nuevos.

Por ejemplo, Gears of War 2 queda así sin tocar nada: ratón para la cámara, clic
izquierdo disparar (`keybind_right_trigger = "MouseLeft"`), clic derecho apuntar, WASD
para moverse, Espacio para cubrirse y correr, R recargar, F cambiar arma, G granada,
Mayús correr. Y si prefieres el mando, lo enchufas y juegas con el mando.

## Novedades 1.32.1

Las publicaciones de GitHub llevan ahora el SHA-256 del instalador en sus notas y
como archivo aparte. El actualizador del programa lo lee y comprueba lo que se ha
descargado antes de instalarlo: sin ese número se instalaba a ciegas.

## Novedades 1.32.0 — pantalla panorámica sin bandas negras

Los juegos de Xbox 360 se hicieron para 16:9. En un monitor panorámico (21:9, 32:9)
la imagen sale con bandas negras a los lados, y estirarla sin más deforma a todo el
mundo. La solución buena existe desde hace años: los parches panorámicos de la base
de datos de Xenia Canary, que cambian el campo de visión del juego para que dibuje a
lo ancho de verdad. ReForge los descartaba a propósito; ahora los usa.

En 🎮 Opciones del juego → Gráficos hay **Pantalla panorámica**:

* **Automática** (de serie) — ReForge mira tu monitor; si es más ancho que 16:9,
  busca el parche de aspecto de ese juego y elige el que mejor encaja con tu pantalla
  (prefiere quedarse corto antes que pasarse, porque pasarse recorta imagen). Al
  preparar el juego en el Taller lo activa con el resto de mejoras, y entonces quita
  las bandas negras: con el parche puesto el juego mete más campo de visión dentro del
  mismo búfer de 16:9, y es al estirarlo al ancho real cuando recupera sus proporciones
  y llena la pantalla. Si ese juego no tiene parche, no se toca nada: mejor bandas que
  una imagen deformada.
* **Estirar la imagen** — quita las bandas aunque no haya parche. Llena la pantalla a
  costa de deformar; está ahí para quien lo prefiera así.
* **No tocar nada** — como antes.

En un monitor de 16:9 esto no hace nada, porque no hay nada que ganar.

## Novedades 1.31.0 — teclado y ratón por juego

Los juegos de Xbox 360 se pensaron para un mando, y rexglue sabe emular uno con el
teclado, pero el reparto de teclas que trae de serie sirve para probar un juego, no
para jugarlo: la puntería va en las flechas y A está en la tecla «ñ». Un shooter así
no hay quien lo juegue.

Ahora ReForge trae **repartos de teclas por tipo de juego** y sabe cuál le toca a cada
uno (`reforge/mnklayouts.py`):

| Reparto | Para qué | Cómo se juega |
|---|---|---|
| Shooter en primera persona | Call of Duty, Halo, Bioshock, Borderlands… | Ratón para apuntar, clic izquierdo disparar, clic derecho apuntar, WASD, Espacio saltar, R recargar, G granada |
| Shooter de coberturas | Gears of War, Mass Effect, Vanquish… | Igual, con A en Espacio para cubrirse y correr y el cuerpo a cuerpo en V |
| Acción y aventura | Castlevania, Batman, Devil May Cry, Ben 10… | El ratón mueve la cámara, clic izquierdo ataque rápido, clic derecho ataque fuerte |
| Conducción | Forza, Need for Speed, DiRT, Burnout… | W acelerar, S frenar, A y D girar, Espacio freno de mano |
| Lucha | Street Fighter, Mortal Kombat, Tekken… | WASD y las flechas, los seis botones en U I O / J K L |
| Teclado | Plataformas, deportes, arcade | WASD y las flechas, los botones en Espacio y J K L I |
| Puntero | Angry Birds, pinball, puzles | El ratón es el stick derecho y el clic izquierdo es A |
| Clásico | — | El reparto original del SDK, por si lo prefieres |

El ratón entra de verdad: además de las teclas, los repartos usan los botones del ratón
(`MouseLeft`, `MouseRight`, `MouseMiddle`, `MouseX1`), que es lo que convierte la
emulación en algo jugable con teclado y ratón.

**Y funcionan los dos a la vez.** Con «Encenderlo solo cuando no haya ningún mando
conectado» (activado de serie), ReForge mira antes de cada partida: si hay un mando
Xbox enchufado se juega con el mando, y si no, enciende el teclado y el ratón con el
reparto que le toca al juego. No hay que tocar nada ni cambiar de opción para pasar de
uno a otro: se enchufa el mando y ya. Y como esto se decide al arrancar, el reparto
elegido a mano en 🎮 Opciones del juego → Controles se respeta siempre.

## Novedades 1.30.0 — rendimiento automático y actualizaciones

- **Ajuste por RAM además de VRAM.** La caché de texturas vive en la VRAM, pero cuando esta se llena el driver
  la desborda a la RAM del PC. Ahora el presupuesto se limita también por la RAM instalada (la octava parte
  como mucho): en un equipo de 32 GB no cambia nada, en uno de 8 GB evita tirones por falta de memoria.
- **Caché de shaders que no se pierde.** rexglue guarda lo que traduce en
  `Documentos/<juego>/cache/shaders/shareable` (`<TITLEID>.xsh` y un `.xpso` por ruta de imagen). ReForge la
  guarda dentro del proyecto tras cada partida, la restaura si se borra, **la reaprovecha entre proyectos del
  mismo juego** (recompilar no empieza de cero) y avisa de que cambiar RTV ↔ ROV estrena pipelines. Se puede
  exportar e importar desde ⚡ Optimizar.
- **Montón del juego automático.** Si en el registro aparece que al juego se le acabó su montón
  (`rexcrt_heap`), ReForge sube `rexcrt_heap_size_mb` para la próxima partida (512 → 768 → 1024).
- **Marcas de depuración apagadas** (`gpu_debug_markers`, `kernel_debug_monitor`): no hacen falta para jugar.
- **Revisión del PC** en el barrido: RAM libre, planificación de GPU por hardware (HAGS), grabación en segundo
  plano (Game DVR), Modo de juego y plan de energía. Solo informa; esos ajustes son de Windows.
- **Actualizaciones desde GitHub.** ReForge compara su versión con la última publicada, avisa y puede
  instalarla sola. Comprueba el tamaño y el SHA-256 del instalador antes de ejecutarlo. En Ajustes →
  Actualizaciones se elige el repositorio, si se instalan sin preguntar y si se incluyen versiones de prueba.

Cada cvar nueva solo se escribe si el runtime del juego la trae (se comprueba en `rexgpu-xenos.dll` y
`rexruntime.dll`), así que una versión antigua del SDK no se ve afectada.

---

## Novedades 1.4.0 — el juego arranca y se configura

- **▶ Jugar vigilado + reparación automática.** Si el juego se cierra con
  `Call to invalid or unregistered function at guest address 0x…`, ReForge declara la dirección en
  `reforge_functions.toml`, regenera, recompila y vuelve a probar hasta que el juego quede abierto.
  También desde **🔧 Reparar** (lee el último log de `logs/` junto al .exe).
- **🎮 Opciones del juego:** pantalla completa, VSync, escala 1×–3×, FSR/CAS, FXAA, anisotrópico,
  mandos SDL/XInput, teclado y ratón con teclas editables, audio. Se escriben en `<juego>.toml`.
- **Doble clic en el .exe:** gancho `OnConfigurePaths` en `src/*_app.h` que encuentra `assets`.
- Límites del runtime: en Windows solo Direct3D 12 (Vulkan no viene compilado en el SDK; OpenGL y
  D3D11 no existen en rexglue) y no hay limitador de FPS propio (usa VSync o el del driver).

## Perfil de análisis 1.3.3

Antes del codegen, si el XEX coincide con Title ID `415608E4`, Media ID
`1A15DA04` y versión `0.0.0.2`, se añade `0x8262E8B8 = {}` a
`reforge_functions.toml`. Esta dirección fue observada en un fallo de ejecución
y no estaba registrada en las fuentes suministradas. ReXGlue determina su
implementación y límites a partir del XEX; no se introduce una función vacía.
Se conservan las declaraciones manuales y se guardan copias `.bak-*` antes de
insertar el ajuste. Otros identificadores no reciben este perfil. La identidad
se verifica por metadatos, no por hash del ejecutable. No prueba compatibilidad
completa: el arranque real sigue pendiente de validación en Windows.

Después de actualizar, abre el proyecto existente, selecciona Configurar,
Codegen y Compilar; no necesitas volver a extraer assets. Luego pulsa Jugar.

## Arranque 1.3.2

«Jugar» prepara rexgpu-xenos del SDK junto al ejecutable y pasa
`--gpu_plugin=xenos` junto con `--game_data_root`. También actualiza el lanzador.
Los accesos directos nuevos incluyen ambos argumentos. La preparación valida
assets/default.xex y selecciona la DLL según el tipo de compilación registrado.
El doble clic directo en el EXE del juego sigue requiriendo parámetros: utiliza
«Jugar» o el BAT generado. No se ha verificado el arranque real del juego en Windows.

## Correcciones 1.3.1

- El Taller vuelve a configurar CMake inmediatamente antes de compilar, después
  de generar las fuentes. También se aplica al seleccionar solo «Compilar».
- Si esa reconfiguración falla, no se inicia la compilación.
- Bloqueo por proyecto entre instancias de ReForge Studio, liberado al terminar
  o cancelar. No bloquea herramientas externas iniciadas manualmente: evita
  ejecutar CMD/Ninja sobre el mismo proyecto mientras el Taller trabaja.
- Cancelación del codegen incluso sin salida de texto; en Windows se solicita
  terminar el árbol de procesos. Al cerrar, se espera a que termine el pipeline.
- Pruebas de regresión incluidas en `tests/test_pipeline.py` y en `build_release.bat`.

## Novedades 1.3 — del XEX al .exe x64 que se ejecuta

- **Codegen con corrección automática**: cuando rexglue informa «UnresolvedCall … target not in
  any function», ReForge declara esas direcciones como funciones (sin tamaño, rexglue descubre
  su final) en `reforge_functions.toml`, lo incluye desde `[entrypoint]` del manifiesto y
  reintenta solo (hasta 8 rondas). El archivo se conserva y puedes editarlo.
- **Clang obligatorio**: rexglue no compila con MSVC. Si `build` estaba configurado con
  `cl.exe`, se borra solo la caché de CMake y se reconfigura con Clang.
- **▶ Jugar**: ejecuta el `.exe` x64 recompilado con `--game_data_root=<proyecto>\assets`.
  Se crea `Jugar <proyecto>.bat` junto al `.exe` y puedes crear un acceso directo en el
  Escritorio. La Biblioteca también tiene ▶.

## Novedades 1.2 «todo incluido»

- **Entorno** integrado: detecta y descarga rexglue, CMake, Ninja, Clang 20+ y Visual Studio
  Build Tools, y se autoconfigura en el primer arranque. Inicio avisa si falta algo.
- **Taller adaptado al rexglue actual**: extrae el juego antes del `init` (`--xex-path`
  obligatorio), lee el target real de codegen del manifiesto y pasa el SDK a CMake.
- **El instalador** permite elegir la carpeta del programa y la de proyectos, y descarga
  el SDK de rexglue dentro del programa (`<programa>\tools\rexglue-sdk`). Si hay un
  `rexglue-sdk-*-win-amd64.zip` junto al instalador, lo usa sin conexión. El SDK se
  conserva al actualizar.
- **Parches incluidos**: Utilidades Xbox viene dentro y se instala o actualiza solo.
  El antiguo parche «Entorno rexglue» se retira automáticamente.
- **Actualizar**: ejecuta el nuevo `ReForgeStudio-Setup-x.y.z.exe`, o desde
  *Parches → Actualizar ReForge Studio…*.

