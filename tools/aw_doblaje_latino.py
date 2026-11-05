"""ReForge Studio · Doblaje latino de Call of Duty: Advanced Warfare (Xbox 360 -> PC).

Toma las voces en español latino de la versión de Xbox 360 (carpeta spanishna, archivos sna_*) y las
pone en la versión oficial de PC en lugar del doblaje de España (carpeta spanish, archivos spa_*).

Cómo funciona:
  1. Abre los fastfiles de nivel de las dos versiones (360: LZX big-endian, PC: LZ4) y lee todas las
     referencias de sonido "streamed" localizadas (pak, posición, tamaño, duración).
  2. Empareja cada voz de PC con la misma voz de 360 (mismo orden, mismo pak, mismo nombre de alias).
  3. Convierte cada voz latina (XMA2 de 360) a FLAC 48 kHz con el formato exacto que usa el juego de PC
     (bloques de 1024 muestras, bloque 'fsiz' y tabla de búsqueda cada 16384 muestras).
  4. Añade las voces al final de cada spa_soundfileN.pak (lo original queda intacto, el multijugador
     sigue funcionando) y reescribe las referencias de los spa_<nivel>.ff para que apunten a ellas.
  5. En los videos de historia (<nivel>_load.bik), que ya traen el audio latino como pista Bink, pone esa
     pista en el lugar de la de España.
  6. Guarda una copia de todo lo que cambia en spanish\\_reforge_respaldo (se puede deshacer con --restaurar).

Uso:
  python aw_doblaje_latino.py --x360 "H:\\cod_aw\\assets\\spanishna" --pc "H:\\Call of Duty Advanced Warfare"
  python aw_doblaje_latino.py --pc "H:\\Call of Duty Advanced Warfare" --restaurar
Necesita: Python 3.8+, lz4 (pip install lz4) y ffmpeg (pip install imageio-ffmpeg, o ffmpeg en el PATH).
"""
import argparse
import concurrent.futures
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time

VERSION = 3
LANG_DIR = "spanish"
PC_PREFIX = "spa_"
X_PREFIX = "sna_"
BACKUP_DIR = "_reforge_respaldo"
STATE_FILE = "reforge_doblaje_latino.json"


LOG_HOOK = None


def log(*a):
    if LOG_HOOK:
        LOG_HOOK(" ".join(str(x) for x in a))
    else:
        print(*a, flush=True)


# ----------------------------------------------------------------------------------------------- LZX (360)
class _Bits:
    __slots__ = ("d", "p", "buf", "n")

    def __init__(self, d, p):
        self.d = d
        self.p = p
        self.buf = 0
        self.n = 0

    def ensure(self, k):
        d = self.d
        while self.n < k:
            p = self.p
            w = (d[p] | (d[p + 1] << 8)) if p + 1 < len(d) else 0
            self.p = p + 2
            self.buf = (self.buf << 16) | w
            self.n += 16

    def read(self, k):
        if k == 0:
            return 0
        self.ensure(k)
        self.n -= k
        v = self.buf >> self.n
        self.buf &= (1 << self.n) - 1
        return v


def _table(lens):
    tab = [None] * 65536
    order = sorted((l, s) for s, l in enumerate(lens) if l)
    code = 0
    prev = 0
    for l, s in order:
        code <<= l - prev
        prev = l
        start = code << (16 - l)
        cnt = 1 << (16 - l)
        if start + cnt > 65536:
            raise ValueError("árbol LZX inválido")
        tab[start:start + cnt] = [(s, l)] * cnt
        code += 1
    return tab


def _sym(br, tab):
    br.ensure(16)
    e = tab[(br.buf >> (br.n - 16)) & 0xFFFF]
    if e is None:
        raise ValueError("código LZX inválido")
    br.n -= e[1]
    br.buf &= (1 << br.n) - 1
    return e[0]


_EXTRA = [0, 0, 0, 0]
_j = 1
while len(_EXTRA) < 51:
    _EXTRA += [_j, _j]
    _j = min(_j + 1, 17)
_EXTRA = _EXTRA[:51]
_BASE = []
_b = 0
for _e in _EXTRA:
    _BASE.append(_b)
    _b += 1 << _e


class _LZX:
    def __init__(self, window_bits):
        self.wsize = 1 << window_bits
        slots = {15: 30, 16: 32, 17: 34, 18: 36, 19: 38, 20: 42, 21: 50}[window_bits]
        self.main_n = 256 + slots * 8
        self.main_len = [0] * self.main_n
        self.len_len = [0] * 250
        self.R = [1, 1, 1]
        self.header = False
        self.remaining = 0
        self.btype = 0
        self.blen = 0
        self.out = bytearray()
        self.mark = 0

    def _lengths(self, br, lens, first, last):
        pt = _table([br.read(4) for _ in range(20)])
        x = first
        while x < last:
            z = _sym(br, pt)
            if z == 17:
                y = br.read(4) + 4
                lens[x:x + y] = [0] * y
                x += y
            elif z == 18:
                y = br.read(5) + 20
                lens[x:x + y] = [0] * y
                x += y
            elif z == 19:
                y = br.read(1) + 4
                z = lens[x] - _sym(br, pt)
                if z < 0:
                    z += 17
                lens[x:x + y] = [z] * y
                x += y
            else:
                z = lens[x] - z
                if z < 0:
                    z += 17
                lens[x] = z
                x += 1

    def frame(self, d, p, out_size):
        br = _Bits(d, p)
        if not self.header:
            self.header = True
            if br.read(1):
                raise ValueError("LZX con traducción E8 (no esperada en fastfiles)")
        out = self.out
        target = self.mark + out_size
        R0, R1, R2 = self.R
        while len(out) < target:
            if self.remaining == 0:
                if self.btype == 3 and (self.blen & 1):
                    br.p += 1
                self.btype = br.read(3)
                hi = br.read(16)
                lo = br.read(8)
                self.remaining = self.blen = (hi << 8) | lo
                if self.btype == 2:
                    self.atab = _table([br.read(3) for _ in range(8)])
                if self.btype in (1, 2):
                    self._lengths(br, self.main_len, 0, 256)
                    self._lengths(br, self.main_len, 256, self.main_n)
                    self.mtab = _table(self.main_len)
                    self._lengths(br, self.len_len, 0, 249)
                    self.ltab = _table(self.len_len) if any(self.len_len) else None
                elif self.btype == 3:
                    br.ensure(16)
                    if br.n > 16:
                        br.p -= 2
                    br.buf = 0
                    br.n = 0
                    R0, R1, R2 = struct.unpack_from("<III", d, br.p)
                    br.p += 12
                else:
                    raise ValueError("bloque LZX de tipo %d" % self.btype)
            run = min(self.remaining, target - len(out))
            if self.btype == 3:
                out += d[br.p:br.p + run]
                br.p += run
                self.remaining -= run
                continue
            endp = len(out) + run
            mt = self.mtab
            lt = self.ltab
            aligned = self.btype == 2
            while len(out) < endp:
                s = _sym(br, mt)
                if s < 256:
                    out.append(s)
                    continue
                s -= 256
                ml = s & 7
                if ml == 7:
                    ml += _sym(br, lt)
                ml += 2
                mo = s >> 3
                if mo > 2:
                    ex = _EXTRA[mo]
                    if aligned:
                        m2 = _BASE[mo] - 2
                        if ex > 3:
                            m2 += br.read(ex - 3) << 3
                            m2 += _sym(br, self.atab)
                        elif ex == 3:
                            m2 += _sym(br, self.atab)
                        elif ex > 0:
                            m2 += br.read(ex)
                        else:
                            m2 = 1
                        mo = m2
                    else:
                        mo = (_BASE[mo] - 2 + br.read(ex)) if mo != 3 else 1
                    R2 = R1
                    R1 = R0
                    R0 = mo
                elif mo == 0:
                    mo = R0
                elif mo == 1:
                    mo = R1
                    R1 = R0
                    R0 = mo
                else:
                    mo = R2
                    R2 = R0
                    R0 = mo
                src = len(out) - mo
                if src < 0:
                    raise ValueError("LZX fuera de la ventana")
                if mo >= ml:
                    out += out[src:src + ml]
                else:
                    for k in range(ml):
                        out.append(out[src + k])
            self.remaining -= run + (len(out) - endp)
        self.R = [R0, R1, R2]
        res = bytes(out[self.mark:target])
        self.mark = target
        if len(out) > self.wsize * 4:
            cut = len(out) - self.wsize * 2
            del out[:cut]
            self.mark -= cut
        return res


def xmem_decompress(d, p, window_bits=19):
    z = _LZX(window_bits)
    out = bytearray()
    while p < len(d):
        if d[p] == 0xFF:
            fsize = (d[p + 1] << 8) | d[p + 2]
            csize = (d[p + 3] << 8) | d[p + 4]
            p += 5
        else:
            fsize = 0x8000
            csize = (d[p] << 8) | d[p + 1]
            p += 2
        if csize == 0:
            break
        out += z.frame(d, p, fsize)
        p += csize
    return bytes(out)


def zone_360(path):
    d = open(path, "rb").read()
    if d[:8] != b"S1ffu100":
        raise ValueError("no es un fastfile S1 de Xbox 360: %s" % path)
    return xmem_decompress(d, 0x24)


# ------------------------------------------------------------------------------------------------ LZ4 (PC)
def _lz4_dec(src, pos, size, maxout):
    out = bytearray()
    end = pos + size
    while pos < end and len(out) < maxout:
        t = src[pos]
        pos += 1
        n = t >> 4
        if n == 15:
            while True:
                b = src[pos]
                pos += 1
                n += b
                if b != 255:
                    break
        out += src[pos:pos + n]
        pos += n
        if pos >= end:
            break
        off = src[pos] | (src[pos + 1] << 8)
        pos += 2
        m = t & 15
        if m == 15:
            while True:
                b = src[pos]
                pos += 1
                m += b
                if b != 255:
                    break
        m += 4
        s = len(out) - off
        if off == 0 or s < 0:
            raise ValueError("LZ4 inválido")
        if off >= m:
            out += out[s:s + m]
        else:
            for k in range(m):
                out.append(out[s + k])
    return bytes(out)


def zone_pc(d):
    if d[:8] != b"S1ffu100":
        raise ValueError("no es un fastfile S1 de PC")
    total = struct.unpack_from("<Q", d, 0x2C)[0]
    pos = 0x38
    out = bytearray()
    while len(out) < total:
        pos = (pos + 3) & ~3
        cs, us = struct.unpack_from("<II", d, pos)
        blk = _lz4_dec(d, pos + 8, cs, us)
        if len(blk) != us:
            raise ValueError("bloque LZ4 incompleto")
        out += blk
        pos += 8 + cs
    return bytes(out)


def pack_pc(header, zone):
    import lz4.block

    parts = [bytearray(header[:0x38])]
    size = 0x38
    for i in range(0, len(zone), 0x10000):
        chunk = zone[i:i + 0x10000]
        comp = lz4.block.compress(chunk, mode="high_compression", compression=12, store_size=False)
        pad = (-size) & 3
        parts.append(b"\0" * pad + struct.pack("<II", len(comp), len(chunk)) + comp)
        size += pad + 8 + len(comp)
    pad = (-size) & 3
    parts.append(b"\0" * pad)
    size += pad
    out = b"".join(bytes(p) for p in parts)
    out = bytearray(out)
    struct.pack_into("<QQQ", out, 0x1C, size, size, len(zone))
    return bytes(out)


# ---------------------------------------------------------------------------------- referencias de sonido
# tipo 2 = voz por streaming · tipo 3 = streaming con "arranque" (los primeros 32 KB del FLAC van dentro
# del fastfile para que suene al instante: las frases de las escenas *_pcap)
_P360 = re.compile(rb"(?:\x02\x01\x00\x00|\x03\x01\x00\x00\xff\xff\xff\xff)\x01[\x00\x01]\x00[\x00-\x7f]", re.S)
_PPC = re.compile(rb"(?:\x02\x01\x00\x00\x00\x00\x00\x00|\x03\x01\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\xff\xfd\xfd\xfd)"
                  rb"\x01[\x00\x01][\x00-\x7f]\x00", re.S)
_ALIAS = re.compile(rb"(?<=[\x00\xff])([a-z][a-z0-9]*_[a-z0-9_]+)\x00")


def _alias_near(z, i):
    names = _ALIAS.findall(z[max(0, i - 600):i])
    return names[-1].decode() if names else ""


def refs_360(z, sizes):
    out = []
    for m in _P360.finditer(z):
        typ = z[m.start()]
        i = m.start() + (4 if typ == 2 else 8)
        idx = struct.unpack_from(">H", z, i + 2)[0]
        off, ln = struct.unpack_from(">II", z, i + 4)
        ms = struct.unpack_from(">I", z, i + 12)[0] if typ == 2 else 0
        if idx in sizes and ln and off + ln <= sizes[idx]:
            out.append(dict(type=typ, idx=idx, off=off, len=ln, ms=ms, alias=_alias_near(z, m.start())))
    return out


def _prime(z, i, ln):
    """Arranque de una voz tipo 3: devuelve (pos_cabecera, pos_datos, tamaño) o None."""
    q = z.find(b"fLaC", i, i + 1200)
    if q < 0:
        return None
    h = z.rfind(struct.pack("<I", ln), i, q)
    if h < 4 or struct.unpack_from("<I", z, h - 4)[0] not in (24000, 32000, 44100, 48000):
        return None
    h -= 4
    size = struct.unpack_from("<I", z, h + 20)[0]
    if not 0 < size <= ln or q + size > len(z):
        return None
    return h, q, size


def refs_pc(z, sizes):
    out = []
    for m in _PPC.finditer(z):
        typ = z[m.start()]
        i = m.start() + (8 if typ == 2 else 16)
        idx = struct.unpack_from("<H", z, i + 2)[0]
        off, ln = struct.unpack_from("<QQ", z, i + 8)
        ms = struct.unpack_from("<I", z, i + 24)[0] if typ == 2 else 0
        if idx in sizes and ln and off % 2048 == 0 and off + ln <= sizes[idx]:
            r = dict(type=typ, pos=i, idx=idx, off=off, len=ln, ms=ms, alias=_alias_near(z, m.start()))
            if typ == 3:
                r["prime"] = _prime(z, i + 24, ln)
                if r["prime"] is None:
                    continue
            out.append(r)
    return out


# --------------------------------------------------------------------------------------------- audio
def find_ffmpeg():
    for base in (getattr(sys, "_MEIPASS", ""), os.path.dirname(os.path.abspath(sys.argv[0] or "."))):
        p = os.path.join(base, "ffmpeg.exe") if base else ""
        if p and os.path.isfile(p):
            return p
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def riff_channels(riff):
    j = 12
    while j + 8 <= len(riff):
        cid = riff[j:j + 4]
        cl = struct.unpack_from("<I", riff, j + 4)[0]
        if cid == b"fmt ":
            return struct.unpack_from("<H", riff, j + 10)[0]
        j += 8 + cl + (cl & 1)
    return 1


def flac_channels(data):
    if data[:4] != b"fLaC":
        return None
    si = data[8:8 + 34]
    return ((si[12] >> 1) & 7) + 1


_CRC8 = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = ((_c << 1) ^ 0x07) & 0xFF if _c & 0x80 else (_c << 1) & 0xFF
    _CRC8.append(_c)


def _crc8(b):
    c = 0
    for x in b:
        c = _CRC8[c ^ x]
    return c


def _frame_offsets(audio):
    """Posición de cada frame FLAC (tamaño de bloque fijo, número de frame en UTF-8)."""
    offs = []
    n = len(audio)
    a = audio + b"\0" * 16
    i = 0
    expect = 0
    while True:
        j = audio.find(b"\xff\xf8", i)
        if j < 0 or j + 5 >= n:
            break
        b0 = a[j + 4]
        if b0 < 0x80:
            num, ln = b0, 1
        elif b0 >= 0xC0:
            ln = 2 if b0 < 0xE0 else 3 if b0 < 0xF0 else 4 if b0 < 0xF8 else 5 if b0 < 0xFC else 6
            num = b0 & (0x7F >> ln)
            for k in range(1, ln):
                num = (num << 6) | (a[j + 4 + k] & 0x3F)
        else:
            i = j + 1
            continue
        hdr_end = j + 4 + ln
        bs_code = a[j + 2] >> 4
        sr_code = a[j + 2] & 15
        if bs_code == 6:
            hdr_end += 1
        elif bs_code == 7:
            hdr_end += 2
        if sr_code == 12:
            hdr_end += 1
        elif sr_code in (13, 14):
            hdr_end += 2
        if num == expect and hdr_end < n and _crc8(a[j:hdr_end]) == a[hdr_end]:
            offs.append(j)
            expect += 1
            i = j + 8
        else:
            i = j + 1
    return offs


_LUFS = re.compile(r"I:\s+(-?[0-9.]+) LUFS")


def loudness(ffmpeg, path_or_bytes):
    """Sonoridad integrada (EBU R128, con compuerta: ignora silencios). None si es muy corta o muda."""
    inp = "pipe:0" if isinstance(path_or_bytes, (bytes, bytearray)) else path_or_bytes
    r = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", inp, "-af", "aresample=48000,aformat=channel_layouts=mono|stereo,ebur128=framelog=quiet",
                        "-f", "null", "-"], input=path_or_bytes if inp == "pipe:0" else None,
                       capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    m = _LUFS.findall(r.stderr.decode("utf-8", "replace"))
    if not m:
        return None
    v = float(m[-1])
    return v if v > -60 else None


MAX_GAIN_DB = 6.0


def build_flac(ffmpeg, riff, channels, min_ms, tmpdir, tag, min_bytes=0, ref=None):
    """XMA2 de 360 -> FLAC con el formato de los paks de PC. Devuelve (bytes, ms, muestras).

    ref = (pak, posición, tamaño) de la voz original de PC: la latina se iguala a su sonoridad, para que
    cada frase quede con el mismo volumen relativo que el juego de PC espera (radio, gritos, susurros...)."""
    src = os.path.join(tmpdir, tag + ".wav")
    dst = os.path.join(tmpdir, tag + ".flac")
    with open(src, "wb") as f:
        f.write(riff)
    # XMA se pasa de 0 dBFS al decodificar (picos de hasta +2 dB): limitador suave a -0.1 dB, como el
    # máster de PC, para que no cruja; el volumen medio queda igual que el doblaje de España.
    gain = 0.0
    if ref:
        try:
            with open(ref[0], "rb") as f:
                f.seek(ref[1])
                orig = f.read(ref[2])
            lo = loudness(ffmpeg, orig) if orig[:4] == b"fLaC" else None
            ll = loudness(ffmpeg, src) if lo is not None else None
            if lo is not None and ll is not None:
                gain = max(-MAX_GAIN_DB, min(MAX_GAIN_DB, lo - ll))
                if abs(gain) < 0.5:
                    gain = 0.0
        except OSError:
            gain = 0.0
    chain = "aresample=48000,alimiter=limit=0.989:attack=1:release=25:level=0"
    if gain:
        chain = "volume=%.2fdB," % gain + chain
    if min_ms:
        chain += ",apad=whole_dur=%dms" % min_ms
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-af", chain, "-ar", "48000",
           "-ac", str(channels), "-sample_fmt", "s16", "-c:a", "flac", "-frame_size", "1024",
           "-compression_level", "8", "-map_metadata", "-1", "-fflags", "+bitexact",
           "-flags:a", "+bitexact", dst]
    r = subprocess.run(cmd, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError("ffmpeg: " + r.stderr.decode("utf-8", "replace")[:300])
    data = open(dst, "rb").read()
    for p in (src, dst):
        try:
            os.remove(p)
        except OSError:
            pass
    if data[:4] != b"fLaC":
        raise RuntimeError("ffmpeg no produjo FLAC")
    # metadatos originales: nos quedamos solo con STREAMINFO
    i = 4
    streaminfo = None
    while True:
        h = data[i]
        ln = int.from_bytes(data[i + 1:i + 4], "big")
        if (h & 0x7F) == 0:
            streaminfo = bytearray(data[i + 4:i + 4 + ln])
        i += 4 + ln
        if h & 0x80:
            break
    audio = data[i:]
    si = streaminfo
    rate = (si[10] << 12) | (si[11] << 4) | (si[12] >> 4)
    total = ((si[13] & 15) << 32) | struct.unpack(">I", bytes(si[14:18]))[0]
    if rate != 48000 or total == 0:
        raise RuntimeError("STREAMINFO inesperado (rate=%d, muestras=%d)" % (rate, total))
    offs = _frame_offsets(audio)
    expected = (total + 1023) // 1024
    if len(offs) != expected:
        raise RuntimeError("frames FLAC %d != %d" % (len(offs), expected))
    vendor = b"reference libFLAC 1.2.1 20070917"
    vorbis = struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", 0)
    app = b"fsiz" + struct.pack("<I", len(audio))
    seek = b""
    for k in range(0, len(offs), 16):
        seek += struct.pack(">QQH", k * 1024, offs[k], 1024)

    def block(t, body, last=False):
        return bytes([t | (0x80 if last else 0)]) + len(body).to_bytes(3, "big") + body

    head = b"fLaC" + block(0, bytes(streaminfo)) + block(4, vorbis) + block(2, app)
    short = min_bytes - (len(head) + 4 + len(seek) + len(audio))
    if short > 0:
        # las frases con "arranque" necesitan al menos ese tamaño: bloque PADDING de FLAC
        out = head + block(3, seek) + block(1, b"\0" * max(short - 4, 0), last=True) + audio
    else:
        out = head + block(3, seek, last=True) + audio
    return out, int(total * 1000 // 48000), total


# ------------------------------------------------------------------------------------------------- flujo
def _paks(folder, prefix):
    sizes = {}
    for n in os.listdir(folder):
        m = re.match(re.escape(prefix) + r"soundfile(\d+)\.pak$", n, re.I)
        if m:
            sizes[int(m.group(1))] = os.path.getsize(os.path.join(folder, n))
    return sizes


def _level_ffs(folder, prefix):
    out = []
    for n in sorted(os.listdir(folder)):
        if not (n.lower().startswith(prefix) and n.lower().endswith(".ff")):
            continue
        base = n[len(prefix):-3]
        parts = base.split("_")
        if "mp" in parts or base.startswith("mp_") or "streamed" in base:
            continue
        out.append(base)
    return out


def _backup(lang, name):
    bdir = os.path.join(lang, BACKUP_DIR)
    os.makedirs(bdir, exist_ok=True)
    b = os.path.join(bdir, name)
    if not os.path.exists(b):
        tmp = b + ".tmp"
        shutil.copyfile(os.path.join(lang, name), tmp)
        os.replace(tmp, b)
    return b


# ------------------------------------------------------------------------------------------ cinemáticas
# Los videos de historia (<nivel>_load.bik) ya traen todos los doblajes como pistas de audio Bink:
#   0/1 inglés · 6/7 francés · 8/9 italiano · a/b alemán · c/d español latino · e/f español de España
#   10/11 ruso · 12/13 japonés  (estéreo + voz mono por idioma; identificado transcribiendo cada pista:
#   la c/d usa pretérito "fue enlazado / engañé", la e/f pretérito perfecto "ha sido enlazado / he engañado").
# Con el idioma «spanish» el juego de PC reproduce e/f; se copian ahí los paquetes de c/d.
CINE_LATINO = (0x0C, 0x0D)
CINE_ESPANA = (0x0E, 0x0F)
# Grabaciones de audio (audio_log_irs_*.bik): 9 pistas estéreo, una por idioma
#   0 inglés · 1 francés · 2 italiano · 3 alemán · 4 español latino · 5 español de España · 6 ruso · 7 japonés · 8
#   (identificado transcribiendo: 4 y 5 tienen el mismo guion con actores distintos; la 5 pronuncia c/z como θ)
LOG_LATINO, LOG_ESPANA = 4, 5
ROOT_BACKUP = "_raiz"


def bik_parse(d):
    frames = struct.unpack_from("<I", d, 8)[0]
    for base in (0x28, 0x2C):
        nt = struct.unpack_from("<I", d, base)[0]
        if not 0 < nt < 64:
            continue
        maxs = base + 4
        rf = maxs + 4 * nt
        ids = rf + 4 * nt
        idx = ids + 4 * nt
        if idx + 4 > len(d):
            continue
        if struct.unpack_from("<I", d, idx)[0] & ~1 == idx + 4 * (frames + 1):
            return dict(frames=frames, nt=nt, maxs=maxs, rf=rf, idx=idx,
                        ids=list(struct.unpack_from("<%dI" % nt, d, ids)))
    return None


def bik_remux(d, mapping):
    """Copia los paquetes de audio de una pista Bink a otra ({destino: origen}, por índice de pista)."""
    h = bik_parse(d)
    nt = h["nt"]
    nf = h["frames"]
    hdr = bytearray(d[:h["idx"]])
    for dst, src in mapping.items():
        for field in ("maxs", "rf"):
            struct.pack_into("<I", hdr, h[field] + 4 * dst, struct.unpack_from("<I", d, h[field] + 4 * src)[0])
    ent = struct.unpack_from("<%dI" % (nf + 1), d, h["idx"])
    pos = h["idx"] + 4 * (nf + 1)
    offs = []
    parts = []
    largest = 0
    for i in range(nf):
        a = ent[i] & ~1
        b = ent[i + 1] & ~1
        fr = d[a:b]
        p = 0
        packets = []
        for _ in range(nt):
            n = struct.unpack_from("<I", fr, p)[0]
            packets.append(fr[p + 4:p + 4 + n])
            p += 4 + n
        for dst, src in mapping.items():
            packets[dst] = packets[src]
        frame = b"".join(struct.pack("<I", len(x)) + x for x in packets) + fr[p:]
        offs.append(pos | (ent[i] & 1))
        parts.append(frame)
        pos += len(frame)
        largest = max(largest, len(frame))
    offs.append(pos)
    out = bytearray(hdr) + struct.pack("<%dI" % (nf + 1), *offs) + b"".join(parts)
    struct.pack_into("<I", out, 4, len(out) - 8)
    struct.pack_into("<I", out, 12, largest)
    return bytes(out)


def _bik_plan(d):
    h = bik_parse(d)
    if not h:
        return None
    ids = h["ids"]
    if ids == list(range(9)):
        pairs = [(LOG_LATINO, LOG_ESPANA)]
    elif all(t in ids for t in CINE_LATINO + CINE_ESPANA):
        pairs = list(zip(CINE_LATINO, CINE_ESPANA))
    else:
        return None
    rf = [struct.unpack_from("<I", d, h["rf"] + 4 * i)[0] for i in range(h["nt"])]
    plan = {}
    for lat, esp in pairs:
        il, ie = ids.index(lat), ids.index(esp)
        if (rf[il] >> 16) & 0x2000 != (rf[ie] >> 16) & 0x2000:  # mismos canales (estéreo / mono)
            return None
        plan[ie] = il
    return plan


def patch_cinematics(pc):
    lang = os.path.join(pc, LANG_DIR)
    bdir = os.path.join(lang, BACKUP_DIR, ROOT_BACKUP)
    done = 0
    for name in sorted(os.listdir(pc)):
        if not name.lower().endswith(".bik"):
            continue
        b = os.path.join(bdir, name)
        src = b if os.path.exists(b) else os.path.join(pc, name)
        with open(src, "rb") as f:
            head = f.read(1 << 16)
        try:
            plan = _bik_plan(head)
        except (struct.error, ValueError):
            plan = None
        if not plan:
            continue
        if not os.path.exists(b):
            os.makedirs(bdir, exist_ok=True)
            shutil.copyfile(os.path.join(pc, name), b + ".tmp")
            os.replace(b + ".tmp", b)
        data = open(b, "rb").read()
        new = bik_remux(data, plan)
        tmp = os.path.join(pc, name + ".tmp")
        open(tmp, "wb").write(new)
        os.replace(tmp, os.path.join(pc, name))
        done += 1
        log("  %s: cinemática con voces latinas" % name)
    return done


def restore(pc):
    lang = os.path.join(pc, LANG_DIR)
    bdir = os.path.join(lang, BACKUP_DIR)
    if not os.path.isdir(bdir):
        log("No hay respaldo: el juego ya tiene su doblaje original.")
        return 0
    n = 0
    for name in sorted(os.listdir(bdir)):
        if name.endswith(".tmp") or not os.path.isfile(os.path.join(bdir, name)):
            continue
        shutil.copyfile(os.path.join(bdir, name), os.path.join(lang, name + ".tmp"))
        os.replace(os.path.join(lang, name + ".tmp"), os.path.join(lang, name))
        n += 1
    rdir = os.path.join(bdir, ROOT_BACKUP)
    if os.path.isdir(rdir):
        for name in sorted(os.listdir(rdir)):
            if name.endswith(".tmp"):
                continue
            shutil.copyfile(os.path.join(rdir, name), os.path.join(pc, name + ".tmp"))
            os.replace(os.path.join(pc, name + ".tmp"), os.path.join(pc, name))
            n += 1
    st = os.path.join(lang, STATE_FILE)
    if os.path.exists(st):
        os.remove(st)
    log("Doblaje de España restaurado (%d archivos)." % n)
    return 0


# ------------------------------------------------------------------------------------------------ textos
# Menús, ayudas y mensajes: los fastfiles guardan cada texto como (valor, clave) seguidos, sin punteros entre ellos.
# Se cambia cada bloque de textos seguidos por los de 360 SIN cambiar el tamaño total del bloque (el latino suele ser
# más corto: «Abandonaste» / «Has abandonado»), así nada de lo que viene detrás se mueve.
_TXT_PC = re.compile(rb"\xff\xff\xff\xff\xff\xfd\xfd\xfd\xff\xff\xff\xff\xff\xfd\xfd\xfd([^\x00]*)\x00([A-Z][A-Z0-9_]+)\x00", re.S)
_TXT_360 = re.compile(rb"\xff\xff\xff\xff\xff\xff\xff\xff([^\x00]*)\x00([A-Z][A-Z0-9_]+)\x00", re.S)
_TOK = re.compile(rb"&&\d|\[\{[^}]*\}\]|\^\d|\$\([^)]*\)|%[sdi]|\n")
_TXT_SKIP = re.compile(r"^(PLATFORM_|EXE_|PC_)|_PC$|_PC_|KEYBOARD|MOUSE|_KBM")


def textos_360(x360):
    out = {}
    for n in sorted(os.listdir(x360)):
        if n.endswith(".ff") and "mp" not in n:
            try:
                z = zone_360(os.path.join(x360, n))
            except Exception:  # noqa: BLE001
                continue
            for m in _TXT_360.finditer(z):
                v = m.group(1)
                try:
                    v.decode("utf-8")
                except UnicodeDecodeError:
                    v = v.decode("latin-1").encode("utf-8")
                out[m.group(2).decode()] = v
    return out


def _txt_ok(key, old, new):
    if new == old or _TXT_SKIP.search(key):
        return False
    low = new.lower()
    if b"xbox" in low or (b"live" in low and b"live" not in old.lower()):
        return False
    return sorted(_TOK.findall(old)) == sorted(_TOK.findall(new))


def _txt_runs(z):
    runs, cur = [], []
    for m in _TXT_PC.finditer(z):
        if cur and m.start() != cur[-1].end():
            runs.append(cur)
            cur = []
        cur.append(m)
    if cur:
        runs.append(cur)
    return runs


def latin_texts(zone, lat):
    """Devuelve (zona nueva, textos cambiados, textos que no cupieron)."""
    z = bytearray(zone)
    changed = left = 0
    for run in _txt_runs(zone):
        items = []
        for m in run:
            key = m.group(2).decode()
            old = m.group(1)
            new = lat.get(key)
            items.append([m, old, new if new is not None and _txt_ok(key, old, new) else old])
        grow = sorted((it for it in items if len(it[2]) > len(it[1])), key=lambda it: len(it[2]) - len(it[1]))
        saved = sum(len(it[1]) - len(it[2]) for it in items if len(it[2]) < len(it[1]))
        need = sum(len(it[2]) - len(it[1]) for it in grow)
        while need > saved and grow:  # los que más crecen se quedan como estaban
            it = grow.pop()
            need -= len(it[2]) - len(it[1])
            it[2] = it[1]
            left += 1
        pad = saved - need
        for it in items:  # el espacio sobrante se devuelve con espacios al final de los que encogieron
            if pad <= 0:
                break
            short = len(it[1]) - len(it[2])
            if short > 0:
                k = min(short, pad)
                it[2] = it[2] + b" " * k
                pad -= k
        start, end = run[0].start(), run[-1].end()
        body = b"".join(m.group(0)[:16] + new + b"\0" + m.group(2) + b"\0" for m, old, new in items)
        if len(body) != end - start:
            raise ValueError("bloque de textos con tamaño distinto")
        z[start:end] = body
        changed += sum(1 for it in items if it[2].rstrip(b" ") != it[1] and it[2] != it[1])
    return bytes(z), changed, left


def patch_texts(x360, pc):
    lang = os.path.join(pc, LANG_DIR)
    lat = textos_360(x360)
    log("Textos latinos de 360: %d" % len(lat))
    tot = left = 0
    for name in sorted(os.listdir(lang)):
        if not (name.startswith(PC_PREFIX) and name.endswith(".ff")) or "_mp" in name:
            continue
        raw = open(os.path.join(lang, name), "rb").read()
        if raw[:8] != b"S1ffu100":
            continue
        zone = zone_pc(raw)
        new, n, l = latin_texts(zone, lat)
        left += l
        if not n:
            continue
        _backup(lang, name)
        packed = pack_pc(raw, new)
        if zone_pc(packed) != new:
            raise SystemExit("La recompresión de %s no es fiel" % name)
        tmp = os.path.join(lang, name + ".tmp")
        open(tmp, "wb").write(packed)
        os.replace(tmp, os.path.join(lang, name))
        tot += n
        log("  %-28s %4d textos en latino" % (name, n))
    log("Textos: %d cambiados al latino (%d no cabían y siguen igual)" % (tot, left))
    return tot


def restore_texts(pc):
    """Vuelve a poner los textos originales (los del respaldo) sin tocar las voces."""
    lang = os.path.join(pc, LANG_DIR)
    bdir = os.path.join(lang, BACKUP_DIR)
    n_files = 0
    for name in sorted(os.listdir(lang)):
        if not (name.startswith(PC_PREFIX) and name.endswith(".ff")) or "_mp" in name:
            continue
        b = os.path.join(bdir, name)
        if not os.path.exists(b):
            continue
        raw = open(os.path.join(lang, name), "rb").read()
        if raw[:8] != b"S1ffu100":
            continue
        zone = zone_pc(raw)
        orig = {m.group(2): m.group(1) for m in _TXT_PC.finditer(zone_pc(open(b, "rb").read()))}
        z = bytearray(zone)
        touched = False
        for run in _txt_runs(zone):
            body = b"".join(m.group(0)[:16] + orig.get(m.group(2), m.group(1)) + b"\0" + m.group(2) + b"\0" for m in run)
            if len(body) != run[-1].end() - run[0].start():
                raise ValueError("%s: no se pudo restaurar un bloque de textos" % name)
            if body != zone[run[0].start():run[-1].end()]:
                z[run[0].start():run[-1].end()] = body
                touched = True
        if not touched:
            continue
        packed = pack_pc(raw, bytes(z))
        tmp = os.path.join(lang, name + ".tmp")
        open(tmp, "wb").write(packed)
        os.replace(tmp, os.path.join(lang, name))
        n_files += 1
        log("  %s: textos originales" % name)
    return n_files


# ------------------------------------------------------------------------------ voces "cargadas" desde el pak
# Algunas frases de escena (unas 70: Cormack en el cuartel de Sentinel, Gideon en Crash...) usan otra variante:
# el juego carga la frase entera desde el pak al empezar el nivel. En PC: 01 01 ... -1 · 32 ceros · -1 · referencia ·
# -1 · cabecera (frecuencia, tamaño, muestras, banderas, ?, tamaño de arranque). En 360 son voces normales (tipo 2),
# con el nombre del alias justo después.
_PLOAD = re.compile(rb"\x01\x01\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\xff\xfd\xfd\xfd" + b"\x00" * 32 +
                    rb"\xff\xff\xff\xff\xff\xfd\xfd\xfd\x01[\x00\x01][\x00-\x7f]\x00", re.S)


def refs_pc_loaded(z, sizes):
    out = []
    for m in _PLOAD.finditer(z):
        i = m.start() + 56
        idx = struct.unpack_from("<H", z, i + 2)[0]
        off, ln = struct.unpack_from("<QQ", z, i + 8)
        if idx not in sizes or not ln or off % 2048 or off + ln > sizes[idx]:
            continue
        h = i + 32
        rate, hlen, samples = struct.unpack_from("<III", z, h)
        if rate not in (24000, 32000, 44100, 48000) or hlen != ln:
            continue
        vo = z[h + 24:z.find(b"\0", h + 24, h + 200)]
        out.append(dict(pos=i, head=h, idx=idx, off=off, len=ln, alias=_alias_near(z, m.start()),
                        vo=vo.decode("ascii", "replace") if vo.startswith(b"voiceovers/") else None))
    return out


def _x360_by_alias(z3, alias, xs, want_ms=None):
    """Voz de 360 (tipo 2) cuyo alias es `alias`: el nombre va antes y la referencia después.
    Si se da want_ms, se elige la que más se parece en duración (y se exige que cuadre)."""
    best = None
    for mm in re.finditer(rb"(?<=[\x00\xff])" + re.escape(alias.encode()) + rb"\x00", z3):
        p = mm.end()
        m = _P360.search(z3, p, p + 900)
        if m is None or z3[m.start()] != 2:
            continue
        nxt = _ALIAS.search(z3, p, m.start())
        if nxt is not None:  # entre el nombre y la referencia hay otro alias: no es la suya
            continue
        i = m.start() + 4
        idx = struct.unpack_from(">H", z3, i + 2)[0]
        off, ln = struct.unpack_from(">II", z3, i + 4)
        ms = struct.unpack_from(">I", z3, i + 12)[0]
        if idx in xs and ln and off + ln <= xs[idx]:
            cand = (idx, off, ln, ms)
            if want_ms is None:
                return cand
            if best is None or abs(ms - want_ms) < abs(best[3] - want_ms):
                best = cand
    if best is not None and want_ms is not None and abs(best[3] - want_ms) > max(700, 0.35 * want_ms):
        return None
    return best


def _pcm_riff(pcm, ch, rate=48000):
    """WAV PCM de 16 bits a partir de muestras int16 intercaladas."""
    data = pcm.tobytes()
    fmt = struct.pack("<HHIIHH", 1, ch, rate, rate * ch * 2, ch * 2, 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


def build_flac_exact(ffmpeg, riff, ch, size, samples, tmpdir, tag, ref):
    """FLAC con el tamaño EXACTO `size` y exactamente `samples` muestras: el juego reserva la memoria de estas
    frases con los valores originales. Más corta: silencio al final; más larga: un poco más rápida (sin cambiar
    el tono). Si sobra sitio se rellena con un bloque PADDING; si no cabe, se quitan bits bajos (inaudible)."""
    import numpy as np
    src = os.path.join(tmpdir, tag + "_in.wav")
    with open(src, "wb") as f:
        f.write(riff)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run([ffmpeg, "-v", "error", "-i", src, "-ar", "48000", "-ac", str(ch), "-f", "s16le", "-"],
                       capture_output=True, creationflags=flags)
    pcm = np.frombuffer(r.stdout, np.int16)
    n = len(pcm) // ch
    if n > samples * 1.35:
        raise RuntimeError("la latina dura demasiado más (%.1fs / %.1fs)" % (n / 48000, samples / 48000))
    if n > samples:
        tempo = n / samples
        r = subprocess.run([ffmpeg, "-v", "error", "-i", src, "-af", "aresample=48000,atempo=%.6f" % min(tempo, 2.0),
                            "-ar", "48000", "-ac", str(ch), "-f", "s16le", "-"], capture_output=True, creationflags=flags)
        pcm = np.frombuffer(r.stdout, np.int16)
    os.remove(src)
    pcm = pcm[:samples * ch]
    if len(pcm) < samples * ch:
        pcm = np.concatenate([pcm, np.zeros(samples * ch - len(pcm), np.int16)])
    # mismo volumen que la frase original de PC
    try:
        with open(ref[0], "rb") as f:
            f.seek(ref[1])
            orig = f.read(ref[2])
        lo, ll = loudness(ffmpeg, orig), loudness(ffmpeg, _pcm_riff(pcm, ch))
        if lo is not None and ll is not None and abs(lo - ll) >= 0.5:
            g = 10 ** (max(-MAX_GAIN_DB, min(MAX_GAIN_DB, lo - ll)) / 20)
            pcm = np.clip(pcm.astype(np.float32) * g, -32768, 32767).astype(np.int16)
    except OSError:
        pass
    for drop in range(0, 9):
        q = pcm if drop == 0 else (pcm.astype(np.int32) >> drop << drop).astype(np.int16)
        out = build_flac(ffmpeg, _pcm_riff(q, ch), ch, 0, tmpdir, tag + "q%d" % drop, size, None)
        if out[2] != samples:
            raise RuntimeError("muestras %d != %d" % (out[2], samples))
        if len(out[0]) == size:
            return out
    raise RuntimeError("no cabe en %d bytes" % size)


def patch_loaded(x360, pc, jobs=0):
    """Frases de escena cargadas desde el pak: latinas, con el mismo tamaño exacto que las originales."""
    lang = os.path.join(pc, LANG_DIR)
    bdir = os.path.join(lang, BACKUP_DIR)
    ffmpeg = find_ffmpeg()
    xs = _paks(x360, X_PREFIX)
    cur, orig = {}, {}
    for n in os.listdir(lang):
        m = re.match(re.escape(PC_PREFIX) + r"soundfile(\d+)\.pak$", n, re.I)
        if m:
            i = int(m.group(1))
            cur[i] = os.path.getsize(os.path.join(lang, n))
            bp = os.path.join(bdir, n)
            orig[i] = os.path.getsize(bp) if os.path.exists(bp) else cur[i]
    vo360, done_lv, xcache = {}, set(), {}
    work, zones = [], {}
    for name in sorted(os.listdir(lang)):
        if not (name.startswith(PC_PREFIX) and name.endswith(".ff")) or "_mp" in name:
            continue
        raw = open(os.path.join(lang, name), "rb").read()
        if raw[:8] != b"S1ffu100":
            continue
        z = zone_pc(raw)
        refs = refs_pc_loaded(z, cur)
        if not refs:
            continue
        bpath = os.path.join(bdir, name)
        zb = zone_pc(open(bpath, "rb").read()) if os.path.exists(bpath) else z
        ro = {r["vo"]: r for r in refs_pc_loaded(zb, orig)}
        base = name[len(PC_PREFIX):-3]
        level = base[6:] if base.startswith("patch_") else base
        for lv in (level, "patch_" + level, "common", "patch_common"):
            p3 = os.path.join(x360, X_PREFIX + lv + ".ff")
            if lv not in done_lv and os.path.exists(p3):
                done_lv.add(lv)
                vo360.update(voiceovers_360(zone_360(p3), x360, xs, xcache))
        zones[name] = (raw, z, zb)
        for r in refs:
            o = ro.get(r["vo"])
            if o is None:
                continue
            r["orig"] = o  # valores originales (España): pak, posición, tamaño y cabecera
            work.append((name, r, r["vo"] if r["vo"] in vo360 else None))
    if not work:
        log("Voces cargadas: nada que cambiar")
        return 0
    tmpdir = tempfile.mkdtemp(prefix="reforge_aw_")
    tasks = {}
    for name, r, vo in work:
        if vo is None or (vo, r["orig"]["len"]) in tasks:
            continue
        o = r["orig"]
        pak = os.path.join(lang, "%ssoundfile%d.pak" % (PC_PREFIX, o["idx"]))
        with open(pak, "rb") as fp:
            fp.seek(o["off"])
            ch = flac_channels(fp.read(64)) or riff_channels(vo360[vo])
        want = struct.unpack_from("<I", zones[name][2], o["head"] + 8)[0]
        tasks[(vo, o["len"])] = (vo360[vo], ch, o["len"], want, (pak, o["off"], o["len"]))
    results = {}
    with concurrent.futures.ThreadPoolExecutor(jobs or max(2, (os.cpu_count() or 4) - 1)) as ex:
        futs = {ex.submit(build_flac_exact, ffmpeg, t[0], t[1], t[2], t[3], tmpdir, "l%d" % n, t[4]): k
                for n, (k, t) in enumerate(tasks.items())}
        for fu in concurrent.futures.as_completed(futs):
            try:
                results[futs[fu]] = fu.result()
            except RuntimeError as e:
                log("  %s: %s" % (futs[fu][0], e))
    shutil.rmtree(tmpdir, ignore_errors=True)
    placed, by_pak = {}, {}
    for name, r, vo in work:
        k = (vo, r["orig"]["len"])
        if vo is None or k not in results:
            continue
        want = struct.unpack_from("<I", zones[name][2], r["orig"]["head"] + 8)[0]
        got = results[k][2]
        if abs(got - want) > max(48000 * 0.8, 0.4 * want):
            log("  %s: %s no cuadra en duración, se deja la original" % (name, r["alias"]))
            continue
        by_pak.setdefault(r["orig"]["idx"], set()).add(k)
    for idx, keys in sorted(by_pak.items()):
        pn = "%ssoundfile%d.pak" % (PC_PREFIX, idx)
        _backup(lang, pn)
        with open(os.path.join(lang, pn), "r+b") as f:
            f.seek(0, 2)
            pos = f.tell()
            for k in sorted(keys):
                data, ms, samples = results[k]
                pad = (-pos) % 2048
                f.write(b"\0" * pad)
                pos += pad
                placed[(idx, k)] = (pos, len(data), samples)
                f.write(data)
                pos += len(data)
            f.write(b"\0" * ((-pos) % 2048))
    n = 0
    for name, (raw, z, zb) in zones.items():
        out = bytearray(z)
        changed = 0
        for nm, r, vo in work:
            if nm != name:
                continue
            o = r["orig"]
            # se parte siempre de la entrada original completa (deshace cualquier versión anterior)
            out[r["pos"]:r["head"] + 24] = zb[o["pos"]:o["head"] + 24]
            k = (vo, o["len"])
            if (o["idx"], k) in placed:
                off, ln, samples = placed[(o["idx"], k)]
                if ln != o["len"]:
                    raise SystemExit("tamaño distinto en %s" % vo)
                struct.pack_into("<Q", out, r["pos"] + 8, off)
                struct.pack_into("<I", out, r["head"] + 8, samples)
                changed += 1
        if bytes(out) == z:
            continue
        _backup(lang, name)
        packed = pack_pc(raw, bytes(out))
        if zone_pc(packed) != bytes(out):
            raise SystemExit("La recompresión de %s no es fiel" % name)
        tmp = os.path.join(lang, name + ".tmp")
        open(tmp, "wb").write(packed)
        os.replace(tmp, os.path.join(lang, name))
        n += changed
        log("  %-26s %3d frases de escena cargadas en latino (mismo tamaño)" % (name, changed))
    log("Voces cargadas: %d en latino" % n)
    return n


def riff_xma2(data, ch, rate):
    """Envuelve XMA2 crudo (frases cargadas dentro de los fastfiles de 360) en un RIFF que ffmpeg entiende."""
    fmt = struct.pack("<HHIIHHH", 0x166, ch, rate, rate * ch * 2 // 8, 2 * ch, 16, 34)
    fmt += struct.pack("<HIIIIIIIBBH", 1, 0 if ch == 1 else 3, 0, max(len(data), 2048), 0, 0, 0, 0, 0, 4, 1)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


_VO = re.compile(rb"voiceovers/[a-z0-9_/]+\x00")


def voiceovers_360(z, x360, xs, cache):
    """Frases de escena de 360 por nombre ("voiceovers/<nivel>/<frase>") -> RIFF XMA2."""
    out = {}
    for m in _VO.finditer(z):
        i = m.start()
        name = z[i:m.end() - 1].decode()
        h = z[i - 56:i]
        if len(h) < 56:
            continue
        rate = struct.unpack_from(">H", h, 36)[0]
        ch = h[38]
        if rate not in (22050, 24000, 32000, 44100, 48000) or ch not in (1, 2):
            continue
        loc, idx = h[4], struct.unpack_from(">H", h, 6)[0]
        off, ln = struct.unpack_from(">II", h, 8)
        if loc == 1 and idx in xs and ln and off + ln <= xs[idx]:
            f = cache.get(idx)
            if f is None:
                f = cache[idx] = open(os.path.join(x360, "%ssoundfile%d.pak" % (X_PREFIX, idx)), "rb").read()
            riff = f[off:off + ln]
            if riff[:4] == b"RIFF":
                out[name] = riff
                continue
        size = struct.unpack_from(">I", h, 52)[0]
        if 0 < size <= 4 << 20 and m.end() + size <= len(z):
            out[name] = riff_xma2(z[m.end():m.end() + size], ch, rate)
    return out


def _prime_name(z, r):
    h, q, size = r["prime"]
    return z[h + 24:q].split(b"\0")[0].decode("ascii", "replace")


def install(x360, pc, jobs=0, dry=False, progress=lambda done, total: None):
    t0 = time.time()
    lang = os.path.join(pc, LANG_DIR)
    if not os.path.isdir(lang):
        raise SystemExit("No encuentro %s (¿es la carpeta del juego de PC?)" % lang)
    if not os.path.isdir(x360):
        raise SystemExit("No encuentro la carpeta de 360 %s" % x360)
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise SystemExit("Falta ffmpeg (pip install imageio-ffmpeg)")
    bdir = os.path.join(lang, BACKUP_DIR)

    def pc_src(name):
        b = os.path.join(bdir, name)
        return b if os.path.exists(b) else os.path.join(lang, name)

    xs = _paks(x360, X_PREFIX)
    ps = {}
    for n in os.listdir(lang):
        m = re.match(re.escape(PC_PREFIX) + r"soundfile(\d+)\.pak$", n, re.I)
        if m:
            ps[int(m.group(1))] = os.path.getsize(pc_src(n))
    log("Paks de voz: 360=%d · PC=%d" % (len(xs), len(ps)))

    xcache = {}
    levels = [b for b in _level_ffs(x360, X_PREFIX) if os.path.exists(os.path.join(lang, PC_PREFIX + b + ".ff"))]
    mapping = {}      # ("s", idx_pc, off_pc) -> RIFF de 360 (voz por streaming)
    vo360 = {}        # "voiceovers/..." -> RIFF de 360 (frases de escena)
    plans = {}        # nombre .ff -> lista de (registro PC, clave)
    zones = {}
    skipped = []
    alias_keys = {}   # (nivel, alias) -> [claves] (para los parches de PC)
    x_alias = {}      # (nivel, alias) -> voces de 360 (líneas que PC solo trae en su parche)
    pc_len = {}
    for base in levels:
        z3 = zone_360(os.path.join(x360, X_PREFIX + base + ".ff"))
        vo360.update(voiceovers_360(z3, x360, xs, xcache))
        r3 = [r for r in refs_360(z3, xs) if r["type"] == 2]
        zp = zone_pc(open(pc_src(PC_PREFIX + base + ".ff"), "rb").read())
        rall = refs_pc(zp, ps)
        rp = [r for r in rall if r["type"] == 2]
        plan = []
        if rp:
            ok = len(r3) == len(rp) and all(a["idx"] == b["idx"] for a, b in zip(r3, rp))
            same = sum(1 for a, b in zip(r3, rp) if a["alias"] and a["alias"] == b["alias"])
            named = sum(1 for a, b in zip(r3, rp) if a["alias"] and b["alias"])
            if not ok or (named and same < named * 0.9):
                skipped.append(base)
                log("  %-16s distinto entre versiones (360=%d, PC=%d): voces de streaming sin cambiar"
                    % (base, len(r3), len(rp)))
            else:
                for a, b in zip(r3, rp):
                    k = ("s", b["idx"], b["off"])
                    riff = xcache.get(a["idx"])
                    if riff is None:
                        riff = xcache[a["idx"]] = open(os.path.join(
                            x360, "%ssoundfile%d.pak" % (X_PREFIX, a["idx"])), "rb").read()
                    mapping.setdefault(k, (a["idx"], a["off"], a["len"], a["ms"]))
                    pc_len[k] = b["len"]
                    x_alias.setdefault((base, a["alias"]), []).append((a["idx"], a["off"], a["len"], a["ms"]))
                    plan.append((b, k))
                    alias_keys.setdefault((base, b["alias"]), []).append(k)
        zones[PC_PREFIX + base + ".ff"] = zp
        plans[PC_PREFIX + base + ".ff"] = plan
    # frases de escena (tipo 3) en los niveles y en los parches de PC; voces cambiadas por los parches de PC
    nprime = 0
    for base in levels + ["patch_" + b for b in levels]:
        name = PC_PREFIX + base + ".ff"
        if not os.path.exists(os.path.join(lang, name)):
            continue
        zp = zones.get(name)
        if zp is None:
            raw = open(pc_src(name), "rb").read()
            if raw[:8] != b"S1ffu100":
                continue
            zp = zones[name] = zone_pc(raw)
        plan = plans.setdefault(name, [])
        level = base[6:] if base.startswith("patch_") else None
        seen = {}
        for r in refs_pc(zp, ps):
            if r["type"] == 3:
                vo = _prime_name(zp, r)
                if vo in vo360:
                    plan.append((r, ("p", vo, r["idx"])))
                    nprime += 1
            elif level is not None:
                keys = alias_keys.get((level, r["alias"]))
                n = seen.get(r["alias"], 0)
                seen[r["alias"]] = n + 1
                if keys:
                    plan.append((r, keys[min(n, len(keys) - 1)]))
                else:
                    xl = x_alias.get((level, r["alias"]))
                    if not xl:
                        z3 = zone_360(os.path.join(x360, X_PREFIX + level + ".ff"))
                        for a in refs_360(z3, xs):
                            if a["type"] == 2:
                                x_alias.setdefault((level, a["alias"]), [])
                        for a in refs_360(z3, xs):
                            if a["type"] == 2 and a["alias"] == r["alias"]:
                                x_alias[(level, a["alias"])].append((a["idx"], a["off"], a["len"], a["ms"]))
                        xl = x_alias.get((level, r["alias"]))
                    if xl:
                        k = ("s", r["idx"], r["off"])
                        if xl[0][0] not in xcache:
                            xcache[xl[0][0]] = open(os.path.join(
                                x360, "%ssoundfile%d.pak" % (X_PREFIX, xl[0][0])), "rb").read()
                        mapping.setdefault(k, xl[min(n, len(xl) - 1)])
                        pc_len[k] = r["len"]
                        plan.append((r, k))
    for name, plan in sorted(plans.items()):
        if plan:
            log("  %-22s %4d voces" % (name, len(plan)))
    if not mapping:
        raise SystemExit("No se encontró ninguna voz que emparejar.")
    log("Voces únicas: %d de streaming · %d frases de escena" % (len(mapping), len(vo360)))
    if dry:
        return 0

    # ---- convertir
    pcf = {}

    def pc_channels(idx, off):
        f = pcf.get(idx)
        if f is None:
            f = pcf[idx] = open(pc_src("%ssoundfile%d.pak" % (PC_PREFIX, idx)), "rb")
        f.seek(off)
        return flac_channels(f.read(64))

    refs_of = {k: (pc_src("%ssoundfile%d.pak" % (PC_PREFIX, k[1])), k[2], pc_len[k]) for k in mapping}
    tasks = {}
    for k, (xi, xo, xl, xms) in mapping.items():
        riff = xcache[xi][xo:xo + xl]
        if riff[:4] != b"RIFF":
            raise SystemExit("Voz de 360 sin cabecera RIFF en sna_soundfile%d.pak:%d" % (xi, xo))
        tasks[k] = (riff, pc_channels(k[1], k[2]) or riff_channels(riff), xms, 0, refs_of.get(k))
    for name, plan in plans.items():
        for r, k in plan:
            if k[0] == "p" and k not in tasks:
                h, q, size = r["prime"]
                ch = zones[name][h + 12]
                riff = vo360[k[1]]
                tasks[k] = (riff, ch if ch in (1, 2) else riff_channels(riff), 0, size,
                            (pc_src("%ssoundfile%d.pak" % (PC_PREFIX, r["idx"])), r["off"], r["len"]))
    for f in pcf.values():
        f.close()
    tmpdir = tempfile.mkdtemp(prefix="reforge_aw_")
    results = {}
    workers = jobs or max(2, (os.cpu_count() or 4) - 1)
    with concurrent.futures.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(build_flac, ffmpeg, riff, ch, ms, tmpdir, "t%d" % n, mb, ref): k
                for n, (k, (riff, ch, ms, mb, ref)) in enumerate(tasks.items())}
        for n, fu in enumerate(concurrent.futures.as_completed(futs), 1):
            results[futs[fu]] = fu.result()
            progress(n, len(futs))
            if n % 500 == 0 or n == len(futs):
                log("  convertidas %d/%d" % (n, len(futs)))
    shutil.rmtree(tmpdir, ignore_errors=True)

    # ---- añadir al final de cada pak (lo original queda intacto)
    new_ref = {}
    by_pak = {}
    for k in results:
        by_pak.setdefault(k[1] if k[0] == "s" else k[2], []).append(k)
    for idx in sorted(by_pak):
        name = "%ssoundfile%d.pak" % (PC_PREFIX, idx)
        src = _backup(lang, name)
        dst = os.path.join(lang, name + ".tmp")
        shutil.copyfile(src, dst)
        with open(dst, "r+b") as f:
            f.seek(0, 2)
            pos = f.tell()
            for k in sorted(by_pak[idx], key=str):
                data, ms, samples = results[k]
                pad = (-pos) % 2048
                f.write(b"\0" * pad)
                pos += pad
                new_ref[k] = (idx, pos, len(data), ms)
                f.write(data)
                pos += len(data)
            f.write(b"\0" * ((-pos) % 2048))
        os.replace(dst, os.path.join(lang, name))
        log("  %s +%d voces latinas" % (name, len(by_pak[idx])))

    # ---- reescribir los fastfiles
    for name, plan in sorted(plans.items()):
        if not plan:
            continue
        src = _backup(lang, name)
        raw = open(src, "rb").read()
        zone = bytearray(zones[name])
        for r, k in plan:
            idx, off, ln, ms = new_ref[k]
            p = r["pos"]
            struct.pack_into("<H", zone, p + 2, idx)
            struct.pack_into("<QQ", zone, p + 8, off, ln)
            if r["type"] == 2:
                struct.pack_into("<I", zone, p + 24, ms)
            else:
                h, q, size = r["prime"]
                data, _ms, samples = results[k]
                struct.pack_into("<II", zone, h + 4, ln, samples)
                zone[q:q + size] = data[:size]
        packed = pack_pc(raw, bytes(zone))
        if zone_pc(packed) != bytes(zone):
            raise SystemExit("La recompresión de %s no es fiel" % name)
        tmp = os.path.join(lang, name + ".tmp")
        open(tmp, "wb").write(packed)
        os.replace(tmp, os.path.join(lang, name))
    log("Voces cargadas:")
    patch_loaded(x360, pc, jobs)
    log("Cinemáticas:")
    cines = patch_cinematics(pc)
    nv = sum(len(p) for p in plans.values())
    state = dict(version=VERSION, x360=x360, referencias=nv, voces=len(results), frases_escena=nprime,
                 archivos=sorted(n for n, p in plans.items() if p), omitidos=skipped, cinematicas=cines,
                 fecha=time.strftime("%Y-%m-%d %H:%M"))
    json.dump(state, open(os.path.join(lang, STATE_FILE), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    log("Listo: %d voces latinas (%d frases de escena) y %d cinemáticas (%.0f s)."
        % (len(results), nprime, cines, time.time() - t0))
    log("En el juego elige el idioma «Español» (spanish). Para volver al doblaje de España: --restaurar")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--x360", help="carpeta spanishna de la versión de Xbox 360")
    ap.add_argument("--pc", required=True, help="carpeta del juego de PC")
    ap.add_argument("--restaurar", action="store_true", help="volver al doblaje de España")
    ap.add_argument("--analizar", action="store_true", help="solo emparejar, sin cambiar nada")
    ap.add_argument("--solo-cinematicas", action="store_true", help="solo los videos de historia")
    ap.add_argument("--solo-textos", action="store_true", help="(experimental) menús y ayudas")
    ap.add_argument("--solo-cargadas", action="store_true", help="solo las frases de escena cargadas desde el pak")
    ap.add_argument("--hilos", type=int, default=0)
    a = ap.parse_args(argv)
    if a.restaurar:
        return restore(a.pc)
    if a.solo_cinematicas:
        log("Listo: %d cinemáticas con voces latinas." % patch_cinematics(a.pc))
        return 0
    if not a.x360:
        ap.error("falta --x360")
    if a.solo_cargadas:
        patch_loaded(a.x360, a.pc, a.hilos)
        return 0
    if a.solo_textos:
        patch_texts(a.x360, a.pc)
        return 0
    return install(a.x360, a.pc, a.hilos, a.analizar)


if __name__ == "__main__":
    sys.exit(main())
