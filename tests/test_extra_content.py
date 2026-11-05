"""Discos extra, DLC y contenido instalado del disco 2.   python tests/test_extra_content.py"""
import os
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-extra-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from xcontent_fixtures import make_stfs  # noqa: E402

from reforge import extra_content as ec  # noqa: E402
from reforge.xiso import MAGIC, SECTOR_SIZE  # noqa: E402

ok = 0
TID = 0x41560914


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


def fake_xex(tid=TID):
    hdr = b"XEX2" + struct.pack(">IIIII", 0, 0x2000, 0, 0x100, 1)
    hdr += struct.pack(">II", 0x00040006, 0x40)
    hdr = hdr.ljust(0x40, b"\0")
    hdr += struct.pack(">IIII", 0x11223344, 0x20000100, 0, tid) + bytes([0, 0, 1, 2]) + b"\0" * 4
    return hdr.ljust(4096, b"\0")


def entry(left, right, sector, size, attr, name):
    raw = struct.pack("<HHIIBB", left, right, sector, size, attr, len(name)) + name.encode()
    return raw + b"\xff" * ((-len(raw)) % 4)


def build_iso(path, blob):
    xex = fake_xex()
    media_dir = entry(0, 0, 50, len(blob), 0x20, "disc2_level.pak")
    a = entry(0, 0, 40, len(xex), 0x20, "default.xex")
    a = entry(0, len(a) // 4, 40, len(xex), 0x20, "default.xex")
    root = a + entry(0, 0, 34, len(media_dir), 0x10, "media")
    with open(path, "wb") as f:
        f.truncate(60 * SECTOR_SIZE)
        f.seek(32 * SECTOR_SIZE)
        f.write(MAGIC + struct.pack("<II", 33, len(root)))
        f.seek(33 * SECTOR_SIZE)
        f.write(root)
        f.seek(34 * SECTOR_SIZE)
        f.write(media_dir)
        f.seek(40 * SECTOR_SIZE)
        f.write(xex)
        f.seek(50 * SECTOR_SIZE)
        f.write(blob)


docs = os.path.join(TMP, "Documentos")
ec.documents_dir = lambda: docs
root = os.path.join(TMP, "codaw")
os.makedirs(os.path.join(root, "assets", "media"))
open(os.path.join(root, "assets", "default.xex"), "wb").write(fake_xex())
open(os.path.join(root, "codaw_manifest.toml"), "w").write('[project]\nname = "codaw"\n')

print("Carpeta GOD con paquetes de contenido")
god = os.path.join(TMP, "COD-AW-GOD", "41560914")
os.makedirs(os.path.join(god, "00000002"))
os.makedirs(os.path.join(god, "00007000"))
camp = os.path.join(god, "00000002", "41560914051BF3C0")
make_stfs(camp, [("campaign/sna_campaign.ff", b"C" * 9000)], magic=b"PIRS", content_type=0x00000002, tid=TID,
          name="Contenido de la campaña")
data = bytearray(open(camp, "rb").read())
struct.pack_into(">QII", data, 0x22C, 0xFFFFFFFFFFFFFFFF, 0x00000001, 0x00000001)   # licencia completa
open(camp, "wb").write(bytes(data))
make_stfs(os.path.join(god, "00000002", "OTRO_JUEGO"), [("x.bin", b"x")], content_type=0x00000002, tid=0x12345678)
found = ec.find_extras(god, "41560914")
check([os.path.basename(p) for p in found["dlc"]] == ["41560914051BF3C0"], "encuentra el paquete del juego (no los de otros)")
done = ec.install_extras(root, god, log=lambda *_a: None)
check(done["dlc"] == 1, "instalado")
store = os.path.join(root, "content", "00000002", "41560914051BF3C0")
check(open(os.path.join(store, "campaign", "sna_campaign.ff"), "rb").read() == b"C" * 9000,
      "extraído junto al proyecto (no llena C:)")
link = os.path.join(docs, "codaw", "0000000000000000", "41560914", "00000002")
check(os.path.realpath(link) == os.path.realpath(os.path.join(root, "content", "00000002")),
      "Documentos/<juego>/0000000000000000/<TitleID>/00000002 enlaza al proyecto")
check(os.path.isfile(os.path.join(link, "41560914051BF3C0", "campaign", "sna_campaign.ff")), "el juego lo ve por el enlace")
hdr = open(os.path.join(docs, "codaw", "0000000000000000", "41560914", "Headers", "00000002",
                        "41560914051BF3C0.header"), "rb").read()
check(len(hdr) == 0x148 + 4, "cabecera XCONTENT_AGGREGATE_DATA (0x148) + máscara de licencias")
check(struct.unpack_from(">II", hdr, 0) == (1, 2) and struct.unpack_from(">I", hdr, 320)[0] == TID,
      "disco duro · tipo 00000002 · Title ID")
check(hdr[264:280].rstrip(b"\0") == b"41560914051BF3C0" and hdr[8:56].decode("utf-16-be").startswith("Contenido"),
      "nombre del paquete y nombre visible")
check(struct.unpack_from("<I", hdr, 0x148)[0] == 1, "licencia leída de la cabecera STFS")
check(ec.install_extras(root, god, log=lambda *_a: None)["dlc"] == 1 and
      ec.installed(root)["dlc"] == ["Contenido de la campaña"], "reinstalar no duplica; queda anotado")

print("Varios discos")
isos = os.path.join(TMP, "isos")
os.makedirs(isos)
build_iso(os.path.join(isos, "Juego (Disc 1).iso"), os.urandom(5000))
blob = os.urandom(7000)
build_iso(os.path.join(isos, "Juego (Disc 2).iso"), blob)
check([os.path.basename(p) for p in ec.other_discs(os.path.join(isos, "Juego (Disc 1).iso"))] == ["Juego (Disc 2).iso"],
      "encuentra el disco 2 junto al disco 1")
check(ec.other_discs(os.path.join(isos, "sin numero.iso")) == [], "sin número de disco: nada")
orig = open(os.path.join(root, "assets", "default.xex"), "rb").read()
done = ec.install_extras(root, os.path.join(isos, "Juego (Disc 1).iso"), log=lambda *_a: None)
check(done["discs"] == 1, "disco 2 unido")
check(open(os.path.join(root, "assets", "media", "disc2_level.pak"), "rb").read() == blob, "sus datos están en assets")
check(open(os.path.join(root, "assets", "default.xex"), "rb").read() == orig, "el ejecutable del disco 1 no se toca")
check(not os.path.exists(os.path.join(root, "_disco_tmp")), "sin restos temporales")
check(ec.install_extras(root, os.path.join(isos, "Juego (Disc 1).iso"), log=lambda *_a: None)["discs"] == 0,
      "un disco ya unido no se repite")
print(f"\nTodas las pruebas pasaron ({ok}).")
