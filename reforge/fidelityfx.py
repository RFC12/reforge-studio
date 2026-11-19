"""Compilar el SDK de rexglue con AMD FidelityFX (FSR 1 y CAS dentro del juego).

Las versiones oficiales de rexglue se publican sin FidelityFX (es una opción experimental al compilarlo). Aquí
se compila, una sola vez por PC, exactamente la misma versión del SDK que estás usando, con
REXGLUE_ENABLE_FIDELITYFX=ON, y se instala como «<versión>-fsr». Después, al recompilar cada juego, su
rexruntime.dll trae FSR/CAS y aparecen en 🎮 Opciones → «Escalado / nitidez».

Además deja una copia en Documentos\\ReForgeStudio\\Respaldo para reinstalarla sin compilar (también tras
formatear: el instalador de ReForge la usa si está junto a él).
"""
import os
import re
import shutil
import sys
import tempfile
import zipfile

from . import toolchain

REPO_URL = "https://github.com/rexglue/rexglue-sdk"
FSR_SUFFIX = "-fsr"


def is_fsr_version(version):
    return str(version or "").endswith(FSR_SUFFIX)


def commit_for_version(version):
    """«0.10.0.24-dev.gbd833a2» → «bd833a2»; «0.10.0» → «v0.10.0»."""
    v = str(version or "").removesuffix(FSR_SUFFIX)
    m = re.search(r"\.g([0-9a-f]{7,40})$", v)
    return m.group(1) if m else ("v" + v if v else "")


def build_root():
    """Carpeta de compilación con ruta corta (Windows tiene un límite de 260 caracteres por ruta)."""
    if sys.platform == "win32":
        for base in (os.environ.get("SystemDrive", "C:") + "\\ReForgeBuild",
                     os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "RFB")):
            try:
                os.makedirs(base, exist_ok=True)
                return base
            except OSError:
                continue
    return os.path.join(os.path.expanduser("~"), ".cache", "reforge-build")


def backup_dir():
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.join(docs if os.path.isdir(docs) else os.path.expanduser("~"), "ReForgeStudio", "Respaldo")


def find_git():
    """git del sistema o el portátil de ReForge (tools/git)."""
    found = shutil.which("git")
    if found:
        return found
    local = os.path.join(os.path.dirname(toolchain._user_tools_root()), "git", "cmd", "git.exe")
    return local if os.path.isfile(local) else ""


def ensure_git(ctx):
    """Descarga MinGit (portátil, sin instalar nada en Windows) si no hay git."""
    git = find_git()
    if git:
        return git
    if sys.platform != "win32":
        raise RuntimeError("Instala git con el gestor de paquetes de tu sistema.")
    import json
    ctx.log("Descargando git portátil (MinGit) para bajar el código de rexglue…")
    with toolchain._open("https://api.github.com/repos/git-for-windows/git/releases/latest") as r:
        rel = json.loads(r.read().decode("utf-8"))
    asset = next(a for a in rel["assets"] if re.match(r"^MinGit-[\d.]+-64-bit\.zip$", a["name"]))
    dest = os.path.join(os.path.dirname(toolchain._user_tools_root()), "git")
    tmp = tempfile.mkdtemp(prefix="mingit-")
    try:
        z = toolchain.download(asset["browser_download_url"], os.path.join(tmp, "mingit.zip"), ctx, asset.get("size", 0))
        with zipfile.ZipFile(z) as zf:
            zf.extractall(dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    git = os.path.join(dest, "cmd", "git.exe")
    if not os.path.isfile(git):
        raise RuntimeError("No se pudo preparar git")
    return git


def fix_symlinks(git, src, env):
    """git en Windows (sin modo desarrollador) deja los enlaces simbólicos como archivos de texto con la ruta
    de destino (p. ej. libmspack/cabextract/mspack/*.c) y la compilación falla. Se sustituyen por una copia."""
    import subprocess
    nw = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    out = subprocess.run([git, "-C", src, "submodule", "foreach", "--recursive", "--quiet", "pwd"], env=env,
                         capture_output=True, text=True, errors="replace", creationflags=nw).stdout
    repos = [src] + [re.sub(r"^/([a-zA-Z])/", r"\1:/", ln.strip()) for ln in out.splitlines() if ln.strip()]
    n = 0
    for repo in repos:
        ls = subprocess.run([git, "-C", repo, "ls-files", "-s"], env=env, capture_output=True,
                            text=True, errors="replace", creationflags=nw).stdout
        for line in ls.splitlines():
            m = re.match(r"^120000 \S+ \d\t(.+)$", line)
            if not m:
                continue
            link = os.path.join(repo, m.group(1))
            if not os.path.isfile(link) or os.path.getsize(link) > 1024:
                continue
            target = open(link, encoding="utf-8", errors="replace").read().strip()
            dst = os.path.normpath(os.path.join(os.path.dirname(link), target))
            if os.path.isfile(dst):
                shutil.copyfile(dst, link)
                n += 1
            elif os.path.isdir(dst):
                os.remove(link)
                shutil.copytree(dst, link)
                n += 1
    return n


def _run(cmd, cwd, env, ctx, what):
    from .game import run_streaming
    code, _lines = run_streaming(cmd, cwd, env, ctx)
    if code != 0:
        raise RuntimeError(f"{what} terminó con código {code} (revisa el log)")


def build(cfg, version, ctx):
    """Compila e instala el SDK con FidelityFX. Devuelve (prefijo, exe, zip_de_respaldo)."""
    commit = commit_for_version(version)
    if not commit:
        raise RuntimeError("No se sabe qué versión de rexglue compilar: elige primero un SDK en Entorno.")
    env = cfg.environment()
    git = ensure_git(ctx)
    env["PATH"] = os.path.dirname(git) + os.pathsep + env.get("PATH", "")
    cmake = getattr(cfg, "cmake", "") or "cmake"
    src = os.path.join(build_root(), "rexglue-sdk")
    root = build_root()
    tag = toolchain.platform_tag()
    ctx.log(f"Versión: rexglue {version} (commit {commit}) · carpeta de compilación {src}")
    _run([git, "config", "--global", "core.longpaths", "true"], root, env, ctx, "git config")
    if not os.path.isdir(os.path.join(src, ".git")):
        ctx.log("Bajando el código de rexglue (una sola vez)…")
        _run([git, "clone", "--filter=blob:none", REPO_URL, src], root, env, ctx, "git clone")
    _run([git, "fetch", "--tags", "origin"], src, env, ctx, "git fetch")
    _run([git, "checkout", "-f", commit], src, env, ctx, "git checkout")
    ctx.log("Bajando las dependencias (submódulos)…")
    _run([git, "submodule", "update", "--init", "--recursive", "--depth", "1", "--jobs", "8"], src, env, ctx,
         "git submodule")
    if sys.platform == "win32":
        n = fix_symlinks(git, src, env)
        if n:
            ctx.log(f"Sustituidos {n} enlaces simbólicos por sus archivos (Windows los baja como texto).", "dim")
    from .sdk_patch import apply_all
    _changed, aplicados, saltados = apply_all(src)
    if aplicados:
        ctx.log("Parches de ReForge aplicados: " + ", ".join(aplicados) + ".", "dim")
    for nombre, motivo in saltados:
        # Un parche no imprescindible que no encaja en esta versión del SDK (un cambio del código movió su
        # sitio): se avisa y se sigue. Los imprescindibles habrían detenido la compilación antes.
        ctx.log(f"Parche «{nombre}» omitido en esta versión de rexglue ({motivo}). El SDK se compila igual; "
                "esa mejora concreta no estará hasta actualizar ReForge.", "warn")
    ctx.log("Configurando con AMD FidelityFX…")
    _run([cmake, "--preset", tag, "-DREXGLUE_ENABLE_FIDELITYFX=ON"], src, env, ctx, "cmake (configurar)")
    ctx.log("Compilando el SDK (tarda: es todo rexglue)…")
    build_dir = os.path.join(src, "out", "build", tag)
    _run([cmake, "--build", build_dir, "--config", "Release", "--target", "install", "--parallel"], src, env, ctx,
         "cmake (compilar)")
    installed = os.path.join(src, "out", "install", tag)
    runtime = [os.path.join(dp, f) for dp, _dn, fs in os.walk(installed) for f in fs
               if f.lower().startswith(("rexruntime", "librexruntime"))]
    if not runtime or not any(b"Guest output effect: bilinear, cas, fsr" in open(p, "rb").read() for p in runtime):
        raise RuntimeError("El SDK se compiló pero sin FidelityFX (revisa el log de cmake: puede faltar una "
                           "dependencia de AMD FidelityFX).")
    # zip de respaldo (para reinstalar sin compilar, también tras formatear) e instalación en ReForge
    os.makedirs(backup_dir(), exist_ok=True)
    fsr_version = str(version).removesuffix(FSR_SUFFIX) + FSR_SUFFIX
    zpath = os.path.join(backup_dir(), f"rexglue-sdk-{fsr_version}-{tag}.zip")
    ctx.log(f"Guardando copia de respaldo: {zpath}")
    tmpz = zpath + ".tmp"
    with zipfile.ZipFile(tmpz, "w", zipfile.ZIP_DEFLATED) as zf:
        for dp, _dn, fs in os.walk(installed):
            for f in fs:
                full = os.path.join(dp, f)
                zf.write(full, os.path.join(tag, os.path.relpath(full, installed)))
    os.replace(tmpz, zpath)
    prefix, exe = toolchain.install_zip(zpath, fsr_version, ctx)
    ctx.log(f"✔ rexglue {fsr_version} con FSR/CAS instalado en {prefix}", "ok")
    return prefix, exe, zpath
