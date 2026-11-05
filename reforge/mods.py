"""Packs de contenido («mods») y capas visuales para los juegos recompilados.

Carpeta «mods» del proyecto (junto a «assets»):

    mods/
      Mi pack/                         ← un pack (carpeta o .zip importado); pack.json opcional
        pack.json                      ← {"nombre": "...", "autor": "...", "descripcion": "..."}
        MEDIA/strings_es.bin           ← archivo suelto: reemplaza assets/MEDIA/strings_es.bin
        MEDIA/uiresource.xpr/A.png     ← textura «A» dentro de assets/MEDIA/uiresource.xpr
      _texturas_originales/            ← todas las texturas XPR del juego en PNG (para editarlas)
      .reforge/                        ← interno: originales guardados y estado

Al jugar, ReForge aplica los packs activos (en orden alfabético: el último gana) más la capa automática de
iconos de botones (PlayStation si hay un DualSense/DualShock conectado o si se eligió). Antes de tocar un
archivo del juego guarda el original en mods/.reforge/originales; al quitar un pack lo devuelve tal cual.
Las texturas se reescriben con su mismo tamaño y formato (si el PNG es de otro tamaño, se ajusta).
"""
import hashlib
import json
import os
import shutil
import zipfile

from . import glyphs, xpr

MODS_DIR = "mods"
INTERNAL = ".reforge"
EXPORT_DIR = "_texturas_originales"
STATE_FILE = "estado.json"
VERSION = 1
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp")
MAX_XPR = 256 * 1024 * 1024
README = """Packs de ReForge para este juego
================================

Cada carpeta de aquí (o .zip importado desde 🎮 Opciones → Packs) es un pack. Dentro, la misma estructura
que la carpeta «assets» del juego:

  • Un archivo con la misma ruta reemplaza al original (p. ej. MEDIA/strings_es.bin).
  • Un PNG dentro de una carpeta con el nombre de un .xpr reemplaza esa textura:
      MEDIA/uiresource.xpr/A.png   →  textura «A» de assets/MEDIA/uiresource.xpr

Para hacer el tuyo: copia de «_texturas_originales» solo los PNG que quieras cambiar, edítalos (mismo
tamaño; si no, se ajustan) y guárdalos en una carpeta nueva con la misma ruta. Al jugar se aplica solo, y
al desactivar o borrar el pack se devuelven los archivos originales.
"""


def mods_dir(root):
    return os.path.join(root, MODS_DIR)


def _internal(root, *parts):
    return os.path.join(root, MODS_DIR, INTERNAL, *parts)


def _rel(path):
    return path.replace("\\", "/").strip("/")


def _load_state(root):
    try:
        with open(_internal(root, STATE_FILE), encoding="utf-8") as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(root, st):
    os.makedirs(_internal(root), exist_ok=True)
    tmp = _internal(root, STATE_FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _internal(root, STATE_FILE))


def _stat(path):
    try:
        s = os.stat(path)
        return [s.st_size, int(s.st_mtime)]
    except OSError:
        return None


# ---------------------------------------------------------------- packs
def list_packs(root):
    """[{name, path, info, files}] de los packs de la carpeta mods (sin la exportación ni lo interno)."""
    base = mods_dir(root)
    out = []
    try:
        names = sorted(os.listdir(base), key=str.lower)
    except OSError:
        return out
    for n in names:
        p = os.path.join(base, n)
        if n.startswith((".", "_")) or not os.path.isdir(p):
            continue
        info = {}
        try:
            with open(os.path.join(p, "pack.json"), encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            pass
        files = sum(len([f for f in fs if f.lower() != "pack.json"]) for _d, _s, fs in os.walk(p))
        out.append({"name": n, "path": p, "info": info if isinstance(info, dict) else {}, "files": files})
    return out


def import_pack(root, source):
    """Copia un pack (.zip o carpeta) a mods/. Devuelve su nombre."""
    base = mods_dir(root)
    os.makedirs(base, exist_ok=True)
    name = os.path.splitext(os.path.basename(os.path.normpath(source)))[0].strip() or "pack"
    dest = os.path.join(base, name)
    i = 2
    while os.path.exists(dest):
        dest = os.path.join(base, f"{name} ({i})")
        i += 1
    if os.path.isdir(source):
        shutil.copytree(source, dest)
    else:
        with zipfile.ZipFile(source) as z:
            members = [m for m in z.namelist() if not m.endswith("/")]
            tops = {m.split("/")[0] for m in members}
            strip = len(tops) == 1 and all("/" in m for m in members)  # zip con una carpeta raíz: se quita
            for m in members:
                parts = [p for p in m.split("/")[1 if strip else 0:] if p not in ("", ".", "..")]
                if not parts:
                    continue
                target = os.path.join(dest, *parts)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(m) as src, open(target, "wb") as f:
                    shutil.copyfileobj(src, f)
    return os.path.basename(dest)


def _pack_entries(root, pack_path, assets):
    """{rel: ("file", src)} y {rel_xpr: {textura: ("png", src)}} de un pack."""
    files, textures = {}, {}
    for d, _sub, fs in os.walk(pack_path):
        for f in fs:
            if f.lower() == "pack.json":
                continue
            src = os.path.join(d, f)
            rel = _rel(os.path.relpath(src, pack_path))
            parts = rel.split("/")
            hit = None
            for k in range(len(parts) - 1, 0, -1):
                cand = "/".join(parts[:k])
                if cand.lower().endswith(".xpr") and os.path.isfile(os.path.join(assets, *parts[:k])):
                    hit = cand
                    break
            if hit and f.lower().endswith(IMAGE_EXT):
                textures.setdefault(hit, {})[os.path.splitext(f)[0]] = ("png", src)
            elif not hit:
                files[rel] = ("file", src)
    return files, textures


# ---------------------------------------------------------------- originales
def original_path(root, rel):
    """Ruta del archivo original del juego (el guardado si ReForge lo cambió, si no el de assets)."""
    saved = _internal(root, "originales", *rel.split("/"))
    return saved if os.path.isfile(saved) else os.path.join(root, "assets", *rel.split("/"))


def _xpr_files(root):
    assets = os.path.join(root, "assets")
    out = []
    for d, _sub, fs in os.walk(assets):
        for f in fs:
            if f.lower().endswith(".xpr"):
                out.append(_rel(os.path.relpath(os.path.join(d, f), assets)))
    return sorted(out)


def _button_layer(root, st):
    """{rel_xpr: {textura: ("ps", tipo) | ("psdiagram", "")}} — capa automática de iconos PlayStation."""
    cache = st.setdefault("escaneo", {})
    out = {}
    for rel in _xpr_files(root):
        src = original_path(root, rel)
        key = _stat(src)
        hit = cache.get(rel)
        if not hit or hit.get("stat") != key:
            found = {}
            try:
                if os.path.getsize(src) <= MAX_XPR:
                    with open(src, "rb") as f:
                        data = f.read()
                    if xpr.is_xpr(data):
                        for t in xpr.parse(data):
                            if not t.supported:
                                continue
                            kind = glyphs.classify(t.name)
                            if kind:
                                found[t.name] = ["ps", kind]
                            elif glyphs.DIAGRAM_RE.search(t.name) and min(t.width, t.height) >= 96:
                                found[t.name] = ["psdiagram", ""]
            except (OSError, ValueError):
                found = {}
            hit = cache[rel] = {"stat": key, "found": found}
        if hit["found"]:
            out[rel] = {k: tuple(v) for k, v in hit["found"].items()}
    return out


# ---------------------------------------------------------------- aplicar
def _sig(spec):
    h = hashlib.sha1(str(VERSION).encode())
    for item in spec:
        h.update(repr(item).encode("utf-8", "replace"))
        if isinstance(item, tuple) and len(item) == 2 and item[0] in ("file", "png"):
            h.update(repr(_stat(item[1])).encode())
    return h.hexdigest()


def _render_xpr(root, rel, textures):
    """Bytes del .xpr original con las texturas cambiadas. Devuelve (bytes, cambiadas)."""
    with open(original_path(root, rel), "rb") as f:
        data = bytearray(f.read())
    by_name = {t.name: t for t in xpr.parse(data)}
    done = 0
    for name, (kind, arg) in sorted(textures.items()):
        t = by_name.get(name)
        if not t or not t.supported:
            continue
        try:
            if kind == "png":
                new = _load_image(arg, t.width, t.height)
            elif kind == "ps":
                new = glyphs.render_button(xpr.decode(data, t), t.width, t.height, arg)
            else:
                new = glyphs.ps_diagram(xpr.decode(data, t), t.width, t.height)
            if new:
                xpr.encode_into(data, t, new)
                done += 1
        except Exception:      # noqa: BLE001 — una textura rara no impide el resto
            continue
    return bytes(data), done


def _load_image(path, w, h):
    from PySide6 import QtCore, QtGui
    img = QtGui.QImage(path)
    if img.isNull():
        raise ValueError(f"Imagen no válida: {path}")
    if img.width() != w or img.height() != h:
        img = img.scaled(w, h, QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
                         QtCore.Qt.TransformationMode.SmoothTransformation)
    return glyphs.from_qimage(img)


def _backup(root, rel):
    saved = _internal(root, "originales", *rel.split("/"))
    if not os.path.isfile(saved):
        os.makedirs(os.path.dirname(saved), exist_ok=True)
        shutil.copy2(os.path.join(root, "assets", *rel.split("/")), saved)


def _write(root, rel, data=None, src=None):
    dst = os.path.join(root, "assets", *rel.split("/"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".reforge-tmp"
    if src:
        shutil.copyfile(src, tmp)
    else:
        with open(tmp, "wb") as f:
            f.write(data)
    os.replace(tmp, dst)


def _restore(root, rel):
    saved = _internal(root, "originales", *rel.split("/"))
    if os.path.isfile(saved):
        dst = os.path.join(root, "assets", *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(saved, dst + ".reforge-tmp")
        os.replace(dst + ".reforge-tmp", dst)
        os.remove(saved)


def apply(root, button_style="xbox", disabled=()):
    """Deja assets como piden los packs activos y el estilo de botones. Devuelve [mensajes]."""
    assets = os.path.join(root, "assets")
    if not os.path.isdir(assets):
        return []
    st = _load_state(root)
    applied = st.setdefault("aplicados", {})
    # si algo de fuera cambió un archivo que ReForge había modificado (actualización del juego…), ese
    # archivo pasa a ser el nuevo original
    for rel, rec in list(applied.items()):
        cur = _stat(os.path.join(assets, *rel.split("/")))
        if cur and rec.get("stat") and cur != rec["stat"]:
            saved = _internal(root, "originales", *rel.split("/"))
            try:
                os.remove(saved)
            except OSError:
                pass
            applied.pop(rel)
    files, textures, used = {}, {}, []
    if button_style == "playstation":
        for rel, tex in _button_layer(root, st).items():
            textures.setdefault(rel, {}).update(tex)
    for pack in list_packs(root):
        if pack["name"] in disabled:
            continue
        f, t = _pack_entries(root, pack["path"], assets)
        if f or t:
            used.append(pack["name"])
        files.update(f)
        for rel, tex in t.items():
            textures.setdefault(rel, {}).update(tex)
    wanted = {}
    for rel, src in files.items():
        wanted[rel] = ("file", src)
    for rel, tex in textures.items():
        if rel not in wanted:             # un .xpr suelto en un pack manda sobre texturas sueltas
            wanted[rel] = ("xpr", tex)
    msgs = []
    changed = 0
    for rel, (kind, spec) in sorted(wanted.items()):
        sig = _sig([kind] + ([spec] if kind == "file" else sorted(spec.items())))
        dst = os.path.join(assets, *rel.split("/"))
        rec = applied.get(rel, {})
        if rec.get("sig") == sig and rec.get("stat") == _stat(dst):
            continue
        try:
            if os.path.isfile(dst):
                _backup(root, rel)
            if kind == "file":
                _write(root, rel, src=spec[1])
            else:
                data, n = _render_xpr(root, rel, spec)
                if not n:
                    continue
                _write(root, rel, data=data)
            applied[rel] = {"sig": sig, "stat": _stat(dst), "new": not os.path.isfile(_internal(
                root, "originales", *rel.split("/")))}
            changed += 1
        except (OSError, ValueError) as e:
            msgs.append(f"⚠ {rel}: {e}")
    for rel in [r for r in applied if r not in wanted]:
        rec = applied.pop(rel)
        saved = _internal(root, "originales", *rel.split("/"))
        dst = os.path.join(assets, *rel.split("/"))
        try:
            if os.path.isfile(saved):
                _restore(root, rel)
            elif rec.get("new") and os.path.isfile(dst):
                os.remove(dst)            # archivo que el juego no tenía: lo añadió un pack
            changed += 1
        except OSError as e:
            msgs.append(f"⚠ {rel}: no se pudo devolver el original ({e})")
    st["estilo"] = button_style
    st["packs"] = used
    _save_state(root, st)
    if changed:
        parts = []
        if button_style == "playstation" and any(k == "xpr" for k, _ in wanted.values()):
            parts.append("iconos de PlayStation")
        if used:
            parts.append("packs: " + ", ".join(used))
        msgs.insert(0, "🎨 Capas visuales aplicadas" + (f" ({'; '.join(parts)})" if parts else
                                                         " (archivos originales devueltos)"))
    return msgs


def status(root):
    st = _load_state(root)
    return {"estilo": st.get("estilo", "xbox"), "packs": st.get("packs", []),
            "archivos": sorted(st.get("aplicados", {}))}


# ---------------------------------------------------------------- exportar
def export_textures(root, progress=None):
    """Todas las texturas XPR del juego (originales) en mods/_texturas_originales como PNG. Devuelve cuántas."""
    out_base = os.path.join(mods_dir(root), EXPORT_DIR)
    n = 0
    rels = _xpr_files(root)
    for i, rel in enumerate(rels):
        try:
            with open(original_path(root, rel), "rb") as f:
                data = f.read()
            texs = xpr.parse(data)
        except (OSError, ValueError):
            continue
        folder = os.path.join(out_base, *rel.split("/"))
        os.makedirs(folder, exist_ok=True)
        for t in texs:
            if not t.supported:
                continue
            if progress:
                progress(f"{rel} · {t.name} ({i + 1}/{len(rels)})")
            try:
                img = glyphs.to_qimage(xpr.decode(data, t), t.width, t.height)
            except Exception:      # noqa: BLE001
                continue
            safe = "".join(c if c.isalnum() or c in "-_ ." else "_" for c in t.name) or "textura"
            img.save(os.path.join(folder, safe + ".png"), "PNG")
            n += 1
    write_readme(root)
    return n


def write_readme(root):
    os.makedirs(mods_dir(root), exist_ok=True)
    path = os.path.join(mods_dir(root), "LEEME.txt")
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(README)
    return path
