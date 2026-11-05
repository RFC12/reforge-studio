"""Ajustes de análisis por identidad XEX; no sustituyen funciones del juego."""
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from .xex import read_xex_info

# Metadata observed in the supplied logs; this is not a binary hash.
ANGRY_BIRDS_ID = ("415608E4", "1A15DA04", "0.0.0.2")
ANGRY_BIRDS_TARGET = 0x8262E8B8


def apply_game_profile(root, ctx):
    from .game import FUNCTIONS_FILE, declared_functions, ensure_include
    xex = Path(root) / "assets" / "default.xex"
    if not xex.is_file():
        return False
    info = read_xex_info(str(xex))
    identity = tuple(info.get(k, "") for k in ("title_id", "media_id", "version"))
    if identity != ANGRY_BIRDS_ID:
        return False
    if ctx.cancelled():
        raise RuntimeError("Cancelado por el usuario")
    manifests = list(Path(root).glob("*_manifest.toml"))
    if len(manifests) != 1:
        raise RuntimeError("El ajuste de Angry Birds requiere un único *_manifest.toml en el proyecto.")
    manifest = manifests[0]
    if ANGRY_BIRDS_TARGET in declared_functions(root):
        ensure_include(root)
        ctx.log("Perfil Angry Birds Trilogy: 0x8262E8B8 ya está declarada; se conserva su configuración.", "dim")
        return False
    path = Path(root) / FUNCTIONS_FILE
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    for original in (path, manifest):
        if original.exists():
            shutil.copy2(original, str(original) + ".bak-" + stamp)
    text = path.read_text(encoding="utf-8") if path.exists() else "[functions]\n"
    # Insert directly inside [functions], preserving other tables and manual sizes.
    import re
    section = re.search(r"^\[functions\][ \t]*(?:#[^\n]*)?$", text, re.M)
    if section is None:
        raise RuntimeError("reforge_functions.toml no tiene una sección [functions] válida; no se modificó.")
    insertion = ("\n# Perfil Angry Birds Trilogy: objetivo indirecto observado en ejecución.\n"
                 "# Sin tamaño: ReXGlue analiza el XEX original. Arranque aún por validar.\n"
                 "0x8262E8B8 = {}\n")
    text = text[:section.end()] + insertion + text[section.end():]
    fd, temp = tempfile.mkstemp(prefix=".reforge-profile-", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(text)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.remove(temp)
    ensure_include(root)
    ctx.log("Perfil Angry Birds Trilogy aplicado: 0x8262E8B8 añadida para análisis. "
            "Title ID, Media ID y versión coinciden. Copias .bak conservadas.", "ok")
    ctx.log("Este ajuste debe validarse al ejecutar el juego; pueden aparecer otros fallos.", "warn")
    return True
