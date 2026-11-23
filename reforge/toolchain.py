"""Herramientas de compilación: detección (VS, Clang, CMake, Ninja) y SDK de rexglue."""
import glob
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

WIN = sys.platform == "win32"
NO_WINDOW = 0x08000000 if WIN else 0
EXE = ".exe" if WIN else ""
CLANG_MIN = 20
CMAKE_MIN = (3, 25)


def run_version(path, args=("--version",), env=None, timeout=20):
    """Devuelve (ok, primera_línea, código)."""
    try:
        r = subprocess.run([path, *args], capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL, timeout=timeout, env=env,
                           creationflags=NO_WINDOW)
        out = (r.stdout or r.stderr or "").strip().splitlines()
        return r.returncode == 0, (out[0] if out else ""), r.returncode
    except FileNotFoundError:
        return False, "no encontrado", None
    except Exception as e:  # noqa
        return False, str(e), None


def _num(s, n=3):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", s or "")
    if not m:
        return ()
    return tuple(int(x or 0) for x in m.groups())[:n]


def program_files():
    out = []
    for k in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        v = os.environ.get(k)
        if v and v not in out:
            out.append(v)
    return out or [r"C:\Program Files"]


def _ver_key(text):
    """Clave numérica para comparar versiones de verdad: 0.11 > 0.10 y 1.10 > 1.9 (no alfabético)."""
    return tuple(int(x) for x in re.findall(r"\d+", text or "")[:4])


def vs_installations():
    """Todas las instalaciones de Visual Studio / Build Tools con C++ x64, la MÁS NUEVA primero.

    `vswhere -latest` devuelve la última *instalada*, no necesariamente la de mayor versión (puede quedarse
    una 17 al actualizar a una 18). Aquí se piden todas con versión y se ordenan numéricamente.
    """
    if not WIN:
        return []
    vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                           "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if not os.path.isfile(vswhere):
        return []
    out = []
    try:
        r = subprocess.run([vswhere, "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                            "-format", "json", "-utf8"],
                           capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL, timeout=30,
                           creationflags=NO_WINDOW)
        for d in json.loads((r.stdout or "").lstrip("\ufeff") or "[]"):
            root = (d.get("installationPath") or "").strip()
            vcvars = os.path.join(root, "VC", "Auxiliary", "Build", "vcvars64.bat")
            if root and os.path.isfile(vcvars):
                out.append({"path": root, "vcvars": vcvars,
                            "version": (d.get("installationVersion") or "").split("+")[0],
                            "name": d.get("displayName") or "Visual Studio"})
    except Exception:
        out = []
    if not out:      # vswhere antiguo o JSON no disponible: al menos la que él considera reciente
        for extra in (["-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64"], []):
            try:
                r = subprocess.run([vswhere, "-latest", "-products", "*", *extra, "-property", "installationPath"],
                                   capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL,
                                   timeout=20, creationflags=NO_WINDOW)
                p = (r.stdout or "").strip().splitlines()
                if p and os.path.isdir(p[0]):
                    vcvars = os.path.join(p[0], "VC", "Auxiliary", "Build", "vcvars64.bat")
                    out.append({"path": p[0], "vcvars": vcvars, "version": "", "name": "Visual Studio"})
                    break
            except Exception:
                pass
    out.sort(key=lambda x: _ver_key(x["version"]), reverse=True)
    return out


def visual_studio():
    """Ruta de la instalación MÁS NUEVA de Visual Studio / Build Tools con herramientas de C++ (o '')."""
    inst = vs_installations()
    return inst[0]["path"] if inst else ""


def _first(paths):
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return ""


def find_vcvars(vs):
    return _first([os.path.join(vs, "VC", "Auxiliary", "Build", "vcvars64.bat")]) if vs else ""


def find_cmake(vs, configured=""):
    cands = [configured, shutil.which("cmake")]
    if WIN:
        cands += [os.path.join(pf, "CMake", "bin", "cmake.exe") for pf in program_files()]
        if vs:
            cands.append(os.path.join(vs, "Common7", "IDE", "CommonExtensions", "Microsoft", "CMake", "CMake",
                                      "bin", "cmake.exe"))
    best, best_v = "", ()
    for c in cands:
        if c and os.path.isfile(c):
            ok, line, _ = run_version(c)
            v = _num(line)
            if ok and v > best_v:
                best, best_v = c, v
    return best, ".".join(map(str, best_v))


def newest_versioned(paths, args=("--version",)):
    """De varias rutas de la misma herramienta, la de versión MÁS ALTA que responde. (ruta, versión, línea)."""
    best = ("", (), "")
    seen = set()
    for p in paths:
        if not p or p in seen or not os.path.isfile(p):
            continue
        seen.add(p)
        ok, line, _ = run_version(p, args)
        v = _num(line)
        if ok and v and v > best[1]:
            best = (p, v, line)
    return best


def find_ninja(vs):
    cands = [shutil.which("ninja")]
    if WIN:
        la = os.environ.get("LOCALAPPDATA", "")
        cands.append(os.path.join(la, "Microsoft", "WinGet", "Links", "ninja.exe"))
        cands += glob.glob(os.path.join(la, "Microsoft", "WinGet", "Packages", "Ninja-build.Ninja*", "ninja.exe"))
        if vs:
            cands.append(os.path.join(vs, "Common7", "IDE", "CommonExtensions", "Microsoft", "CMake", "Ninja",
                                      "ninja.exe"))
    p, _v, line = newest_versioned(cands)
    return (p, line) if p else ("", "")


def find_clang(vs):
    """Elige el clang más nuevo disponible. Devuelve (clang, clang++, versión, origen)."""
    cands = []
    if WIN:
        for pf in program_files():
            cands.append((os.path.join(pf, "LLVM", "bin"), "LLVM"))
        if vs:
            cands.append((os.path.join(vs, "VC", "Tools", "Llvm", "x64", "bin"), "Visual Studio"))
    w = shutil.which("clang")
    if w:
        cands.append((os.path.dirname(w), "PATH"))
    if not WIN:
        for n in range(30, 17, -1):
            w = shutil.which(f"clang-{n}")
            if w:
                cands.append((os.path.dirname(w), f"clang-{n}"))
    best = ("", "", (), "")
    seen = set()
    for d, origin in cands:
        if origin.startswith("clang-"):
            cc, cxx = os.path.join(d, origin), os.path.join(d, origin.replace("clang", "clang++"))
        else:
            cc, cxx = os.path.join(d, "clang" + EXE), os.path.join(d, "clang++" + EXE)
        if cc in seen or not os.path.isfile(cc):
            continue
        seen.add(cc)
        ok, line, _ = run_version(cc)
        v = _num(line)
        if ok and v > best[2]:
            best = (cc, cxx if os.path.isfile(cxx) else cc, v, origin)
    return best[0], best[1], ".".join(map(str, best[2])), best[3]


def sdk_prefix_from_exe(rexglue_exe):
    """bin/rexglue(.exe) → raíz del SDK (contiene lib/cmake/rexglue)."""
    if not rexglue_exe:
        return ""
    root = os.path.dirname(os.path.dirname(os.path.abspath(rexglue_exe)))
    return root if os.path.isfile(os.path.join(root, "lib", "cmake", "rexglue", "rexglueConfig.cmake")) else ""


def rexglue_cli_flavor(rexglue_exe, env=None):
    """'project' (CLI actual: --project-name/--xex-path) o 'app' (versiones antiguas: --app_name)."""
    try:
        r = subprocess.run([rexglue_exe, "init", "--help"], capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL, timeout=20,
                           env=env, creationflags=NO_WINDOW)
        txt = (r.stdout or "") + (r.stderr or "")
    except Exception:
        return ""
    if "--project-name" in txt or "--xex-path" in txt:
        return "project"
    if "--app_name" in txt or "--app-name" in txt:
        return "app"
    return ""


def explain_exit(code):
    if code in (-1073741515, 3221225781):   # 0xC0000135
        return "Falta una DLL del sistema (instala Visual C++ Redistributable x64)."
    if code in (-1073741701, 3221225595):   # 0xC000007B
        return "Arquitectura incorrecta (se necesita Windows de 64 bits)."
    return ""

# ============================================================================
#  SDK oficial de rexglue (GitHub Releases)
# ============================================================================
REPO = "rexglue/rexglue-sdk"
API = f"https://api.github.com/repos/{REPO}/releases?per_page=15"
UA = "ReForgeStudio"


def platform_tag():
    m = platform.machine().lower()
    arch = "arm64" if m in ("arm64", "aarch64") else "amd64"
    if sys.platform == "win32":
        return f"win-{arch}"
    if sys.platform == "darwin":
        return f"mac-{arch}"
    return f"linux-{arch}"


def app_base():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _user_tools_root():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "ReForgeStudio", "tools", "rexglue-sdk")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "ReForgeStudio", "tools", "rexglue-sdk")


def tools_root():
    """Instalado con el instalador → <carpeta del programa>/tools/rexglue-sdk (se conserva al actualizar).
    Portable o sin permisos → carpeta del usuario."""
    override = os.environ.get("REFORGE_TOOLS_DIR")
    if override:
        return os.path.join(override, "rexglue-sdk")
    base = app_base()
    if os.path.isfile(os.path.join(base, "version.json")) and os.access(base, os.W_OK):
        return os.path.join(base, "tools", "rexglue-sdk")
    return _user_tools_root()


def _open(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context())


def list_releases(tag=None):
    """Versiones con zip para esta plataforma. Usa la API de GitHub y, si falla
    (límite de consultas, red corporativa…), el feed público de releases."""
    tag = tag or platform_tag()
    try:
        return _list_api(tag)
    except Exception as api_error:
        try:
            out = _list_feed(tag)
            if out:
                return out
        except Exception:
            pass
        raise RuntimeError(f"No se pudo consultar GitHub ({api_error}). Descarga el zip "
                           f"«…-{tag}.zip» desde {RELEASES_URL} y usa «Instalar desde .zip».")


RELEASES_URL = f"https://github.com/{REPO}/releases"


def _list_feed(tag):
    with _open(RELEASES_URL + ".atom") as r:
        feed = r.read().decode("utf-8", "replace")
    out = []
    for entry in re.findall(r"<entry>(.*?)</entry>", feed, re.S)[:8]:
        m = re.search(r"/releases/tag/([^\"<]+)\"", entry)
        if not m:
            continue
        rtag = m.group(1)
        title = re.search(r"<title>(.*?)</title>", entry, re.S)
        date = re.search(r"<updated>(\d{4}-\d{2}-\d{2})", entry)
        with _open(f"{RELEASES_URL}/expanded_assets/{rtag}") as r:
            html = r.read().decode("utf-8", "replace")
        for href in re.findall(r'href="([^"]+/releases/download/[^"]+\.zip)"', html):
            m2 = re.search(r"rexglue-sdk-(.+)-" + re.escape(tag) + r"\.zip$", href)
            if m2:
                url = href if href.startswith("http") else "https://github.com" + href
                out.append({"version": m2.group(1), "name": (title.group(1).strip() if title else rtag),
                            "date": date.group(1) if date else "", "url": url, "size": 0,
                            "prerelease": "nightly" in rtag.lower(), "tag": rtag})
    return out


def _list_api(tag):
    with _open(API) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = []
    for rel in data:
        for a in rel.get("assets", []):
            name = a.get("name", "")
            m = re.match(r"rexglue-sdk-(.+)-" + re.escape(tag) + r"\.zip$", name)
            if m:
                out.append({"version": m.group(1), "name": rel.get("name") or rel.get("tag_name"),
                            "date": (rel.get("published_at") or "")[:10], "url": a["browser_download_url"],
                            "size": a.get("size", 0), "prerelease": rel.get("prerelease", False),
                            "tag": rel.get("tag_name", "")})
    return out


def _sdk_key(version):
    """Orden real de versiones de SDK (0.11.0.13 > 0.10.0.24) y, a igual versión, la variante FSR primero."""
    return (_ver_key(version), 1 if "fsr" in (version or "").lower() else 0)


def sdk_roots():
    """Carpetas donde puede haber SDK de rexglue: instalación, usuario y rutas típicas de Program Files."""
    roots = [tools_root(), _user_tools_root()]
    if WIN:
        la = os.environ.get("LOCALAPPDATA", "")
        if la:
            roots.append(os.path.join(la, "Programs", "ReForge Studio", "tools", "rexglue-sdk"))
        for pf in program_files():
            roots.append(os.path.join(pf, "ReForge Studio", "tools", "rexglue-sdk"))
            roots.append(os.path.join(pf, "rexglue-sdk"))
            roots.append(os.path.join(pf, "ReForge", "rexglue-sdk"))
    out = []
    for r in roots:
        r = os.path.normpath(r)
        if r and r not in out and os.path.isdir(r):
            out.append(r)
    return out


def installed_sdks():
    """[(versión, prefijo, exe)] de los SDK instalados, el MÁS NUEVO primero."""
    out, seen = [], set()
    for root in sdk_roots():
        try:
            versions = [v for v in os.listdir(root) if not v.endswith(".tmp")]
        except OSError:
            continue
        for ver in sorted(versions, key=_sdk_key, reverse=True):
            d = os.path.join(root, ver)
            if not os.path.isdir(d):
                continue
            exe = find_exe(d)
            if exe and exe not in seen:
                seen.add(exe)
                out.append((ver, os.path.dirname(os.path.dirname(exe)), exe))
    out.sort(key=lambda t: _sdk_key(t[0]), reverse=True)
    return out


def _version_of(path):
    """Versión que reporta un ejecutable ((), si no se puede ejecutar)."""
    if not path:
        return ()
    ok, line, _ = run_version(path)
    return _num(line) if ok else ()


def _newer(new, cur):
    """¿`new` es una versión más nueva que `cur` (o `cur` no existe/no se puede ejecutar)?"""
    if not new:
        return False
    if not cur or not os.path.isfile(cur):
        return True
    nv, cv = _version_of(new), _version_of(cur)
    return bool(nv) and (not cv or nv > cv)


def _vs_install_of(vcvars):
    """Instalación de Visual Studio a la que pertenece un vcvars64.bat (o {})."""
    p = os.path.normcase(os.path.normpath(vcvars or ""))
    if not p:
        return {}
    for inst in vs_installations():
        if p.startswith(os.path.normcase(os.path.normpath(inst["path"])) + os.sep):
            return inst
    return {}


def latest():
    """Las versiones MÁS NUEVAS instaladas de cada herramienta de compilación (y el SDK más nuevo)."""
    inst = vs_installations()
    vs = inst[0] if inst else {}
    vs_path = vs.get("path", "")
    cmake, cmake_v = find_cmake(vs_path)
    ninja, ninja_v = find_ninja(vs_path)
    cc, cxx, clang_v, clang_origin = find_clang(vs_path)
    sdks = installed_sdks()
    sdk_ver, sdk_prefix, sdk_exe = sdks[0] if sdks else ("", "", "")
    return {
        "vs": vs,
        "vcvars": vs.get("vcvars", ""),
        "cmake": {"path": cmake, "version": cmake_v},
        "ninja": {"path": ninja, "version": ninja_v},
        "clang": {"cc": cc, "cxx": cxx, "version": clang_v, "origin": clang_origin},
        "sdk": {"version": sdk_ver, "prefix": sdk_prefix, "exe": sdk_exe},
    }


def describe(info=None):
    """Línea legible de las versiones elegidas: «CMake 4.3.1 · Ninja 1.13.2 · Clang 23.1.3 · …»."""
    i = info if info is not None else latest()
    parts = []
    if i.get("cmake", {}).get("path"):
        parts.append("CMake " + (i["cmake"].get("version") or "?"))
    if i.get("ninja", {}).get("path"):
        parts.append("Ninja " + (i["ninja"].get("version") or "?").split()[0])
    if i.get("clang", {}).get("cc"):
        parts.append("Clang " + (i["clang"].get("version") or "?"))
    vs = i.get("vs") or {}
    if vs.get("version"):
        parts.append("VS " + ".".join(vs["version"].split(".")[:2]))
    if i.get("sdk", {}).get("version"):
        parts.append("SDK " + i["sdk"]["version"])
    return " · ".join(parts)


def sdk_version(cfg):
    """Versión del SDK de rexglue configurado (…/<versión>/win-amd64[/bin/rexglue.exe]) o ''."""
    prefix = (getattr(cfg, "rexglue_sdk", "") or "").strip()
    if prefix:
        return os.path.basename(os.path.dirname(os.path.normpath(prefix)))
    exe = (getattr(cfg, "rexglue", "") or "").strip()
    if exe:
        return os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.normpath(exe)))))
    return ""


def upgrade_config(cfg, info=None, allow_sdk=True):
    """Pone en `cfg` las versiones MÁS NUEVAS instaladas de VS, CMake, Ninja y Clang.

    Solo sube de versión: si la configurada ya es la más nueva (o no se puede ejecutar), se queda como está.
    El SDK se actualiza solo cuando `allow_sdk` (proyecto nuevo): cambiarlo en una build que funciona fuerza una
    reconfiguración completa y una versión *dev* nueva puede no compilar ese proyecto.
    Devuelve (cambios legibles, info de versiones).
    """
    i = info if info is not None else latest()
    changes = []

    def take(attr, new, label, ver=""):
        cur = (getattr(cfg, attr, "") or "").strip()
        if new and new != cur and _newer(new, cur):
            setattr(cfg, attr, new)
            changes.append(f"{label} {ver}".strip() + " (la versión más nueva instalada)")

    take("cmake", i.get("cmake", {}).get("path", ""), "CMake", i.get("cmake", {}).get("version", ""))
    take("ninja", i.get("ninja", {}).get("path", ""), "Ninja", i.get("ninja", {}).get("version", ""))
    clang = i.get("clang", {})
    if clang.get("cxx"):
        cur_cxx = (getattr(cfg, "cxx_compiler", "") or "").strip()
        if cur_cxx != clang["cxx"] and _newer(clang["cxx"], cur_cxx):
            cfg.cxx_compiler = clang["cxx"]
            changes.append("Clang más nuevo: " + (clang.get("version") or ""))
            cur_cc = (getattr(cfg, "c_compiler", "") or "").strip()
            if clang.get("cc") and (not cur_cc or "clang" in os.path.basename(cur_cc).lower()):
                cfg.c_compiler = clang["cc"]
    new_vs = i.get("vs") or {}
    if new_vs.get("vcvars"):
        old_vs = _vs_install_of(getattr(cfg, "vcvars", ""))
        if not old_vs or _ver_key(new_vs.get("version", "")) > _ver_key(old_vs.get("version", "")):
            if new_vs["vcvars"] != (getattr(cfg, "vcvars", "") or ""):
                cfg.vcvars = new_vs["vcvars"]
                changes.append("Visual Studio más nuevo: " + (new_vs.get("version") or new_vs.get("name") or ""))
    sdk = i.get("sdk") or {}
    if allow_sdk and sdk.get("prefix") and sdk.get("exe") and os.path.isdir(sdk["prefix"]):
        if _sdk_key(sdk.get("version", "")) > _sdk_key(sdk_version(cfg)):
            cfg.rexglue_sdk, cfg.rexglue = sdk["prefix"], sdk["exe"]
            cfg.cli_flavor = ""
            changes.append("SDK de rexglue más nuevo: " + sdk["version"])
    return changes, i


def sdk_update_available(cfg, info=None):
    """Versión del SDK instalado si es más nueva que la configurada (o "")."""
    i = info if info is not None else latest()
    v = (i.get("sdk") or {}).get("version", "")
    return v if v and _sdk_key(v) > _sdk_key(sdk_version(cfg)) else ""


def find_exe(folder):
    name = "rexglue.exe" if sys.platform == "win32" else "rexglue"
    for dp, _dn, fn in os.walk(folder):
        if name in fn and os.path.basename(dp) == "bin":
            return os.path.join(dp, name)
    return ""


def download(url, dest, ctx, expected=0):
    tmp = dest + ".part"
    done = 0
    with _open(url, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or expected or 0)
        while True:
            if ctx.cancelled():
                f.close()
                os.remove(tmp)
                raise RuntimeError("Descarga cancelada")
            buf = r.read(1 << 20)
            if not buf:
                break
            f.write(buf)
            done += len(buf)
            if total:
                ctx.progress(int(done * 1000 / total), 1000)
    if expected and done != expected:
        os.remove(tmp)
        raise RuntimeError(f"Descarga incompleta ({done} de {expected} bytes)")
    os.replace(tmp, dest)
    return dest


def install_zip(zip_path, version, ctx):
    """Extrae el zip en tools/rexglue-sdk/<versión>/ de forma atómica. Devuelve (prefijo, exe)."""
    root = tools_root()
    os.makedirs(root, exist_ok=True)
    final = os.path.join(root, version)
    staging = final + ".tmp"
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as z:
        members = [m for m in z.infolist() if not m.is_dir()]
        total = sum(m.file_size for m in members) or 1
        done = 0
        real_staging = os.path.realpath(staging)
        for m in members:
            target = os.path.realpath(os.path.join(staging, m.filename))
            if not target.startswith(real_staging + os.sep):
                raise RuntimeError(f"Ruta no válida en el zip: {m.filename}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(m) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            mode = (m.external_attr >> 16) & 0o777
            if os.name != "nt" and mode:
                os.chmod(target, mode)
            done += m.file_size
            ctx.progress(int(done * 1000 / total), 1000)
    exe = find_exe(staging)
    if not exe:
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError("El zip no contiene bin/rexglue")
    if os.name != "nt":
        os.chmod(exe, 0o755)
    shutil.rmtree(final, ignore_errors=True)
    os.replace(staging, final)
    exe = find_exe(final)
    return os.path.dirname(os.path.dirname(exe)), exe


def version_from_zip_name(path):
    m = re.search(r"rexglue-sdk-(.+?)-(?:win|linux|mac)-(?:amd64|arm64)\.zip$", os.path.basename(path))
    return m.group(1) if m else os.path.splitext(os.path.basename(path))[0]


def download_and_install(release, ctx):
    size = f" ({release['size'] / 1e6:.0f} MB)" if release.get("size") else ""
    ctx.log(f"Descargando {release['name']}{size}…")
    tmpdir = tempfile.mkdtemp(prefix="rexglue-")
    try:
        z = download(release["url"], os.path.join(tmpdir, "sdk.zip"), ctx, release.get("size", 0))
        ctx.log("Extrayendo…")
        return install_zip(z, release["version"], ctx)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
