# ReForge Studio 1.38.0

Interfaz de escritorio estilo consola para recompilar juegos de Xbox 360 a PC con
[rexglue-sdk](https://github.com/rexglue/rexglue-sdk) y
[XenonRecomp](https://github.com/hedge-dev/XenonRecomp), ampliable con **parches**.

> Proyecto independiente, sin relación con Microsoft ni Xbox. Úsalo solo con juegos que
> poseas legalmente.

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

## Instalar en Windows

1. Ejecuta **`build_release.bat`** (una vez, en un PC con Python 3.10+). Genera
   `dist\ReForgeStudio-Setup-1.3.3.exe`, el instalador completo.
2. Abre el instalador, elige carpetas y deja marcada la descarga de rexglue SDK. Crea el
   **acceso directo en el Escritorio**, la entrada del menú Inicio y la desinstalación en
   *Configuración → Aplicaciones*.
3. Abre ReForge Studio → **Entorno → «Preparar todo»** para instalar lo que falte
   (Visual Studio Build Tools, LLVM) con winget.

### Actualizar ReForge Studio

Ejecuta el instalador de una versión nueva. El instalador:

| Situación detectada | Qué hace |
|---|---|
| No hay instalación | Instala |
| Tienes una versión anterior | **Actualiza** en la misma carpeta |
| Tienes la misma versión | Repara (reinstala los archivos del programa) |
| Tienes una versión más nueva | Avisa y solo continúa si confirmas |

La actualización es **atómica**: prepara la versión nueva aparte y solo entonces la
intercambia con la anterior. Si algo falla, tu versión anterior queda intacta.
Tus proyectos, ajustes y parches están en `%APPDATA%\ReForgeStudio` y nunca se tocan.

Instalación desatendida: `ReForgeStudio-Setup-1.3.3.exe --silent [--dir RUTA] [--workspace RUTA] [--sdk] [--sdk-zip ZIP] [--no-desktop] [--force]`

---

## Parches

Un parche es un archivo **`.rfpatch`** que añade secciones y funciones sin modificar el
programa. La página **Parches** muestra la versión instalada del núcleo y, por cada parche,
su versión, estado, novedades, créditos y fecha de instalación.

### Por qué un parche no puede romper ReForge Studio

- **Integridad:** cada archivo del parche se verifica con SHA-256. Un parche dañado o
  modificado se rechaza.
- **Compatibilidad:** cada parche declara la versión del núcleo que necesita
  (`requires_core`) y la API (`api`). Si no encaja, aparece como *incompatible* y no se carga.
- **Aislamiento:** si un parche falla al cargar, se marca con *error* y se retira todo lo que
  hubiera añadido a la interfaz. El resto de la app y los demás parches siguen funcionando.
- **Protección contra caídas:** si la app se cierra inesperadamente mientras carga un
  parche, en el siguiente arranque ese parche se desactiva solo y te avisa.
- **Revertir:** al actualizar un parche se guarda la versión anterior. Un botón la restaura.
- **Modo seguro:** *Parches → Reiniciar en modo seguro* (o mantener **Shift** al abrir, o
  `--safe-mode`) arranca sin ningún parche.

### Parche incluido: Utilidades Xbox v1.0.1

Integra las funciones del **360 Utility Batch Create Extract v1.2** y de **Qwix**:

| Pestaña | Función |
|---|---|
| ISO → Carpeta | Extracción por lotes de ISOs de Xbox 360 **y Xbox Clásica**, con título, Title ID y región. Opcional: borrar la ISO tras extraer (a la papelera). |
| Carpeta → ISO | Creación por lotes de ISOs desde carpetas con `default.xex`/`default.xbe`. Creador XDVDFS **nativo**, validado contra `extract-xiso` en ambos sentidos. |
| Xbox Clásica | ISO de Xbox original → carpeta (y al revés), con revisión de nombres FATX. |
| Herramientas | Abre 360mpGui, Iso2God, God2Iso, Xbox Image Browser, abgx360, ImgBurn y Qwix desde tu carpeta `x_tool`. Botón para registrar MSCOMCTL.OCX. |
| FTP | Envía un juego a la consola (Avalaunch, UnleashX, XBMC, Aurora…), omitiendo nombres no válidos para FATX (>42 caracteres). |
| Limpieza | Borra carpetas de juego **a la papelera** por defecto. El borrado permanente exige escribir `ELIMINAR`. |

Cambios respecto al 360 Utility original: no usa clics automáticos con coordenadas fijas
(fallaban con otra resolución o escala de pantalla); en su lugar abre la herramienta y te
indica los pasos. Las herramientas de terceros no se incluyen: se usan desde tu `x_tool`.

### Entorno rexglue (integrado desde la 1.2; antes era un parche)

Resuelve «No se pudo iniciar rexglue» y adapta el Taller al rexglue actual:

- **Asistente:** detecta rexglue, Visual Studio Build Tools (C++), Clang 20+, CMake 3.25+ y Ninja.
  *Preparar todo* descarga el SDK oficial desde GitHub Releases
  (`%LOCALAPPDATA%\ReForgeStudio\tools\rexglue-sdk\<versión>`) y guarda las rutas en Ajustes.
  Lo que falte se instala con winget. Alternativas: *Instalar desde .zip* o *Usar un SDK existente*.
- **Taller:** el `rexglue init` actual exige el XEX, así que el orden pasa a ser
  Juego → assets → Verificar XEX → `rexglue init --project-name … --project-root … --xex-path assets/default.xex --game-root assets`
  → CMake (con `CMAKE_PREFIX_PATH` al SDK) → Codegen → Compilar.
- El target de codegen se lee del manifiesto: rexglue normaliza el nombre
  (`angry_birds_trilogy` → `angrybirdstrilogy_codegen`).
- Si tu rexglue es una versión antigua (`--app_name/--app_root`), se usa la sintaxis antigua.

---

## Crear tus propios parches

```
patches/mi_parche/
  manifest.json
  plugin.py          ← define register(api)
  …otros .py
```

`manifest.json`:

```json
{
  "id": "mi-parche",
  "name": "Mi parche",
  "version": "1.0.0",
  "author": "Yo",
  "api": 1,
  "requires_core": ">=1.1.0,<2.0.0",
  "entry": "plugin.py",
  "description": "Qué hace",
  "changelog": [{"version": "1.0.0", "date": "2026-10-15", "notes": ["Primera versión"]}]
}
```

`plugin.py`:

```python
def register(api):
    page = api.ui.QtWidgets.QLabel("¡Hola desde mi parche!")
    api.add_page("main", "★   Mi parche", "Mi parche", page)
    api.add_home_tile("★", "Mi parche", "Descripción corta", lambda: api.go("main"))
```

Empaquetar: `python tools\make_patch.py patches\mi_parche -o dist\patches`
(o `build_patches.bat` para todos). El script calcula los SHA-256 y verifica el resultado.

Lo que ofrece la API v1 (`reforge/plugin_api.py`): `add_page`, `add_home_tile`, `go`,
`notify`, `settings` (ajustes persistentes del parche), `data_dir`, componentes visuales en
`api.ui` (Tile, LogView, PathField, panel…), `api.runner` (tareas en segundo plano con
progreso y cancelación), `api.formats` (lector de ISO y XEX) y `api.helpers`.
Para publicar una versión nueva de tu parche, sube `version` y añade una entrada al
`changelog`: los usuarios verán «Actualizar v1.0.0 → v1.1.0» al instalarlo.

---

## Recompilación (Taller)

1. **Crear proyecto** → `rexglue init --app_name <nombre> --app_root <raíz>` (se salta si ya existe).
2. **Juego → assets** → extrae la ISO directamente en `<raíz>/assets`.
3. **Verificar XEX** → `default.xex` en la raíz de `assets`; lee el Title ID.
4. **Configurar** → `cmake -S <raíz> -B <raíz>/build -DCMAKE_BUILD_TYPE=Release`.
5. **Codegen** → `cmake --build build --target <nombre>_codegen`.
6. **Compilar** → `cmake --build build --parallel N`.

Configuración recomendada en Windows (**Ajustes**): *Detectar automáticamente*, generador
`Ninja`, compilador `clang-cl`, y `vcvars64.bat` para heredar el entorno de Visual Studio.

## Desarrollo

Hace falta **Python 3.11 o más nuevo**.

```bash
python -m pip install -r requirements.txt
python main.py                 # ejecutar desde el código
python tests/test_xiso.py      # lector de ISO
python tests/test_patches.py   # parches, instalador de parches, creador de ISO
```

| Script | Resultado |
|---|---|
| `build_release.bat` | Instalador + parches (lo recomendado) |
| `build_exe.bat` | `.exe` portable de un solo archivo, sin instalador |
| `build_patches.bat` | Solo los `.rfpatch` |
| `buscar_python.bat` | Lo llaman los tres anteriores: busca un Python 3.11+ (con el lanzador `py`, porque `python` en Windows suele ser una versión vieja) y activa UTF-8 en la consola |

`build_release.bat` ejecuta todas las pruebas de `tests\` antes de compilar, así
que no hay que añadirlas a mano cuando se crea una nueva.

Para que el actualizador automático vea una versión nueva, hay que publicar una
Release en GitHub y subir el instalador tal cual sale de `dist\`, sin cambiarle
el nombre (`ReForgeStudio-Setup-<versión>.exe`): ese es el nombre que busca.

## Herramientas (`tools/`)

Además de `make_patch.py` y `make_payload.py`, que empaquetan los parches y el
instalador, en `tools/` están las herramientas de los proyectos grandes hechos
con ReForge: el doblaje latino de *Call of Duty: Advanced Warfare* (parcheador,
interfaz y los scripts que comprueban el resultado e identifican el idioma de
cada pista) y las tres versiones de ReForge DualSense para juegos de PC
(XInput, Borderlands 2 con reescalado por IA, y `libScePad` de God of War).
Cada carpeta lleva su propio `README.md`; el índice está en
[`tools/README.md`](tools/README.md).

Atajos: `F11` pantalla completa · `Ctrl+1…9` secciones · flechas + `Enter` en los tiles.
