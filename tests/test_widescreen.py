"""Pantalla panorámica: elegir el parche de aspecto y quitar las bandas negras."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import pc_enhance as P                 # noqa: E402
from reforge.game_options import GameOptions        # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


class Patch:
    def __init__(self, name):
        self.name = name


ULTRA, ANCHA, CINE = 2560 / 1080, 1920 / 1080, 3840 / 1080

print("Reconocer los parches de aspecto")
for nombre in ("Widescreen Fix", "Ultrawide 21:9", "Custom: Aspect Ratio 16:9", "Disable Pillarboxing",
               "Remove Letterboxing", "32:9 Aspect Ratio"):
    check(P.classify(nombre) == "widescreen", f"«{nombre}» es un parche panorámico")
for nombre in ("Unlock FPS", "Disable Motion Blur", "Shadow Fix", "HUD Fix", "Infinite Ammo"):
    check(P.classify(nombre) != "widescreen", f"«{nombre}» no se confunde con uno")

print("Qué relación deja cada parche")
check(abs(P.patch_aspect("Ultrawide 21:9") - 21 / 9) < 0.01, "«21:9» se lee del nombre")
check(abs(P.patch_aspect("32:9 Aspect Ratio") - 32 / 9) < 0.01, "«32:9» también")
check(abs(P.patch_aspect("Widescreen Fix") - 16 / 9) < 0.01, "sin número se supone 16:9")
check(abs(P.patch_aspect("Ultrawide Support") - 21 / 9) < 0.01, "«ultrawide» sin número son 21:9")

print("Elegir el parche para la pantalla")
todos = [Patch(n) for n in ("Unlock FPS", "Widescreen Fix", "Ultrawide 21:9", "32:9 Aspect Ratio")]
check(P.best_widescreen(todos, ULTRA).name == "Ultrawide 21:9", "en 21:9 gana el parche de 21:9")
check(P.best_widescreen(todos, CINE).name == "32:9 Aspect Ratio", "en 32:9 gana el de 32:9")
check(P.best_widescreen(todos, ANCHA) is None, "en 16:9 no se toca nada: no hay bandas que quitar")
check(P.best_widescreen([Patch("Unlock FPS")], ULTRA) is None, "si el juego no tiene parche, no se inventa")
check(P.best_widescreen([Patch("Widescreen Fix")], ULTRA).name == "Widescreen Fix",
      "con solo uno de 16:9 se usa ese (mejor que 4:3)")
check(P.best_widescreen([Patch("32:9 Aspect Ratio"), Patch("Ultrawide 21:9")], ULTRA).name == "Ultrawide 21:9",
      "se prefiere quedarse corto antes que pasarse de ancho")
check(P.panoramic(ULTRA) and not P.panoramic(ANCHA), "21:9 es panorámica y 16:9 no")

print("Recomendación completa")
rec = P.recommended(todos, wide_target=ULTRA)
check(any(p.name == "Ultrawide 21:9" for p in rec), "el parche panorámico entra en la recomendación")
check(any(p.name == "Unlock FPS" for p in rec), "sin quitar lo que ya se recomendaba")
check(not any(P.classify(p.name) == "widescreen" for p in P.recommended(todos)),
      "sin pantalla panorámica no se mete ningún parche de aspecto")
check("panorámica" in P.describe(rec), "el resumen lo menciona")

print("Bandas negras")
o = GameOptions()
check(o.letterbox_value() is True, "de serie se respeta la forma del juego")
o.widescreen_patched = True
check(o.letterbox_value() is False, "con el juego parcheado la imagen llena la pantalla")
o.widescreen = "off"
check(o.letterbox_value() is True, "«no tocar nada» manda sobre el parche")
o.widescreen, o.widescreen_patched = "on", False
check(o.letterbox_value() is False, "«estirar» quita las bandas aunque no haya parche")
o.widescreen = "auto"
check(o.runtime_values()["present_letterbox"] is True, "lo que se escribe en el .toml sale de ahí")

print()
print(f"{len(fallos)} fallos" if fallos else "0 fallos")
sys.exit(1 if fallos else 0)
