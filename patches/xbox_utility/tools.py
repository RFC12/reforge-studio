"""Herramientas externas de terceros (no se incluyen; se usan desde tu carpeta x_tool)."""
import os
import subprocess
import sys

TOOLS = [
    {"key": "360mpgui", "glyph": "🛠", "name": "360mpGui v1.5",
     "rel": "360 mp Gui v1.5.0.0/360mpGui v1.5.0.0.exe", "exe": "360mpgui v1.5.0.0.exe",
     "desc": "Arregla ISOs creadas para grabar o abrir en Xbox Image Browser (añade vídeo y relleno).",
     "howto": "Si avisa de que no hay unidad, pulsa OK. Ve a la pestaña «Create ISO» → "
              "«Convert an created ISO» y elige las ISOs una por una."},
    {"key": "iso2god", "glyph": "⇢", "name": "Iso2God",
     "rel": "iso2god-v1.3.8/Iso2God.exe", "exe": "iso2god.exe",
     "desc": "ISO → GOD (Games on Demand) para Xbox 360. También convierte ISOs de Xbox Clásica."},
    {"key": "god2iso", "glyph": "⇠", "name": "God2Iso",
     "rel": "God2Iso 1.0.5/God2Iso.exe", "exe": "god2iso.exe",
     "desc": "GOD → ISO. Luego pasa la ISO por 360mpGui y marca «Fix CreateIsoGood broken header» si hace falta."},
    {"key": "imgbrowser", "glyph": "🔍", "name": "Xbox Image Browser",
     "rel": "360 mp Gui v1.5.0.0/360mpTools/Xbox Image Browser.exe", "exe": "xbox image browser.exe",
     "desc": "Explora el contenido de ISOs de Xbox/Xbox 360 (Redline99).",
     "howto": "Si muestra un error de MSCOMCTL.OCX, usa «Registrar MSCOMCTL.OCX» (pide administrador) y vuelve a abrirlo."},
    {"key": "abgx360", "glyph": "✓", "name": "abgx360",
     "rel": "360 mp Gui v1.5.0.0/360mpTools/abgx360.exe", "exe": "abgx360.exe",
     "desc": "Verifica y corrige ISOs de Xbox 360 (stealth, PFI/DMI, AP25)."},
    {"key": "imgburn", "glyph": "◉", "name": "ImgBurn",
     "rel": "360 mp Gui v1.5.0.0/360mpTools/ImgBurn.exe", "exe": "imgburn.exe",
     "desc": "Graba ISOs en disco."},
    {"key": "qwix", "glyph": "⚡", "name": "Qwix",
     "rel": "Qwix/Qwix.exe", "exe": "qwix.exe",
     "desc": "Gestor de ISOs de Xbox Clásica (Team Avalaunch): ISO optimizadas, Boost FTP, gestión de títulos."},
]


def find_tool(xtool_dir, tool, override=""):
    if override and os.path.isfile(override):
        return override
    if not xtool_dir or not os.path.isdir(xtool_dir):
        return ""
    direct = os.path.join(xtool_dir, *tool["rel"].split("/"))
    if os.path.isfile(direct):
        return direct
    base_depth = xtool_dir.rstrip(os.sep).count(os.sep)
    for dp, dn, fn in os.walk(xtool_dir):
        if dp.count(os.sep) - base_depth >= 4:
            dn[:] = []
        for f in fn:
            if f.lower() == tool["exe"]:
                return os.path.join(dp, f)
    return ""


def guess_xtool_near(path):
    """Busca una carpeta x_tool junto a la ruta dada (estructura del 360 Utility)."""
    for cand in (path, os.path.dirname(path or "")):
        if cand and os.path.isdir(os.path.join(cand, "x_tool")):
            return os.path.join(cand, "x_tool")
    return ""


def launch(path):
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("No se encontró el ejecutable")
    if sys.platform == "win32":
        flags = 0x00000008  # DETACHED_PROCESS
        subprocess.Popen([path], cwd=os.path.dirname(path), creationflags=flags, close_fds=True)
    else:
        subprocess.Popen(["wine", path], cwd=os.path.dirname(path))


def register_mscomctl(xtool_dir):
    """Registra MSCOMCTL.OCX con permisos de administrador (necesario para Xbox Image Browser)."""
    if sys.platform != "win32":
        raise RuntimeError("Solo disponible en Windows")
    import ctypes
    tools_dir = os.path.join(xtool_dir, "360 mp Gui v1.5.0.0", "360mpTools")
    bat = os.path.join(tools_dir, "RunAsAdmin MSCOMCTL.OCX.bat")
    ocx = os.path.join(tools_dir, "MSCOMCTL.OCX")
    if os.path.isfile(bat):
        r = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", f'/c "{bat}"', tools_dir, 1)
    elif os.path.isfile(ocx):
        windir = os.environ.get("WINDIR", r"C:\Windows")
        regsvr = os.path.join(windir, "SysWOW64", "regsvr32.exe")
        if not os.path.isfile(regsvr):
            regsvr = os.path.join(windir, "System32", "regsvr32.exe")
        r = ctypes.windll.shell32.ShellExecuteW(None, "runas", regsvr, f'"{ocx}"', tools_dir, 1)
    else:
        raise FileNotFoundError("No se encontró MSCOMCTL.OCX en x_tool")
    if r <= 32:
        raise RuntimeError("Se canceló o falló la elevación de permisos")
