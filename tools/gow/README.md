# ReForge DualSense — libScePad (God of War y similares)

Algunos juegos de PC usan la librería de Sony (`libScePad.dll`) y solo ven el
DualSense por cable. Esta DLL de reemplazo:

* pasa todas las llamadas a la original (renómbrala a `libScePad_sony.dll`);
* si la original no ve el mando (por ejemplo por Bluetooth), lee el DualSense
  por HID y se lo entrega al juego en el mismo formato (botones, sticks,
  L2/R2, panel táctil), y aplica la vibración y la barra de luz que pide;
* añade gatillos adaptativos: L2 con resistencia al apuntar, R2 con punto de
  disparo y vibración del gatillo en los golpes fuertes, por USB o Bluetooth.

| Archivo | Para qué sirve |
| --- | --- |
| `scepad_proxy3.cpp` | La DLL de reemplazo. |
| `ds3.def` | Exportaciones con las ordinales que espera el juego. |
| `build3.cmd` | Compila la DLL de 64 bits con las Build Tools de Visual Studio. |

## Uso rápido

```bat
build3.cmd
ren "...\God of War\libScePad.dll" libScePad_sony.dll
copy libScePad3.dll "...\God of War\libScePad.dll"
```
