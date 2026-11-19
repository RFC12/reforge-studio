# ReForge Studio 1.31.0

Interfaz de escritorio estilo consola para recompilar juegos de Xbox 360 a PC con
[rexglue-sdk](https://github.com/rexglue/rexglue-sdk) y
[XenonRecomp](https://github.com/hedge-dev/XenonRecomp), ampliable con **parches**.

> Proyecto independiente, sin relación con Microsoft ni Xbox. Úsalo solo con juegos que
> poseas legalmente.

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
