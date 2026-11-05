"""Pruebas del lector XDVDFS con imágenes sintéticas.  Ejecutar: python -m tests.test_xiso"""
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from reforge.xiso import XisoImage, SECTOR_SIZE, MAGIC  # noqa
from reforge.xex import read_xex_info  # noqa


def entry(left, right, sector, size, attr, name):
    raw = struct.pack("<HHIIBB", left, right, sector, size, attr, len(name)) + name.encode()
    return raw + b"\xff" * ((-len(raw)) % 4)


def fake_xex():
    hdr = b"XEX2" + struct.pack(">IIIII", 0, 0x2000, 0, 0x100, 1)
    hdr += struct.pack(">II", 0x00040006, 0x40)
    hdr = hdr.ljust(0x40, b"\0")
    hdr += struct.pack(">IIII", 0x11223344, 0x20000100, 0, 0x4D5307E6) + bytes([0, 0, 1, 2]) + b"\0" * 4
    return hdr.ljust(4096, b"\0")


def build_iso(path, base):
    xex, blob = fake_xex(), os.urandom(10000)
    # sectores: 32 header, 33 root, 34 media dir, 40 xex, 50 blob
    e0 = entry(0, 0, 0, 0, 0, "")  # placeholder
    media_dir = entry(0, 0, 50, len(blob), 0x20, "level1.pak")
    # root: [default.xex] -> right -> [media]
    a = entry(0, 0, 40, len(xex), 0x20, "default.xex")
    b_off = len(a) // 4
    a = entry(0, b_off, 40, len(xex), 0x20, "default.xex")
    root = a + entry(0, 0, 34, len(media_dir), 0x10, "media")
    with open(path, "wb") as f:
        f.truncate(base + 60 * SECTOR_SIZE)
        f.seek(base + 32 * SECTOR_SIZE)
        f.write(MAGIC + struct.pack("<II", 33, len(root)))
        f.seek(base + 33 * SECTOR_SIZE); f.write(root)
        f.seek(base + 34 * SECTOR_SIZE); f.write(media_dir)
        f.seek(base + 40 * SECTOR_SIZE); f.write(xex)
        f.seek(base + 50 * SECTOR_SIZE); f.write(blob)
    del e0
    return xex, blob


def run(base, label):
    with tempfile.TemporaryDirectory() as d:
        iso = os.path.join(d, "game.iso")
        xex, blob = build_iso(iso, base)
        with XisoImage(iso) as img:
            assert img.layout == label, img.layout
            paths = [e.path for e in img.entries()]
            assert paths == ["default.xex", "media", "media/level1.pak"], paths
            out = os.path.join(d, "assets")
            n, total = img.extract(out)
        assert n == 2 and total == len(xex) + len(blob)
        assert open(os.path.join(out, "default.xex"), "rb").read() == xex
        assert open(os.path.join(out, "media", "level1.pak"), "rb").read() == blob
        info = read_xex_info(os.path.join(out, "default.xex"))
        assert info["title_id"] == "4D5307E6" and info["disc"] == "1/2", info
        print(f"OK {label}: {paths} · Title ID {info['title_id']}")


if __name__ == "__main__":
    run(0, "XISO")
    run(0x0FD90000, "XGD2")
    run(0x02080000, "XGD3")
    print("Todas las pruebas pasaron.")
