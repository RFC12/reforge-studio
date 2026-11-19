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
    check(0.1 <= float(data["sens"]) <= 5.0, f"{key}: la sensibilidad cabe en el control del diálogo")
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

print()
print(f"{len(fallos)} fallos" if fallos else "0 fallos")
sys.exit(1 if fallos else 0)
