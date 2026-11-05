"""Empaqueta una carpeta de parche en un archivo .rfpatch firmado con SHA-256.

Uso:
    python tools/make_patch.py patches/xbox_utility -o dist/patches
"""
import argparse
import datetime
import hashlib
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from reforge.patches import read_package, validate_manifest  # noqa: E402

SKIP_DIRS = {"__pycache__", ".git", "tests"}
SKIP_EXT = {".pyc", ".pyo"}


def build(src, out_dir):
    with open(os.path.join(src, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    validate_manifest(manifest)
    files = {}
    blobs = {}
    for dp, dn, fn in os.walk(src):
        dn[:] = sorted(d for d in dn if d not in SKIP_DIRS)
        for name in sorted(fn):
            if name == "manifest.json" or os.path.splitext(name)[1] in SKIP_EXT:
                continue
            full = os.path.join(dp, name)
            rel = os.path.relpath(full, src).replace(os.sep, "/")
            data = open(full, "rb").read()
            files[rel] = hashlib.sha256(data).hexdigest()
            blobs[rel] = data
    manifest["files"] = files
    manifest["built_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{manifest['id']}-{manifest['version']}.rfpatch")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for rel, data in blobs.items():
            z.writestr(rel, data)
    read_package(out)   # autoverificación
    print(f"OK  {out}  ({len(files)} archivos, v{manifest['version']}, requiere núcleo {manifest['requires_core']})")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="+", help="carpeta(s) de parche con manifest.json")
    ap.add_argument("-o", "--out", default="dist/patches")
    a = ap.parse_args()
    for s in a.src:
        build(s, a.out)
