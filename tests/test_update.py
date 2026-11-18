"""Pruebas del actualizador desde GitHub.  python tests/test_update.py"""
import hashlib
import io
import json
import os
import sys
import tempfile
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-update-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
sys.path.insert(0, ROOT)

from reforge import update  # noqa: E402

PAYLOAD = b"instalador falso" * 1000
SHA = hashlib.sha256(PAYLOAD).hexdigest()
N = 0


def check(cond, msg):
    global N
    N += 1
    print(("  ok  " if cond else "FALLA ") + msg)
    assert cond, msg


def release(ver, prerelease=False, sha_in_notes=True, asset="exe"):
    assets = []
    if asset == "exe":
        assets.append({"name": f"ReForgeStudio-Setup-{ver}.exe", "size": len(PAYLOAD), "id": 1,
                       "browser_download_url": f"https://x/{ver}.exe"})
    elif asset == "zip":
        assets.append({"name": f"codigo-{ver}.zip", "size": 10, "id": 2, "browser_download_url": "https://x/z"})
    return {"tag_name": f"v{ver}", "prerelease": prerelease, "draft": False, "assets": assets,
            "body": (f"Novedades.\nsha256: {SHA}" if sha_in_notes else "Novedades.")}


class FakeResp(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def fake_http(releases, payload=PAYLOAD, fail_code=0):
    def _open(url, timeout=30, token="", accept=""):
        if fail_code:
            raise urllib.error.HTTPError(url, fail_code, "no", {}, None)
        if "api.github.com" in url:
            return FakeResp(json.dumps(releases).encode())
        return FakeResp(payload, {"Content-Length": str(len(payload))})
    return _open


print("== qué versión hay")
update.__dict__["__version__"] = "1.29.0"
update.current_version = lambda: "1.29.0"
check(update.vtuple("1.30.0") > update.vtuple("1.29.0"), "1.30.0 es más nueva que 1.29.0")
check(update.vtuple("1.9.0") < update.vtuple("1.10.0"), "1.10.0 es más nueva que 1.9.0")

print("== elegir la publicación")
update._open = fake_http([release("1.28.0"), release("1.30.0"), release("1.31.0", prerelease=True)])
info = update.check(force=True)
check(info and info["version"] == "1.30.0", "coge la estable más nueva, no la de prueba")
update.save_config(prereleases=True)
check(update.check(force=True)["version"] == "1.31.0", "con «versiones de prueba» coge la 1.31.0")
update.save_config(prereleases=False)

update._open = fake_http([release("1.29.0"), release("1.20.0")])
check(update.check(force=True) is None, "si la más nueva es la que tienes, no avisa")
update._open = fake_http([release("1.30.0", asset="zip")])
check(update.check(force=True) is None, "una publicación sin instalador no cuenta")

print("== no molestar")
update._open = fake_http([release("1.30.0")])
update.save_config(skip="1.30.0", last_check=0)
check(update.check() is None, "respeta «omitir esta versión»")
check(update.check(force=True) is not None, "pero al buscar a mano sí la ofrece")
update.save_config(skip="", last_check=0)
check(update.check() is not None, "sin omitir, avisa")
check(update.check() is None, "y no vuelve a preguntar a GitHub el mismo día")
update.save_config(enabled=False, last_check=0)
check(update.check() is None, "desactivado no consulta")
update.save_config(enabled=True, last_check=0)

print("== repositorio privado")
update._open = fake_http([], fail_code=404)
try:
    update.check(force=True)
    check(False, "avisa de que el repositorio privado no se puede consultar")
except update.UpdateError as e:
    check("privado" in str(e), "avisa de que el repositorio privado no se puede consultar")
check(update.load_config().get("last_error", ""), "deja el error anotado para la interfaz")

print("== descarga comprobada")
update._open = fake_http([release("1.30.0")])
info = update.check(force=True)
path = update.download(info)
check(os.path.isfile(path) and open(path, "rb").read() == PAYLOAD, "descarga el instalador")
check(update.download(info) == path, "si ya está descargado y cuadra, no lo baja otra vez")

update._open = fake_http([release("1.30.0")], payload=b"corrupto")
os.remove(path)
try:
    update.download(info)
    check(False, "una descarga corrupta se descarta")
except update.UpdateError as e:
    check("incompleta" in str(e) or "SHA-256" in str(e), "una descarga corrupta se descarta: " + str(e)[:40])
check(not os.path.isfile(path), "y no deja el archivo malo")

print("== SHA-256 que no coincide")
bad = dict(info)
bad["sha256"] = "0" * 64
bad["size"] = 0
update._open = fake_http([release("1.30.0")])
try:
    update.download(bad)
    check(False, "un SHA-256 distinto se rechaza")
except update.UpdateError as e:
    check("SHA-256" in str(e), "un SHA-256 distinto se rechaza")

print("== limpieza")
update._open = fake_http([release("1.30.0")])
path = update.download(info)
open(os.path.join(update.download_dir(), "viejo.exe"), "wb").close()
check(update.cleanup(keep=path) == 1 and os.path.isfile(path), "borra lo viejo y conserva lo actual")

print(f"\nTodas las pruebas pasaron ({N}).")
