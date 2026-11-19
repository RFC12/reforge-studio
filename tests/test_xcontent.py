"""Paquetes GOD (SVOD) y XBLA (STFS) y XEX suelto.   python tests/test_xcontent.py"""
import os
import random
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from reforge.xcontent import XContentError, XContentPackage, find_package  # noqa: E402

TMP = tempfile.mkdtemp(prefix="reforge-xcontent-")
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


def header(magic, content_type, volume_type, vd, data_files=0, name="Juego de prueba", tid=0x58410A1B):
    h = bytearray(0x971A)
    h[0:4] = magic
    struct.pack_into(">I", h, 0x340, 0x971A)
    struct.pack_into(">I", h, 0x344, content_type)
    struct.pack_into(">IIII", h, 0x354, 0x1234, 0, 0, tid)
    h[0x379:0x379 + len(vd)] = vd
    struct.pack_into(">I", h, 0x39D, data_files)
    struct.pack_into(">I", h, 0x3A9, volume_type)
    n = name.encode("utf-16-be")
    h[0x411:0x411 + len(n)] = n
    h[0x1691:0x1691 + len(n)] = n
    return h


def payload(size, seed):
    rnd = random.Random(seed)
    return bytes(rnd.getrandbits(8) for _ in range(size))


# ---------------------------------------------------------------- XBLA (STFS, LIVE)
def make_stfs(path, files):
    """files: [(ruta, datos)] con carpetas implícitas. Formato solo lectura (una tabla de hashes)."""
    entries, dirs = [], {}
    for rel, _d in files:
        parts = rel.split("/")
        for i in range(1, len(parts)):
            d = "/".join(parts[:i])
            if d not in dirs:
                dirs[d] = len(entries)
                entries.append((d, None))
        entries.append((rel, _d))
    order = list(range(1, 160))
    random.Random(7).shuffle(order)          # bloques desordenados: hay que seguir la cadena de hashes
    nxt = iter(order)
    blocks = {}
    hashes = {0: 0xFFFFFF}
    table = bytearray(0x1000)
    for i, (rel, data) in enumerate(entries):
        parts = rel.split("/")
        parent = dirs["/".join(parts[:-1])] if len(parts) > 1 else 0xFFFF
        e = bytearray(0x40)
        nm = parts[-1].encode()
        e[:len(nm)] = nm
        if data is None:
            e[0x28] = len(nm) | 0x80
            start = 0
        else:
            e[0x28] = len(nm)
            chain = [next(nxt) for _ in range(max(1, (len(data) + 0xFFF) // 0x1000))]
            for k, b in enumerate(chain):
                blocks[b] = data[k * 0x1000:(k + 1) * 0x1000]
                hashes[b] = chain[k + 1] if k + 1 < len(chain) else 0xFFFFFF
            start = chain[0]
            e[0x29:0x2C] = len(chain).to_bytes(3, "little")
            e[0x2C:0x2F] = len(chain).to_bytes(3, "little")
        e[0x2F:0x32] = start.to_bytes(3, "little")
        struct.pack_into(">HI", e, 0x32, parent, 0 if data is None else len(data))
        table[i * 0x40:(i + 1) * 0x40] = e
    blocks[0] = bytes(table)
    vd = bytearray(0x24)
    vd[0], vd[2] = 0x24, 1                   # descriptor, solo lectura
    struct.pack_into("<H", vd, 3, 1)         # una tabla de archivos en el bloque 0
    struct.pack_into(">I", vd, 0x1C, 160)
    out = header(b"LIVE", 0x000D0000, 0, vd)
    out += bytes(0xA000 - len(out))
    ht = bytearray(0x1000)
    for b, n in hashes.items():
        struct.pack_into(">I", ht, b * 0x18 + 0x14, 0x80000000 | n)
    out += ht
    for b in range(0, 160):
        out += (blocks.get(b, b"") + bytes(0x1000))[:0x1000]
    open(path, "wb").write(out)


print("XBLA (STFS)")
xbla_files = [("default.xex", b"XEX2" + payload(9000, 1)), ("media/music.xma", payload(5000, 2)),
              ("media/levels/l1.bin", payload(4096, 3)), ("config.ini", b"[x]\nok=1\n")]
d = os.path.join(TMP, "xbla", "58410A1B", "000D0000")
os.makedirs(d)
pkg = os.path.join(d, "0123456789ABCDEF0123456789ABCDEF01234567")
make_stfs(pkg, xbla_files)
check(find_package(os.path.join(TMP, "xbla")) == pkg, "encuentra el paquete dentro de la carpeta del Title ID")
with XContentPackage(os.path.join(TMP, "xbla")) as p:
    check(p.magic == "LIVE" and p.content_name == "Xbox Live Arcade" and p.title_id == "58410A1B"
          and p.title_name == "Juego de prueba", "lee tipo, Title ID y nombre del juego")
    check(sorted(e.path for e in p.files()) == sorted(f for f, _ in xbla_files), "lista todos los archivos")
    check(p.read_file(p.find("default.xex"), 4) == b"XEX2", "lee el inicio de default.xex")
    out = os.path.join(TMP, "xbla_out")
    n, total = p.extract(out)
check(n == 4 and all(open(os.path.join(out, *f.split("/")), "rb").read() == data for f, data in xbla_files),
      "extrae byte a byte (siguiendo cadenas de bloques desordenadas)")


# ---------------------------------------------------------------- GOD (SVOD, CON)
def svod_addr(block):                       # EGDF, start_data_block = 0, bloques < 0x198
    return (block + 2) * 0x800 + 0x2000


def gdf_dir(entries):
    """entries: [(nombre, bloque, longitud, es_dir)] → bloque de directorio GDF (árbol: cada uno a la derecha)."""
    raw = bytearray()
    offs = []
    for name, _b, _l, _d in entries:
        offs.append(len(raw))
        raw += bytes(14 + len(name))
        raw += bytes((-len(raw)) % 4)
    for i, (name, blk, length, is_dir) in enumerate(entries):
        right = offs[i + 1] // 4 if i + 1 < len(entries) else 0
        struct.pack_into("<HHIIBB", raw, offs[i], 0, right, blk, length, 0x10 if is_dir else 0x80, len(name))
        raw[offs[i] + 14:offs[i] + 14 + len(name)] = name.encode()
    return bytes(raw)


def make_god(base, files_root, media_files, data_files=1, write_parts=1):
    data = bytearray(0x40000)
    blk = [10]

    def put(content):
        b = blk[0]
        a = svod_addr(b)
        data[a:a + len(content)] = content
        blk[0] += (len(content) + 0x7FF) // 0x800 + 1
        return b

    media_entries = [(n, put(c), len(c), False) for n, c in media_files]
    media_dir = gdf_dir(media_entries)
    mb = put(media_dir)
    root_entries = [(n, put(c), len(c), False) for n, c in files_root] + [("media", mb, len(media_dir), True)]
    root_dir = gdf_dir(root_entries)
    rb = put(root_dir)
    data[0x2000:0x2014] = b"MICROSOFT*XBOX*MEDIA"
    struct.pack_into("<II", data, 0x2014, rb, len(root_dir))
    vd = bytearray(0x24)
    vd[0], vd[0x18] = 0x24, 0x40            # EGDF
    os.makedirs(os.path.dirname(base), exist_ok=True)
    open(base, "wb").write(header(b"CON ", 0x00007000, 1, vd, data_files=data_files, name="Juego GOD"))
    os.makedirs(base + ".data", exist_ok=True)
    for i in range(write_parts):
        open(os.path.join(base + ".data", f"Data{i:04d}"), "wb").write(bytes(data) if i == 0 else b"")


print("Games on Demand (SVOD)")
god_root = [("default.xex", b"XEX2" + payload(7000, 4)), ("title.dat", payload(100, 5))]
god_media = [("intro.wmv", payload(6000, 6)), ("menu.xzp", payload(2048, 7))]
gbase = os.path.join(TMP, "god", "4D5307E6", "00007000", "ABCDEF0123456789ABCDEF0123456789ABCDEF01")
make_god(gbase, god_root, god_media)
with XContentPackage(os.path.join(TMP, "god")) as p:
    check(p.magic == "CON" and p.content_name == "Games on Demand" and p.volume_type == 1 and p.is_game,
          "reconoce un paquete GOD (SVOD)")
    paths = sorted(e.path for e in p.files())
    check(paths == sorted(["default.xex", "title.dat", "media/intro.wmv", "media/menu.xzp"]),
          "recorre el árbol GDF con subcarpetas")
    out = os.path.join(TMP, "god_out")
    p.extract(out)
everything = god_root + [("media/" + n, c) for n, c in god_media]
check(all(open(os.path.join(out, *f.split("/")), "rb").read() == c for f, c in everything),
      "extrae byte a byte desde Data0000")
check(XContentPackage(gbase).title_name == "Juego GOD", "también acepta el archivo de cabecera directamente")

broken = os.path.join(TMP, "god2", "4D5307E6", "00007000", "FFFF")
make_god(broken, god_root, god_media, data_files=3, write_parts=2)
try:
    XContentPackage(broken)
    check(False, "detecta partes Data que faltan")
except XContentError as e:
    check("3" in str(e) and "2" in str(e), "detecta partes Data que faltan (lo explica)")
try:
    XContentPackage(os.path.join(TMP, "xbla_out"))
    check(False, "rechaza carpetas sin paquete")
except XContentError:
    check(True, "rechaza carpetas sin paquete")

print("Taller: detecta el formato y extrae")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_xiso import fake_xex  # noqa: E402
from PySide6.QtWidgets import QMainWindow  # noqa: E402

from reforge.core import AppConfig, Library  # noqa: E402
from reforge.pages import WorkshopPage  # noqa: E402

xex = fake_xex()
make_god(os.path.join(TMP, "god3", "4D5307E6", "00007000", "AA11"), [("default.xex", xex)], god_media)


class Ventana(QMainWindow):
    """Lo mínimo que el Taller necesita de la ventana principal.

    Esta prueba es del Taller (detectar el formato del juego y extraerlo), no de la aplicación entera,
    así que monta solo esa página. Además, en Windows crear la ventana completa deja el proceso tocado
    y al salir devuelve 0xC0000409 aunque todas las comprobaciones hayan pasado; está localizado en la
    página «Entorno» (sustituirla por una vacía hace que el proceso salga limpio) y viene de antes de
    esta prueba, pero así no tumba la compilación mientras se busca.
    """

    def __init__(self):
        super().__init__()
        self.cfg, self.lib = AppConfig.load(), Library.load()
        self.args, self.nav, self.nav_order = {"safe_mode": True, "install_patch": ""}, {}, []

    def go(self, *_a, **_k):
        pass

    def notify(self, *_a, **_k):
        pass

    def set_busy(self, *_a, **_k):
        pass


w = Ventana()
ws = WorkshopPage(w)


class Ctx:
    def __init__(self):
        self.lines = []

    def log(self, t, level="info"):
        self.lines.append(t)

    def progress(self, *_a):
        pass

    def cancelled(self):
        return False


def run_steps(mode, src, root):
    ctx = Ctx()
    for st in ws._build_steps("juego", root, mode, src, ["assets", "verify"]):
        st.func(ctx)
    return ctx


ws.src.setText(os.path.join(TMP, "god3"))
ws._scan_source()
check(ws._mode_key() == "pkg" and "Games on Demand" in ws.src_info.text() and "58410A1B" in ws.src_info.text(),
      "al elegir la carpeta GOD cambia solo a «Paquete GOD / XBLA»")
root = os.path.join(TMP, "proj_god")
ctx = run_steps("pkg", os.path.join(TMP, "god3"), root)
check(open(os.path.join(root, "assets", "default.xex"), "rb").read() == xex and
      os.path.isfile(os.path.join(root, "assets", "media", "intro.wmv")) and
      ws._result.get("title_id") == "4D5307E6", "extrae el GOD en assets y verifica el default.xex")

xdir = os.path.join(TMP, "suelto")
os.makedirs(os.path.join(xdir, "data"))
open(os.path.join(xdir, "juego.xex"), "wb").write(xex)
open(os.path.join(xdir, "data", "a.bin"), "wb").write(b"abc")
ws.src.setText(os.path.join(xdir, "juego.xex"))
ws._scan_source()
check(ws._mode_key() == "xex" and "default.xex" in ws.src_info.text(), "un .xex suelto cambia a «Archivo XEX»")
root = os.path.join(TMP, "proj_xex")
run_steps("xex", os.path.join(xdir, "juego.xex"), root)
check(open(os.path.join(root, "assets", "default.xex"), "rb").read() == xex and
      os.path.isfile(os.path.join(root, "assets", "data", "a.bin")), "copia su carpeta y lo guarda como default.xex")
ws.src.setText(pkg)
ws._scan_source()
check(ws._mode_key() == "pkg" and "Xbox Live Arcade" in ws.src_info.text(), "un paquete XBLA se reconoce por su cabecera")
from reforge.runner import wait_threads  # noqa: E402
wait_threads()
print(f"\nTodas las pruebas pasaron ({ok}).")
