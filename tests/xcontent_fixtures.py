"""Paquetes XContent sintéticos para las pruebas (STFS de solo lectura)."""
import random
import struct


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
def make_stfs(path, files, magic=b"LIVE", content_type=0x000D0000, tid=0x58410A1B, name="Juego de prueba"):
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
    out = header(magic, content_type, 0, vd, name=name, tid=tid)
    out += bytes(0xA000 - len(out))
    ht = bytearray(0x1000)
    for b, n in hashes.items():
        struct.pack_into(">I", ht, b * 0x18 + 0x14, 0x80000000 | n)
    out += ht
    for b in range(0, 160):
        out += (blocks.get(b, b"") + bytes(0x1000))[:0x1000]
    open(path, "wb").write(out)
