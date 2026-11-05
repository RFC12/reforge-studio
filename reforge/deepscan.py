"""Análisis profundo de entradas de función que el análisis de rexglue no ve.

En juegos grandes (Gears of War 2…) el juego llama a funciones a través de tablas de métodos virtuales o
de punteros calculados en el código, y muchas de esas entradas están a mitad de otra función (entradas
secundarias). rexglue no las registra y el juego se cierra con «Call to invalid or unregistered function»:
una por arranque. Este análisis las busca todas de una vez en la imagen del juego ya cargada (la vuelca
la extensión de ReForge al arrancar: reforge_image.bin junto al .exe):

* Tablas de punteros (vtables): secuencias de punteros a código en las secciones de datos donde al menos
  la mitad ya son funciones registradas; el resto son entradas que faltan.
* Constantes de código: pares «lis rX, hi / addi|ori rY, rX, lo» que forman una dirección de código
  dentro de OTRA función (si es de la misma, es la base de un switch y se ignora).
"""
import array
import bisect
import os
import re
import struct
import sys

IMAGE_FILE = "reforge_image.bin"
SETFUNC_RE = re.compile(rb"SetFunction\(0x([0-9A-Fa-f]+),")


def registered_starts(gen_dir):
    out = set()
    try:
        names = [f for f in os.listdir(gen_dir) if f.endswith("_register.cpp")]
    except OSError:
        return out
    for n in names:
        with open(os.path.join(gen_dir, n), "rb") as f:
            out.update(int(a, 16) for a in SETFUNC_RE.findall(f.read()))
    return out


def page_layout(xex):
    """[(inicio, fin, tipo)] de las páginas del XEX (tipo 1 = código)."""
    _flags, _hs, _r, sec = struct.unpack_from(">IIII", xex, 4)
    image_flags, base = struct.unpack_from(">II", xex, sec + 0x10C)
    count = struct.unpack_from(">I", xex, sec + 0x180)[0]
    page = 4096 if image_flags & 0x10000000 else 65536
    out, cur = [], base
    for i in range(min(count, 8192)):
        v = struct.unpack_from(">I", xex, sec + 0x184 + i * 24)[0]
        end = cur + (v >> 4) * page
        out.append((cur, end, v & 0xF))
        cur = end
    return base, out


def scan(image, xex, registered):
    """Direcciones candidatas (ordenadas) a declarar como función."""
    base, pages = page_layout(xex)
    code = [(s, e) for s, e, t in pages if t == 1]
    if not code:
        return []
    cs, ce = code[0][0], code[-1][1]
    words = array.array("I")
    words.frombytes(image[: len(image) // 4 * 4])
    if sys.byteorder == "little":
        words.byteswap()
    starts = sorted(registered)

    def fn_of(v):
        i = bisect.bisect_right(starts, v) - 1
        return starts[i] if i >= 0 else None

    found = set()
    # 1) tablas de punteros en las secciones de datos
    for s, e, t in pages:
        if t == 1:
            continue
        lo, hi = (s - base) // 4, min((e - base) // 4, len(words))
        run = []
        for i in range(lo, hi + 1):
            v = words[i] if i < hi else 0
            if i < hi and cs <= v < ce and not v & 3:
                run.append(v)
                continue
            if len(run) >= 2 and sum(x in registered for x in run) * 2 >= len(run):
                found.update(x for x in run if x not in registered and x & 0xFFFF)
            run = []
    # 2) constantes de código (lis + addi/ori) que apuntan dentro de otra función
    for s, e in code:
        lo, hi = (s - base) // 4, min((e - base) // 4, len(words))
        for i in range(lo, hi):
            ins = words[i]
            if ins >> 26 != 15 or (ins >> 16) & 31:
                continue
            rd, high = (ins >> 21) & 31, (ins & 0xFFFF) << 16
            for j in range(i + 1, min(i + 9, hi)):
                n = words[j]
                op = n >> 26
                src = (n >> 16) & 31 if op == 14 else (n >> 21) & 31   # addi rD,rA,SIMM · ori rA,rS,UIMM
                if op in (14, 24) and src == rd:
                    low = n & 0xFFFF
                    v = (high + ((low ^ 0x8000) - 0x8000)) & 0xFFFFFFFF if op == 14 else high | low
                    # una dirección redonda de 64 KB casi nunca es una función: suele ser una base de datos
                    if cs <= v < ce and not v & 3 and v & 0xFFFF and v not in registered \
                            and fn_of(v) != fn_of(base + i * 4):
                        found.add(v)
                    break
                if (n >> 21) & 31 == rd:
                    break
    return sorted(a for a in found if fn_of(a) is not None)


def deep_scan_project(root, exe, gen_dir):
    """Candidatas del proyecto o None si el juego aún no volcó su imagen (sin las ya descartadas)."""
    path = os.path.join(os.path.dirname(exe), IMAGE_FILE) if exe else ""
    if not path or not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        image = f.read()
    with open(os.path.join(root, "assets", "default.xex"), "rb") as f:
        xex = f.read()
    from .game import rejected_functions
    bad = rejected_functions(root)
    return [a for a in scan(image, xex, registered_starts(gen_dir)) if a not in bad]
