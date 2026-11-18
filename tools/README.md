# tools/

Utilidades que acompañan a ReForge Studio. No forman parte de la aplicación:
son las herramientas con las que se empaquetan sus parches y con las que se
han hecho los proyectos grandes (doblaje latino, DualSense en PC).

## Empaquetado

| Archivo | Para qué sirve |
| --- | --- |
| `make_patch.py` | Empaqueta una carpeta de parche en un `.rfpatch` firmado con SHA-256. `python tools/make_patch.py patches/xbox_utility -o dist/patches` |
| `make_payload.py` | Empaqueta la app compilada (PyInstaller `--onedir`) como payload del instalador. `python tools/make_payload.py dist/ReForgeStudio build/installer` |

## Doblaje latino — Call of Duty: Advanced Warfare

Trae el doblaje latino de la versión de Xbox 360 a la versión de PC: busca cada
voz en los fastfiles del juego de PC, la sustituye por la de 360 (FLAC dentro de
los paks `spa_soundfile*.pak`) y rehace las referencias.

| Archivo | Para qué sirve |
| --- | --- |
| `aw_doblaje_latino.py` | El parcheador. Es también la librería que importan los demás scripts (`import aw_doblaje_latino as A`). |
| `aw_latino_gui.py` | Interfaz gráfica del parcheador. |
| `build_aw_latino.bat` | Compila `ReForge-Doblaje-Latino-AW.exe` con PyInstaller. |
| `aplicar_cargadas.ps1` | Espera a que el juego se cierre y aplica entonces las voces embebidas (`--solo-cargadas`), que no se pueden escribir con el juego abierto. |

### Comprobación del resultado

| Archivo | Para qué sirve |
| --- | --- |
| `aw_revisar_latino.py` | Qué voces de la campaña siguen apuntando al audio original de España tras el parche. |
| `aw_revisar_raiz.py` | Voces en paks `spa_` referenciadas desde fastfiles que no están en la carpeta `spanish`. |
| `aw_revisar_cargadas.py` | Voces guardadas completas dentro del fastfile (FLAC embebido, sin pak). |
| `aw_refs_sueltas.py` | Cualquier referencia (pak, desplazamiento, tamaño) a la zona original, sin exigir el prefijo que reconoce el parche. |
| `aw_revisar_bik.py` | Qué cinemáticas `.bik` están ya parcheadas. |
| `aw_textos.py` | Compara los textos de menús y subtítulos del PC (España) con los de 360 (latino), por clave. |

### Identificación de idioma y de voz

Estas usan `faster-whisper` y `ffmpeg` para decidir, sin oír nada a mano, qué
pista de audio es la latina.

| Archivo | Para qué sirve |
| --- | --- |
| `aw_pistas_bik.py` | Idioma de cada pista de un `.bik` y, en las españolas, la prueba del ceceo. |
| `aw_ceceo.py` | Distingue latino de España midiendo la energía de alta frecuencia en las «c/z» frente a las «s» de la misma pista. |
| `aw_encuesta_bik.py` | Transcribe las dos pistas en español de cada vídeo multi-idioma para decidir cuál es la latina. |
| `aw_texto_pistas.py` | Transcribe las pistas que se le indiquen y marca los modismos de España (*vosotros*, *vale*, *ordenador*…). |
| `aw_pistas_audio_log.py` | Transcribe las nueve pistas de un archivo, una por una. |
| `aw_voz_irons.py` | Qué pista tiene al actor latino de Irons: compara el timbre (MFCC) con frases suyas latinas y de España. |
| `aw_voz_ref.py` | Compara el timbre de varias pistas contra dos referencias de la misma sesión. |
| `aw_oir_nivel.py` | Transcribe las voces que un nivel reproduce ahora, para comprobar que son las latinas. |

Las rutas del juego, de `ffmpeg.exe` y del volcado de 360 están al principio de
cada script; cámbialas por las tuyas antes de usarlos.

## DualSense en juegos de PC

Tres variantes del mismo trabajo: presentar el DualSense (USB o Bluetooth) a un
juego de PC con vibración, gatillos adaptativos, barra de luz e iconos de
PlayStation.

| Carpeta | Juego / librería |
| --- | --- |
| `dualsense_pc/` | XInput (`xinput1_3.dll`) y `libScePad.dll`, versión original. |
| `bl2/` | Borderlands 2 (XInput de 32 bits) más el reescalado con IA de texturas y cinemáticas. Ver `bl2/README.md`. |
| `gow/` | God of War y otros juegos con la librería de Sony (`libScePad.dll`). Ver `gow/README.md`. |
