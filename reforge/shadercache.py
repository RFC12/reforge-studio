"""Caché de shaders de los juegos recompilados: que el juego no tenga que volver a traducirlos.

rexglue guarda de forma persistente lo que traduce (lo dice su propio registro: «Translated N shaders from the
storage», «Created N graphics pipelines … from the storage»), en la carpeta de documentos del juego:

    Documentos/<nombre del exe>/cache/shaders/shareable/
        <TITLEID>.xsh                  ← shaders del juego tal y como venían en la Xbox 360
        <TITLEID>.rtv.d3d12.xpso       ← pipelines de Direct3D 12 ya creados, para la ruta rápida
        <TITLEID>.rov.d3d12.xpso       ← …y para la ruta precisa

La primera partida siempre traduce shaders (de ahí los tirones y parpadeos iniciales); a partir de la segunda
se cargan de la caché. Este módulo hace que esa caché no se pierda ni se repita:

* la comparte entre proyectos del mismo juego (recompilar otra vez no empieza de cero),
* la guarda dentro del proyecto y la restaura si se borra o se mueve el juego,
* avisa de que cambiar la ruta de imagen (RTV ↔ ROV) estrena una caché de pipelines vacía,
* permite exportarla e importarla para llevársela a otro PC.
"""
import os
import shutil
import time
import zipfile

CACHE_REL = os.path.join("cache", "shaders", "shareable")
PROJECT_COPY = os.path.join(".reforge", "shadercache")
PATHS = ("rtv", "rov")


def documents_dir():
    return os.path.join(os.path.expanduser("~"), "Documents")


def game_name(exe):
    return os.path.splitext(os.path.basename(exe))[0]


def cache_dir(exe):
    """Carpeta donde rexglue guarda la caché de este juego."""
    return os.path.join(documents_dir(), game_name(exe), CACHE_REL)


def _files(folder, title_id):
    """[(nombre, tamaño)] de la caché de ese juego dentro de la carpeta."""
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    tid = (title_id or "").upper()
    for n in names:
        if tid and not n.upper().startswith(tid + "."):
            continue
        p = os.path.join(folder, n)
        if os.path.isfile(p):
            out.append((n, os.path.getsize(p)))
    return out


def status(exe, title_id, render_path=""):
    """Estado de la caché: tamaño, rutas de imagen con pipelines guardados y si la actual está vacía."""
    folder = cache_dir(exe)
    files = _files(folder, title_id)
    by_path = {}
    shaders = 0
    for n, size in files:
        low = n.lower()
        if low.endswith(".xsh"):
            shaders = size
        for rp in PATHS:
            if low.endswith(f".{rp}.d3d12.xpso"):
                by_path[rp] = size
    path = (render_path or "rtv").lower()
    return {
        "dir": folder,
        "exists": bool(files),
        "total": sum(s for _n, s in files),
        "shaders_bytes": shaders,
        "paths": by_path,
        "render_path": path,
        "cold": shaders > 0 and path not in by_path,
    }


def describe(st):
    """Una línea para la interfaz."""
    if not st["exists"]:
        return "Sin caché de shaders todavía: la primera partida la crea."
    mb = st["total"] / (1 << 20)
    paths = ", ".join(sorted(st["paths"])).upper() or "ninguna"
    txt = f"Caché de shaders: {mb:.1f} MB · pipelines guardados para {paths}"
    if st["cold"]:
        txt += (f". La ruta de imagen actual ({st['render_path'].upper()}) todavía no tiene pipelines: "
                "la próxima partida volverá a crearlos.")
    return txt


# ---------------------------------------------------------------- compartir entre proyectos del mismo juego
def other_caches(exe, title_id):
    """[(carpeta, bytes, fecha)] de cachés del MISMO juego en otros proyectos, de la mayor a la menor."""
    if not title_id:
        return []
    docs = documents_dir()
    mine = os.path.normcase(os.path.abspath(cache_dir(exe)))
    out = []
    try:
        entries = os.listdir(docs)
    except OSError:
        return out
    for name in entries:
        folder = os.path.join(docs, name, CACHE_REL)
        if os.path.normcase(os.path.abspath(folder)) == mine or not os.path.isdir(folder):
            continue
        files = _files(folder, title_id)
        if not files:
            continue
        total = sum(s for _n, s in files)
        newest = max(os.path.getmtime(os.path.join(folder, n)) for n, _s in files)
        out.append((folder, total, newest))
    out.sort(key=lambda r: (-r[1], -r[2]))
    return out


def _copy_into(src, dst, title_id, only_newer=True):
    """Copia los archivos de caché de src a dst. Devuelve los nombres copiados."""
    os.makedirs(dst, exist_ok=True)
    copied = []
    for n, size in _files(src, title_id):
        s, d = os.path.join(src, n), os.path.join(dst, n)
        if only_newer and os.path.isfile(d) and os.path.getsize(d) >= size:
            continue        # lo que ya hay es igual o más completo
        tmp = d + ".tmp"
        shutil.copy2(s, tmp)
        os.replace(tmp, d)
        copied.append(n)
    return copied


def reuse_existing(exe, title_id):
    """Trae la caché más completa que haya de ese juego en otro proyecto. Devuelve el mensaje o ''."""
    best = other_caches(exe, title_id)
    if not best:
        return ""
    folder, total, _mtime = best[0]
    copied = _copy_into(folder, cache_dir(exe), title_id)
    if not copied:
        return ""
    return (f"Shaders reaprovechados de «{os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(folder))))}» "
            f"({total / (1 << 20):.1f} MB): este juego arranca sin volver a traducirlos.")


# ---------------------------------------------------------------- copia dentro del proyecto
def backup(root, exe, title_id):
    """Guarda la caché dentro del proyecto (sobrevive a mover o reinstalar el juego). Bytes copiados."""
    dst = os.path.join(root, PROJECT_COPY)
    copied = _copy_into(cache_dir(exe), dst, title_id, only_newer=True)
    return sum(os.path.getsize(os.path.join(dst, n)) for n in copied)


def restore(root, exe, title_id):
    """Devuelve al juego la caché guardada en el proyecto si la suya está vacía o es menor. Mensaje o ''."""
    src = os.path.join(root, PROJECT_COPY)
    if not os.path.isdir(src):
        return ""
    copied = _copy_into(src, cache_dir(exe), title_id)
    if not copied:
        return ""
    return f"Caché de shaders restaurada desde el proyecto ({len(copied)} archivos)."


def sync(root, exe, title_id):
    """Antes de jugar: restaurar lo guardado y, si no hay nada, reaprovechar otro proyecto del mismo juego."""
    msgs = []
    try:
        m = restore(root, exe, title_id)
        if m:
            msgs.append(m)
        if not status(exe, title_id)["exists"]:
            m = reuse_existing(exe, title_id)
            if m:
                msgs.append(m)
    except OSError:
        pass
    return msgs


# ---------------------------------------------------------------- exportar / importar
def export_zip(exe, title_id, dest):
    """Empaqueta la caché en un .zip para llevarla a otro PC. Devuelve la ruta o ''."""
    files = _files(cache_dir(exe), title_id)
    if not files:
        return ""
    folder = cache_dir(exe)
    tmp = dest + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n, _s in files:
            z.write(os.path.join(folder, n), n)
        z.writestr("reforge_cache.txt",
                   f"Caché de shaders de ReForge Studio\ntitle_id = {title_id}\nfecha = "
                   f"{time.strftime('%Y-%m-%d %H:%M')}\n")
    os.replace(tmp, dest)
    return dest


def import_zip(exe, title_id, src):
    """Mete en la caché del juego los archivos de un .zip exportado. Número de archivos."""
    folder = cache_dir(exe)
    os.makedirs(folder, exist_ok=True)
    n = 0
    tid = (title_id or "").upper()
    with zipfile.ZipFile(src) as z:
        for info in z.infolist():
            name = os.path.basename(info.filename)
            if not name or info.is_dir() or name == "reforge_cache.txt":
                continue
            if tid and not name.upper().startswith(tid + "."):
                continue        # caché de otro juego: no se mezcla
            with z.open(info) as f, open(os.path.join(folder, name) + ".tmp", "wb") as out:
                shutil.copyfileobj(f, out)
            os.replace(os.path.join(folder, name) + ".tmp", os.path.join(folder, name))
            n += 1
    return n


def clear(exe, title_id):
    """Borra la caché del juego (para empezar de cero si algo se corrompió). Archivos borrados."""
    folder = cache_dir(exe)
    n = 0
    for name, _s in _files(folder, title_id):
        try:
            os.remove(os.path.join(folder, name))
            n += 1
        except OSError:
            pass
    return n
