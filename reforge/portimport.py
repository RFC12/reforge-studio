"""Importa datos de recompilación de un puerto de la familia XenonRecomp a un proyecto de rexglue.

Para qué: un puerto maduro de un juego (por ejemplo el de VitoMiguelF para Crash of the Titans) incluye, en su
config de XenonRecomp, dos cosas que son ESPECÍFICAS DEL JUEGO (del mismo `default.xex`) y que su autor halló a
mano o con análisis: la lista de funciones (hojas sin .pdata, derivadas de tablas de saltos…) y las tablas de
saltos (`[[switch]]`). Cuando rexglue no detecta alguna de esas tablas, un salto indirecto cae en una dirección
sin mapear y el juego se cierra (p. ej. «unhandled title read of 0x701A0000»). rexglue acepta exactamente la
misma información (`functions`, `switch_tables`), solo que con otros nombres de clave; este módulo traduce.

rexglue NO es XenonRecomp: su runtime es otro, así que esto NO trasplanta el runtime de ese puerto. Solo lleva
los datos de recompilación específicos del juego (que valen porque es el mismo binario) al formato de rexglue.

Mapeo de tablas de saltos: XenonRecomp `[[switch]]` (`base`, `r`, `labels`) → rexglue `[[switch_tables]]`
(`address`, `register`, `labels`). Funciones: `{address, size}` → entradas `[functions]` `0xADDR = { size = … }`.
"""
import os
import re

try:
    import tomllib        # Python 3.11+
except ModuleNotFoundError:   # pragma: no cover
    tomllib = None

SWITCH_FILE = "reforge_port_switch_tables.toml"
FUNCS_MARK = "# ReForge: funciones importadas de un puerto de la comunidad"


def _load_toml(path):
    if tomllib is None:
        raise RuntimeError("se necesita Python 3.11+ (tomllib) para leer la config del puerto")
    with open(path, "rb") as f:
        return tomllib.load(f)


def convert_switch_tables(xenon_switch_path):
    """Lee el archivo de tablas de saltos de XenonRecomp (`[[switch]]`) y devuelve el texto TOML en el formato
    de rexglue (`[[switch_tables]]` con address/register/labels). Devuelve (texto, nº de tablas)."""
    data = _load_toml(xenon_switch_path)
    tables = data.get("switch") or data.get("switch_tables") or []
    out = ["# ReForge Studio: tablas de saltos importadas de un puerto de la comunidad (mismo juego, mismo XEX).",
           "# Traducidas al formato de rexglue. No editar a mano.", ""]
    n = 0
    for t in tables:
        addr = t.get("base", t.get("address"))
        reg = t.get("r", t.get("register"))
        labels = t.get("labels") or []
        if addr is None or reg is None or not labels:
            continue
        out.append("[[switch_tables]]")
        out.append(f"address = 0x{int(addr):08X}")
        out.append(f"register = {int(reg)}")
        out.append("labels = [")
        out += [f"    0x{int(l):08X}," for l in labels]
        out.append("]")
        out.append("")
        n += 1
    return "\n".join(out), n


def read_functions(xenon_main_path):
    """Lee la lista `functions = [{address, size}, …]` de la config principal de XenonRecomp.
    Devuelve [(address, size)]."""
    data = _load_toml(xenon_main_path)
    funcs = []
    for f in (data.get("main", {}).get("functions") or data.get("functions") or []):
        addr = f.get("address")
        if addr is None:
            continue
        funcs.append((int(addr), int(f.get("size", 0))))
    return funcs


def merge_functions(root, funcs):
    """Añade las funciones del puerto a reforge_functions.toml (sin duplicar las que ya estén). Devuelve cuántas
    nuevas añadió."""
    path = os.path.join(root, "reforge_functions.toml")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            txt = f.read()
    except OSError:
        txt = "[functions]\n"
    if "[functions]" not in txt:
        txt = "[functions]\n" + txt
    existing = set(m.group(1).upper() for m in re.finditer(r"(0x[0-9A-Fa-f]{8})\s*=", txt))
    nuevas = []
    for addr, size in funcs:
        key = f"0x{addr:08X}"
        if key.upper() in existing:
            continue
        nuevas.append(f"{key} = {{ size = 0x{size:X} }}  # del puerto de la comunidad" if size
                      else f"{key} = {{}}  # del puerto de la comunidad")
    if not nuevas:
        return 0
    block = "\n" + FUNCS_MARK + "\n" + "\n".join(nuevas) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt.rstrip("\n") + "\n" + block)
    return len(nuevas)


def _manifest(root):
    for f in os.listdir(root):
        if f.endswith("_manifest.toml"):
            return os.path.join(root, f)
    return ""


def ensure_include(root, name):
    """Añade `name` a la lista `includes` del manifest si no está. Devuelve True si lo añadió."""
    man = _manifest(root)
    if not man:
        return False
    txt = open(man, encoding="utf-8", errors="replace").read()
    if name in txt:
        return False
    m = re.search(r"(includes\s*=\s*\[)([^\]]*)\]", txt)
    if m:
        inner = m.group(2).rstrip()
        sep = "" if (not inner.strip() or inner.strip().endswith(",")) else ", "
        txt = txt[:m.start()] + f'{m.group(1)}{inner}{sep}"{name}"]' + txt[m.end():]
    else:
        txt = re.sub(r"(\[entrypoint\][^\[]*)", r'\1includes = ["' + name + '"]\n', txt, count=1)
    with open(man, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)
    return True


def apply_profile(root, xenon_main_path, xenon_switch_path, log=None):
    """Aplica al proyecto los datos del puerto: escribe las tablas de saltos traducidas, fusiona las funciones y
    las engancha en el manifest. Devuelve un resumen (dict)."""
    def _say(msg):
        if log:
            log(msg, "ok")
    switch_text, n_tables = convert_switch_tables(xenon_switch_path)
    with open(os.path.join(root, SWITCH_FILE), "w", encoding="utf-8", newline="\n") as f:
        f.write(switch_text)
    ensure_include(root, SWITCH_FILE)
    n_funcs = merge_functions(root, read_functions(xenon_main_path))
    ensure_include(root, "reforge_functions.toml")   # por si acaso no estuviera
    _say(f"Importado del puerto de la comunidad: {n_tables} tablas de saltos y {n_funcs} funciones nuevas. "
         "Recompila para aplicarlo.")
    return {"switch_tables": n_tables, "functions": n_funcs}
