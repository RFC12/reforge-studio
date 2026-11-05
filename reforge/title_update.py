"""Actualizaciones de título (title updates, TU) de Xbox 360.

Una TU es un paquete STFS (tipo 0x000B0000) con «default.xexp» (parche delta del ejecutable) y, a veces,
archivos nuevos que el juego lee desde «update:\\».

Cómo se aplica en rexglue (comprobado en el código del SDK 0.10):
* El cargador de módulos busca «default.xexp» junto a «default.xex» y aplica el parche al cargarlo. El
  codegen carga el XEX con ese mismo cargador, así que el código recompilado sale ya actualizado y el
  runtime aplica el mismo parche al arrancar (datos y cabeceras coinciden).
* El resto de archivos se monta como «update:\\» (update_data_root): ReForge los deja en
  <proyecto>/update y el gancho de rutas del .exe la encuentra sola.
Por eso, tras instalar o quitar una TU hay que volver a generar el código y compilar.
"""
import hashlib
import json
import os
import shutil
import struct

from .xex import _version, read_xex_info

KEY_DELTA_PATCH = 0x000005FF
KEY_EXECUTION_INFO = 0x00040006
TU_CONTENT_TYPE = 0x000B0000
STATE_FILE = ".reforge_update.json"


class TitleUpdateError(Exception):
    pass


def _opt_headers(data):
    if len(data) < 0x18 or data[:4] != b"XEX2":
        raise TitleUpdateError("No es un archivo XEX2/XEXP válido.")
    count = struct.unpack_from(">I", data, 0x14)[0]
    out = {}
    for i in range(min(count, 64)):
        pos = 0x18 + i * 8
        if pos + 8 > len(data):
            break
        key, value = struct.unpack_from(">II", data, pos)
        out[key] = value
    return out


def base_digest(xex_data):
    """SHA-1 de la firma RSA del XEX base (lo que una TU espera encontrar)."""
    sec = struct.unpack_from(">I", xex_data, 0x10)[0]
    sig = xex_data[sec + 8: sec + 8 + 0x100]
    if len(sig) != 0x100:
        raise TitleUpdateError("El default.xex está incompleto (sin bloque de seguridad).")
    return hashlib.sha1(sig).digest()


def read_patch_info(xexp_data):
    """{'title_id', 'version', 'source_version', 'digest_source'} de un default.xexp."""
    hdr = _opt_headers(xexp_data)
    off = hdr.get(KEY_DELTA_PATCH)
    if off is None or off + 0x20 > len(xexp_data):
        raise TitleUpdateError("Este archivo no es un parche de actualización (default.xexp).")
    target, source = struct.unpack_from(">II", xexp_data, off + 4)
    info = {"version": _version(target), "source_version": _version(source),
            "digest_source": xexp_data[off + 0xC: off + 0x20], "title_id": ""}
    ex = hdr.get(KEY_EXECUTION_INFO)
    if ex is not None and ex + 16 <= len(xexp_data):
        info["title_id"] = f"{struct.unpack_from('>I', xexp_data, ex + 12)[0]:08X}"
    return info


def _read_source(src):
    """(datos del default.xexp, paquete XContent o None, nombre). src: paquete TU o default.xexp suelto."""
    from .xcontent import XContentError, XContentPackage, find_package
    if os.path.isfile(src) and src.lower().endswith(".xexp"):
        with open(src, "rb") as f:
            return f.read(), None, os.path.basename(src)
    try:
        if not find_package(src):
            raise TitleUpdateError("Elige el paquete de la actualización (archivo sin extensión, normalmente "
                                   "dentro de una carpeta 000B0000) o un default.xexp.")
        pkg = XContentPackage(src)
    except XContentError as e:
        raise TitleUpdateError(str(e)) from e
    entry = next((e for e in pkg.files() if os.path.basename(e.path).lower() == "default.xexp"), None)
    if entry is None:
        kind = pkg.content_name.lower()
        pkg.close()
        raise TitleUpdateError(f"Ese paquete ({kind}) no contiene default.xexp: no es una actualización del juego.")
    return pkg.read_file(entry), pkg, pkg.display_name or pkg.title_name


def check_update(root, src):
    """Comprueba que la actualización corresponde al juego del proyecto. Devuelve un resumen."""
    xex = os.path.join(root, "assets", "default.xex")
    if not os.path.isfile(xex):
        raise TitleUpdateError("El proyecto aún no tiene assets/default.xex: compila primero el juego base.")
    from .cheats import cheats_state
    if cheats_state(root) is not None:
        raise TitleUpdateError("Este proyecto tiene trucos aplicados (🎯 Trucos). Trucos y actualización usan el "
                               "mismo mecanismo (default.xexp): quita los trucos antes de instalar la actualización.")
    data, pkg, name = _read_source(src)
    try:
        info = read_patch_info(data)
        game = read_xex_info(xex)
        tid = info["title_id"] or (pkg.title_id if pkg else "")
        if tid and game.get("title_id") and tid != game["title_id"]:
            raise TitleUpdateError(f"Esta actualización es de otro juego (Title ID {tid}); el proyecto es "
                                   f"{game['title_id']}.")
        with open(xex, "rb") as f:
            base = f.read()
        if info["digest_source"] != base_digest(base):
            raise TitleUpdateError(
                f"Esta actualización no corresponde a tu default.xex: espera la versión {info['source_version']} "
                f"y tu juego es la {game.get('version') or 'desconocida'}. Usa el juego base original (sin "
                "parchear) o la actualización de tu región/versión.")
        files = [e for e in pkg.files()] if pkg else []
        return {"name": name, "title_id": tid or game.get("title_id", ""), "version": info["version"],
                "from_version": info["source_version"], "files": len(files),
                "size": sum(e.size for e in files) if pkg else len(data)}
    finally:
        if pkg:
            pkg.close()


def install_update(root, src, log=None):
    """Instala la actualización en el proyecto. Devuelve el resumen (ver check_update)."""
    summary = check_update(root, src)
    prev = installed_update(root)
    data, pkg, _name = _read_source(src)
    assets = os.path.join(root, "assets")
    update = os.path.join(root, "update")
    try:
        if os.path.isdir(update):
            shutil.rmtree(update)
        os.makedirs(update)
        if pkg:
            pkg.extract(update, on_file=(lambda e: log(f"  {e.path}")) if log else None)
    finally:
        if pkg:
            pkg.close()
    target = os.path.join(assets, "default.xexp")
    tmp = target + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, target)
    with open(os.path.join(update, STATE_FILE), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in summary.items()}, f, indent=2)
    from .game_options import ensure_paths_hook
    ensure_paths_hook(root)
    from .game import forget_module_hash, invalidate_codegen, switch_function_set
    old_tag = f"tu-{prev.get('version', '?')}" if prev else "base"
    if old_tag != f"tu-{summary.get('version', '?')}":
        switch_function_set(root, old_tag, f"tu-{summary.get('version', '?')}")
    invalidate_codegen(root)
    forget_module_hash(root)
    return summary


def installed_update(root):
    """Resumen de la actualización instalada o None."""
    from .cheats import cheats_state
    if not os.path.isfile(os.path.join(root, "assets", "default.xexp")) or cheats_state(root) is not None:
        return None
    try:
        with open(os.path.join(root, "update", STATE_FILE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        try:
            with open(os.path.join(root, "assets", "default.xexp"), "rb") as f:
                info = read_patch_info(f.read())
            return {"name": "default.xexp", "version": info["version"], "from_version": info["source_version"]}
        except (OSError, TitleUpdateError):
            return {"name": "default.xexp", "version": "?"}


def remove_update(root):
    """Quita la actualización (vuelve al juego base). True si había una."""
    had = False
    prev = installed_update(root)
    xexp = os.path.join(root, "assets", "default.xexp")
    from .cheats import cheats_state
    if os.path.isfile(xexp) and cheats_state(root) is None:
        os.remove(xexp)
        had = True
    update = os.path.join(root, "update")
    if os.path.isdir(update):
        shutil.rmtree(update)
        had = True
    if had:
        from .game import forget_module_hash, invalidate_codegen, switch_function_set
        if prev:
            switch_function_set(root, f"tu-{prev.get('version', '?')}", "base")
        invalidate_codegen(root)
        forget_module_hash(root)
    return had
