"""Qué pasó exactamente, según el volcado de Windows (.dmp).

Windows escribe un minivolcado en `%LOCALAPPDATA%\\CrashDumps\\<juego>.exe.<pid>.dmp` cuando el
proceso muere por una excepción. Del volcado se saca lo que el log no siempre tiene: el tipo de
acceso (lectura, escritura o ejecución), la dirección que se tocó y el módulo que falló. Solo se
leen las cabeceras, no los cientos de MB de memoria, así que tarda milisegundos.

Formato: cabecera `MDMP` + directorio de streams (`MINIDUMP_DIRECTORY`), y dentro de él el
`MINIDUMP_EXCEPTION_STREAM` (tipo 6) con el registro de excepción y el contexto del hilo, y la
`MINIDUMP_MODULE_LIST` (tipo 4) con la base y el nombre de cada módulo cargado.
"""
import mmap
import os
import struct

EXCEPTION_STREAM = 6
MODULE_LIST_STREAM = 4

# EXCEPTION_ACCESS_VIOLATION: ExceptionInformation[0] dice qué se intentó hacer.
_ACCESS = {0: "read", 1: "write", 8: "execute"}

_MAX_STREAMS = 64
_MAX_MODULES = 1024
_RIP_OFFSET = 0xF8          # CONTEXT de AMD64: RIP
_CONTEXT_AT = 160           # MINIDUMP_EXCEPTION_STREAM: ThreadContext (DataSize, Rva)


def _u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def _u64(buf, off):
    return struct.unpack_from("<Q", buf, off)[0]


def _streams(buf):
    """{tipo: desplazamiento} del directorio de streams."""
    out = {}
    count, rva = _u32(buf, 8), _u32(buf, 12)
    for i in range(min(count, _MAX_STREAMS)):
        kind, _size, at = struct.unpack_from("<III", buf, rva + i * 12)
        out.setdefault(kind, at)
    return out


def _modules(buf, at):
    """[(base, tamaño, nombre)] de la lista de módulos."""
    out = []
    off = at + 4
    for _ in range(min(_u32(buf, at), _MAX_MODULES)):
        base, size, name_rva = _u64(buf, off), _u32(buf, off + 8), _u32(buf, off + 20)
        length = _u32(buf, name_rva)
        name = buf[name_rva + 4:name_rva + 4 + length].decode("utf-16-le", "replace")
        out.append((base, size, os.path.basename(name.replace("\\", "/"))))
        off += 108                      # sizeof(MINIDUMP_MODULE)
    return out


def _module_at(modules, address):
    for base, size, name in modules:
        if base and base <= address < base + size:
            return name, address - base
    return "", 0


def _read(buf):
    if buf[:4] != b"MDMP":
        return {}
    streams = _streams(buf)
    if EXCEPTION_STREAM not in streams:
        return {}
    at = streams[EXCEPTION_STREAM]
    out = {"code": _u32(buf, at + 8)}                 # ExceptionCode
    params = _u32(buf, at + 32)                       # NumberParameters
    info = [_u64(buf, at + 40 + 8 * i) for i in range(min(params, 15))]
    if len(info) > 1 and info[0] in _ACCESS:          # 0xC0000005: (tipo, dirección)
        out["access"] = _ACCESS[info[0]]
        out["address"] = info[1]
    size, context = _u32(buf, at + _CONTEXT_AT), _u32(buf, at + _CONTEXT_AT + 4)
    if size and context and MODULE_LIST_STREAM in streams:
        rip = _u64(buf, context + _RIP_OFFSET)
        name, offset = _module_at(_modules(buf, streams[MODULE_LIST_STREAM]), rip)
        if name:
            out["module"], out["offset"] = name, offset
    return out


def read(path):
    """{code, access, address, module, offset} del volcado, o {} si no se puede leer."""
    try:
        with open(path, "rb") as file:
            with mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as buf:
                return _read(buf)
    except (OSError, ValueError, struct.error, IndexError):
        return {}
