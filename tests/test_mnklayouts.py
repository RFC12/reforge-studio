"""Repartos de teclado y ratón por tipo de juego."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import mnklayouts as M                      # noqa: E402
from reforge.game_options import DEFAULT_KEYBINDS        # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


print("Repartos")
VALIDAS = {"MouseLeft", "MouseRight", "MouseMiddle", "MouseX1", "MouseX2", "MouseWheelX", "MouseWheelY"}
for key in M.ORDER:
    data = M.LAYOUTS[key]
    kb = M.keybinds(key)
    check(len(kb) == 24 and set(kb) == set(DEFAULT_KEYBINDS),
          f"{key}: los 24 botones del mando, ni uno de más")
    check(all(v.strip() for v in kb.values()), f"{key}: ningún botón se queda sin tecla")
    check(bool(data["titulo"]) and bool(data["ayuda"]), f"{key}: tiene nombre y explicación")
    check(0.1 <= float(data["sens"]) <= 10.0, f"{key}: la sensibilidad cabe en el control del diálogo")
    check("sens_x" in data and "sens_y" in data, f"{key}: tiene sensibilidad por eje")
    if data["mouse"]:
        check(float(data["sens"]) >= 3.0,
              f"{key}: sin el parche del SDK, la sensibilidad pasa de la zona muerta ({data['sens']})")
        check(0.1 <= float(data["sens_x"]) <= 10.0 and 0.1 <= float(data["sens_y"]) <= 10.0,
              f"{key}: los ejes caben en el rango del cvar")
    ratones = {t for v in kb.values() for t in v.split(",") if t.startswith("Mouse")}
    check(ratones <= VALIDAS, f"{key}: solo botones de ratón que entiende rexglue ({sorted(ratones) or 'ninguno'})")
    if data["mouse"]:
        resto = [kb[k] for k in ("keybind_rstick_up", "keybind_rstick_down",
                                 "keybind_rstick_left", "keybind_rstick_right")]
        check(all(v.strip() for v in resto),
              f"{key}: con el ratón apagado el stick derecho sigue teniendo teclas")

print("Un shooter se juega como un shooter")
sh = M.keybinds("shooter")
check(sh["keybind_right_trigger"] == "MouseLeft", "disparar es el clic izquierdo")
check(sh["keybind_left_trigger"] == "MouseRight", "apuntar es el clic derecho")
check(sh["keybind_lstick_up"] == "W" and sh["keybind_lstick_left"] == "A", "moverse con WASD")
check(sh["keybind_a"] == "Space", "saltar con Espacio")
check(M.LAYOUTS["shooter"]["mouse"] is True, "la puntería va con el ratón")
check(M.LAYOUTS["shooter"]["sens"] >= 3.0, "y con sensibilidad suficiente para que el juego la vea")
check(M.keybinds("carreras")["keybind_right_trigger"] == "W", "en carreras se acelera con W")
check(M.LAYOUTS["carreras"]["mouse"] is False, "en carreras el ratón no mueve nada")

print("Qué reparto le toca a cada juego")
for nombre, esperado in (("gearsofwar2latino", "cobertura"), ("Gears of War 2", "cobertura"),
                         ("Call of Duty: Advanced Warfare", "shooter"), ("halo3", "shooter"),
                         ("forza_horizon", "carreras"), ("street_fighter_iv", "lucha"),
                         ("castlevania_sotn", "accion"), ("ben_10_omniverse_tm", "accion"),
                         ("angry_birds_trilogy", "puntero"), ("fifa_14", "teclado")):
    got, _ = M.suggest(nombre)
    check(got == esperado, f"{nombre} → {got or 'sin reparto'} (esperado {esperado})")
check(M.suggest("un juego que no conozco") == ("", ""), "un juego desconocido no se inventa un reparto")
check(M.suggest("", "415608E4")[0] == "puntero", "el Title ID manda sobre el nombre")

print("Aplicar a unas opciones")


class Fake:
    keybinds = dict(DEFAULT_KEYBINDS)
    mnk_mouse = False
    mnk_sensitivity = 1.0
    mnk_layout = "auto"


o = Fake()
check(M.apply(o, "shooter") is True, "aplica el reparto pedido")
check(o.keybinds["keybind_right_trigger"] == "MouseLeft" and o.mnk_mouse is True,
      "deja las teclas y enciende el ratón")
check(o.mnk_layout == "shooter", "recuerda cuál se aplicó")
check(M.apply(o, "inventado") is False, "un reparto que no existe no cambia nada")

print("Dejarlo listo al compilar")
import tempfile                                               # noqa: E402
from reforge.game_options import GameOptions                  # noqa: E402

raiz = tempfile.mkdtemp(prefix="reforge-mnk-")
lay, texto = M.configure(raiz, "", "Gears of War 2")
guardado = GameOptions.load(raiz)
check(lay == "cobertura", "al compilar Gears of War le pone el reparto de coberturas")
check(guardado.mnk_mode is True, "deja el teclado y el ratón encendidos")
check(guardado.mnk_mouse is True, "y el ratón moviendo la cámara")
check(guardado.keybinds["keybind_right_trigger"] == "MouseLeft", "disparar queda en el clic izquierdo")
check(guardado.mnk_layout == "cobertura", "el reparto queda escrito, no en «auto»")
check("mando" in texto.lower(), "y lo dice en el registro del Taller")
check(M.configure(raiz, "", "Gears of War 2") == ("", ""), "al recompilar no vuelve a pisar las teclas")

raiz2 = tempfile.mkdtemp(prefix="reforge-mnk-")
o2 = GameOptions()
o2.mnk_auto = False
o2.save(raiz2)
check(M.configure(raiz2, "", "Halo 3") == ("", ""), "si el jugador lo lleva a mano, no se toca nada")

print("Proyectos de antes de los repartos")
raiz3 = tempfile.mkdtemp(prefix="reforge-mnk-")
import json                                                   # noqa: E402
import os as _os                                              # noqa: E402
from reforge.game_options import OPTIONS_FILE                 # noqa: E402

with open(_os.path.join(raiz3, OPTIONS_FILE), "w", encoding="utf-8") as f:
    json.dump({"mnk_mode": False, "mnk_mouse": False, "gpu_plugin": "xenos"}, f)
viejo = GameOptions.load(raiz3)
check(viejo.mnk_mode is True, "se les enciende el teclado y el ratón")
check(viejo.mnk_layout == "auto", "y el reparto queda pendiente de elegir")

print("Mando y teclado a la vez")
o3 = GameOptions()
o3.mnk_layout, o3.mnk_mode = "shooter", True
M.apply(o3, "shooter")
vals = o3.runtime_values()
check(vals["mnk_mode"] is True and vals["mnk_mouse"] is True, "el .toml enciende los dos")
check(vals["keybind_left_trigger"] == "MouseRight", "y escribe las teclas del reparto")
check(vals["input_backend"] in ("sdl", "xinput"), "el mando conserva su propio backend")

print("Parche de puntería del SDK")
import tempfile as _tmp                                        # noqa: E402
import os as _os2                                              # noqa: E402
import shutil as _sh                                           # noqa: E402

from reforge import sdk_patch                                  # noqa: E402

FUENTE = _os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), "fixtures_mnk_driver.cpp")
if _os2.path.isfile(FUENTE):
    arbol = _tmp.mkdtemp(prefix="reforge-sdk-")
    destino = _os2.path.join(arbol, "src", "input", "mnk")
    _os2.makedirs(destino)
    _sh.copyfile(FUENTE, _os2.path.join(destino, "mnk_input_driver.cpp"))
    check(sdk_patch.apply_mouseaim(arbol) is True, "se aplica sobre el código de rexglue")
    check(sdk_patch.apply_mouseaim(arbol) is False, "y no se vuelve a aplicar encima (idempotente)")
    texto = open(_os2.path.join(destino, "mnk_input_driver.cpp"), encoding="utf-8").read()
    check("REXCVAR_DEFINE_DOUBLE(mnk_sensitivity_x" in texto, "añade el cvar de sensibilidad horizontal")
    check("REXCVAR_DEFINE_DOUBLE(mnk_sensitivity_y" in texto, "y el de la vertical")
    check(texto.count("REXCVAR_GET(mnk_sensitivity_x)") == 1, "y los usa en el cálculo del stick")
    check("double reforge_aim_x = 0.0;" in texto, "declara el recorrido pendiente")
    check("kBaseScale" not in texto, "quita el cálculo viejo de píxeles por fotograma")
    # parche del arranque tolerante
    rt_dir = _os2.path.join(arbol, "src", "system")
    _os2.makedirs(rt_dir)
    with open(_os2.path.join(rt_dir, "runtime.cpp"), "w", encoding="utf-8") as f:
        f.write("    if (rejected > 0) {\n"
                '      REXSYS_ERROR("PPCImageInfo registration: {} func_mappings entries rejected", rejected);\n'
                "      Shutdown();\n"
                "      return X_STATUS_UNSUCCESSFUL;\n"
                "    }\n")
    check(sdk_patch.apply_funcmap_tolerant(arbol) is True, "el arranque se hace tolerante a funciones fuera del módulo")
    check(sdk_patch.apply_funcmap_tolerant(arbol) is False, "y no se aplica dos veces")
    rt = open(_os2.path.join(rt_dir, "runtime.cpp"), encoding="utf-8").read()
    check("func_mappings entries skipped" in rt, "ahora avisa y sigue")
    check("Shutdown();" not in rt, "ya no aborta el arranque por esto")
    # parche del resolve vacío
    gdir = _os2.path.join(arbol, "src", "graphics", "util")
    _os2.makedirs(gdir)
    with open(_os2.path.join(gdir, "draw.cpp"), "w", encoding="utf-8") as f:
        f.write("  assert_true(x0 < x1 && y0 < y1);\n"
                "  if (x0 >= x1 || y0 >= y1) {\n"
                '    REXGPU_ERROR("Resolve region is empty");\n'
                "    return false;\n"
                "  }\n")
    check(sdk_patch.apply_resolve_noop(arbol) is True, "un resolve vacío deja de abortar el frame")
    check(sdk_patch.apply_resolve_noop(arbol) is False, "y no se aplica dos veces")
    dw = open(_os2.path.join(gdir, "draw.cpp"), encoding="utf-8").read()
    check("info_out.coordinate_info.width_div_8 = 0;" in dw and "return true;" in dw,
          "devuelve tamaño 0 con éxito, como espera el llamador")
    check("return false;" not in dw, "ya no devuelve false en un resolve vacío")
    # apply_all degrada con elegancia: un parche cosmético que no encaja no tumba la compilación
    vacio = _tmp.mkdtemp(prefix="reforge-sdkv-")
    cambio, aplicados, saltados = sdk_patch.apply_all(vacio)
    nombres_saltados = [n for n, _m in saltados]
    check("iconos de botones PlayStation" in nombres_saltados,
          "un parche que no encaja (SDK nuevo) se salta en vez de abortar")
    check(cambio is False, "sin árbol de rexglue no se cambia nada, pero no revienta")
    check(sdk_patch.is_applied(arbol) is False, "is_applied no da por bueno un árbol sin el resto de parches")
else:
    print("  (sin el código de rexglue a mano: no se puede probar el parche aquí)")

print()
print(f"{len(fallos)} fallos" if fallos else "0 fallos")
sys.exit(1 if fallos else 0)
