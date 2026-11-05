"""Trucos y parches de la base de datos de Xenia Canary (github.com/xenia-canary/game-patches).

* La base de datos se descarga (zip de GitHub) a la carpeta de ajustes y se actualiza desde ReForge.
* Cada archivo «TITLEID - Nombre.patch.toml» trae los «hash» de módulo a los que se aplica. El hash es el
  de Xenia (XXH3-64 de las páginas de código del ejecutable cargado); la extensión de ReForge lo calcula
  dentro del juego al arrancar sin trucos y lo deja en «reforge_module.txt» junto al .exe.
* Los trucos elegidos se convierten en un default.xexp propio (xexpatch.py) que rexglue aplica al cargar:
  los de código entran en el código recompilado (hay que recompilar) y los de datos valen al arrancar.
"""
import io
import json
import os
import re
import shutil
import struct
import tomllib
import urllib.request
import zipfile
from dataclasses import dataclass, field

from .core import config_dir

DB_URL = "https://codeload.github.com/xenia-canary/game-patches/zip/refs/heads/main"
DB_REPO = "https://github.com/xenia-canary/game-patches"
MODULE_FILE = "reforge_module.txt"
CHEATS_MARKER = ".reforge_cheats.json"        # en assets/: el default.xexp es de trucos (no una actualización)
FILE_RE = re.compile(r"^([0-9A-Fa-f]{8}) - .*\.patch\.toml$")
TYPES = ("be8", "be16", "be32", "be64", "f32", "f64", "string", "u16string", "array")


class CheatError(Exception):
    pass


@dataclass
class Patch:
    name: str
    desc: str = ""
    author: str = ""
    writes: list = field(default_factory=list)       # [(dirección, bytes)]

    @property
    def key(self):
        return self.name


@dataclass
class PatchFile:
    path: str
    title_id: str
    title_name: str
    hashes: list
    patches: list


# ---------------------------------------------------------------- base de datos
def db_dir():
    return os.path.join(config_dir(), "game-patches")


def db_info():
    try:
        with open(os.path.join(db_dir(), "info.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def download_db(progress=None, url=DB_URL, timeout=60):
    """Descarga (o actualiza) la base de datos. Devuelve el número de archivos de parches."""
    req = urllib.request.Request(url, headers={"User-Agent": "ReForgeStudio"})
    with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310 (URL fija de GitHub)
        total = int(r.headers.get("Content-Length") or 0)
        buf = io.BytesIO()
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            buf.write(chunk)
            if progress:
                progress(buf.tell(), total)
    return install_db_zip(buf.getvalue())


def install_db_zip(data):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise CheatError("La descarga de la base de datos no es un zip válido.") from e
    tmp = db_dir() + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(os.path.join(tmp, "patches"))
    n = 0
    for name in z.namelist():
        base = os.path.basename(name)
        if "/patches/" in name.replace("\\", "/") and FILE_RE.match(base):
            with open(os.path.join(tmp, "patches", base), "wb") as f:
                f.write(z.read(name))
            n += 1
    if not n:
        shutil.rmtree(tmp, ignore_errors=True)
        raise CheatError("La descarga no contiene archivos de parches (.patch.toml).")
    import datetime
    with open(os.path.join(tmp, "info.json"), "w", encoding="utf-8") as f:
        json.dump({"files": n, "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "source": DB_REPO},
                  f, indent=2)
    old = db_dir() + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.isdir(db_dir()):
        os.replace(db_dir(), old)
    os.replace(tmp, db_dir())
    shutil.rmtree(old, ignore_errors=True)
    return n


# ---------------------------------------------------------------- lectura de .patch.toml
def _value_bytes(kind, value):
    if kind == "be8":
        return struct.pack(">B", int(value) & 0xFF)
    if kind == "be16":
        return struct.pack(">H", int(value) & 0xFFFF)
    if kind == "be32":
        return struct.pack(">I", int(value) & 0xFFFFFFFF)
    if kind == "be64":
        return struct.pack(">Q", int(value) & 0xFFFFFFFFFFFFFFFF)
    if kind == "f32":
        return struct.pack(">f", float(value))
    if kind == "f64":
        return struct.pack(">d", float(value))
    if kind == "string":
        return str(value).encode("utf-8")
    if kind == "u16string":
        return str(value).encode("utf-16-le")          # igual que Xenia (copia el u16string del host)
    if kind == "array":
        s = re.sub(r"\s+", "", str(value))
        s = s[2:] if s.lower().startswith("0x") else s
        if len(s) % 2:
            raise ValueError("array con número impar de dígitos")
        return bytes.fromhex(s)
    raise ValueError(kind)


def parse_patch_file(path):
    with open(path, "rb") as f:
        data = tomllib.load(f)
    tid = str(data.get("title_id", "")).upper()
    hashes = data.get("hash", [])
    if isinstance(hashes, str):
        hashes = [hashes]
    hashes = [h.upper() for h in hashes if isinstance(h, str) and h.strip()]
    patches = []
    for p in data.get("patch", []) or []:
        if not isinstance(p, dict):
            continue
        writes = []
        for kind in TYPES:
            for e in p.get(kind, []) or []:
                try:
                    writes.append((int(e["address"]) & 0xFFFFFFFF, _value_bytes(kind, e["value"])))
                except (KeyError, ValueError, TypeError, struct.error):
                    continue
        if writes:
            patches.append(Patch(str(p.get("name", "")).strip() or "(sin nombre)", str(p.get("desc", "")).strip(),
                                 str(p.get("author", "")).strip(), writes))
    return PatchFile(path, tid, str(data.get("title_name", "")), hashes, patches)


def files_for_title(title_id, base=None):
    d = os.path.join(base or db_dir(), "patches")
    tid = str(title_id).upper()
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        m = FILE_RE.match(n)
        if m and m.group(1).upper() == tid:
            try:
                out.append(parse_patch_file(os.path.join(d, n)))
            except (OSError, tomllib.TOMLDecodeError):
                continue
    return out


def patches_for(title_id, module_hash, base=None):
    """Parches que corresponden a este juego y versión exacta (hash). [(archivo, parche)]."""
    h = str(module_hash or "").upper()
    return [(f, p) for f in files_for_title(title_id, base) if h and h in f.hashes for p in f.patches]


# ---------------------------------------------------------------- hash del módulo (lo escribe el juego)
def read_module_info(exe):
    info = {}
    try:
        with open(os.path.join(os.path.dirname(exe), MODULE_FILE), encoding="utf-8") as f:
            for ln in f:
                if "=" in ln:
                    k, v = ln.split("=", 1)
                    info[k.strip()] = v.strip().upper()
    except OSError:
        pass
    return info


# ---------------------------------------------------------------- aplicar al proyecto
def code_ranges(xex):
    """[(inicio, fin)] de las secciones de código del XEX (descriptores de páginas)."""
    _flags, _hs, _r, sec = struct.unpack_from(">IIII", xex, 4)
    image_flags = struct.unpack_from(">I", xex, sec + 0x10C)[0]
    base = struct.unpack_from(">I", xex, sec + 0x110)[0]
    count = struct.unpack_from(">I", xex, sec + 0x180)[0]
    page = 4096 if image_flags & 0x10000000 else 65536
    out, cur = [], base
    for i in range(min(count, 4096)):
        v = struct.unpack_from(">I", xex, sec + 0x184 + i * 24)[0]
        info, pages = v & 0xF, v >> 4
        end = cur + pages * page
        if info == 1:
            out.append((cur, end))
        cur = end
    return out


def project_root_for_exe(exe):
    d = os.path.dirname(os.path.abspath(exe))
    for _ in range(5):
        if os.path.isfile(os.path.join(d, "assets", "default.xex")):
            return d
        d = os.path.dirname(d)
    return ""


def cheats_active_for_exe(exe):
    root = project_root_for_exe(exe)
    return bool(root and cheats_state(root))


def touches_code(writes, ranges):
    return any(a < e and a + len(d) > s for a, d in writes for s, e in ranges)


def cheats_state(root):
    try:
        with open(os.path.join(root, "assets", CHEATS_MARKER), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _note_fps_unlock(root, selected):
    """Anota en las opciones del juego si hay un parche que desbloquea los FPS (el ritmo automático lo usa)."""
    try:
        from .game_options import GameOptions
        from .pc_enhance import unlocks_framerate
        o = GameOptions.load(root)
        val = any(unlocks_framerate(p.name) for p in selected)
        if o.fps_unlocked != val:
            o.fps_unlocked = val
            o.save(root)
    except Exception:      # noqa: BLE001
        pass


def apply_cheats(root, selected):
    """Escribe (o quita) el default.xexp de trucos. selected: [Patch]. Devuelve True si cambió el código
    del juego (hay que recompilar) y False si basta con volver a arrancar."""
    assets = os.path.join(root, "assets")
    xex_path = os.path.join(assets, "default.xex")
    xexp = os.path.join(assets, "default.xexp")
    marker = os.path.join(assets, CHEATS_MARKER)
    prev = cheats_state(root)
    if os.path.isfile(xexp) and prev is None:
        raise CheatError("Este proyecto tiene instalada una actualización del juego (default.xexp). Los trucos "
                         "y la actualización usan el mismo mecanismo: quita la actualización (⬆ Actualización) "
                         "para usar trucos, o usa trucos hechos para la versión actualizada.")
    with open(xex_path, "rb") as f:
        xex = f.read()
    ranges = code_ranges(xex)
    writes = [w for p in selected for w in p.writes]
    code_writes = sorted((a, d.hex()) for a, d in writes if touches_code([(a, d)], ranges))
    prev_code = [tuple(x) for x in (prev or {}).get("code_writes", [])]
    if not writes:
        for p in (xexp, marker):
            if os.path.exists(p):
                os.remove(p)
    else:
        from .xexpatch import build_xexp
        data = build_xexp(xex, writes)
        tmp = xexp + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, xexp)
        with open(marker, "w", encoding="utf-8") as f:
            json.dump({"patches": [p.name for p in selected], "code_writes": code_writes}, f, indent=1)
    _note_fps_unlock(root, selected)
    changed = code_writes != prev_code
    if changed:
        from .game import invalidate_codegen
        invalidate_codegen(root)
    return changed
