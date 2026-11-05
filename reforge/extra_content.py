"""Contenido extra de un juego: DLC, contenido instalado desde otro disco, actualización y discos 2, 3…

Cómo lo busca el juego recompilado (igual que rexglue/Xenia):
* Paquetes de contenido (tipo 00000002: DLC y la «instalación» del disco 2 de juegos como Call of Duty AW,
  GTA V…): carpeta extraída en <datos de usuario>/0000000000000000/<TitleID>/00000002/<nombre del paquete>/
  más una cabecera <datos>/0000000000000000/<TitleID>/Headers/00000002/<nombre>.header (XCONTENT_AGGREGATE_DATA,
  0x148 bytes big-endian, y la máscara de licencias). <datos de usuario> = Documentos/<nombre del ejecutable>.
  Los paquetes se guardan junto al proyecto (content/) y en Documentos queda un enlace (junction): no llenan C:.
* Actualización (000B0000): la instala title_update (default.xexp + archivos del parche en update/).
* Juegos de varios discos: los datos de los discos 2, 3… se unen en assets (sin pisar los del disco 1); si
  un disco trae paquetes de contenido, se instalan como tales.

ReForge lo encuentra solo: en la carpeta GOD/«Content» del juego (<TitleID>/00000002, 000B0000, 00007000),
junto a la ISO del disco 1 («Disc 2», «Disco 2», «CD2»…) o en la carpeta que elijas.
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys

from .xcontent import MAGICS, XContentError, XContentPackage

TYPE_GAME = 0x00007000
TYPE_DLC = 0x00000002
TYPE_UPDATE = 0x000B0000
STATE_FILE = "reforge_extras.json"
DISC_RE = re.compile(r"(disc|disco|disk|cd|dvd)[\s._\-]*([1-9])", re.I)
HDD_DEVICE = 1
AGG_SIZE = 0x148


# ---------------------------------------------------------------- rutas
def documents_dir():
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:   # CSIDL_PERSONAL
                return buf.value
        except Exception:      # noqa: BLE001
            pass
        return os.path.join(os.path.expanduser("~"), "Documents")
    return os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")


def user_data_root(root):
    """Carpeta de datos de usuario que usa el juego recompilado (Documentos/<nombre del ejecutable>)."""
    from .game import manifest_project_name
    name = manifest_project_name(root) or os.path.basename(os.path.normpath(root))
    return os.path.join(documents_dir(), name)


def title_id_of(root):
    from .xex import read_xex_info
    return read_xex_info(os.path.join(root, "assets", "default.xex")).get("title_id", "").upper()


def _link_dir(link, target):
    """Enlace de carpeta (junction en Windows, sin permisos de administrador; symlink en Linux)."""
    os.makedirs(os.path.dirname(link), exist_ok=True)
    if os.path.islink(link) or _is_junction(link):
        try:
            if os.path.realpath(link) == os.path.realpath(target):
                return True
        except OSError:
            pass
        os.unlink(link) if os.path.islink(link) else os.rmdir(link)
    elif os.path.isdir(link):
        # ya había paquetes en Documentos: se mueven al proyecto y se enlaza
        for n in os.listdir(link):
            if not os.path.exists(os.path.join(target, n)):
                shutil.move(os.path.join(link, n), os.path.join(target, n))
        shutil.rmtree(link, ignore_errors=True)
    if sys.platform == "win32":
        r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True,
                           creationflags=0x08000000, stdin=subprocess.DEVNULL)
        return r.returncode == 0
    os.symlink(target, link, target_is_directory=True)
    return True


def _is_junction(path):
    try:
        return bool(os.lstat(path).st_file_attributes & 0x400)     # FILE_ATTRIBUTE_REPARSE_POINT
    except (OSError, AttributeError):
        return False


# ---------------------------------------------------------------- cabecera de contenido
def aggregate_header(file_name, display_name, title_id, content_type=TYPE_DLC, xuid=0):
    """XCONTENT_AGGREGATE_DATA (0x148 bytes, big-endian) como la escribe rexglue."""
    b = bytearray(AGG_SIZE)
    struct.pack_into(">II", b, 0, HDD_DEVICE, content_type)
    name16 = (display_name or file_name)[:127].encode("utf-16-be")
    b[8:8 + len(name16)] = name16
    fn = file_name.encode("ascii", "replace")[:42]
    b[264:264 + len(fn)] = fn
    struct.pack_into(">QI", b, 312, xuid, int(title_id, 16) if isinstance(title_id, str) else title_id)
    return bytes(b)


def license_mask(pkg_path):
    """Máscara de licencias de la cabecera STFS (como InstallContentPackage de rexglue)."""
    with open(pkg_path, "rb") as f:
        h = f.read(0x22C + 16 * 16)
    mask = 0
    for i in range(16):
        _lid, bits, flags = struct.unpack_from(">QII", h, 0x22C + i * 16)
        if flags:
            mask |= bits
    return mask


# ---------------------------------------------------------------- encontrar contenido
def _is_package(path):
    try:
        with open(path, "rb") as f:
            return f.read(4) in MAGICS
    except OSError:
        return False


def _content_type(path):
    with open(path, "rb") as f:
        f.seek(0x344)
        return struct.unpack(">I", f.read(4))[0]


def find_extras(source, title_id, exclude=()):
    """{dlc: [...], update: [...], discs: [...]} encontrados en `source` (carpeta GOD/Content, ISO o carpeta)."""
    out = {"dlc": [], "update": [], "discs": []}
    title_id = title_id.upper()
    excl = {os.path.normcase(os.path.abspath(p)) for p in exclude if p}
    roots = []
    if os.path.isfile(source):
        d = os.path.dirname(os.path.abspath(source))
        # <TitleID>/<tipo>/<paquete>  →  buscar en <TitleID>
        up = os.path.dirname(d)
        roots.append(up if os.path.basename(up).upper() == title_id else d)
        if source.lower().endswith(".iso"):
            out["discs"] += other_discs(source)
    elif os.path.isdir(source):
        roots.append(source)
    seen = set()
    for base in roots:
        for d, subs, files in os.walk(base):
            subs[:] = [s for s in subs if not s.lower().endswith(".data")]
            if d.count(os.sep) - base.count(os.sep) > 4:
                subs[:] = []
            for f in files:
                p = os.path.join(d, f)
                key = os.path.normcase(os.path.abspath(p))
                if key in seen or key in excl or os.path.getsize(p) < 0xA000 or not _is_package(p):
                    continue
                seen.add(key)
                try:
                    ct = _content_type(p)
                    with XContentPackage(p) as pkg:
                        tid = pkg.title_id.upper()
                except (OSError, XContentError, struct.error, KeyError):
                    continue
                if tid != title_id:
                    continue
                if ct == TYPE_DLC:
                    out["dlc"].append(p)
                elif ct == TYPE_UPDATE:
                    out["update"].append(p)
                elif ct == TYPE_GAME:
                    out["discs"].append(p)
    return out


def other_discs(iso):
    """ISOs hermanas del disco 1 («… Disc 2.iso», «… (Disco 2).iso», «CD2.iso»…)."""
    folder, name = os.path.split(os.path.abspath(iso))
    m = DISC_RE.search(name)
    if not m:
        return []
    pat = re.compile(re.escape(name[:m.start(2)]) + r"([1-9])" + re.escape(name[m.end(2):]), re.I)
    out = []
    for f in sorted(os.listdir(folder)):
        mm = pat.fullmatch(f)
        if mm and mm.group(1) != m.group(2):
            out.append(os.path.join(folder, f))
    return out


# ---------------------------------------------------------------- instalar
def _state(root):
    try:
        with open(os.path.join(root, STATE_FILE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"dlc": {}, "discs": {}}


def _save_state(root, st):
    with open(os.path.join(root, STATE_FILE), "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1, ensure_ascii=False)


def install_dlc(root, pkg_path, log=print, progress=None, cancelled=None):
    """Extrae un paquete de contenido para el juego recompilado. Devuelve su nombre visible."""
    tid = title_id_of(root)
    file_name = os.path.basename(pkg_path)
    store = os.path.join(root, "content", "00000002")
    os.makedirs(store, exist_ok=True)
    udr = user_data_root(root)
    _link_dir(os.path.join(udr, "0000000000000000", tid, "00000002"), store)
    dest = os.path.join(store, file_name)
    with XContentPackage(pkg_path) as pkg:
        name = pkg.display_name or pkg.title_name or file_name
        if not os.path.isdir(dest) or not os.listdir(dest):
            log(f"  📦 {name} ({file_name})")
            tmp = dest + ".partial"
            shutil.rmtree(tmp, ignore_errors=True)
            pkg.extract(tmp, progress=progress, cancelled=cancelled)
            os.replace(tmp, dest)
        else:
            log(f"  ✔ {name} ya estaba instalado")
    hdr_dir = os.path.join(udr, "0000000000000000", tid, "Headers", "00000002")
    os.makedirs(hdr_dir, exist_ok=True)
    with open(os.path.join(hdr_dir, file_name + ".header"), "wb") as f:
        f.write(aggregate_header(file_name, name, tid))
        mask = license_mask(pkg_path)
        if mask:
            f.write(struct.pack("<I", mask))
    st = _state(root)
    st.setdefault("dlc", {})[file_name] = {"nombre": name, "origen": os.path.abspath(pkg_path)}
    _save_state(root, st)
    return name


def merge_disc(root, src, log=print, progress=None, cancelled=None):
    """Une los datos de otro disco (ISO o GOD) en assets; los paquetes de contenido que traiga se instalan."""
    from .xiso import XisoImage
    assets = os.path.join(root, "assets")
    tmp = os.path.join(root, "_disco_tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    opener = XisoImage if src.lower().endswith(".iso") else XContentPackage
    with opener(src) as img:
        img.extract(tmp, progress=progress, cancelled=cancelled)
    added = same = conflict = 0
    for d, _subs, files in os.walk(tmp):
        for f in files:
            s = os.path.join(d, f)
            rel = os.path.relpath(s, tmp)
            if _is_package(s) and os.path.getsize(s) >= 0xA000:
                try:
                    if _content_type(s) == TYPE_DLC:
                        install_dlc(root, s, log)
                        continue
                except (OSError, XContentError, struct.error):
                    pass
            if rel.lower() in ("default.xex", "default.xexp"):
                continue
            t = os.path.join(assets, rel)
            if not os.path.exists(t):
                os.makedirs(os.path.dirname(t), exist_ok=True)
                shutil.move(s, t)
                added += 1
            elif os.path.getsize(t) == os.path.getsize(s):
                same += 1
            else:
                conflict += 1
    shutil.rmtree(tmp, ignore_errors=True)
    st = _state(root)
    st.setdefault("discs", {})[os.path.basename(src)] = {"añadidos": added, "iguales": same, "distintos": conflict}
    _save_state(root, st)
    log(f"  💿 {os.path.basename(src)}: {added} archivo(s) nuevos unidos a assets"
        + (f" · {same} ya estaban" if same else "") + (f" · {conflict} distintos (se deja el del disco 1)"
                                                       if conflict else ""))
    return added


def install_extras(root, source, log=print, progress=None, cancelled=None, main_package=""):
    """Busca y aplica todo el contenido extra del juego en `source`. Devuelve un resumen."""
    tid = title_id_of(root)
    if not tid:
        return {}
    found = find_extras(source, tid, exclude=[main_package])
    st = _state(root)
    done = {"dlc": 0, "update": "", "discs": 0}
    for p in found["discs"]:
        if os.path.basename(p) in st.get("discs", {}):
            continue
        try:
            with XContentPackage(p) as pkg:
                disc = pkg.disc
        except (OSError, XContentError):
            disc = 0
        if p.lower().endswith(".iso") or disc != 1:
            done["discs"] += 1
            merge_disc(root, p, log, progress, cancelled)
    for p in found["dlc"]:
        install_dlc(root, p, log, progress, cancelled)
        done["dlc"] += 1
    if found["update"]:
        from .title_update import check_update, install_update, installed_update
        best = None
        for p in found["update"]:
            try:
                info = check_update(root, p)
                if not best or info.get("version", "") > best[1].get("version", ""):
                    best = (p, info)
            except Exception as e:      # noqa: BLE001
                log(f"  ⚠ {os.path.basename(p)}: {e}")
        cur = installed_update(root) or {}
        if best and best[1].get("version") != cur.get("version"):
            install_update(root, best[0], lambda m: None)
            done["update"] = best[1].get("version", "?")
            log(f"  ⬆ Actualización {done['update']} instalada (ejecutable y archivos del parche)")
    return done


def installed(root):
    st = _state(root)
    return {"dlc": [v.get("nombre", k) for k, v in st.get("dlc", {}).items()], "discs": list(st.get("discs", {}))}
