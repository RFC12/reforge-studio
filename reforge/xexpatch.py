"""Parche delta (default.xexp) propio para aplicar trucos/parches de la base de datos de Xenia.

rexglue (como Xenia) carga «default.xexp» junto a «default.xex» y aplica el parche al cargar el módulo,
tanto en el codegen como al arrancar el juego. ReForge aprovecha ese mecanismo: construye un XEXP que
escribe los bytes de los parches elegidos en la imagen del juego. Así los parches de código entran en el
código recompilado y los de datos se aplican antes de que el juego se ejecute (como en Xenia).

Formato (ver XexModule::ApplyPatch del SDK):
* Cabecera XEX2 con módulo «patch delta», información de seguridad mínima, formato de archivo sin cifrar
  con compresión delta, y el descriptor de parche (huella del XEX base y clave de imagen comprobada).
* Un bloque de datos con entradas {old_addr, new_addr, tamaño, tamaño comprimido, datos}; los datos son
  un flujo LZX con un bloque «sin comprimir», que copia los bytes tal cual.
"""
import hashlib
import struct

XEX_MODULE_PATCH_DELTA = 0x00000040
KEY_FILE_FORMAT = 0x000003FF
KEY_DELTA_PATCH = 0x000005FF
KEY_EXECUTION_INFO = 0x00040006
RETAIL_KEY = bytes.fromhex("20B185A59D28FDC340583FBB0896BF91")
DEVKIT_KEY = bytes(16)
WINDOW_SIZE = 0x8000
MAX_CHUNK = 0x7FF0


class XexPatchError(Exception):
    pass


# ---------------------------------------------------------------- AES-128 (dos bloques: no hace falta más)
_SBOX = [0] * 256
_INV = [0] * 256


def _init_sbox():
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1 | q >> 7) & 0xFF) ^ ((q << 2 | q >> 6) & 0xFF) ^ ((q << 3 | q >> 5) & 0xFF) \
            ^ ((q << 4 | q >> 4) & 0xFF) ^ 0x63
        _SBOX[p] = x
        _INV[x] = p
        if p == 1:
            break
    _SBOX[0] = 0x63
    _INV[0x63] = 0


_init_sbox()


def _xt(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xt(a)
        b >>= 1
    return r


def _expand(key):
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = [_SBOX[b] for b in t[1:] + t[:1]]
            t[0] ^= rcon
            rcon = _xt(rcon)
        w.append([a ^ b for a, b in zip(w[i - 4], t)])
    return [sum(w[r * 4:r * 4 + 4], []) for r in range(11)]


def aes_encrypt_block(key, block):
    rk = _expand(key)
    s = [b ^ k for b, k in zip(block, rk[0])]
    for rnd in range(1, 11):
        s = [_SBOX[b] for b in s]
        s = [s[(c * 4 + r + r * 4) % 16] for c in range(4) for r in range(4)]          # ShiftRows
        if rnd != 10:
            t = []
            for c in range(4):
                a = s[c * 4:c * 4 + 4]
                t += [_mul(a[0], 2) ^ _mul(a[1], 3) ^ a[2] ^ a[3], a[0] ^ _mul(a[1], 2) ^ _mul(a[2], 3) ^ a[3],
                      a[0] ^ a[1] ^ _mul(a[2], 2) ^ _mul(a[3], 3), _mul(a[0], 3) ^ a[1] ^ a[2] ^ _mul(a[3], 2)]
            s = t
        s = [b ^ k for b, k in zip(s, rk[rnd])]
    return bytes(s)


def aes_decrypt_block(key, block):
    rk = _expand(key)
    s = [b ^ k for b, k in zip(block, rk[10])]
    for rnd in range(9, -1, -1):
        s = [s[(c * 4 + r - r * 4) % 16] for c in range(4) for r in range(4)]          # InvShiftRows
        s = [_INV[b] for b in s]
        s = [b ^ k for b, k in zip(s, rk[rnd])]
        if rnd:
            t = []
            for c in range(4):
                a = s[c * 4:c * 4 + 4]
                t += [_mul(a[0], 14) ^ _mul(a[1], 11) ^ _mul(a[2], 13) ^ _mul(a[3], 9),
                      _mul(a[0], 9) ^ _mul(a[1], 14) ^ _mul(a[2], 11) ^ _mul(a[3], 13),
                      _mul(a[0], 13) ^ _mul(a[1], 9) ^ _mul(a[2], 14) ^ _mul(a[3], 11),
                      _mul(a[0], 11) ^ _mul(a[1], 13) ^ _mul(a[2], 9) ^ _mul(a[3], 14)]
            s = t
    return bytes(s)


# ---------------------------------------------------------------- LZX: un bloque sin comprimir
def lzx_uncompressed(data):
    """Flujo LZX (libmspack) con un único bloque sin comprimir que produce `data` tal cual."""
    n = len(data)
    if not 0 < n <= 0x8000:
        raise XexPatchError("Trozo LZX fuera de rango")
    bits = [0] + [0, 1, 1]                                  # sin traducción E8 · tipo 3 (sin comprimir)
    bits += [(n >> (23 - i)) & 1 for i in range(24)]        # tamaño: 16 + 8 bits
    bits += [0] * (32 - len(bits))                          # relleno hasta alinear a 16 bits
    words = b"".join(struct.pack("<H", int("".join(map(str, bits[i:i + 16])), 2)) for i in range(0, 32, 16))
    out = words + struct.pack("<III", 1, 1, 1) + bytes(data)   # R0, R1, R2
    if n & 1:
        out += b"\0"
    return out


# ---------------------------------------------------------------- XEX base
def _opt_headers(data):
    count = struct.unpack_from(">I", data, 0x14)[0]
    return {struct.unpack_from(">I", data, 0x18 + i * 8)[0]: struct.unpack_from(">I", data, 0x1C + i * 8)[0]
            for i in range(min(count, 64))}


def base_info(xex):
    if xex[:4] != b"XEX2":
        raise XexPatchError("default.xex no es un XEX2")
    flags, header_size, _res, sec = struct.unpack_from(">IIII", xex, 4)
    if flags & 0x60:
        raise XexPatchError("default.xex ya es un parche")
    info = {
        "header_size": header_size,
        "image_size": struct.unpack_from(">I", xex, sec + 4)[0],
        "signature": xex[sec + 8: sec + 0x108],
        "load_address": struct.unpack_from(">I", xex, sec + 0x110)[0],
        "aes_key": xex[sec + 0x150: sec + 0x160],
        "version": 0, "title_id": 0,
    }
    hdr = _opt_headers(xex)
    base_addr = hdr.get(0x00010001)          # XEX_HEADER_IMAGE_BASE_ADDRESS (valor directo)
    if base_addr:
        info["load_address"] = base_addr
    ex = hdr.get(KEY_EXECUTION_INFO)
    if ex:
        info["version"] = struct.unpack_from(">I", xex, ex + 4)[0]
        info["title_id"] = struct.unpack_from(">I", xex, ex + 12)[0]
    ff = hdr.get(KEY_FILE_FORMAT)
    info["encrypted"] = bool(ff and struct.unpack_from(">H", xex, ff + 4)[0])
    return info


def session_key(info, devkit=False):
    return aes_decrypt_block(DEVKIT_KEY if devkit else RETAIL_KEY, info["aes_key"])


# ---------------------------------------------------------------- construir el parche
def _merge(writes):
    """[(dirección, bytes)] → tramos contiguos sin solapes (el último gana) y de tamaño acotado."""
    mem = {}
    for addr, data in writes:
        for i, b in enumerate(data):
            mem[addr + i] = b
    out, cur_start, cur = [], None, bytearray()
    for a in sorted(mem):
        if cur_start is not None and a == cur_start + len(cur) and len(cur) < MAX_CHUNK:
            cur.append(mem[a])
            continue
        if cur_start is not None:
            out.append((cur_start, bytes(cur)))
        cur_start, cur = a, bytearray([mem[a]])
    if cur_start is not None:
        out.append((cur_start, bytes(cur)))
    return out


def build_xexp(xex, writes, devkit=False):
    """Bytes de un default.xexp que escribe `writes` [(dirección guest, bytes)] sobre el XEX base."""
    info = base_info(xex)
    base, size = info["load_address"], info["image_size"]
    entries = b""
    for addr, data in _merge(writes):
        off = addr - base
        if off < 0 or off + len(data) > size:
            raise XexPatchError(f"La dirección 0x{addr:08X} está fuera del ejecutable")
        lz = lzx_uncompressed(data)
        entries += struct.pack(">IIHH", off, off, len(data), len(lz)) + lz
    entries += bytes(12)                                     # fin de las entradas
    block = struct.pack(">I", 0) + bytes(20) + entries      # siguiente bloque: ninguno
    first_block = (len(block), hashlib.sha1(block).digest())

    key = session_key(info, devkit)
    sec_size = 0x184
    ff = struct.pack(">IHHI", 36, 0, 3, WINDOW_SIZE) + struct.pack(">I", first_block[0]) + first_block[1]
    desc = struct.pack(">III", 0x5C, info["version"] + 1, info["version"]) + hashlib.sha1(info["signature"]).digest()
    desc += aes_encrypt_block(key, key)                     # image_key_source: comprobado por el cargador
    desc += struct.pack(">IIIIIII", info["header_size"], 0, 0, 0, 0, size, 0)
    desc += bytes(12)                                       # cabecera: sin cambios (entrada vacía)
    exec_info = struct.pack(">IIII", 0, info["version"] + 1, info["version"], info["title_id"]) + bytes(8)

    n_hdr = 3
    off_ff = 0x18 + n_hdr * 8
    off_desc = off_ff + len(ff)
    off_exec = off_desc + len(desc)
    sec_off = (off_exec + len(exec_info) + 15) & ~15
    header_size = (sec_off + sec_size + 0xFFF) & ~0xFFF
    h = bytearray(header_size)
    struct.pack_into(">4sIIIII", h, 0, b"XEX2", XEX_MODULE_PATCH_DELTA, header_size, 0, sec_off, n_hdr)
    for i, (k, v) in enumerate(((KEY_FILE_FORMAT, off_ff), (KEY_DELTA_PATCH, off_desc), (KEY_EXECUTION_INFO, off_exec))):
        struct.pack_into(">II", h, 0x18 + i * 8, k, v)
    h[off_ff:off_ff + len(ff)] = ff
    h[off_desc:off_desc + len(desc)] = desc
    h[off_exec:off_exec + len(exec_info)] = exec_info
    struct.pack_into(">II", h, sec_off, sec_size, size)
    struct.pack_into(">I", h, sec_off + 0x110, base)
    return bytes(h) + block
