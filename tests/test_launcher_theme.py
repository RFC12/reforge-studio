"""Launcher temático de los juegos recompilados: nombre bonito y color del icono."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import game  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


print("Nombre bonito a partir de la carpeta")
check(game.display_name("asura_s_wrath") == "Asura's Wrath", "asura_s_wrath → Asura's Wrath")
check(game.display_name("gears_of_war_2_latino") == "Gears Of War 2 Latino", "gears_of_war_2_latino → Gears Of War 2 Latino")
check(game.display_name("") == "Juego", "vacío → Juego")

print("Color de consola según el icono")
check(game._console_color((220, 20, 20)) == "C", "rojo → C (rojo claro)")
check(game._console_color((20, 210, 90)) == "A", "verde → A (verde claro)")
check(game._console_color(None) == "F", "sin color → F (blanco)")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
