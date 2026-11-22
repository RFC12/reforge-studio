"""Movimiento suave por driver (NVIDIA Smooth Motion / AMD Fluid Motion): el juego a su velocidad real y el
driver interpola. No debe acelerar aunque haya desbloqueo de FPS, y debe fijar un ritmo estable."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge.game_options import GameOptions  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


print("Por defecto está desactivado")
check(GameOptions().smooth_motion is False, "smooth_motion por defecto = False")

print("Movimiento suave mantiene velocidad real y ritmo estable")
o = GameOptions()
o.smooth_motion = True
o.fps_unlocked = True          # aunque el usuario tenga el desbloqueo anotado…
o.fps_mode = "unlimited"       # …y el modo «sin límite»
v = o.runtime_values()
check(v.get("vsync") is True, "fuerza vsync (ritmo estable para interpolar)")
check(v.get("video_mode_refresh_rate") is not None, "no deja el modo «sin límite» (necesita un ritmo base)")
check(v.get("d3d12_allow_variable_refresh_rate_and_tearing") is False, "desactiva tearing/VRR variable")

print("Sin movimiento suave, el desbloqueo sí quita el límite")
o2 = GameOptions()
o2.smooth_motion = False
o2.fps_mode = "unlimited"
check(o2.runtime_values().get("vsync") is False, "modo «sin límite» sin smooth → vsync off")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
