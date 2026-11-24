"""Menú Guía dentro del juego (botón Xbox/PS).   python tests/test_guide_menu.py"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-guide-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
sys.path.insert(0, ROOT)
from reforge import ext_cpp, game_options as go, profile  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


src = ext_cpp.EXT_SOURCE
print("Extensión")
check("class GuideMenu" in src and "GetStateForUI" in src, "lee el mando directamente (aunque el juego esté en pausa)")
check("kGuideButton" in src and "~kGuideButton" in src, "el botón Guía nunca le llega al juego")
check("g_guide_open.load()" in src and "gp.buttons = 0" in src, "con el menú abierto el juego no recibe el mando")
check("BroadcastNotification(0x00000009" in src, "avisa al juego como la consola (XN_SYS_UI): la mayoría se pausa")
check("RequestClose()" in src and "¿Salir del juego?" in src, "salir del juego con el mando, con confirmación")
check("ListAchievements()" in src and "GetUnlockTime" in src, "logros con fecha de desbloqueo")
check("Silenciar el juego" in src and 'SetFlagByName(\"audio_mute\"' in src,
      "botón para silenciar el juego desde el menú Guía (se aplica al momento)")
check("Prefs().mute == 1" in src and 'key == "mute"' in src, "el silencio elegido se recuerda en el menú")
check("Idioma del juego" in src and "kLanguageNames" in src and "g_language.store" in src,
      "idioma del juego en Ajustes, aplicado al momento por XGetLanguage")
check("XGetLanguage_hook" in src and "GameLanguage()" in src, "el juego ve el idioma elegido")
check("reforge_playtime.txt" in src and "reforge_menu.ini" in src, "tiempo de juego total y ajustes guardados por juego")
check("ImGuiKey_Home" in src, "también con la tecla Inicio del teclado")
check("&achievements()" in ext_cpp.APP_BLOCK, "el juego le pasa sus logros")
check("RegisterUnlockCallback" in src and "ToastSlot" in src,
      "el aviso sale al desbloquear (no solo si el runtime pide la notificación)")
check("pending.event.achievement.id == event.achievement.id" in src,
      "el mismo logro no se avisa dos veces (desbloqueo + notificación)")
check("[ReForge] Logro desbloqueado:" in src, "queda en el log del juego cada aviso mostrado")

print("Partidas (ranuras)")
check("class SaveSlots" in src and "kSlotCount = 4" in src, "4 ranuras de partidas en el menú Guía")
check("CaptureGuestOutput" in src and "thumb.rgba" in src, "cada ranura guarda una miniatura de la imagen del juego")
check("struct SlotRestoreAtStartup" in src and "WaitForSingleObject" in src,
      "cargar: el juego se reinicia solo y pone las partidas antes de leerlas")
check("reforge_restart.flag" in src, "avisa a ReForge de que es un reinicio, no un fin de partida")
from reforge import game  # noqa: E402
import time  # noqa: E402
gexe = os.path.join(TMP, "g", "juego.exe")
os.makedirs(os.path.dirname(gexe))
open(gexe, "w").write("")
check(not game.consume_restart_flag(gexe), "sin aviso: partida normal")
open(os.path.join(TMP, "g", "reforge_restart.flag"), "w").write("x")
check(game.consume_restart_flag(gexe) and not game.consume_restart_flag(gexe), "el aviso se usa una vez")
open(os.path.join(TMP, "g", "reforge_restart.flag"), "w").write("x")
old = time.time() - 600
os.utime(os.path.join(TMP, "g", "reforge_restart.flag"), (old, old))
check(not game.consume_restart_flag(gexe), "un aviso viejo no cuenta")

print("Configuración")
check(go.GameOptions().runtime_values()["guide_button"] is True, "rexglue deja pasar el botón Xbox/PS")
check(go.GameOptions(guide_menu=False).runtime_values()["guide_button"] is False, "se puede desactivar")
exe = os.path.join(TMP, "gears_of_war_2_latino", "build", "gearsofwar2.exe")
os.makedirs(os.path.dirname(exe))
open(exe, "w").write("")
profile.write_ext_ini(exe, go.GameOptions())
ini = open(profile.ext_ini_path(exe), encoding="utf-8").read()
check("guide_menu = 1" in ini and "game_name = Gears Of War 2 Latino" in ini and "avatar = " in ini,
      "reforge_ext.ini lleva el menú, el nombre del juego y el avatar")
profile.write_ext_ini(exe, go.GameOptions(guide_menu=False))
check("guide_menu = 0" in open(profile.ext_ini_path(exe), encoding="utf-8").read(), "desactivado en el .ini")
print(f"\nTodas las pruebas pasaron ({ok}).")
