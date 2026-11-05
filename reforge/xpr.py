"""Texturas XPR2 (paquete de recursos de Xbox 360): leer, convertir a RGBA y volver a escribir.

Muchos juegos guardan su interfaz (botones, menús, logos) en archivos .xpr con texturas con nombre
(«A», «BTN_LB», «ALUCARDCONTROLS_P1»…). Formato:
* Cabecera: «XPR2», tamaño de cabecera (los datos empiezan en 12 + ese valor), tamaño de datos, nº recursos.
* Entradas de 16 bytes: tipo («TX2D»), desplazamiento del descriptor y del nombre (relativos a 12).
* Descriptor D3D (52 bytes) con la constante de lectura de textura de la GPU Xenos: formato, orden de
  bytes, ancho/alto, «pitch», si está en mosaico («tiled») y dirección base de los datos.

Formatos soportados: 8888 (ARGB), DXT1, DXT3 y DXT5, en mosaico o lineales. El nivel base se reescribe en el
mismo sitio y con el mismo tamaño, así el archivo queda idéntico salvo los píxeles cambiados. Python puro: no
necesita librerías (se usa también en el instalador).
"""
import struct

FMT_8888, FMT_DXT1, FMT_DXT3, FMT_DXT5 = 6, 18, 19, 20
FORMATS = {FMT_8888: ("8888", 1, 4), FMT_DXT1: ("DXT1", 4, 8), FMT_DXT3: ("DXT3", 4, 16), FMT_DXT5: ("DXT5", 4, 16)}


class Texture:
    __slots__ = ("name", "fmt", "endian", "width", "height", "pitch", "tiled", "offset")

    def __init__(self, name, fmt, endian, width, height, pitch, tiled, offset):
        self.name, self.fmt, self.endian = name, fmt, endian
        self.width, self.height, self.pitch, self.tiled, self.offset = width, height, pitch, tiled, offset

    @property
    def supported(self):
        return self.fmt in FORMATS

    def layout(self):
        kind, bd, bpp = FORMATS[self.fmt]
        bw, bh = (self.width + bd - 1) // bd, (self.height + bd - 1) // bd
        pw = max(self.pitch // bd, bw)
        if self.tiled:                 # en mosaico las filas van en grupos de 32 bloques (ancho y alto)
            pw = (pw + 31) & ~31
        rows = ((bh + 31) & ~31) if self.tiled else bh
        return kind, bd, bpp, bw, bh, pw, pw * rows * bpp

    def __repr__(self):
        return f"Texture({self.name!r}, fmt={self.fmt}, {self.width}x{self.height})"


def is_xpr(data):
    return data[:4] == b"XPR2"


def parse(data):
    """Texturas 2D del archivo (las de otros tipos o formatos raros se listan como no soportadas)."""
    if not is_xpr(data) or len(data) < 16:
        raise ValueError("No es un archivo XPR2")
    _m, hsize, _dsize, n = struct.unpack_from(">4sIII", data, 0)
    out = []
    for i in range(min(n, 100000)):
        p = 16 + i * 16
        if p + 16 > len(data):
            break
        typ, off, size, name_off = struct.unpack_from(">4sIII", data, p)
        if typ != b"TX2D" or size < 52 or 12 + off + 52 > len(data):
            continue
        name = data[12 + name_off: 12 + name_off + 128].split(b"\0")[0].decode("latin-1", "replace")
        dw0, dw1, dw2 = struct.unpack_from(">III", data, 12 + off + 28)
        out.append(Texture(name, dw1 & 0x3F, (dw1 >> 6) & 3, (dw2 & 0x1FFF) + 1, ((dw2 >> 13) & 0x1FFF) + 1,
                           ((dw0 >> 22) & 0x1FF) * 32, bool(dw0 >> 31), 12 + hsize + ((dw1 >> 12) << 12)))
    return out


# ---------------------------------------------------------------- mosaico y orden de bytes
def tiled_index(x, y, w, bpp):
    """Índice del bloque (x, y) en una textura en mosaico de Xenos (XGAddress2DTiledOffset)."""
    aw = (w + 31) & ~31
    lb = (bpp >> 2) + ((bpp >> 1) >> (bpp >> 2))
    macro = ((x >> 5) + (y >> 5) * (aw >> 5)) << (lb + 7)
    micro = ((x & 7) + ((y & 6) << 2)) << lb
    off = macro + ((micro & ~15) << 1) + (micro & 15) + ((y & 8) << (3 + lb)) + ((y & 1) << 4)
    return (((off & ~511) << 3) + ((off & 448) << 2) + (off & 63) + ((y & 16) << 7)
            + (((((y & 8) >> 2) + (x >> 3)) & 3) << 6)) >> lb


def _swap(b, endian):
    b = bytearray(b)
    if endian == 1:          # 8 en 16
        b[0::2], b[1::2] = b[1::2], b[0::2]
    elif endian == 2:        # 8 en 32
        b[0::4], b[1::4], b[2::4], b[3::4] = b[3::4], b[2::4], b[1::4], b[0::4]
    elif endian == 3:        # 16 en 32
        b[0::4], b[1::4], b[2::4], b[3::4] = b[2::4], b[3::4], b[0::4], b[1::4]
    return b


def _block_offsets(tex):
    _k, _bd, bpp, bw, bh, pw, _size = tex.layout()
    for by in range(bh):
        for bx in range(bw):
            yield bx, by, (tiled_index(bx, by, pw, bpp) if tex.tiled else by * pw + bx) * bpp


# ---------------------------------------------------------------- DXT
def _565(c):
    return (((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31)


def _color_block(b, four):
    c0, c1, bits = struct.unpack_from("<HHI", b, 0)
    p0, p1 = _565(c0), _565(c1)
    if c0 > c1 or four:
        pal = [p0 + (255,), p1 + (255,), tuple((2 * a + c) // 3 for a, c in zip(p0, p1)) + (255,),
               tuple((a + 2 * c) // 3 for a, c in zip(p0, p1)) + (255,)]
    else:
        pal = [p0 + (255,), p1 + (255,), tuple((a + c) // 2 for a, c in zip(p0, p1)) + (255,), (0, 0, 0, 0)]
    return [pal[(bits >> (2 * i)) & 3] for i in range(16)]


def _alpha5(b):
    a0, a1 = b[0], b[1]
    bits = int.from_bytes(b[2:8], "little")
    if a0 > a1:
        pal = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
    else:
        pal = [a0, a1] + [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255]
    return [pal[(bits >> (3 * i)) & 7] for i in range(16)]


def decode(data, tex):
    """RGBA (bytes, ancho×alto×4) del nivel base."""
    if not tex.supported:
        raise ValueError(f"Formato de textura {tex.fmt} no soportado")
    kind, bd, bpp, bw, bh, _pw, size = tex.layout()
    raw = _swap(data[tex.offset: tex.offset + size], tex.endian)
    w, h = tex.width, tex.height
    out = bytearray(w * h * 4)
    for bx, by, o in _block_offsets(tex):
        blk = raw[o:o + bpp]
        if len(blk) < bpp:
            continue
        if kind == "8888":                       # tras el cambio de orden: A R G B
            out[(by * w + bx) * 4:(by * w + bx) * 4 + 4] = bytes((blk[1], blk[2], blk[3], blk[0]))
            continue
        if kind == "DXT1":
            px = _color_block(blk, False)
        else:
            px = _color_block(blk[8:], True)
            if kind == "DXT3":
                al = [((blk[i // 2] >> (4 * (i & 1))) & 15) * 17 for i in range(16)]
            else:
                al = _alpha5(blk)
            px = [p[:3] + (a,) for p, a in zip(px, al)]
        for i, p in enumerate(px):
            x, y = bx * 4 + (i & 3), by * 4 + (i >> 2)
            if x < w and y < h:
                q = (y * w + x) * 4
                out[q:q + 4] = bytes(p)
    return bytes(out)


def _to565(r, g, b):
    return ((r * 31 + 127) // 255 << 11) | ((g * 63 + 127) // 255 << 5) | ((b * 31 + 127) // 255)


def _enc_color(px, allow_transparent):
    """Bloque de color DXT (8 bytes) por ajuste de extremos en el eje de mayor variación."""
    solid = [p for p in px if p[3] >= 128] if allow_transparent else px
    transparent = allow_transparent and len(solid) < 16
    if not solid:
        return struct.pack("<HHI", 0, 0xFFFF, 0xFFFFFFFF)
    ch = max(range(3), key=lambda c: max(p[c] for p in solid) - min(p[c] for p in solid))
    lo = min(solid, key=lambda p: (p[ch], sum(p[:3])))
    hi = max(solid, key=lambda p: (p[ch], sum(p[:3])))
    c_hi, c_lo = _to565(*hi[:3]), _to565(*lo[:3])
    if transparent:                     # modo 3 colores + transparente: c0 <= c1
        c0, c1 = min(c_hi, c_lo), max(c_hi, c_lo)
        p0, p1 = _565(c0), _565(c1)
        pal = [p0, p1, tuple((a + c) // 2 for a, c in zip(p0, p1))]
    else:
        if c_hi == c_lo:
            return struct.pack("<HHI", c_hi, c_lo, 0)
        c0, c1 = max(c_hi, c_lo), min(c_hi, c_lo)
        p0, p1 = _565(c0), _565(c1)
        pal = [p0, p1, tuple((2 * a + c) // 3 for a, c in zip(p0, p1)), tuple((a + 2 * c) // 3 for a, c in zip(p0, p1))]
    bits = 0
    for i, p in enumerate(px):
        if transparent and p[3] < 128:
            idx = 3
        else:
            idx = min(range(len(pal)), key=lambda k: sum((p[c] - pal[k][c]) ** 2 for c in range(3)))
        bits |= idx << (2 * i)
    return struct.pack("<HHI", c0, c1, bits)


def _enc_alpha5(al):
    a0, a1 = max(al), min(al)
    if a0 == a1:
        return bytes((a0, a1)) + bytes(6)
    pal = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
    bits = 0
    for i, a in enumerate(al):
        bits |= min(range(8), key=lambda k: abs(a - pal[k])) << (3 * i)
    return bytes((a0, a1)) + bits.to_bytes(6, "little")


def _enc_alpha4(al):
    out = bytearray(8)
    for i, a in enumerate(al):
        out[i // 2] |= ((a * 15 + 127) // 255) << (4 * (i & 1))
    return bytes(out)


def encode_into(data, tex, rgba):
    """Escribe `rgba` (ancho×alto×4 del tamaño exacto de la textura) en `data` (bytearray), en su sitio."""
    if not tex.supported:
        raise ValueError(f"Formato de textura {tex.fmt} no soportado")
    w, h = tex.width, tex.height
    if len(rgba) != w * h * 4:
        raise ValueError("Tamaño de imagen distinto al de la textura")
    kind, bd, bpp, _bw, _bh, _pw, size = tex.layout()
    raw = _swap(data[tex.offset: tex.offset + size], tex.endian)
    for bx, by, o in _block_offsets(tex):
        if o + bpp > len(raw):
            continue
        if kind == "8888":
            q = (by * w + bx) * 4
            r, g, b, a = rgba[q:q + 4]
            raw[o:o + 4] = bytes((a, r, g, b))
            continue
        px = []
        for i in range(16):
            x, y = min(bx * 4 + (i & 3), w - 1), min(by * 4 + (i >> 2), h - 1)
            q = (y * w + x) * 4
            px.append(tuple(rgba[q:q + 4]))
        if kind == "DXT1":
            blk = _enc_color(px, True)
        else:
            al = [p[3] for p in px]
            color = _enc_color([p[:3] + (255,) for p in px], False)
            blk = (_enc_alpha4(al) if kind == "DXT3" else _enc_alpha5(al)) + color
        raw[o:o + bpp] = blk
    data[tex.offset: tex.offset + size] = _swap(raw, tex.endian)
