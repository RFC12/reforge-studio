"""Actualizaciones de ReForge Studio desde GitHub.

ReForge sabe qué versión es (reforge.__version__), pregunta a GitHub cuál es la última publicada y, si hay una
más nueva, se descarga el instalador y lo lanza. Todo con comprobaciones para no instalar nada corrupto:

* el archivo tiene que llamarse ReForgeStudio-Setup-<versión>.exe y venir del repositorio configurado,
* se comprueba el tamaño y, si la publicación trae un SHA-256 (archivo .sha256 o la línea «sha256: …» de las
  notas), también el resumen criptográfico,
* la descarga se hace a un archivo temporal y solo se usa si termina entera.

La comprobación es automática (una vez al día como mucho). Instalar sustituye el programa, así que por
defecto se pregunta; quien quiera puede dejarlo en automático desde la configuración.
"""
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

from . import __version__
from .core import config_dir

REPO = "RFC12/reforge-studio"
UA = f"ReForgeStudio/{__version__}"
CONFIG = "update.json"
ASSET_RE = re.compile(r"^ReForgeStudio-Setup-(\d+(?:\.\d+)*)\.exe$", re.I)
SHA_RE = re.compile(r"\b([0-9a-f]{64})\b", re.I)
CHECK_EVERY = 24 * 3600


def vtuple(v):
    parts = [int(x) for x in str(v).split(".") if x.isdigit()]
    return tuple(parts + [0] * (4 - len(parts)))


def current_version():
    return __version__


# ---------------------------------------------------------------- configuración
def config_path():
    return os.path.join(config_dir(), CONFIG)


def load_config():
    cfg = {"enabled": True, "auto_install": False, "prereleases": False, "repo": REPO, "token": "",
           "last_check": 0, "skip": ""}
    try:
        with open(config_path(), encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:      # noqa: BLE001
        pass
    return cfg


def save_config(**updates):
    cfg = load_config()
    cfg.update(updates)
    try:
        os.makedirs(config_dir(), exist_ok=True)
        tmp = config_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, config_path())
    except OSError:
        pass
    return cfg


# ---------------------------------------------------------------- consultar GitHub
def _open(url, timeout=30, token="", accept="application/vnd.github+json"):
    headers = {"User-Agent": UA, "Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context())


class UpdateError(RuntimeError):
    pass


def _api(repo, path, token=""):
    url = f"https://api.github.com/repos/{repo}{path}"
    try:
        with _open(url, token=token) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            raise UpdateError(
                f"GitHub respondió {e.code} para {repo}. Si el repositorio es privado, ReForge no puede "
                "consultarlo sin permiso: hazlo público o añade un token personal en la configuración de "
                "actualizaciones.") from e
        raise UpdateError(f"GitHub respondió {e.code}.") from e
    except Exception as e:      # noqa: BLE001
        raise UpdateError(f"No se pudo consultar GitHub ({e}).") from e


def _release_info(rel):
    """(versión, url del instalador, tamaño, sha256) de una publicación, o None si no trae instalador."""
    best = None
    sha = ""
    body = rel.get("body") or ""
    for a in rel.get("assets") or []:
        name = a.get("name") or ""
        m = ASSET_RE.match(name)
        if m:
            best = (m.group(1), a.get("browser_download_url") or "", int(a.get("size") or 0), a)
        elif name.lower().endswith(".sha256"):
            sha = a.get("browser_download_url") or ""
    if not best:
        return None
    ver, url, size, asset = best
    digest = ""
    m = SHA_RE.search(body)
    if m:
        digest = m.group(1).lower()
    return {"version": ver, "url": url, "size": size, "sha256": digest, "sha_url": sha,
            "notes": body.strip(), "tag": rel.get("tag_name") or "", "asset_id": asset.get("id")}


def latest(cfg=None):
    """La publicación más nueva con instalador, o None si no hay ninguna."""
    cfg = cfg or load_config()
    rels = _api(cfg.get("repo") or REPO, "/releases?per_page=20", cfg.get("token") or "")
    if isinstance(rels, dict):
        rels = [rels]
    best = None
    for rel in rels:
        if rel.get("draft"):
            continue
        if rel.get("prerelease") and not cfg.get("prereleases"):
            continue
        info = _release_info(rel)
        if info and (best is None or vtuple(info["version"]) > vtuple(best["version"])):
            best = info
    return best


def check(cfg=None, force=False):
    """¿Hay versión nueva? Devuelve la publicación, o None. No lanza errores de red: los deja en el config."""
    cfg = cfg or load_config()
    if not cfg.get("enabled") and not force:
        return None
    if not force and time.time() - float(cfg.get("last_check") or 0) < CHECK_EVERY:
        return None
    try:
        info = latest(cfg)
        save_config(last_check=time.time(), last_error="")
    except UpdateError as e:
        save_config(last_check=time.time(), last_error=str(e))
        if force:
            raise
        return None
    if not info:
        return None
    if vtuple(info["version"]) <= vtuple(current_version()):
        return None
    if not force and cfg.get("skip") == info["version"]:
        return None
    return info


# ---------------------------------------------------------------- descargar e instalar
def download_dir():
    return os.path.join(config_dir(), "updates")


def download(info, progress=None, cancelled=None, token=""):
    """Descarga el instalador comprobando tamaño y SHA-256. Devuelve la ruta del .exe."""
    os.makedirs(download_dir(), exist_ok=True)
    dest = os.path.join(download_dir(), f"ReForgeStudio-Setup-{info['version']}.exe")
    if os.path.isfile(dest) and (not info["size"] or os.path.getsize(dest) == info["size"]):
        if _verify(dest, info, token):
            return dest
    tmp = dest + ".part"
    h = hashlib.sha256()
    done = 0
    with _open(info["url"], timeout=60, token=token, accept="application/octet-stream") as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or info["size"] or 0)
        while True:
            if cancelled and cancelled():
                f.close()
                os.remove(tmp)
                raise UpdateError("Descarga cancelada")
            buf = r.read(1 << 20)
            if not buf:
                break
            f.write(buf)
            h.update(buf)
            done += len(buf)
            if progress and total:
                progress(done, total)
    if info["size"] and done != info["size"]:
        os.remove(tmp)
        raise UpdateError(f"Descarga incompleta ({done} de {info['size']} bytes).")
    want = _expected_sha(info, token)
    if want and h.hexdigest().lower() != want:
        os.remove(tmp)
        raise UpdateError("El instalador descargado no coincide con su SHA-256: se ha descartado.")
    os.replace(tmp, dest)
    return dest


def _expected_sha(info, token=""):
    if info.get("sha256"):
        return info["sha256"].lower()
    if info.get("sha_url"):
        try:
            with _open(info["sha_url"], token=token, accept="application/octet-stream") as r:
                m = SHA_RE.search(r.read(4096).decode("utf-8", "replace"))
                return m.group(1).lower() if m else ""
        except Exception:      # noqa: BLE001
            return ""
    return ""


def _verify(path, info, token=""):
    want = _expected_sha(info, token)
    if not want:
        return True
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().lower() == want


def install(setup_exe, silent=False):
    """Lanza el instalador descargado y devuelve True. ReForge debe cerrarse después."""
    if not os.path.isfile(setup_exe):
        raise UpdateError("No se encuentra el instalador descargado.")
    if sys.platform != "win32":
        raise UpdateError("La actualización automática solo está disponible en Windows.")
    args = [setup_exe] + (["--silent"] if silent else [])
    subprocess.Popen(args, close_fds=True,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    return True


def cleanup(keep=""):
    """Borra instaladores descargados que ya no hacen falta."""
    folder = download_dir()
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    n = 0
    for name in names:
        p = os.path.join(folder, name)
        if os.path.abspath(p) == os.path.abspath(keep):
            continue
        try:
            os.remove(p)
            n += 1
        except OSError:
            pass
    return n


def summary(info):
    if not info:
        return f"ReForge Studio {current_version()}: es la versión más reciente."
    return (f"Hay una versión nueva: {info['version']} (tienes la {current_version()})."
            + (f"\n\n{info['notes'][:600]}" if info.get("notes") else ""))
