"""Lectura mínima de cabeceras XEX2 (Title ID, versión, disco, nombre original)."""
import struct

KEY_EXECUTION_INFO = 0x00040006
KEY_ORIGINAL_PE_NAME = 0x000183FF


def _version(v):
    return f"{(v >> 28) & 0xF}.{(v >> 24) & 0xF}.{(v >> 8) & 0xFFFF}.{v & 0xFF}"


def read_xex_info_bytes(data):
    if len(data) < 0x18 or data[:4] != b"XEX2":
        raise ValueError("No es un archivo XEX2 válido")
    _flags, pe_off, _res, _sec, count = struct.unpack_from(">IIIII", data, 4)
    info = {"title_id": "", "version": "", "disc": "", "original_name": "", "media_id": ""}
    for i in range(min(count, 64)):
        pos = 0x18 + i * 8
        if pos + 8 > len(data):
            break
        key, value = struct.unpack_from(">II", data, pos)
        if key == KEY_EXECUTION_INFO and value + 24 <= len(data):
            media, ver, _base, tid = struct.unpack_from(">IIII", data, value)
            _plat, _etype, disc, discs = struct.unpack_from(">BBBB", data, value + 16)
            info.update(title_id=f"{tid:08X}", version=_version(ver),
                        media_id=f"{media:08X}", disc=f"{disc}/{discs}" if discs else "")
        elif key == KEY_ORIGINAL_PE_NAME and value + 4 <= len(data):
            (size,) = struct.unpack_from(">I", data, value)
            raw = data[value + 4: value + min(size, 260)]
            info["original_name"] = raw.split(b"\0")[0].decode("latin-1", "replace")
    return info


def read_xex_info(path):
    with open(path, "rb") as f:
        data = f.read(1024 * 1024)
    return read_xex_info_bytes(data)
