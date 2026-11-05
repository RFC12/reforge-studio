"""Gestor de parches (.rfpatch) de ReForge Studio.

Un parche es un .zip con extensión .rfpatch que contiene:
    manifest.json   id, name, version, api, requires_core, entry, files{ruta: sha256}, changelog…
    <entry>.py      módulo con register(api)
    …               otros módulos/recursos del parche

Garantías para no romper la aplicación:
  * Se verifica el SHA-256 de cada archivo y que no haya rutas peligrosas.
  * Solo se cargan parches cuya API y versión mínima del núcleo sean compatibles.
  * La instalación es atómica (carpeta temporal → intercambio) y guarda una copia
    de la versión anterior para poder revertir.
  * Cada parche se carga dentro de try/except; si falla, se marca con error y lo que
    hubiera registrado en la interfaz se retira.
  * Si la app se cierra inesperadamente mientras carga un parche, en el siguiente
    arranque ese parche se desactiva automáticamente.
"""
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import traceback
import zipfile
from dataclasses import dataclass, field

from .core import config_dir

PATCH_EXT = ".rfpatch"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,48}$")
VER_RE = re.compile(r"^\d+(\.\d+){0,3}$")
REQUIRED = ("id", "name", "version", "api", "requires_core", "entry")


class PatchError(Exception):
    pass


def vtuple(v):
    parts = [int(x) for x in str(v).strip().split(".") if x.isdigit()]
    return tuple(parts + [0] * (4 - len(parts)))


def check_requirement(spec, version):
    """spec: ">=1.1.0" o ">=1.1.0,<2.0.0" o "1.1.0" (igualdad)."""
    v = vtuple(version)
    for cond in [c.strip() for c in (spec or "").split(",") if c.strip()]:
        m = re.match(r"^(>=|<=|==|>|<|=)?\s*([\d.]+)$", cond)
        if not m:
            return False
        op, target = m.group(1) or "==", vtuple(m.group(2))
        ok = {">=": v >= target, "<=": v <= target, ">": v > target, "<": v < target,
              "==": v == target, "=": v == target}[op]
        if not ok:
            return False
    return True


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class PatchInfo:
    id: str
    name: str
    version: str
    path: str = ""
    author: str = ""
    description: str = ""
    api: int = 1
    requires_core: str = ""
    entry: str = "plugin.py"
    changelog: list = field(default_factory=list)
    credits: list = field(default_factory=list)
    files: dict = field(default_factory=dict)
    installed_at: str = ""
    enabled: bool = True
    status: str = "pendiente"      # activo | desactivado | incompatible | error | modo seguro | pendiente
    error: str = ""
    has_backup: str = ""           # versión guardada para revertir

    @classmethod
    def from_manifest(cls, m, path=""):
        return cls(id=m["id"], name=m["name"], version=str(m["version"]), path=path,
                   author=m.get("author", ""), description=m.get("description", ""),
                   api=int(m.get("api", 1)), requires_core=m.get("requires_core", ""),
                   entry=m.get("entry", "plugin.py"), changelog=m.get("changelog", []),
                   credits=m.get("credits", []), files=m.get("files", {}))


def validate_manifest(m):
    for k in REQUIRED:
        if k not in m:
            raise PatchError(f"Falta el campo «{k}» en manifest.json")
    if not ID_RE.match(str(m["id"])):
        raise PatchError(f"Identificador de parche inválido: {m['id']}")
    if not VER_RE.match(str(m["version"])):
        raise PatchError(f"Versión inválida: {m['version']}")
    if not str(m["entry"]).endswith(".py"):
        raise PatchError("El punto de entrada debe ser un archivo .py")


def _safe_rel(name):
    n = name.replace("\\", "/")
    if n.startswith("/") or re.match(r"^[A-Za-z]:", n) or any(p == ".." for p in n.split("/")):
        raise PatchError(f"Ruta peligrosa dentro del parche: {name}")
    return n


def read_package(path):
    """Lee y verifica un .rfpatch. Devuelve (manifest, {ruta: bytes})."""
    if not zipfile.is_zipfile(path):
        raise PatchError("El archivo no es un paquete de parche válido (.rfpatch)")
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        if "manifest.json" not in names:
            raise PatchError("El parche no contiene manifest.json")
        try:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        except Exception as e:
            raise PatchError(f"manifest.json no es JSON válido: {e}")
        validate_manifest(manifest)
        declared = manifest.get("files") or {}
        if not declared:
            raise PatchError("El manifiesto no declara archivos con su SHA-256")
        payload = {}
        for n in names:
            if n == "manifest.json":
                continue
            rel = _safe_rel(n)
            data = z.read(n)
            if rel not in declared:
                raise PatchError(f"Archivo no declarado en el manifiesto: {rel}")
            if sha256_bytes(data) != declared[rel]:
                raise PatchError(f"Verificación fallida (SHA-256) en {rel}: el parche está dañado o fue modificado")
            payload[rel] = data
        missing = set(declared) - set(payload)
        if missing:
            raise PatchError(f"Faltan archivos en el paquete: {', '.join(sorted(missing))}")
        if manifest["entry"] not in payload:
            raise PatchError(f"No se encontró el punto de entrada {manifest['entry']}")
    return manifest, payload


class PatchManager:
    def __init__(self, core_version, supported_apis, base_dir=None):
        self.core_version = core_version
        self.supported_apis = set(supported_apis)
        self.base = base_dir or os.path.join(config_dir(), "patches")
        self.backups = os.path.join(self.base, ".backup")
        self.data_root = os.path.join(config_dir(), "patch_data")
        os.makedirs(self.base, exist_ok=True)
        os.makedirs(self.backups, exist_ok=True)
        self.state_path = os.path.join(self.base, "state.json")
        self.flag_path = os.path.join(self.base, "loading.flag")
        self.state = self._load_state()
        self.patches = {}
        self.modules = {}
        self.crashed_patch = ""
        self.safe_mode = False

    # ---------------------------------------------------------------- estado
    def _load_state(self):
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_state(self):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.state_path)

    def check_crash_guard(self):
        """Si el arranque anterior murió cargando un parche, lo desactiva."""
        if os.path.isfile(self.flag_path):
            try:
                pid = open(self.flag_path, encoding="utf-8").read().strip()
            except Exception:
                pid = ""
            if pid and pid in self.state:
                self.state[pid]["enabled"] = False
                self.state[pid]["auto_disabled"] = "La aplicación se cerró inesperadamente al cargar este parche"
                self._save_state()
                self.crashed_patch = pid
            try:
                os.remove(self.flag_path)
            except OSError:
                pass
        return self.crashed_patch

    # ---------------------------------------------------------------- listado
    def scan(self):
        self.patches = {}
        for d in sorted(os.listdir(self.base)):
            full = os.path.join(self.base, d)
            mf = os.path.join(full, "manifest.json")
            if d.startswith(".") or not os.path.isfile(mf):
                continue
            try:
                with open(mf, encoding="utf-8") as f:
                    m = json.load(f)
                validate_manifest(m)
                info = PatchInfo.from_manifest(m, full)
            except Exception as e:
                info = PatchInfo(id=d, name=d, version="?", path=full, status="error",
                                 error=f"Manifiesto dañado: {e}", enabled=False)
                self.patches[info.id] = info
                continue
            st = self.state.setdefault(info.id, {"enabled": True})
            info.enabled = st.get("enabled", True)
            info.installed_at = st.get("installed_at", "")
            info.has_backup = self._backup_version(info.id)
            if st.get("auto_disabled") and not info.enabled:
                info.error = st["auto_disabled"]
            self.patches[info.id] = info
        return list(self.patches.values())

    def compatibility(self, info):
        if info.api not in self.supported_apis:
            return f"Requiere la API de parches v{info.api}; este ReForge Studio admite v{', v'.join(map(str, sorted(self.supported_apis)))}"
        if info.requires_core and not check_requirement(info.requires_core, self.core_version):
            return f"Requiere ReForge Studio {info.requires_core} (tienes {self.core_version})"
        return ""

    # ---------------------------------------------------------------- instalar
    def inspect(self, package_path):
        """Verifica el paquete sin instalarlo. Devuelve (PatchInfo nuevo, PatchInfo instalado|None, incompat)."""
        m, _ = read_package(package_path)
        new = PatchInfo.from_manifest(m)
        self.scan()
        old = self.patches.get(new.id)
        return new, old, self.compatibility(new)

    def install(self, package_path):
        m, payload = read_package(package_path)
        pid = m["id"]
        dest = os.path.join(self.base, pid)
        tmp = os.path.join(self.base, f".tmp-{pid}")
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            for rel, data in payload.items():
                target = os.path.join(tmp, *rel.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(data)
            with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(m, f, indent=2, ensure_ascii=False)
            # verificación en disco
            for rel, h in m["files"].items():
                if sha256_file(os.path.join(tmp, *rel.split("/"))) != h:
                    raise PatchError(f"Error al escribir {rel}")
            # copia de seguridad de la versión anterior
            if os.path.isdir(dest):
                bak = os.path.join(self.backups, pid)
                shutil.rmtree(bak, ignore_errors=True)
                shutil.move(dest, bak)
            os.replace(tmp, dest)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            bak = os.path.join(self.backups, pid)
            if not os.path.isdir(dest) and os.path.isdir(bak):
                shutil.move(bak, dest)
            raise
        st = self.state.setdefault(pid, {})
        st.update(enabled=True, installed_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
        st.pop("auto_disabled", None)
        self._save_state()
        self.scan()
        return self.patches[pid]

    def _backup_version(self, pid):
        mf = os.path.join(self.backups, pid, "manifest.json")
        try:
            with open(mf, encoding="utf-8") as f:
                return str(json.load(f).get("version", ""))
        except Exception:
            return ""

    def rollback(self, pid):
        bak = os.path.join(self.backups, pid)
        dest = os.path.join(self.base, pid)
        if not os.path.isdir(bak):
            raise PatchError("No hay una versión anterior guardada")
        swap = os.path.join(self.base, f".swap-{pid}")
        shutil.rmtree(swap, ignore_errors=True)
        if os.path.isdir(dest):
            shutil.move(dest, swap)
        shutil.move(bak, dest)
        if os.path.isdir(swap):
            shutil.move(swap, bak)       # la versión que se retira queda como respaldo
        self.state.setdefault(pid, {})["enabled"] = True
        self._save_state()
        self.scan()

    def uninstall(self, pid, keep_data=True):
        shutil.rmtree(os.path.join(self.base, pid), ignore_errors=True)
        shutil.rmtree(os.path.join(self.backups, pid), ignore_errors=True)
        if not keep_data:
            shutil.rmtree(os.path.join(self.data_root, pid), ignore_errors=True)
        self.state.pop(pid, None)
        self._save_state()
        self.scan()

    def set_enabled(self, pid, on):
        st = self.state.setdefault(pid, {})
        st["enabled"] = bool(on)
        st.pop("auto_disabled", None)
        self._save_state()
        self.scan()

    # ---------------------------------------------------------------- carga
    def load_all(self, make_api, safe_mode=False):
        """make_api(info) -> objeto API. Devuelve lista de PatchInfo con su estado final."""
        self.safe_mode = safe_mode
        self.scan()
        for info in self.patches.values():
            if info.status == "error":
                continue
            if safe_mode:
                info.status = "modo seguro"
                continue
            if not info.enabled:
                info.status = "desactivado"
                continue
            why = self.compatibility(info)
            if why:
                info.status, info.error = "incompatible", why
                continue
            api = make_api(info)
            with open(self.flag_path, "w", encoding="utf-8") as f:
                f.write(info.id)
            try:
                modname = "rfpatch_" + info.id.replace("-", "_")
                entry = os.path.join(info.path, info.entry)
                spec = importlib.util.spec_from_file_location(
                    modname, entry, submodule_search_locations=[info.path])
                mod = importlib.util.module_from_spec(spec)
                sys.modules[modname] = mod
                spec.loader.exec_module(mod)
                if not hasattr(mod, "register"):
                    raise PatchError(f"{info.entry} no define register(api)")
                mod.register(api)
                self.modules[info.id] = mod
                info.status, info.error = "activo", ""
            except Exception:
                info.status = "error"
                info.error = traceback.format_exc(limit=6)
                try:
                    api._rollback()
                except Exception:
                    pass
                for k in [k for k in sys.modules if k.startswith("rfpatch_" + info.id.replace("-", "_"))]:
                    sys.modules.pop(k, None)
        try:
            os.remove(self.flag_path)
        except OSError:
            pass
        return list(self.patches.values())

    def shutdown(self):
        for pid, mod in self.modules.items():
            fn = getattr(mod, "unregister", None)
            if fn:
                try:
                    fn()
                except Exception:
                    pass
