"""Perfil de jugador de ReForge (Gamertag, imagen, Xbox Live simulado) y notificación de logros.

Se guarda una vez en la carpeta de ajustes y se aplica a cada juego escribiendo «reforge_ext.ini»
junto a su .exe; la extensión C++ (ext_cpp.py) lo lee al arrancar el juego.
"""
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass, fields

from .core import config_dir

TOAST_POSITIONS = [
    ("top_left", "Superior izquierda"), ("top_center", "Superior centro"), ("top_right", "Superior derecha"),
    ("bottom_left", "Inferior izquierda"), ("bottom_center", "Inferior centro"),
    ("bottom_right", "Inferior derecha"),
]
GAMERTAG_RE = re.compile(r"^[A-Za-z0-9 ]{1,15}$")

# Las imágenes de jugador que trae ReForge (Perfil → Imagen de jugador). Se repiten aquí para no cargar Qt
# solo por escribir el .ini, y el menú Guía del SDK 0.11 dibuja la misma figura (allí no hay texturas a mano).
AVATAR_STYLES = [
    ("19d3a2", "0b3d30", "hex"), ("ff9f1c", "4a2a00", "bolt"), ("5b8cff", "14224d", "star"),
    ("e5484d", "47121a", "ring"), ("b072ff", "2b1450", "diamond"), ("f5d90a", "3d3500", "wave"),
    ("3dd6f5", "0b3440", "pad"), ("ff6ac1", "4a1236", "crown"),
]


def avatar_style(profile):
    """Figura y colores de la imagen de jugador del perfil: (estilo, color de la figura, fondo)."""
    if profile.avatar and not profile.avatar.startswith("gen:"):
        return "none", "19d3a2", "0b3d30"     # una imagen propia necesita textura: no se puede dibujar aquí
    idx = 0
    if profile.avatar.startswith("gen:"):
        try:
            idx = int(profile.avatar[4:])
        except ValueError:
            idx = 0
    fg, bg, shape = AVATAR_STYLES[idx % len(AVATAR_STYLES)]
    return shape, fg, bg


@dataclass
class Profile:
    gamertag: str = "Player"
    live: bool = False
    avatar: str = ""                 # nombre del archivo dentro de profile_dir() o «gen:N»
    toast_position: str = "bottom_right"
    toast_seconds: float = 5.0
    toast_title: str = "Logro desbloqueado"
    accent: str = "19D3A2"
    toast_sound: str = "reforge"     # "reforge" (timbre propio), "custom" (archivo del usuario) o "none"
    toast_volume: int = 80
    toast_badge: str = "none"        # "custom" (logo elegido, profile/badge.png) o "none"

    @staticmethod
    def path():
        return os.path.join(config_dir(), "profile.json")

    @classmethod
    def load(cls):
        p = cls()
        try:
            with open(cls.path(), encoding="utf-8") as f:
                data = json.load(f)
            names = {f.name for f in fields(cls)}
            for k, v in data.items():
                if k in names:
                    setattr(p, k, v)
        except Exception:
            pass
        if not valid_gamertag(p.gamertag):
            p.gamertag = clean_gamertag(p.gamertag) or "Player"
        if p.toast_position not in dict(TOAST_POSITIONS):
            p.toast_position = "bottom_right"
        return p

    def save(self):
        os.makedirs(config_dir(), exist_ok=True)
        tmp = self.path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path())

    def avatar_path(self):
        if self.avatar and not self.avatar.startswith("gen:"):
            p = os.path.join(profile_dir(), self.avatar)
            return p if os.path.isfile(p) else ""
        return ""


def profile_dir():
    return os.path.join(config_dir(), "profile")


def valid_gamertag(tag):
    return bool(GAMERTAG_RE.match(tag or "")) and not tag.startswith(" ") and not tag.endswith(" ")


def clean_gamertag(tag):
    """Gamertag como en Xbox 360: letras, números y espacios, máximo 15."""
    import unicodedata
    t = unicodedata.normalize("NFKD", tag or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).replace("_", " ")   # Rogér_X → Roger X
    t = re.sub(r"[^A-Za-z0-9 ]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:15].strip()


def import_avatar(src):
    """Copia una imagen elegida por el usuario a la carpeta del perfil. Devuelve el nombre guardado."""
    os.makedirs(profile_dir(), exist_ok=True)
    ext = os.path.splitext(src)[1].lower() or ".png"
    name = "avatar" + ext
    for f in os.listdir(profile_dir()):
        if f.startswith("avatar."):
            try:
                os.remove(os.path.join(profile_dir(), f))
            except OSError:
                pass
    shutil.copyfile(src, os.path.join(profile_dir(), name))
    return name


def ext_ini_path(exe):
    return os.path.join(os.path.dirname(exe), "reforge_ext.ini")


def export_avatar(profile, exe_dir, size=128):
    """reforge_avatar.rgba junto al juego (avatar del perfil para el menú Guía). Devuelve el nombre o ''."""
    dst = os.path.join(exe_dir, "reforge_avatar.rgba")
    try:
        import struct
        from PySide6.QtGui import QGuiApplication, QImage
        if QGuiApplication.instance() is None:
            return os.path.basename(dst) if os.path.isfile(dst) else ""
        from .profile_page import avatar_pixmap
        img = avatar_pixmap(profile, size).toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        if img.isNull():
            return ""
        w, h, bpl = img.width(), img.height(), img.bytesPerLine()
        raw = bytes(img.constBits())[: bpl * h]
        rows = b"".join(raw[y * bpl: y * bpl + w * 4] for y in range(h))
        tmp = dst + ".tmp"
        with open(tmp, "wb") as f:
            f.write(b"RFBG" + struct.pack("<II", w, h) + rows)
        os.replace(tmp, dst)
        return os.path.basename(dst)
    except Exception:      # noqa: BLE001 — sin avatar antes que sin juego
        return ""


def write_ext_ini(exe, options=None, profile=None, frame_cap=None):
    """Escribe reforge_ext.ini junto al .exe del juego (perfil, Live, idioma y notificaciones)."""
    p = profile or Profile.load()
    if frame_cap is None:
        try:
            from .pc_enhance import frame_cap as cap_for
            frame_cap = cap_for(options.frame_mode()) if options is not None else 0.0
        except Exception:      # noqa: BLE001
            frame_cap = 0.0
    lang = options.effective_language()[0] if hasattr(options, "effective_language") else \
        (int(getattr(options, "language", 0) or 0) if options is not None else 0)
    lines = [
        "# ReForge Studio: perfil, idioma y notificación de logros (cámbialo desde ReForge → Perfil)",
        f"gamertag = {clean_gamertag(p.gamertag) or 'Player'}",
        f"live = {1 if p.live and not getattr(options, 'live_offline', False) else 0}",
        f"language = {lang}",
        f"toast_position = {p.toast_position}",
        f"toast_seconds = {float(p.toast_seconds):.1f}",
        f"toast_title = {p.toast_title.replace(chr(10), ' ')[:40]}",
        f"accent = {p.accent}",
        f"hide_cursor = {0 if options is not None and not getattr(options, 'hide_cursor', True) else 1}",
        f"diagnostics = {1 if options is not None and getattr(options, 'diagnostics', False) else 0}",
        f"frame_cap = {float(frame_cap or 0.0):.1f}",
    ]
    try:
        from .sound import export_for_game
        lines.append(f"sound = {export_for_game(p, os.path.dirname(exe))}")
    except Exception:      # noqa: BLE001 — sin sonido antes que sin juego
        lines.append("sound = ")
    try:
        from .cheats import cheats_active_for_exe
        lines.append(f"cheats = {1 if cheats_active_for_exe(exe) else 0}")
    except Exception:      # noqa: BLE001
        lines.append("cheats = 0")
    try:
        from .badge import export_for_game as export_badge
        lines.append(f"badge = {export_badge(p, os.path.dirname(exe))}")
    except Exception:      # noqa: BLE001 — sin logo antes que sin juego
        lines.append("badge = ")
    lines.append(f"avatar = {export_avatar(p, os.path.dirname(exe))}")
    shape, fg, bg = avatar_style(p)     # la misma imagen de jugador del perfil, para el menú Guía de 0.11
    lines.append(f"avatar_style = {shape}")
    lines.append(f"avatar_fg = {fg}")
    lines.append(f"avatar_bg = {bg}")
    root = os.path.dirname(os.path.dirname(os.path.abspath(exe)))
    lines.append(f"game_name = {os.path.basename(root).replace('_', ' ').strip().title()[:60]}")
    lines.append(f"guide_menu = {0 if options is not None and not getattr(options, 'guide_menu', True) else 1}")
    lines.append(f"image_guard = {0 if options is not None and not getattr(options, 'image_guard', True) else 1}")
    try:
        from .controller import resolve
        lines.append(f"pad_style = {resolve(getattr(options, 'button_style', 'auto') if options is not None else 'auto')}")
    except Exception:      # noqa: BLE001
        lines.append("pad_style = xbox")
    path = ext_ini_path(exe)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)
    return path
