"""Pruebas del instalador/actualizador.   python tests/test_installer.py"""
import json
import os
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-setup-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
os.environ["TEMP"] = os.environ["TMPDIR"] = TMP
RES = os.path.join(TMP, "res")
os.makedirs(RES)
os.environ["REFORGE_SETUP_RES"] = RES
sys.path.insert(0, os.path.join(ROOT, "installer"))
sys.path.insert(0, ROOT)
import setup  # noqa: E402

# Aislar: nunca tocar el registro real ni cerrar programas del usuario al ejecutar las pruebas en Windows.
class FileRegistry:
    path = os.path.join(TMP, "install.json")

    def read(self):
        try:
            return json.load(open(self.path))
        except Exception:
            return None

    def write(self, d, v):
        json.dump({"dir": d, "version": v}, open(self.path, "w"))

    def associate(self, d):
        pass


setup.Registry = FileRegistry
setup.close_running = lambda *_a, **_k: None
setup.shortcut_paths = lambda: []

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


def make_payload(version, marker):
    with zipfile.ZipFile(os.path.join(RES, "payload.zip"), "w") as z:
        z.writestr(setup.EXE, f"exe {version}")
        z.writestr("_internal/lib.dat", marker)
        z.writestr(f"_internal/only_{version}.txt", version)
    with open(os.path.join(RES, "payload.json"), "w") as f:
        json.dump({"version": version, "api": 1}, f)


def read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


target = os.path.join(TMP, "Programs", "ReForge Studio")
quiet = lambda *_a: None  # noqa: E731

print("Instalación nueva")
make_payload("1.3.0", "old")
check(setup.plan(target)["action"] == "install", "sin instalación previa → instalar")
setup.install(target, desktop=False, startmenu=False, associate=False, log=quiet)
check(setup.installed_version(target) == "1.3.0", "v1.3.0 instalada")
os.makedirs(os.path.join(target, "tools", "rexglue-sdk"))
open(os.path.join(target, "tools", "rexglue-sdk", "sdk.bin"), "w").write("sdk")

print("Actualización")
make_payload("1.4.0", "new")
pl = setup.plan(target)
check(pl["action"] == "update" and pl["old"] == "1.3.0", "detecta v1.3.0 → actualizar")
setup.install(target, desktop=False, startmenu=False, associate=False, log=quiet)
check(setup.installed_version(target) == "1.4.0", "queda v1.4.0")
check(read(target, "_internal", "lib.dat") == "new", "archivos del programa reemplazados")
check(not os.path.exists(os.path.join(target, "_internal", "only_1.3.0.txt")), "sin restos de la versión vieja")
check(read(target, "tools", "rexglue-sdk", "sdk.bin") == "sdk", "la carpeta tools (SDK) se conserva")
check(not os.path.exists(target + ".new") and not os.path.exists(target + ".old"), "sin carpetas temporales")
check(setup.plan(target)["action"] == "repair", "misma versión → reparar")

print("Registro desfasado")
setup.Registry().write(target, "1.3.0")
check(setup.plan(target)["old"] == "1.4.0", "version.json de la carpeta manda sobre el registro")

print("Archivo bloqueado unos segundos (antivirus)")
make_payload("1.4.1", "av")
real_replace = os.replace
fails = {"n": 0}


def flaky(src, dst):
    if fails["n"] < 3 and src.endswith(os.path.join(".new", "_internal")):
        fails["n"] += 1
        raise PermissionError(13, "en uso")
    return real_replace(src, dst)


os.replace = flaky
try:
    setup.install(target, desktop=False, startmenu=False, associate=False, log=quiet)
finally:
    os.replace = real_replace
check(fails["n"] == 3 and setup.installed_version(target) == "1.4.1", "reintenta y termina la actualización")

print("Archivo bloqueado de verdad")
make_payload("1.5.0", "broken")


def locked(src, dst):
    if src.endswith(os.path.join(".new", setup.EXE)):
        raise PermissionError(13, "en uso")
    return real_replace(src, dst)


os.replace = locked
setup._retry.__defaults__ = (3, 0.01)
try:
    setup.install(target, desktop=False, startmenu=False, associate=False, log=quiet)
    raise AssertionError("debió fallar")
except RuntimeError as e:
    check("en uso" in str(e) and "Cierra ReForge Studio" in str(e), "explica qué archivo está en uso")
finally:
    os.replace = real_replace
check(setup.installed_version(target) == "1.4.1" and read(target, "_internal", "lib.dat") == "av"
      and read(target, setup.EXE) == "exe 1.4.1", "la versión anterior queda intacta")
check(read(target, "tools", "rexglue-sdk", "sdk.bin") == "sdk", "el SDK sigue intacto")
check(os.path.isfile(setup.log_path()) and "ERROR" in read(setup.log_path()), "deja un log con el error")

print("Salida de programas en otro idioma/codificación (Python 3.15 usa UTF-8)")
import re  # noqa: E402
import subprocess  # noqa: E402
bad = []
for d in ("reforge", "installer"):
    for f in os.listdir(os.path.join(ROOT, d)):
        if f.endswith(".py"):
            for n, ln in enumerate(open(os.path.join(ROOT, d, f), encoding="utf-8"), 1):
                if re.search(r"text=True", ln) and "errors=" not in ln:
                    bad.append(f"{d}/{f}:{n}")
check(not bad, "toda lectura de texto de procesos tolera caracteres no UTF-8 " + ",".join(bad))
cmd = [sys.executable, "-X", "utf8", "-c",
       "import subprocess,sys;r=subprocess.run([sys.executable,'-c',\"import sys;sys.stdout.buffer.write("
       "'INFORMACIÓN: tareas'.encode('cp850'))\"],capture_output=True,text=True,errors='replace',"
       "stdin=subprocess.DEVNULL);print('ok' if 'INFORMACI' in r.stdout else 'mal')"]
check(subprocess.run(cmd, capture_output=True).stdout.strip() == b"ok",
      "lee la respuesta de tasklist en español (cp850) sin fallar")

print(f"\nTodas las pruebas pasaron ({ok}).")
