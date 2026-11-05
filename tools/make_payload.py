"""Empaqueta la app compilada (PyInstaller --onedir) como payload del instalador.

Uso:  python tools/make_payload.py dist/ReForgeStudio build/installer
"""
import datetime
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from reforge import API_VERSION, __version__  # noqa: E402


def main(app_dir, out_dir):
    if not os.path.isdir(app_dir):
        sys.exit(f"No existe {app_dir}. Compila primero la app con PyInstaller --onedir.")
    os.makedirs(out_dir, exist_ok=True)
    zpath = os.path.join(out_dir, "payload.zip")
    n = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dp, _dn, fn in os.walk(app_dir):
            for f in fn:
                full = os.path.join(dp, f)
                z.write(full, os.path.relpath(full, app_dir).replace(os.sep, "/"))
                n += 1
    info = {"version": __version__, "api": API_VERSION, "channel": "stable",
            "build": datetime.datetime.now().strftime("%Y%m%d-%H%M")}
    with open(os.path.join(out_dir, "payload.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    print(f"OK  payload v{__version__}: {n} archivos → {zpath} ({os.path.getsize(zpath) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dist/ReForgeStudio",
         sys.argv[2] if len(sys.argv) > 2 else "build/installer")
