# Historial de versiones — ReForge Studio

> El README muestra solo lo esencial. Aquí está el detalle de cada versión.

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

