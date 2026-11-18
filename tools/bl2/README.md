# ReForge DualSense + HD — Borderlands 2 (PC)

Versión de ReForge DualSense para juegos de PC que usan XInput, probada en
Borderlands 2 (`Binaries\Win32`). Sustituye `xinput1_3.dll` y lee el
DualSense / DualSense Edge directamente por HID (USB o Bluetooth).

| Archivo | Para qué sirve |
| --- | --- |
| `dualsense_bl2e.cpp` | La DLL completa: mando por HID, vibración, gatillos adaptativos, barra de luz e iconos de PlayStation (sustitución de texturas por huella en D3D11/D3D9). |
| `xi_bl2.def` | Exportaciones de `xinput1_3.dll` (incluidas las ordinales sin nombre 100-103 que usa el juego). |
| `build_bl2e.cmd` | Compila la DLL de 32 bits con las Build Tools de Visual Studio. Ajusta la ruta de `vcvars32.bat` si tu instalación es otra. |
| `reforge_dualsense.ini` | Configuración junto al `.exe` del juego (fuerza de los gatillos, color de la barra, volcado de texturas…). |
| `reforge_hd.py` | Escala con Real-ESRGAN las texturas de interfaz que la DLL ha volcado y las deja como pak en `reforge_paks\HD\<huella>.png`. Solo procesa las nuevas, se puede repetir tras jugar. |
| `cine_hd.py` | Reescala con IA las cinemáticas Bink 1 y las vuelve a codificar conservando todas las pistas de audio con sus mismos identificadores. |
| `galeria9b.py` | Vuelca en una hoja de contactos las texturas capturadas, para localizar a mano la huella de un icono. |

## Uso rápido

```bat
build_bl2e.cmd
copy xinput1_3.dll "...\Borderlands 2\Binaries\Win32\"
copy reforge_dualsense.ini "...\Borderlands 2\Binaries\Win32\"
```

Las rutas de `ffmpeg.exe`, `realesrgan-ncnn-vulkan.exe` y RAD Video Tools están
al principio de `cine_hd.py`; cámbialas por las tuyas antes de usarlo.
