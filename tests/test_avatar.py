"""La «imagen de jugador» del perfil viaja al .ini del juego (el menú Guía de 0.11 la dibuja igual).

En 0.11 no hay texturas a mano, así que el menú pinta la misma figura que enseña ReForge (hexágono, rayo,
estrella…) con sus colores; aquí se comprueba que ReForge los escribe en reforge_ext.ini.
python tests/test_avatar.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-avatar-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
sys.path.insert(0, ROOT)

from reforge import profile  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


def ini_for(avatar):
    root = tempfile.mkdtemp(prefix="reforge-game-")
    exe = os.path.join(root, "build", "juego.exe")
    os.makedirs(os.path.dirname(exe))
    open(exe, "wb").close()
    profile.write_ext_ini(exe, None, profile.Profile(gamertag="Roger", avatar=avatar))
    return open(profile.ext_ini_path(exe), encoding="utf-8").read()


print("Figura de la imagen de jugador")
print("  ", profile.avatar_style(profile.Profile(avatar="gen:2")))
check(profile.avatar_style(profile.Profile(avatar="gen:2"))[0] == "star", "gen:2 es la estrella")
check(profile.avatar_style(profile.Profile(avatar="gen:0"))[0] == "hex", "gen:0 es el hexágono (por defecto)")
check(profile.avatar_style(profile.Profile(avatar="") )[0] == "hex", "sin elegir nada, el hexágono")
check(profile.avatar_style(profile.Profile(avatar="avatar.png"))[0] == "none",
      "una foto propia no se puede dibujar en 0.11: se marca «none» (el menú pone el trofeo)")

print("Se escribe en reforge_ext.ini")
ini = ini_for("gen:2")
check("avatar_style = star" in ini, "el estilo de la imagen elegida")
check("avatar_fg = 5b8cff" in ini and "avatar_bg = 14224d" in ini, "y sus colores")
check("avatar_style = none" in ini_for("avatar.png"), "con foto propia, «none»")

print("El menú de 0.11 los usa")
menu = open(os.path.join(ROOT, "reforge", "ext11.py"), encoding="utf-8").read()
for pieza, que in (("avatar_style", "lee el estilo del perfil"),
                   ("DrawAvatar", "dibuja la figura en la cabecera"),
                   ("avatar_bg", "usa los colores del perfil"),
                   ("crown", "cubre todas las figuras (corona incluida)")):
    check(pieza in menu, que)

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
