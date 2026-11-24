"""Base de datos de iconos por juego (Title ID), compartida entre todos los proyectos.

Con cada recompilación ReForge saca el icono oficial del propio juego —del XEX si no usa compresión LZX, o
de la imagen ya cargada en memoria en la primera partida (reforge_image.bin)— y lo guarda aquí, con nombre
`<TITLEID>.png` en la carpeta de ajustes de ReForge. Así el mismo juego en otro proyecto (o tras borrar el
build) sale con su icono ya puesto, sin depender de volver a extraerlo.

Solo se guardan iconos que trae el juego (nunca el de iniciales) y se leen sin red: la base es local.
"""
import os

from .core import config_dir

IMAGE_NAME = "reforge_icon.png"


def icons_dir():
    """Carpeta de la base de datos de iconos (se crea si falta)."""
    d = os.path.join(config_dir(), "icons")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return d
    return d


def icon_path(title_id):
    tid = (title_id or "").strip().upper()
    return os.path.join(icons_dir(), f"{tid}.png") if tid else ""


def lookup(title_id):
    """PNG del icono guardado para ese Title ID, o b"" si no está en la base."""
    path = icon_path(title_id)
    if not path or not os.path.isfile(path):
        return b""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return b""
    return data if data.startswith(b"\x89PNG") else b""


def remember(title_id, png):
    """Guarda el icono del juego en la base (para este y otros proyectos). True si se guardó."""
    path = icon_path(title_id)
    if not path or not png or not png.startswith(b"\x89PNG"):
        return False
    try:
        with open(path, "wb") as f:
            f.write(png)
    except OSError:
        return False
    return True


def count():
    """Cuántos juegos tiene la base (para mostrarlo en la interfaz)."""
    try:
        return len([f for f in os.listdir(icons_dir()) if f.lower().endswith(".png")])
    except OSError:
        return 0
