"""Lectura de cabeceras XBE (ejecutables de Xbox Clásica): título y Title ID."""
import struct

REGIONS = {0x1: "NTSC-U", 0x2: "NTSC-J", 0x4: "PAL", 0x80000000: "Debug"}


def read_xbe_info_bytes(data):
    if len(data) < 0x178 or data[:4] != b"XBEH":
        raise ValueError("No es un archivo XBE válido")
    base, = struct.unpack_from("<I", data, 0x104)
    cert_addr, = struct.unpack_from("<I", data, 0x118)
    off = cert_addr - base
    if off < 0 or off + 0xA4 > len(data):
        raise ValueError("Certificado XBE fuera de rango")
    tid, = struct.unpack_from("<I", data, off + 0x08)
    raw = data[off + 0x0C: off + 0x0C + 80]
    title = raw.decode("utf-16-le", "replace").split("\0")[0].strip()
    region, = struct.unpack_from("<I", data, off + 0xA0)
    regions = [n for bit, n in REGIONS.items() if region & bit]
    pub = bytes([(tid >> 24) & 0xFF, (tid >> 16) & 0xFF])
    pub_s = pub.decode("ascii", "replace") if all(32 <= c < 127 for c in pub) else ""
    return {"title": title, "title_id": f"{tid:08X}",
            "game_code": f"{pub_s}-{tid & 0xFFFF:03d}" if pub_s else "",
            "region": "/".join(regions)}


def read_xbe_info(path):
    with open(path, "rb") as f:
        return read_xbe_info_bytes(f.read(256 * 1024))
