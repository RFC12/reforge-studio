"""Lector/extractor nativo de paquetes de contenido de Xbox 360 (XContent: CON / LIVE / PIRS).

* XBLA (juegos Arcade) y demos: volumen STFS dentro de un único archivo
  («<TitleID>/000D0000/<hash>»).
* Games on Demand (GOD): volumen SVOD repartido en «<hash>» (cabecera) + «<hash>.data/Data0000…»
  («<TitleID>/00007000/<hash>»).

Port directo de StfsContainerDevice del runtime de rexglue (Xenia), así que lee los paquetes igual
que el propio runtime. Misma interfaz que XisoImage (entries / files / find / read_file / extract).
"""
import os
import struct
from dataclasses import dataclass, field

MAGICS = {b"CON ": "CON", b"LIVE": "LIVE", b"PIRS": "PIRS"}
HEADER_MIN = 0x971A
BLOCK = 0x1000
BLOCKS_PER_HASH_LEVEL = (170, 28900, 4913000)
END_OF_CHAIN = 0xFFFFFF
MEDIA_MAGIC = b"MICROSOFT*XBOX*MEDIA"
CHUNK = 4 * 1024 * 1024

CONTENT_TYPES = {
    0x00007000: "Games on Demand",
    0x000D0000: "Xbox Live Arcade",
    0x00080000: "Demo",
    0x00004000: "Juego instalado",
    0x000B0000: "Actualización (title update)",
    0x00000002: "Contenido descargable (DLC)",
    0x00000001: "Partida guardada",
    0x00010000: "Perfil",
    0x00020000: "Imagen de jugador",
    0x00030000: "Tema",
}
GAME_TYPES = (0x00007000, 0x000D0000, 0x00080000, 0x00004000)


class XContentError(Exception):
    pass


@dataclass
class XContentEntry:
    path: str                     # ruta relativa con "/"
    size: int
    is_dir: bool
    blocks: list = field(default_factory=list)   # [(índice de archivo, desplazamiento, longitud)]


def _u24le(b, o):
    return b[o] | (b[o + 1] << 8) | (b[o + 2] << 16)


def _round_up(v, a):
    return (v + a - 1) // a * a


def read_magic(path):
    try:
        with open(path, "rb") as f:
            return MAGICS.get(f.read(4))
    except OSError:
        return None


def find_package(path):
    """Archivo de cabecera del paquete: el propio archivo, o el primero que se encuentre en la carpeta
    (p. ej. la carpeta del Title ID con 00007000/<hash> o 000D0000/<hash>)."""
    if os.path.isfile(path):
        return path if read_magic(path) else ""
    best = ""
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = sorted(d for d in dirnames if not d.lower().endswith(".data"))
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(p) < HEADER_MIN:
                    continue
            except OSError:
                continue
            if read_magic(p):
                kind = os.path.basename(dirpath).upper()
                if kind in ("00007000", "000D0000"):
                    return p
                best = best or p
    return best


class XContentPackage:
    def __init__(self, path):
        hdr_path = find_package(path)
        if not hdr_path:
            raise XContentError("No es un paquete de Xbox 360 (GOD/XBLA): falta la cabecera CON/LIVE/PIRS. "
                                "Elige el archivo sin extensión dentro de 00007000 (GOD) o 000D0000 (XBLA), "
                                "o la carpeta del juego.")
        self.path = hdr_path
        with open(hdr_path, "rb") as f:
            h = f.read(HEADER_MIN)
        if len(h) < HEADER_MIN:
            raise XContentError("La cabecera del paquete está incompleta.")
        self.magic = MAGICS[h[:4]]
        self.header_size = struct.unpack_from(">I", h, 0x340)[0]
        self.content_type = struct.unpack_from(">I", h, 0x344)[0]
        self.media_id, self.version, _base, tid = struct.unpack_from(">IIII", h, 0x354)
        self.title_id = f"{tid:08X}"
        self.disc = h[0x366]
        vd = h[0x379:0x379 + 0x24]
        self.data_file_count = struct.unpack_from(">I", h, 0x39D)[0]
        self.volume_type = struct.unpack_from(">I", h, 0x3A9)[0]
        self.display_name = self._utf16(h, 0x411, 0x100)
        self.title_name = self._utf16(h, 0x1691, 0x80)
        self._files = []
        self._entries = None
        try:
            if self.volume_type == 0:
                self._open_stfs(vd)
            elif self.volume_type == 1:
                self._open_svod(vd)
            else:
                raise XContentError(f"Tipo de volumen desconocido ({self.volume_type}).")
        except Exception:
            self.close()
            raise

    @staticmethod
    def _utf16(h, off, size):
        s = h[off:off + size].decode("utf-16-be", "replace")
        return s.split("\0", 1)[0].strip()

    # -- utilidades -------------------------------------------------------
    @property
    def content_name(self):
        return CONTENT_TYPES.get(self.content_type, f"tipo 0x{self.content_type:08X}")

    @property
    def layout(self):
        return f"{self.content_name} ({'SVOD' if self.volume_type else 'STFS'} · {self.magic})"

    @property
    def is_game(self):
        return self.content_type in GAME_TYPES

    def close(self):
        for f in self._files:
            try:
                f.close()
            except Exception:
                pass
        self._files = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def _pread(self, idx, off, size):
        f = self._files[idx]
        f.seek(off)
        return f.read(size)

    # -- STFS (XBLA, demos) -----------------------------------------------
    def _open_stfs(self, vd):
        self._files = [open(self.path, "rb")]
        flags = vd[2]
        self.read_only = bool(flags & 1)
        self.root_active = bool(flags & 2)
        self.ft_count = struct.unpack_from("<H", vd, 3)[0]
        self.ft_block = _u24le(vd, 5)
        self.total_blocks = struct.unpack_from(">I", vd, 0x1C)[0]
        self.bpht = 1 if self.read_only else 2
        self.step0 = BLOCKS_PER_HASH_LEVEL[0] + self.bpht
        self.step1 = BLOCKS_PER_HASH_LEVEL[1] + (BLOCKS_PER_HASH_LEVEL[0] + 1) * self.bpht
        self._hash_cache = {}
        self._data_base = _round_up(self.header_size, BLOCK)

    def _stfs_offset(self, block_index):
        base = BLOCKS_PER_HASH_LEVEL[0]
        block = block_index
        for _ in range(3):
            block += ((block_index + base) // base) * self.bpht
            if block_index < base:
                break
            base *= BLOCKS_PER_HASH_LEVEL[0]
        return self._data_base + (block << 12)

    def _hash_block_number(self, block_index, level):
        L0, L1 = BLOCKS_PER_HASH_LEVEL[0], BLOCKS_PER_HASH_LEVEL[1]
        if level == 0:
            if block_index < L0:
                return 0
            block = (block_index // L0) * self.step0
            block += ((block_index // L1) + 1) * self.bpht
            return block if block_index < L1 else block + self.bpht
        if level == 1:
            if block_index < L1:
                return self.step0
            return (block_index // L1) * self.step1 + self.bpht
        return self.step1

    def _hash_table(self, offset):
        t = self._hash_cache.get(offset)
        if t is None:
            t = self._pread(0, offset, BLOCK)
            if len(t) < BLOCK:
                raise XContentError("El paquete está truncado (tabla de hashes).")
            self._hash_cache[offset] = t
        return t

    def _block_info(self, block_index):
        """Campo «info» de la entrada de hash del bloque (siguiente bloque en los 24 bits bajos)."""
        L0, L1 = BLOCKS_PER_HASH_LEVEL[0], BLOCKS_PER_HASH_LEVEL[1]
        off0 = self._data_base + (self._hash_block_number(block_index, 0) << 12)
        secondary = BLOCK if self.root_active else 0
        if self.read_only:
            secondary = 0
        elif self.total_blocks > L0:
            off1 = self._data_base + (self._hash_block_number(block_index, 1) << 12)
            if self.total_blocks > L1:
                off2 = self._data_base + (self._hash_block_number(block_index, 2) << 12)
                t2 = self._hash_table(off2 + secondary)
                rec = (block_index // L1) % L0
                secondary = BLOCK if struct.unpack_from(">I", t2, rec * 0x18 + 0x14)[0] & 0x40000000 else 0
            t1 = self._hash_table(off1 + secondary)
            rec = (block_index // L0) % L0
            secondary = BLOCK if struct.unpack_from(">I", t1, rec * 0x18 + 0x14)[0] & 0x40000000 else 0
        t0 = self._hash_table(off0 + secondary)
        return struct.unpack_from(">I", t0, (block_index % L0) * 0x18 + 0x14)[0]

    def _stfs_entries(self):
        out, all_entries = [], []
        tb = self.ft_block
        for _n in range(max(1, self.ft_count)):
            data = self._pread(0, self._stfs_offset(tb), BLOCK)
            if len(data) < BLOCK:
                raise XContentError("El paquete está truncado (tabla de archivos).")
            for m in range(BLOCK // 0x40):
                e = data[m * 0x40:(m + 1) * 0x40]
                if e[0] == 0:
                    break
                flags = e[0x28]
                nlen = flags & 0x3F
                is_dir = bool(flags & 0x80)
                start = _u24le(e, 0x2F)
                parent_idx, length = struct.unpack_from(">HI", e, 0x32)
                name = e[:nlen].decode("latin-1", "replace")
                if parent_idx == 0xFFFF:
                    prefix = ""
                elif parent_idx < len(all_entries):
                    prefix = all_entries[parent_idx].path + "/"
                else:
                    raise XContentError("Tabla de archivos STFS dañada.")
                ent = XContentEntry(prefix + name, 0 if is_dir else length, is_dir)
                all_entries.append(ent)
                if not is_dir:
                    remaining, b = length, start
                    while remaining and b != END_OF_CHAIN:
                        n = min(BLOCK, remaining)
                        ent.blocks.append((0, self._stfs_offset(b), n))
                        remaining -= n
                        b = self._block_info(b) & 0xFFFFFF
                    if remaining:
                        raise XContentError(f"El paquete está incompleto: faltan datos de {ent.path}.")
                out.append(ent)
            tb = self._block_info(tb) & 0xFFFFFF
            if tb == END_OF_CHAIN:
                break
        return out

    # -- SVOD (Games on Demand) -------------------------------------------
    def _open_svod(self, vd):
        self.egdf = bool(vd[0x18] & 0x40)
        self.start_data_block = _u24le(vd, 0x1C)
        data_dir = self.path + ".data"
        if os.path.isdir(data_dir):
            parts = sorted(f for f in os.listdir(data_dir) if os.path.isfile(os.path.join(data_dir, f)))
            if self.data_file_count and len(parts) != self.data_file_count:
                raise XContentError(f"Faltan partes del juego: la cabecera indica {self.data_file_count} "
                                    f"archivos Data y hay {len(parts)} en {os.path.basename(data_dir)}.")
            self._files = [open(os.path.join(data_dir, p), "rb") for p in parts]
        elif self.data_file_count <= 1:
            self._files = [open(self.path, "rb")]
        else:
            raise XContentError(f"Falta la carpeta {os.path.basename(data_dir)} con los archivos Data0000… "
                                "junto al archivo de cabecera.")
        if not self._files:
            raise XContentError("La carpeta .data está vacía.")
        if self.egdf:
            if self._pread(0, 0x2000, 20) != MEDIA_MAGIC:
                raise XContentError("SVOD con formato EGDF pero sin el bloque «MICROSOFT*XBOX*MEDIA».")
            self.svod_base, magic_off, self.svod_layout = 0, 0x2000, "egdf"
        elif self._pread(0, 0x12000, 20) == MEDIA_MAGIC:
            self.svod_base, magic_off, self.svod_layout = 0x10000, 0x12000, "xsf"
        elif self._pread(0, 0xD000, 20) == MEDIA_MAGIC:
            self.svod_base, magic_off = 0xB000, 0xD000
            self.svod_layout = "single" if len(self._files) == 1 else "unknown"
        else:
            raise XContentError("No se encontró el sistema de archivos del juego dentro del paquete GOD.")
        self.root_block, self.root_size = struct.unpack_from("<II", self._pread(0, magic_off + 0x14, 8))

    def _svod_offset(self, block):
        BLOCK_SIZE, HASH_BLOCK_SIZE = 0x800, 0x1000
        BLOCKS_PER_L0_HASH, HASHES_PER_L1_HASH = 0x198, 0xA1C4
        BLOCKS_PER_FILE, MAX_FILE_SIZE = 0x14388, 0xA290000
        true_block = block - self.start_data_block * 2
        if self.svod_layout == "egdf":
            true_block += 2
        file_block = true_block % BLOCKS_PER_FILE
        file_index = true_block // BLOCKS_PER_FILE
        l0 = file_block // BLOCKS_PER_L0_HASH + 1
        offset = l0 * HASH_BLOCK_SIZE
        offset += (l0 // HASHES_PER_L1_HASH + 1) * HASH_BLOCK_SIZE
        if self.svod_layout == "single":
            offset += self.svod_base
        addr = file_block * BLOCK_SIZE + offset
        if addr >= MAX_FILE_SIZE:
            file_index += 1
            addr = addr % MAX_FILE_SIZE + 0x2000
        return file_index, addr

    def _svod_entries(self):
        out = []
        pending = [(self.root_block, 0, "")]
        seen = set()
        while pending:
            block, ordinal, prefix = pending.pop()
            key = (block, ordinal)
            if key in seen:
                continue
            seen.add(key)
            ord_off = ordinal * 4
            fi, addr = self._svod_offset(block + ord_off // 0x800)
            if fi >= len(self._files):
                raise XContentError("El paquete GOD está incompleto (faltan archivos Data).")
            raw = self._pread(fi, addr + ord_off % 0x800, 14 + 255)
            if len(raw) < 14:
                raise XContentError("El paquete GOD está truncado.")
            node_l, node_r, data_block, length, attr, nlen = struct.unpack_from("<HHIIBB", raw, 0)
            if node_l == 0xFFFF and node_r == 0xFFFF:
                continue                    # relleno
            name = raw[14:14 + nlen].decode("latin-1", "replace")
            if node_l:
                pending.append((block, node_l, prefix))
            if node_r:
                pending.append((block, node_r, prefix))
            if not name or name in (".", "..") or "/" in name or "\\" in name or "\0" in name:
                continue
            rel = prefix + name
            if attr & 0x10:
                out.append(XContentEntry(rel, 0, True))
                if length:
                    pending.append((data_block, 0, rel + "/"))
                continue
            ent = XContentEntry(rel, length, False)
            remaining, b = _round_up(length, 0x800), data_block
            last = None
            while remaining:
                fi, off = self._svod_offset(b)
                b += 1
                remaining -= 0x800
                if last is not None and ent.blocks[last][0] == fi and off - ent.blocks[last][1] - ent.blocks[last][2] == 0:
                    f0, o0, n0 = ent.blocks[last]
                    ent.blocks[last] = (f0, o0, n0 + 0x800)
                    continue
                ent.blocks.append((fi, off, 0x800))
                last = len(ent.blocks) - 1
            out.append(ent)
        return out

    # -- listado ----------------------------------------------------------
    def entries(self):
        if self._entries is None:
            ents = self._stfs_entries() if self.volume_type == 0 else self._svod_entries()
            ents.sort(key=lambda e: e.path.lower())
            self._entries = ents
        return self._entries

    def files(self):
        return [e for e in self.entries() if not e.is_dir]

    def total_size(self):
        return sum(e.size for e in self.files())

    def find(self, rel_path):
        rel = rel_path.replace("\\", "/").lower()
        for e in self.entries():
            if e.path.lower() == rel:
                return e
        return None

    def _iter_data(self, entry, limit=None):
        remaining = entry.size if limit is None else min(entry.size, limit)
        for fi, off, n in entry.blocks:
            if remaining <= 0:
                break
            pos, left = off, min(n, remaining)
            while left > 0:
                buf = self._pread(fi, pos, min(CHUNK, left))
                if not buf:
                    raise XContentError(f"El paquete está truncado (archivo {entry.path}).")
                yield buf
                pos += len(buf)
                left -= len(buf)
                remaining -= len(buf)

    def read_file(self, entry, limit=None):
        return b"".join(self._iter_data(entry, limit))

    # -- extracción -------------------------------------------------------
    def extract(self, dest, progress=None, cancelled=None, on_file=None):
        """Extrae todo a `dest`. progress(done, total); cancelled() -> bool."""
        dest_real = os.path.realpath(dest)
        os.makedirs(dest_real, exist_ok=True)
        ents = self.entries()
        total = sum(e.size for e in ents if not e.is_dir)
        done = count = 0
        for e in ents:
            target = os.path.realpath(os.path.join(dest_real, *e.path.split("/")))
            if not (target == dest_real or target.startswith(dest_real + os.sep)):
                raise XContentError(f"Ruta insegura en el paquete: {e.path}")
            if e.is_dir:
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if on_file:
                on_file(e)
            with open(target, "wb") as out:
                for buf in self._iter_data(e):
                    if cancelled and cancelled():
                        raise XContentError("Extracción cancelada")
                    out.write(buf)
                    done += len(buf)
                    if progress:
                        progress(done, total)
            count += 1
        return count, total
