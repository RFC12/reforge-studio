"""Icono del juego para el .exe recompilado.

Cada XEX lleva dentro su base de datos XDBF (recurso con el nombre del Title ID), y en ella la imagen
oficial del título (sección «imagen», id 0x8000: el PNG de 64×64 que la consola muestra en el menú y en
el Marketplace). ReForge la saca así, de la más directa a la de respaldo:

1. Del propio default.xex: si está sin comprimir o con compresión «básica» (la mayoría de juegos de disco
   y muchos arcade) se descifra con AES-CBC solo el trozo del recurso, sin tocar el resto.
2. De «reforge_image.bin» (la imagen del juego ya cargada que la extensión ReForge deja junto al .exe al
   abrirlo): sirve para los XEX con compresión LZX, tras la primera partida.
3. Si el juego no trae imagen, un icono generado con las iniciales del título (nunca el genérico de Windows).

Luego arma un .ico (16–256 px, entradas PNG) y lo graba como recurso del .exe con la API de Windows
(BeginUpdateResource/UpdateResource), conservando la fecha del .exe para no disparar recompilaciones.
"""
import json
import os
import struct
import sys

from .xexpatch import _INV, _SBOX, _expand, _mul, _opt_headers, base_info, session_key  # noqa: F401

KEY_RESOURCE_INFO = 0x000002FF
KEY_FILE_FORMAT = 0x000003FF
XDBF_SECTION_IMAGE = 2
XDBF_ID_TITLE = 0x8000
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
MARK_FILE = "reforge_icon.json"
PNG_FILE = "reforge_icon.png"
ICO_FILE = "reforge_icon.ico"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------- AES-128 descifrado rápido (tablas)
_M9 = [_mul(i, 9) for i in range(256)]
_M11 = [_mul(i, 11) for i in range(256)]
_M13 = [_mul(i, 13) for i in range(256)]
_M14 = [_mul(i, 14) for i in range(256)]
_ISR = [(c * 4 + r - r * 4) % 16 for c in range(4) for r in range(4)]


class _Aes:
    def __init__(self, key):
        self.rk = _expand(key)

    def decrypt(self, block):
        rk = self.rk
        s = [b ^ k for b, k in zip(block, rk[10])]
        for rnd in range(9, -1, -1):
            s = [_INV[s[i]] for i in _ISR]
            s = [b ^ k for b, k in zip(s, rk[rnd])]
            if rnd:
                t = []
                for c in range(0, 16, 4):
                    a0, a1, a2, a3 = s[c], s[c + 1], s[c + 2], s[c + 3]
                    t += [_M14[a0] ^ _M11[a1] ^ _M13[a2] ^ _M9[a3], _M9[a0] ^ _M14[a1] ^ _M11[a2] ^ _M13[a3],
                          _M13[a0] ^ _M9[a1] ^ _M14[a2] ^ _M11[a3], _M11[a0] ^ _M13[a1] ^ _M9[a2] ^ _M14[a3]]
                s = t
        return bytes(s)


class _ImageReader:
    """Lee bytes de la imagen del juego directamente del XEX (sin compresión o compresión básica)."""

    def __init__(self, xex, devkit=False):
        self.x = xex
        info = base_info(xex)
        self.header_size = info["header_size"]
        self.image_size = info["image_size"]
        hdr = _opt_headers(xex)
        ff = hdr.get(KEY_FILE_FORMAT)
        if not ff:
            raise ValueError("XEX sin información de formato")
        info_size, enc, comp = struct.unpack_from(">IHH", xex, ff)
        self.aes = _Aes(session_key(info, devkit)) if enc else None
        if comp == 0:          # sin compresión: la imagen es el flujo de datos tal cual
            self.blocks = [(self.image_size, 0)]
        elif comp == 1:        # básica: bloques (datos, ceros)
            n = max(0, (info_size - 8) // 8)
            self.blocks = [struct.unpack_from(">II", xex, ff + 8 + i * 8) for i in range(n)]
        else:
            raise ValueError("XEX con compresión LZX")

    def _stream(self, off, n):
        """Bytes [off, off+n) del flujo de datos (descifrados si hace falta)."""
        base = self.header_size
        if not self.aes:
            return self.x[base + off: base + off + n]
        a = off & ~15
        b = (off + n + 15) & ~15
        out = bytearray()
        prev = self.x[base + a - 16: base + a] if a else bytes(16)
        for p in range(a, b, 16):
            blk = self.x[base + p: base + p + 16]
            if len(blk) < 16:
                break
            out += bytes(x ^ y for x, y in zip(self.aes.decrypt(blk), prev))
            prev = blk
        return bytes(out[off - a: off - a + n])

    def read(self, off, n):
        out = bytearray()
        img = stream = 0
        for data, zero in self.blocks:
            for length, is_data in ((data, True), (zero, False)):
                lo, hi = max(off, img), min(off + n, img + length)
                if lo < hi:
                    out += self._stream(stream + lo - img, hi - lo) if is_data else bytes(hi - lo)
                img += length
                if is_data:
                    stream += length
            if img >= off + n:
                break
        return bytes(out)


# ---------------------------------------------------------------- XDBF
def resource_entries(xex):
    r = _opt_headers(xex).get(KEY_RESOURCE_INFO)
    if not r:
        return []
    size = struct.unpack_from(">I", xex, r)[0]
    out = []
    for i in range(max(0, (size - 4) // 16)):
        p = r + 4 + i * 16
        name = xex[p:p + 8].split(b"\0")[0].decode("latin-1", "replace")
        addr, length = struct.unpack_from(">II", xex, p + 8)
        out.append((name, addr, length))
    return out


def _xdbf_title_image(read, length):
    """PNG de la imagen del título dentro de un XDBF; read(off, n) lee relativo al inicio del XDBF."""
    head = read(0, 0x18)
    if len(head) < 0x18 or head[:4] != b"XDBF":
        return b""
    _ver, ent_len, ent_count, free_len, _free_count = struct.unpack_from(">IIIII", head, 4)
    if ent_count > 4096 or ent_len > 4096:
        return b""
    table = read(0x18, ent_count * 18)
    data_start = 0x18 + ent_len * 18 + free_len * 8
    for i in range(ent_count):
        sec, eid, off, size = struct.unpack_from(">HQII", table, i * 18)
        if sec == XDBF_SECTION_IMAGE and eid == XDBF_ID_TITLE and 0 < size < 4 << 20 \
                and data_start + off + size <= length:
            png = read(data_start + off, size)
            return png if png.startswith(PNG_MAGIC) else b""
    return b""


def _pick_resource(entries, title_id):
    for name, addr, length in entries:
        if name.upper() == title_id.upper():
            return addr, length
    for name, addr, length in entries:   # algunos lo nombran distinto: el que tenga cara de Title ID
        if len(name) == 8 and all(c in "0123456789ABCDEFabcdef" for c in name):
            return addr, length
    return None


def title_png(xex_path, image_bin=""):
    """(png, origen) con la imagen oficial del juego, o (b"", "") si no se puede sacar."""
    try:
        with open(xex_path, "rb") as f:
            xex = f.read()
        info = base_info(xex)
    except (OSError, ValueError, struct.error, Exception):     # noqa: BLE001
        return b"", ""
    tid = f"{info['title_id']:08X}"
    res = _pick_resource(resource_entries(xex), tid)
    if not res:
        return b"", ""
    addr, length = res
    off = addr - info["load_address"]
    if off < 0:
        return b"", ""
    for devkit in (False, True):
        try:
            reader = _ImageReader(xex, devkit)
        except ValueError:
            break
        except Exception:        # noqa: BLE001
            break
        try:
            png = _xdbf_title_image(lambda o, n: reader.read(off + o, n), length)
        except (struct.error, IndexError):
            png = b""
        if png:
            return png, "xex"
        if not reader.aes:
            break
    if image_bin and os.path.isfile(image_bin):
        try:
            with open(image_bin, "rb") as f:
                def rd(o, n):
                    f.seek(off + o)
                    return f.read(n)
                png = _xdbf_title_image(rd, length)
        except (OSError, struct.error):
            png = b""
        if png:
            return png, "imagen"
    return b"", ""


# ---------------------------------------------------------------- .ico
def _qt():
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QImage
    return QBuffer, QByteArray, QIODevice, Qt, QImage


def _png_bytes(img):
    QBuffer, QByteArray, QIODevice, _Qt, _QImage = _qt()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba.data())


def build_ico(png, sizes=ICON_SIZES):
    """ICO con una entrada PNG por tamaño (Windows Vista+ las acepta)."""
    _QBuffer, _QByteArray, _QIODevice, Qt, QImage = _qt()
    src = QImage.fromData(png)
    if src.isNull():
        raise ValueError("Imagen no válida")
    src = src.convertToFormat(QImage.Format.Format_ARGB32)
    images = []
    for s in sizes:
        img = src.scaled(s, s, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        images.append((s, _png_bytes(img)))
    return pack_ico(images)


def pack_ico(images):
    out = struct.pack("<HHH", 0, 1, len(images))
    off = 6 + 16 * len(images)
    body = b""
    for s, data in images:
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), off + len(body))
        body += data
    return out + body


def parse_ico(ico):
    """[(ancho, alto, colores, reservado, planos, bits, datos)] de un .ico."""
    _r, _t, n = struct.unpack_from("<HHH", ico, 0)
    out = []
    for i in range(n):
        w, h, c, r, planes, bits, size, off = struct.unpack_from("<BBBBHHII", ico, 6 + i * 16)
        out.append((w, h, c, r, planes, bits, ico[off:off + size]))
    return out


def fallback_png(title, size=256):
    """Icono de respaldo: iniciales del juego sobre un degradado con el color que sale de su nombre."""
    import hashlib

    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath
    words = [w for w in "".join(c if c.isalnum() else " " for c in title or "").split() if w]
    initials = ("".join(w[0] for w in words[:2]) or "RF").upper()
    hue = int(hashlib.md5((title or "reforge").encode("utf-8")).hexdigest()[:4], 16) % 360
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor.fromHsv(hue, 170, 235))
    g.setColorAt(1, QColor.fromHsv((hue + 40) % 360, 220, 120))
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.2, size * 0.2)
    p.fillPath(path, g)
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None:      # sin aplicación Qt no hay fuentes: solo el degradado
        p.end()
        return _png_bytes(img)
    f = QFont("Segoe UI", 1)
    f.setBold(True)
    f.setPixelSize(int(size * (0.46 if len(initials) > 1 else 0.58)))
    p.setFont(f)
    p.setPen(QColor(255, 255, 255))
    p.drawText(QRectF(0, 0, size, size), int(Qt.AlignmentFlag.AlignCenter), initials)
    p.end()
    return _png_bytes(img)


# ---------------------------------------------------------------- grabar en el .exe (Windows)
RT_ICON = 3
RT_GROUP_ICON = 14
ICON_GROUP_ID = 1
ICON_FIRST_ID = 1


def _group_entry(w, h, c, r, planes, bits, data, rid):
    return struct.pack("<BBBBHHIH", w, h, c, r, planes, bits, len(data), rid)


def embed_icon(exe, ico):
    """Graba el .ico como icono principal del .exe; conserva la fecha del archivo. Devuelve True si pudo."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.BeginUpdateResourceW.restype = wintypes.HANDLE
    k32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    k32.UpdateResourceW.restype = wintypes.BOOL
    k32.UpdateResourceW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD,
                                    ctypes.c_void_p, wintypes.DWORD]
    k32.EndUpdateResourceW.restype = wintypes.BOOL
    k32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    entries = parse_ico(ico)
    st = os.stat(exe)
    h = k32.BeginUpdateResourceW(exe, False)
    if not h:
        return False
    ok = True
    group = struct.pack("<HHH", 0, 1, len(entries))
    for i, (w, hh, c, r, planes, bits, data) in enumerate(entries):
        rid = ICON_FIRST_ID + i
        buf = ctypes.create_string_buffer(data, len(data))
        ok &= bool(k32.UpdateResourceW(h, RT_ICON, rid, 0, buf, len(data)))
        group += _group_entry(w, hh, c, r, planes, bits, data, rid)
    gbuf = ctypes.create_string_buffer(group, len(group))
    ok &= bool(k32.UpdateResourceW(h, RT_GROUP_ICON, ICON_GROUP_ID, 0, gbuf, len(group)))
    if not k32.EndUpdateResourceW(h, not ok):
        return False
    if ok:
        try:
            os.utime(exe, ns=(st.st_atime_ns, st.st_mtime_ns))
        except OSError:
            pass
        try:   # que el Explorador olvide el icono viejo que tenía en caché
            ctypes.WinDLL("shell32").SHChangeNotify(0x08000000, 0, None, None)   # SHCNE_ASSOCCHANGED
        except Exception:      # noqa: BLE001
            pass
    return ok


# ---------------------------------------------------------------- todo junto
def _mark(exe):
    return os.path.join(os.path.dirname(exe), MARK_FILE)


def _read_mark(exe):
    try:
        with open(_mark(exe), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def ensure(exe, root, title="", force=False):
    """Pone al .exe el icono del juego si no lo tiene ya (o si ahora hay uno mejor). Devuelve un texto
    corto con lo hecho, o "" si no hizo falta. No lanza excepciones: el icono nunca impide jugar."""
    try:
        return _ensure(exe, root, title, force)
    except Exception as e:     # noqa: BLE001
        return f"icono no aplicado ({e})"


def _ensure(exe, root, title, force):
    if not exe or not os.path.isfile(exe):
        return ""
    xex = os.path.join(root, "assets", "default.xex")
    mark = _read_mark(exe)
    mtime = int(os.path.getmtime(exe))
    if not force and mark.get("exe_mtime") == mtime and mark.get("source") in ("xex", "imagen"):
        return ""
    image_bin = os.path.join(os.path.dirname(exe), "reforge_image.bin")
    png, source = title_png(xex, image_bin) if os.path.isfile(xex) else (b"", "")
    if not png:
        if not force and mark.get("exe_mtime") == mtime and mark.get("source") == "iniciales":
            return ""
        png, source = fallback_png(title or os.path.basename(root).replace("_", " ").title()), "iniciales"
    ico = build_ico(png)
    folder = os.path.dirname(exe)
    with open(os.path.join(folder, PNG_FILE), "wb") as f:
        f.write(png)
    with open(os.path.join(folder, ICO_FILE), "wb") as f:
        f.write(ico)
    try:   # copia junto al proyecto: la Biblioteca y los accesos directos la pueden usar
        with open(os.path.join(root, PNG_FILE), "wb") as f:
            f.write(png)
    except OSError:
        pass
    if not embed_icon(exe, ico):
        return "icono guardado (no se pudo grabar en el .exe: ¿está abierto?)" if sys.platform == "win32" else ""
    with open(_mark(exe), "w", encoding="utf-8") as f:
        json.dump({"exe_mtime": int(os.path.getmtime(exe)), "source": source}, f)
    return {"xex": "icono oficial del juego aplicado al .exe",
            "imagen": "icono oficial del juego aplicado al .exe (sacado de la partida)",
            "iniciales": "el juego no trae imagen: icono con sus iniciales aplicado al .exe"}[source]


def dominant_color(root):
    """(r, g, b) del color más característico del icono del juego (reforge_icon.png / imagen del XEX), o None.

    Elige el píxel más vivo (mayor saturación × brillo) entre los opacos: así coge el color de marca del
    juego (el rojo de Asura, el verde de un logo…) y evita negros, blancos y grises de fondo."""
    import os
    data = None
    png = os.path.join(root, PNG_FILE)
    if os.path.isfile(png):
        try:
            with open(png, "rb") as f:
                data = f.read()
        except OSError:
            data = None
    if not data:
        xex = os.path.join(root, "assets", "default.xex")
        if os.path.isfile(xex):
            try:
                data, _src = title_png(xex)
            except Exception:      # noqa: BLE001
                data = None
    if not data:
        return None
    try:
        _QBuffer, _QByteArray, _QIODevice, _Qt, QImage = _qt()
        img = QImage.fromData(data)
        if img.isNull():
            return None
        img = img.convertToFormat(QImage.Format.Format_ARGB32).scaled(24, 24)
        best, best_score = None, -1
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if c.alpha() < 128:
                    continue
                _h, s, v, _a = c.getHsv()
                score = s * v
                if score > best_score:
                    best_score, best = score, (c.red(), c.green(), c.blue())
        return best
    except Exception:      # noqa: BLE001
        return None


def write_ico(root, dest):
    """Guarda el icono del juego como .ico en `dest` (para accesos directos). True si pudo."""
    import os
    data = None
    png = os.path.join(root, PNG_FILE)
    if os.path.isfile(png):
        try:
            with open(png, "rb") as f:
                data = f.read()
        except OSError:
            data = None
    if not data:
        xex = os.path.join(root, "assets", "default.xex")
        if os.path.isfile(xex):
            try:
                data, _src = title_png(xex)
            except Exception:      # noqa: BLE001
                data = None
    if not data:
        return False
    try:
        _QBuffer, _QByteArray, _QIODevice, _Qt, QImage = _qt()
        img = QImage.fromData(data)
        if img.isNull():
            return False
        if img.width() > 256 or img.height() > 256:
            img = img.scaled(256, 256, _Qt.AspectRatioMode.KeepAspectRatio,
                             _Qt.TransformationMode.SmoothTransformation)
        return bool(img.save(dest, "ICO"))
    except Exception:      # noqa: BLE001
        return False
