"""Configuración, biblioteca de proyectos, comandos y utilidades de sistema."""
import datetime
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, fields

APP_DIR_NAME = "ReForgeStudio"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def config_dir():
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    d = os.path.join(base, APP_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


TOOL_DEFAULTS = {
    "rexglue": "rexglue",
    "cmake": "cmake",
    "xenonrecomp": "XenonRecomp",
    "xenonanalyse": "XenonAnalyse",
}


@dataclass
class AppConfig:
    rexglue: str = ""
    cmake: str = ""
    generator: str = ""
    build_type: str = "Release"
    c_compiler: str = ""
    cxx_compiler: str = ""
    jobs: int = os.cpu_count() or 4
    extra_cmake_args: str = ""
    extra_env: str = ""
    vcvars: str = ""
    ninja: str = ""              # ruta del Ninja más nuevo (se pasa a CMake como CMAKE_MAKE_PROGRAM)
    latest_tools: bool = True    # 1.47: al compilar, subir a las versiones más nuevas instaladas de VS/CMake/Ninja/Clang
    xenonrecomp: str = ""
    xenonanalyse: str = ""
    ppc_context: str = ""
    workspace: str = os.path.join(os.path.expanduser("~"), "ReForgeProjects")
    accent: str = "Esmeralda"
    # 1.2: entorno de rexglue
    rexglue_sdk: str = ""        # prefijo del SDK (contiene lib/cmake/rexglue) → CMAKE_PREFIX_PATH
    path_dirs: str = ""          # carpetas extra para PATH al compilar (separadas por os.pathsep)
    cli_flavor: str = ""         # "project" (CLI actual) | "app" (rexglue antiguo) | "" = detectar
    watch_games: bool = True     # 1.7: detectar el juego abierto y repararlo si falla

    @staticmethod
    def path():
        return os.path.join(config_dir(), "config.json")

    @classmethod
    def load(cls):
        cfg = cls()
        try:
            with open(cls.path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            names = {f.name for f in fields(cls)}
            for k, v in data.items():
                if k in names:
                    setattr(cfg, k, v)
        except Exception:
            pass
        return cfg

    def save(self):
        with open(self.path(), "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    def tool(self, key):
        v = (getattr(self, key, "") or "").strip()
        if v:
            return v
        d = TOOL_DEFAULTS[key]
        return shutil.which(d) or d

    def sdk_prefix(self):
        if self.rexglue_sdk and os.path.isdir(self.rexglue_sdk):
            return self.rexglue_sdk
        exe = self.tool("rexglue")
        if exe and os.path.isfile(exe):
            root = os.path.dirname(os.path.dirname(os.path.abspath(exe)))
            if os.path.isfile(os.path.join(root, "lib", "cmake", "rexglue", "rexglueConfig.cmake")):
                return root
        return ""

    def environment(self):
        env = dict(os.environ)
        if os.name == "nt":
            env = {k.upper(): v for k, v in env.items()}
            if self.vcvars.strip():
                env.update({k.upper(): v for k, v in load_vcvars_env(self.vcvars.strip()).items()})
        extra = [d for d in (self.path_dirs or "").split(os.pathsep) if d and os.path.isdir(d)]
        if extra:
            env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
        prefix = self.sdk_prefix()
        if prefix:
            old = env.get("CMAKE_PREFIX_PATH", "")
            env["CMAKE_PREFIX_PATH"] = prefix + (os.pathsep + old if old and prefix not in old else "")
        for line in re.split(r"[;\n]", self.extra_env or ""):
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip():
                    env[k.strip().upper() if os.name == "nt" else k.strip()] = v.strip()
        return env


_VC_CACHE = {}


def load_vcvars_env(path):
    if path in _VC_CACHE:
        return _VC_CACHE[path]
    env = {}
    if os.path.isfile(path):
        try:
            r = subprocess.run(f'"{path}" >nul && set', shell=True, capture_output=True,
                               text=True, errors="replace", stdin=subprocess.DEVNULL, timeout=180, creationflags=NO_WINDOW)
            for line in r.stdout.splitlines():
                if "=" in line and not line.startswith("="):
                    k, v = line.split("=", 1)
                    env[k] = v
        except Exception:
            pass
    _VC_CACHE[path] = env
    return env


def find_vcvars():
    if os.name != "nt":
        return ""
    vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                           "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if not os.path.isfile(vswhere):
        return ""
    try:
        r = subprocess.run([vswhere, "-latest", "-products", "*", "-property", "installationPath"],
                           capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL, timeout=20, creationflags=NO_WINDOW)
        p = os.path.join(r.stdout.strip(), "VC", "Auxiliary", "Build", "vcvars64.bat")
        return p if os.path.isfile(p) else ""
    except Exception:
        return ""


def detect_tools():
    names = {
        "rexglue": "rexglue", "cmake": "cmake", "ninja": "ninja", "clang": "clang",
        "clang-cl": "clang-cl", "xenonrecomp": "XenonRecomp", "xenonanalyse": "XenonAnalyse",
        "git": "git",
    }
    found = {k: (shutil.which(v) or "") for k, v in names.items()}
    found["vcvars"] = find_vcvars()
    return found


# ---------------------------------------------------------------- nombres/rutas
def sanitize_name(s):
    s = re.sub(r"\(.*?\)|\[.*?\]", "", s or "")
    s = re.sub(r"[^a-z0-9_]+", "_", s.lower()).strip("_")
    s = re.sub(r"_+", "_", s)
    if s and s[0].isdigit():
        s = "g_" + s
    return s or "juego"


def human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def split_args(s):
    s = (s or "").strip()
    return shlex.split(s, posix=(os.name != "nt")) if s else []


# ---------------------------------------------------------------- comandos
def rexglue_init_cmd(cfg, name, root):
    """CLI actual de rexglue: exige el XEX (por eso el juego se extrae antes del init).
    Las versiones antiguas (--app_name/--app_root) se siguen admitiendo."""
    exe = cfg.tool("rexglue")
    if cfg.cli_flavor == "app":
        return [exe, "init", "--app_name", name, "--app_root", root]
    assets = os.path.join(root, "assets")
    return [exe, "init", "--project-name", name, "--project-root", root,
            "--xex-path", os.path.join(assets, "default.xex"), "--game-root", assets]


def manifest_project_name(root):
    """[project].name del *_manifest.toml que genera rexglue (normaliza el nombre:
    angry_birds_trilogy → angrybirdstrilogy)."""
    import glob
    for path in sorted(glob.glob(os.path.join(root, "*_manifest.toml"))):
        try:
            txt = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        m = re.search(r"^\[project\][^\[]*?^\s*name\s*=\s*\"([^\"]+)\"", txt, re.M | re.S)
        if m:
            return m.group(1)
    return ""


def cmake_configure_cmd(cfg, root, build):
    cmd = [cfg.tool("cmake"), "-S", root, "-B", build, f"-DCMAKE_BUILD_TYPE={cfg.build_type}"]
    if cfg.generator.strip():
        cmd += ["-G", cfg.generator.strip()]
    if cfg.c_compiler.strip():
        cmd.append(f"-DCMAKE_C_COMPILER={cfg.c_compiler.strip()}")
    if cfg.cxx_compiler.strip():
        cmd.append(f"-DCMAKE_CXX_COMPILER={cfg.cxx_compiler.strip()}")
    ninja = (getattr(cfg, "ninja", "") or "").strip()
    if ninja and cfg.generator.strip().lower() == "ninja":
        # versión explícita: no depende del PATH ni de la que traiga VS; queda en la caché de CMake
        cmd.append(f"-DCMAKE_MAKE_PROGRAM={ninja}")
    extra = split_args(cfg.extra_cmake_args)
    if not any(a.startswith("-DCMAKE_CXX_FLAGS") for a in extra):
        # Banderas de compilación del código recompilado. Se pasan siempre (aunque sea solo -ffp-contract=off)
        # para que al cambiar una opción CMake actualice su caché y recompile.
        #
        # -ffp-contract=off (extraído de Pinyon Shift / ShiftGlue): por defecto clang fusiona a*b+c en una
        # instrucción FMA, que da un resultado distinto al del Xbox 360. Desactivarlo hace que el punto flotante
        # del juego recompilado coincida con el original → física, animaciones y render más fieles. Vale para
        # TODOS los juegos y prácticamente no cuesta rendimiento.
        flags = ["-ffp-contract=off"]
        baseline = ""
        try:
            from .game_options import GameOptions
            o = GameOptions.load(root)
            baseline = (getattr(o, "cpu_baseline", "") or "").strip()
            if not baseline and getattr(o, "cpu_native", False):   # compat con la opción antigua
                baseline = "nativo"
        except Exception:      # noqa: BLE001
            pass
        if baseline == "nativo":
            flags.append("-march=native")               # instrucciones de ESTE PC (el .exe no es portable)
        elif baseline == "moderno":
            flags += ["-march=x86-64-v3", "-mfma"]       # AVX2/FMA: rápido y portable a CPUs de ~2015 en adelante
        cmd.append("-DCMAKE_CXX_FLAGS=" + " ".join(flags))
    return cmd + extra


def cmake_codegen_cmd(cfg, build, name):
    name = manifest_project_name(os.path.dirname(build)) or name
    return [cfg.tool("cmake"), "--build", build, "--target", f"{name}_codegen",
            "--config", cfg.build_type]


def cmake_build_cmd(cfg, build):
    return [cfg.tool("cmake"), "--build", build, "--config", cfg.build_type,
            "--parallel", str(max(1, int(cfg.jobs)))]


# ---------------------------------------------------------------- biblioteca
@dataclass
class Project:
    name: str
    root: str
    source: str = ""
    title_id: str = ""
    status: str = "Nuevo"
    updated: str = ""
    output: str = ""

    def touch(self):
        self.updated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


class Library:
    def __init__(self):
        self.projects = []

    @staticmethod
    def path():
        return os.path.join(config_dir(), "projects.json")

    @classmethod
    def load(cls):
        lib = cls()
        try:
            with open(cls.path(), "r", encoding="utf-8") as f:
                names = {f.name for f in fields(Project)}
                for d in json.load(f):
                    lib.projects.append(Project(**{k: v for k, v in d.items() if k in names}))
        except Exception:
            pass
        return lib

    def save(self):
        with open(self.path(), "w", encoding="utf-8") as f:
            json.dump([asdict(p) for p in self.projects], f, indent=2, ensure_ascii=False)

    def get(self, root):
        key = os.path.normcase(os.path.abspath(root))
        for p in self.projects:
            if os.path.normcase(os.path.abspath(p.root)) == key:
                return p
        return None

    def upsert(self, project):
        project.touch()
        old = self.get(project.root)
        if old:
            self.projects.remove(old)
        self.projects.insert(0, project)
        self.save()
        return project

    def remove(self, root):
        p = self.get(root)
        if p:
            self.projects.remove(p)
            self.save()

    def recent(self, n=4):
        return sorted(self.projects, key=lambda p: p.updated, reverse=True)[:n]


# ---------------------------------------------------------------- sistema
SKIP_DIRS = {"CMakeFiles", "_deps", ".cmake", "codegen", "generated"}


def find_outputs(build_dir, name):
    if not os.path.isdir(build_dir):
        return []
    cands = []
    for dirpath, dirnames, filenames in os.walk(build_dir):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            if os.name == "nt":
                ok = fn.lower().endswith(".exe")
            else:
                ok = ("." not in fn) and os.access(full, os.X_OK) and os.path.isfile(full)
            if ok:
                cands.append(full)
    stem = name.lower()
    cands.sort(key=lambda p: (os.path.splitext(os.path.basename(p))[0].lower() != stem,
                              -os.path.getmtime(p)))
    return cands


def open_path(path):
    if not path:
        return
    if os.name == "nt":
        os.startfile(path)  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def copy_tree(src, dst, ctx):
    files = []
    for dirpath, _d, filenames in os.walk(src):
        for fn in filenames:
            files.append(os.path.join(dirpath, fn))
    total = sum(os.path.getsize(f) for f in files) or 1
    done = 0
    for f in files:
        rel = os.path.relpath(f, src)
        target = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        ctx.log(rel, "dim")
        with open(f, "rb") as a, open(target, "wb") as b:
            while True:
                if ctx.cancelled():
                    raise RuntimeError("Copia cancelada")
                buf = a.read(4 * 1024 * 1024)
                if not buf:
                    break
                b.write(buf)
                done += len(buf)
                ctx.progress(int(done * 1000 / total), 1000)
        shutil.copystat(f, target)
    return len(files), total
