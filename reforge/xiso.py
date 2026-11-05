"""Lector/extractor nativo de imágenes de disco de Xbox 360 (XDVDFS / XGD).

Soporta ISOs "completas" (XGD1, XGD2, XGD3) y XISO recortadas (partición en 0).
No necesita herramientas externas como extract-xiso.
"""
import os
import struct
from dataclasses import dataclass

SECTOR_SIZE = 2048
MAGIC = b"MICROSOFT*XBOX*MEDIA"
# (nombre, desplazamiento de la partición de juego dentro del archivo)
PARTITIONS = (
    ("XISO", 0x00000000),
    ("XGD3", 0x02080000),
    ("XGD2", 0x0FD90000),
    ("XGD1", 0x18300000),
)
ATTR_DIRECTORY = 0x10
CHUNK = 4 * 1024 * 1024


class XisoError(Exception):
    pass


@dataclass
class XisoEntry:
    path: str      # ruta relativa con "/"
    sector: int
    size: int
    is_dir: bool


class XisoImage:
    def __init__(self, path):
        self.path = path
        self.file_size = os.path.getsize(path)
        self._f = open(path, "rb")
        self.layout = None
        self.base = 0
        self._entries = None
        for name, off in PARTITIONS:
            pos = off + 32 * SECTOR_SIZE
            if pos + 0x20 > self.file_size:
                continue
            self._f.seek(pos)
            hdr = self._f.read(0x20)
            if hdr[:20] == MAGIC:
                self.layout, self.base = name, off
                self.root_sector, self.root_size = struct.unpack_from("<II", hdr, 20)
                break
        if self.layout is None:
            self._f.close()
            raise XisoError(
                "No se encontró un sistema de archivos de Xbox (XDVDFS) en esta imagen. "
                "¿Es una ISO de Xbox 360? Para paquetes GOD/XBLA (carpetas con Data0000… o archivos "
                "sin extensión) elige «Paquete GOD / XBLA» como origen."
            )

    # -- utilidades -------------------------------------------------------
    def close(self):
        try:
            self._f.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def _read(self, sector, size):
        self._f.seek(self.base + sector * SECTOR_SIZE)
        return self._f.read(size)

    # -- listado ----------------------------------------------------------
    def entries(self):
        if self._entries is not None:
            return self._entries
        out = []
        dirs = [(self.root_sector, self.root_size, "")]
        visited = set()
        while dirs:
            sec, size, prefix = dirs.pop()
            if size == 0 or sec in visited:
                continue
            visited.add(sec)
            data = self._read(sec, size)
            pending, seen = [0], set()
            while pending:
                off = pending.pop()
                if off in seen or off + 14 > len(data):
                    continue
                seen.add(off)
                left, right, start, fsize, attr, nlen = struct.unpack_from("<HHIIBB", data, off)
                if left == 0xFFFF:  # relleno
                    continue
                raw = data[off + 14: off + 14 + nlen]
                name = raw.decode("latin-1", "replace")
                if left:
                    pending.append(left * 4)
                if right:
                    pending.append(right * 4)
                if not name or name in (".", "..") or "/" in name or "\\" in name or "\0" in name:
                    continue
                rel = prefix + name
                if attr & ATTR_DIRECTORY:
                    out.append(XisoEntry(rel, start, 0, True))
                    dirs.append((start, fsize, rel + "/"))
                else:
                    out.append(XisoEntry(rel, start, fsize, False))
        out.sort(key=lambda e: e.path.lower())
        self._entries = out
        return out

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

    def read_file(self, entry, limit=None):
        n = entry.size if limit is None else min(entry.size, limit)
        return self._read(entry.sector, n)

    # -- extracción -------------------------------------------------------
    def extract(self, dest, progress=None, cancelled=None, on_file=None):
        """Extrae todo a `dest`. progress(done, total); cancelled() -> bool."""
        dest_real = os.path.realpath(dest)
        os.makedirs(dest_real, exist_ok=True)
        ents = self.entries()
        total = sum(e.size for e in ents if not e.is_dir)
        done = 0
        count = 0
        for e in ents:
            target = os.path.realpath(os.path.join(dest_real, *e.path.split("/")))
            if not (target == dest_real or target.startswith(dest_real + os.sep)):
                raise XisoError(f"Ruta insegura en la imagen: {e.path}")
            if e.is_dir:
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if on_file:
                on_file(e)
            self._f.seek(self.base + e.sector * SECTOR_SIZE)
            remaining = e.size
            with open(target, "wb") as out:
                while remaining > 0:
                    if cancelled and cancelled():
                        raise XisoError("Extracción cancelada")
                    buf = self._f.read(min(CHUNK, remaining))
                    if not buf:
                        raise XisoError(f"La imagen está truncada (archivo {e.path})")
                    out.write(buf)
                    remaining -= len(buf)
                    done += len(buf)
                    if progress:
                        progress(done, total)
            count += 1
        return count, total
