"""Creador nativo de imágenes XISO (XDVDFS) para Xbox Clásica y Xbox 360.

Produce el mismo tipo de imagen que `extract-xiso -c`: la partición de juego sin el
relleno de vídeo/XGD. Para quemar en disco o usar Xbox Image Browser hay que
completarla con 360mpGui / abgx360 (igual que con extract-xiso).
"""
import os
import struct
import time

SECTOR = 2048
MAGIC = b"MICROSOFT*XBOX*MEDIA"
ATTR_DIR = 0x10
ATTR_NORMAL = 0x80
FILE_MODULUS = 0x10000
CHUNK = 4 * 1024 * 1024


class XisoWriteError(Exception):
    pass


class _Node:
    __slots__ = ("name", "path", "is_dir", "size", "children", "sector", "table_size")

    def __init__(self, name, path, is_dir, size=0):
        self.name, self.path, self.is_dir, self.size = name, path, is_dir, size
        self.children = []
        self.sector = 0
        self.table_size = 0


def _entry_len(name_bytes):
    n = 14 + len(name_bytes)
    return n + ((-n) % 4)


def _key(node):
    return node.name.upper()


def _scan(path, name=""):
    node = _Node(name, path, True)
    entries = sorted(os.listdir(path), key=lambda s: s.upper())
    for n in entries:
        full = os.path.join(path, n)
        try:
            n.encode("ascii")
        except UnicodeEncodeError:
            raise XisoWriteError(f"Nombre con caracteres no ASCII (XDVDFS no lo admite): {full}")
        if len(n) > 255:
            raise XisoWriteError(f"Nombre demasiado largo: {full}")
        if os.path.isdir(full):
            node.children.append(_scan(full, n))
        elif os.path.isfile(full):
            size = os.path.getsize(full)
            if size > 0xFFFFFFFF:
                raise XisoWriteError(f"Archivo mayor de 4 GB (no admitido): {full}")
            node.children.append(_Node(n, full, False, size))
    node.children.sort(key=_key)
    return node


def _layout_table(children):
    """Árbol binario equilibrado en pre-orden. Devuelve [(node, offset, left_off, right_off)], tamaño."""
    order = []

    def build(lo, hi):
        if lo > hi:
            return None
        mid = (lo + hi) // 2
        idx = len(order)
        order.append([children[mid], 0, None, None])
        left = build(lo, mid - 1)
        right = build(mid + 1, hi)
        order[idx][2], order[idx][3] = left, right
        return idx

    build(0, len(children) - 1)
    off = 0
    for item in order:
        ln = _entry_len(item[0].name.encode("ascii"))
        if off % SECTOR + ln > SECTOR:          # una entrada no puede cruzar sectores
            off += SECTOR - off % SECTOR
        item[1] = off
        off += ln
    size = off + ((-off) % SECTOR)
    return order, max(size, SECTOR)


def _serialize_table(order, size):
    buf = bytearray(b"\xff" * size)
    for node, off, li, ri in order:
        name = node.name.encode("ascii")
        left = order[li][1] // 4 if li is not None else 0
        right = order[ri][1] // 4 if ri is not None else 0
        if node.is_dir:
            sector, length, attr = (node.sector, node.table_size, ATTR_DIR) if node.children else (0, 0, ATTR_DIR)
        else:
            sector, length, attr = node.sector, node.size, ATTR_NORMAL
        struct.pack_into("<HHIIBB", buf, off, left, right, sector, length, attr, len(name))
        buf[off + 14: off + 14 + len(name)] = name
    return bytes(buf)


def _filetime():
    return int((time.time() + 11644473600) * 10_000_000)


def plan(src_dir):
    """Analiza la carpeta y devuelve (raíz, dirs, files, total_bytes) sin escribir nada."""
    if not os.path.isdir(src_dir):
        raise XisoWriteError(f"No existe la carpeta {src_dir}")
    root = _scan(src_dir)
    if not root.children:
        raise XisoWriteError("La carpeta está vacía")
    dirs, files = [], []

    def walk(n):
        if n.is_dir:
            dirs.append(n)
            for c in n.children:
                walk(c)
        else:
            files.append(n)
    walk(root)
    return root, dirs, files, sum(f.size for f in files)


def create_xiso(src_dir, out_path, progress=None, cancelled=None, on_file=None):
    root, dirs, files, total = plan(src_dir)
    tables = {}
    for d in dirs:
        if d.children:
            tables[id(d)] = _layout_table(d.children)
            d.table_size = tables[id(d)][1]
    # asignación de sectores: cabecera en 32, tablas desde 33, luego archivos
    sector = 33
    for d in dirs:
        if d.children:
            d.sector = sector
            sector += d.table_size // SECTOR
    for f in files:
        f.sector = sector
        sector += (f.size + SECTOR - 1) // SECTOR
    end = sector * SECTOR
    end += (-end) % FILE_MODULUS

    tmp = out_path + ".part"
    done = 0
    try:
        with open(tmp, "wb") as out:
            out.truncate(end)
            hdr = bytearray(SECTOR)
            hdr[0:20] = MAGIC
            struct.pack_into("<IIQ", hdr, 20, root.sector, root.table_size, _filetime())
            hdr[0x7EC:0x7EC + 20] = MAGIC
            out.seek(32 * SECTOR)
            out.write(hdr)
            for d in dirs:
                if d.children:
                    order, size = tables[id(d)]
                    out.seek(d.sector * SECTOR)
                    out.write(_serialize_table(order, size))
            for f in files:
                if on_file:
                    on_file(f)
                out.seek(f.sector * SECTOR)
                with open(f.path, "rb") as src:
                    while True:
                        if cancelled and cancelled():
                            raise XisoWriteError("Creación cancelada")
                        buf = src.read(CHUNK)
                        if not buf:
                            break
                        out.write(buf)
                        done += len(buf)
                        if progress:
                            progress(done, total)
        os.replace(tmp, out_path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return len(files), total, end
