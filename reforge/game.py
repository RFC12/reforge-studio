"""Codegen con corrección automática, caché de CMake y ejecución del juego recompilado."""
import os
from pathlib import Path
import re
import time
import shutil
import subprocess
import sys
import queue
import threading

from .core import NO_WINDOW, cmake_codegen_cmd, manifest_project_name
from .runner import MAKE_RE, NINJA_RE, classify

FUNCTIONS_FILE = "reforge_functions.toml"
UNRESOLVED_RE = re.compile(
    r"^\s*0x([0-9A-Fa-f]{8}) from 0x([0-9A-Fa-f]{8}):.*(target not in any function|no CallEdge recorded)")
# Avisos (el codegen termina bien, pero el juego llamaría a REX_FATAL al llegar ahí)
UNRESOLVED_WARN_RE = re.compile(
    r"Unresolved (?:b target|function|call from|conditional branch to) 0x([0-9A-Fa-f]{8}) from 0x([0-9A-Fa-f]{8})")
FATAL_BRANCH_RE = re.compile(r'REX_FATAL\("Unresolved (?:branch|call) from 0x([0-9A-Fa-f]{8}) to 0x([0-9A-Fa-f]{8})"\)')
MAX_ROUNDS = 8


# ---------------------------------------------------------------- funciones no resueltas
def parse_unresolved(lines):
    """[(destino, origen)] de las líneas «UnresolvedCall» de rexglue codegen."""
    out, seen = [], set()
    for line in lines:
        m = UNRESOLVED_RE.match(line)
        if m:
            target = int(m.group(1), 16)
            if target not in seen:
                seen.add(target)
                out.append((target, int(m.group(2), 16)))
    return out


def parse_unresolved_warnings(lines):
    """[(destino, origen)] de los avisos «Unresolved b target/function» (saltos a código sin función)."""
    out, seen = [], set()
    for line in lines:
        m = UNRESOLVED_WARN_RE.search(line)
        if m:
            target = int(m.group(1), 16)
            if target not in seen:
                seen.add(target)
                out.append((target, int(m.group(2), 16)))
    return out


def fatal_branches_in_code(gen):
    """[(destino, origen)] de los saltos que el código generado convirtió en REX_FATAL (el juego se cerraría al
    llegar ahí). Declarando el destino como función, rexglue lo genera como salto a esa función."""
    out, seen = [], set()
    try:
        files = [f for f in os.listdir(gen) if re.search(r"_recomp\.\d+\.cpp$", f)]
    except OSError:
        return out
    for f in files:
        txt = Path(os.path.join(gen, f)).read_text(encoding="utf-8", errors="replace")
        if "REX_FATAL(\"Unresolved" not in txt:
            continue
        for s_, t_ in FATAL_BRANCH_RE.findall(txt):
            t = int(t_, 16)
            if t not in seen:
                seen.add(t)
                out.append((t, int(s_, 16)))
    return out


ENTRY_RE = re.compile(r"^(\s*)(0x[0-9A-Fa-f]+)\s*=\s*\{([^}]*)\}(.*)$", re.M)


def normalize_function_overlaps(root):
    """rexglue rechaza el manifiesto si una función declarada cae dentro de otra a la que se le dio «end»
    («Overlapping boundaries»). Esas entradas se declaran como fragmento («parent») de la que las contiene:
    siguen registradas como entrada de función y ya no chocan. Devuelve cuántas se ajustaron."""
    path = os.path.join(root, FUNCTIONS_FILE)
    if not os.path.isfile(path):
        return 0
    txt = Path(path).read_text(encoding="utf-8", errors="replace")
    ranges = sorted((int(a, 16), int(e, 16)) for a, e in
                    re.findall(r"^\s*(0x[0-9A-Fa-f]+)\s*=\s*\{[^}]*\bend\s*=\s*(0x[0-9A-Fa-f]+)", txt, re.M))
    if not ranges:
        return 0
    changed = 0

    def fix(m):
        nonlocal changed
        addr, body = int(m.group(2), 16), m.group(3)
        if re.search(r"\b(end|size|parent)\s*=", body):
            return m.group(0)
        for a, e in ranges:
            if a < addr < e:
                changed += 1
                return f"{m.group(1)}0x{addr:08X} = {{ parent = 0x{a:08X} }}{m.group(4)}"
        return m.group(0)
    new = ENTRY_RE.sub(fix, txt)
    if changed:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new)
        os.replace(tmp, path)
    return changed


REJECT_FILE = "reforge_not_functions.txt"


def rejected_functions(root):
    """Direcciones que ReForge comprobó que NO son inicio de función (parten una función real en dos)."""
    out = set()
    try:
        with open(os.path.join(root, REJECT_FILE), encoding="utf-8") as f:
            for ln in f:
                m = re.match(r"\s*0x([0-9A-Fa-f]+)", ln)
                if m:
                    out.add(int(m.group(1), 16))
    except OSError:
        pass
    return out


def reject_functions(root, items):
    """Anota [(dirección, motivo)] como «no es función» para que ningún análisis la vuelva a declarar."""
    have = rejected_functions(root)
    new = [(a, why) for a, why in items if a not in have]
    if not new:
        return
    path = os.path.join(root, REJECT_FILE)
    first = not os.path.isfile(path)
    with open(path, "a", encoding="utf-8") as f:
        if first:
            f.write("# ReForge Studio: direcciones que NO son inicio de función (declararlas partía una función\n"
                    "# real y el juego se cerraba con «Unresolved branch»). Ningún análisis las vuelve a declarar.\n")
        for a, why in new:
            f.write(f"0x{a:08X}  # {why}\n")


_RANGE_CACHE = {}


def module_range(root):
    """(code_lo, code_hi, image_lo, image_hi) del módulo del juego, leídos de su XEX. ((0,0,0,0) si no se puede).

    Una dirección fuera de [image_lo, image_hi) no puede ser una función del juego: declararla hace que el
    runtime rechace TODA la tabla de funciones al arrancar («func_mappings entries rejected») y el juego ni
    siquiera abre. Por eso todo lo que declara ReForge se filtra antes con este rango.
    """
    xex = os.path.join(root, "assets", "default.xex")
    try:
        key = (xex, os.path.getmtime(xex))
    except OSError:
        return (0, 0, 0, 0)
    if key in _RANGE_CACHE:
        return _RANGE_CACHE[key]
    try:
        from .deepscan import page_layout
        with open(xex, "rb") as f:
            data = f.read()
        base, pages = page_layout(data)
        code = [(lo, hi) for lo, hi, t in pages if t == 1]
        image_hi = pages[-1][1] if pages else base
        rng = ((code[0][0], code[-1][1], base, image_hi) if code else (0, 0, 0, 0))
    except Exception:      # noqa: BLE001
        rng = (0, 0, 0, 0)
    _RANGE_CACHE[key] = rng
    return rng


def in_module(root, address):
    """¿La dirección cae dentro de la imagen del módulo del juego? (True si no se puede saber el rango)."""
    _cl, _ch, lo, hi = module_range(root)
    if not hi:
        return True       # sin rango fiable, no se descarta nada
    return lo <= address < hi


def prune_bad_functions(root):
    """Quita de reforge_functions.toml las direcciones que caen FUERA del módulo y las anota como no-función.

    Son las que dejan el proyecto sin arrancar («func_mappings entries rejected»). Devuelve la lista de las
    que quitó.
    """
    path = os.path.join(root, FUNCTIONS_FILE)
    if not os.path.isfile(path):
        return []
    _cl, _ch, lo, hi = module_range(root)
    if not hi:
        return []
    lineas = Path(path).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    quitadas, fuera = [], []
    for ln in lineas:
        m = re.match(r"\s*0x([0-9A-Fa-f]+)\s*=", ln)
        if m:
            a = int(m.group(1), 16)
            if not (lo <= a < hi):
                quitadas.append(a)
                continue
        fuera.append(ln)
    if quitadas:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(fuera)
        reject_functions(root, [(a, "fuera del modulo del juego: un salto a esta direccion es un puntero danado, "
                                    "no una funcion") for a in quitadas])
    return quitadas


def declare_functions(root, addresses, note):
    """Declara varias funciones de una vez. Devuelve las nuevas."""
    have = declared_functions(root) | rejected_functions(root)
    new = [a for a in addresses if a not in have and in_module(root, a)]
    if not new:
        return []
    ensure_include(root)
    path = os.path.join(root, FUNCTIONS_FILE)
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("# ReForge Studio: funciones declaradas automáticamente.\n\n[functions]\n")
    with open(path, "a", encoding="utf-8") as f:
        for a in new:
            f.write(f"0x{a:08X} = {{}}  # {note}\n")
    return new


UNREGISTERED_RE = re.compile(r"Call to invalid or unregistered function at guest address 0x([0-9A-Fa-f]{8})")


def unregistered_in_log(path):
    """Todas las direcciones «unregistered» de un log del juego (varios hilos pueden fallar a la vez)."""
    try:
        txt = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for m in UNREGISTERED_RE.finditer(txt):
        a = int(m.group(1), 16)
        if a not in out:
            out.append(a)
    return out


def declared_functions(root):
    path = os.path.join(root, FUNCTIONS_FILE)
    if not os.path.isfile(path):
        return set()
    txt = Path(path).read_text(encoding="utf-8", errors="replace")
    return {int(a, 16) for a in re.findall(r"^\s*(0x[0-9A-Fa-f]+)\s*=", txt, re.M)}


def add_functions(root, items):
    """Declara funciones (sin tamaño: rexglue descubre su final). Devuelve las nuevas."""
    have = declared_functions(root) | rejected_functions(root)
    new = [(t, s) for t, s in items if t not in have]
    if not new:
        return []
    path = os.path.join(root, FUNCTIONS_FILE)
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("# ReForge Studio: funciones que el análisis de rexglue no detectó por sí solo.\n"
                    "# Se declaran sin tamaño para que rexglue descubra dónde terminan.\n"
                    "# Puedes editar este archivo; se conserva entre recompilaciones.\n\n"
                    "[functions]\n")
    with open(path, "a", encoding="utf-8") as f:
        for t, s in new:
            f.write(f"0x{t:08X} = {{}}  # salto desde 0x{s:08X}\n")
    return new


# ---------------------------------------------------------------- funciones cortadas
# rexglue registra como función cada entrada de .pdata. Algunos compiladores parten una función en varios
# fragmentos (otra entrada .pdata a mitad de la función, p. ej. el destino de un caso de un switch) y el
# análisis la corta antes de tiempo: el código generado salta («goto loc_X») a etiquetas que no emitió y el
# compilador falla con «use of undeclared label». Se arregla declarando dónde termina de verdad la función.
DEFINE_RE = re.compile(r"^DEFINE_REX_FUNC\((\w+)\) \{\n(.*?)^\}\n", re.S | re.M)
SETFUNC_RE = re.compile(r"SetFunction\(0x([0-9A-Fa-f]+),\s*(\w+)\)")
UNDECLARED_LABEL_RE = re.compile(r"use of undeclared label '?loc_([0-9A-Fa-f]+)")


def generated_dir(root):
    mans = [f for f in os.listdir(root) if f.endswith("_manifest.toml")] if os.path.isdir(root) else []
    rel = "generated/default"
    if mans:
        m = re.search(r'^\s*out_directory_path\s*=\s*"([^"]+)"',
                      Path(os.path.join(root, mans[0])).read_text(encoding="utf-8", errors="replace"), re.M)
        if m:
            rel = m.group(1)
    return os.path.join(root, *rel.split("/"))


def registered_functions(gen):
    """{nombre: dirección} de las funciones que registra el código generado."""
    out = {}
    try:
        names = [f for f in os.listdir(gen) if f.endswith("_register.cpp")]
    except OSError:
        return out
    for f in names:
        for a, n in SETFUNC_RE.findall(Path(os.path.join(gen, f)).read_text(encoding="utf-8", errors="replace")):
            out.setdefault(n, int(a, 16))
    return out


def find_missing_labels(gen):
    """{dirección de la función: {etiquetas que usa y no define}} en el código generado."""
    funcs = registered_functions(gen)
    bad = {}
    try:
        files = sorted(f for f in os.listdir(gen) if re.search(r"_recomp\.\d+\.cpp$", f))
    except OSError:
        return bad
    for f in files:
        txt = Path(os.path.join(gen, f)).read_text(encoding="utf-8", errors="replace")
        for m in DEFINE_RE.finditer(txt):
            body = m.group(2)
            used = set(re.findall(r"goto loc_([0-9A-Fa-f]+);", body))
            if not used:
                continue
            missing = used - set(re.findall(r"^loc_([0-9A-Fa-f]+):", body, re.M))
            if missing:
                name = m.group(1)
                addr = funcs.get(name)
                if addr is None and re.fullmatch(r"sub_[0-9A-Fa-f]{8}", name):
                    addr = int(name[4:], 16)
                if addr is not None:
                    bad[addr] = {int(x, 16) for x in missing}
    return bad


def function_ends(root):
    """{dirección: fin} ya declarados con «end» en reforge_functions.toml."""
    path = os.path.join(root, FUNCTIONS_FILE)
    if not os.path.isfile(path):
        return {}
    txt = Path(path).read_text(encoding="utf-8", errors="replace")
    return {int(a, 16): int(e, 16) for a, e in
            re.findall(r"^\s*(0x[0-9A-Fa-f]+)\s*=\s*\{[^}]*\bend\s*=\s*(0x[0-9A-Fa-f]+)", txt, re.M)}


def set_function_end(root, addr, end, note):
    """Declara (o corrige) «0xADDR = { end = 0xEND }» en reforge_functions.toml."""
    ensure_include(root)
    path = os.path.join(root, FUNCTIONS_FILE)
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("# ReForge Studio: funciones declaradas automáticamente.\n\n[functions]\n")
    txt = Path(path).read_text(encoding="utf-8", errors="replace")
    line = f"0x{addr:08X} = {{ end = 0x{end:08X} }}  # {note}"
    pat = re.compile(rf"^\s*0x0*{addr:X}\s*=.*$", re.M | re.I)
    txt = pat.sub(line, txt, count=1) if pat.search(txt) else txt.rstrip("\n") + "\n" + line + "\n"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(txt)
    os.replace(tmp, path)


def fix_truncated_functions(root, ctx=None):
    """Busca funciones cortadas en el código generado y declara su final real (la siguiente función
    registrada después de la última etiqueta que les falta). Devuelve [(función, fin)] corregidas."""
    gen = generated_dir(root)
    bad = find_missing_labels(gen)
    if not bad:
        return []
    starts = sorted(set(registered_functions(gen).values()))
    ends = function_ends(root)
    fixed = []
    for addr, missing in sorted(bad.items()):
        last = max(missing)
        nxt = [a for a in starts if a > last]
        end = nxt[0] if nxt else (last + 4)
        if ends.get(addr) == end or (last < addr):
            continue            # ya estaba declarado así (o salta hacia atrás fuera de ella): no se puede más
        set_function_end(root, addr, end, f"cortada por el análisis: faltaban {len(missing)} etiqueta(s)")
        fixed.append((addr, end))
        if ctx:
            ctx.log(f"  sub_{addr:08X}: termina en 0x{end:08X} (le faltaban "
                    f"{', '.join(f'loc_{x:08X}' for x in sorted(missing)[:4])})", "warn")
    return fixed


REMOVABLE_NOTE_RE = re.compile(r"análisis profundo|salto desde|otro hilo", re.I)


def fix_split_functions(root, ctx=None):
    """Saltos de una función a otra que rexglue no puede resolver («Unresolved branch from S to T»): casi
    siempre porque una entrada declarada por ReForge (análisis profundo, saltos) cae entre S y T y parte una
    función real en dos. Se quitan esas entradas (y el destino T si se había declarado solo por ese salto) y se
    anotan para no volver a declararlas. Devuelve las direcciones quitadas."""
    branches = fatal_branches_in_code(generated_dir(root))
    path = os.path.join(root, FUNCTIONS_FILE)
    if not branches or not os.path.isfile(path):
        return []
    txt = Path(path).read_text(encoding="utf-8", errors="replace")
    entries = {}
    for m in ENTRY_RE.finditer(txt):
        try:
            entries[int(m.group(2), 16)] = m.group(4)
        except ValueError:
            continue
    remove = {}
    for t, s_ in branches:
        lo, hi = min(s_, t), max(s_, t)
        between = [e for e, note in entries.items() if lo < e <= hi and e != t and REMOVABLE_NOTE_RE.search(note)]
        for e in between:
            remove[e] = f"partía la función: salto de 0x{s_:08X} a 0x{t:08X}"
        if between and t in entries and re.search(rf"salto desde 0x0*{s_:X}\b", entries[t], re.I):
            remove[t] = f"solo se declaró por el salto desde 0x{s_:08X}"
    if not remove:
        return []
    keep = []
    for ln in txt.splitlines(keepends=True):
        m = ENTRY_RE.match(ln.rstrip("\r\n"))
        if m:
            try:
                if int(m.group(2), 16) in remove:
                    continue
            except ValueError:
                pass
        keep.append(ln)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("".join(keep))
    os.replace(tmp, path)
    reject_functions(root, sorted(remove.items()))
    if ctx:
        ctx.log(f"  quitadas {len(remove)} entrada(s) que partían funciones reales: "
                + ", ".join(f"0x{a:08X}" for a in sorted(remove)[:6]) + ("…" if len(remove) > 6 else ""), "warn")
    return sorted(remove)


def switch_function_set(root, old_tag, new_tag):
    """Cada versión del ejecutable (juego base, actualización X) tiene su propia lista de funciones declaradas:
    al cambiar de versión el código se mueve y las direcciones de la otra versión partirían o romperían
    funciones. Guarda la lista actual como `old_tag` y recupera (o empieza vacía) la de `new_tag`."""
    names = (FUNCTIONS_FILE, REJECT_FILE)
    for n in names:
        cur = os.path.join(root, n)
        if os.path.isfile(cur):
            shutil.copyfile(cur, f"{cur}.{old_tag}")
    for n in names:
        cur = os.path.join(root, n)
        saved = f"{cur}.{new_tag}"
        if os.path.isfile(saved):
            shutil.copyfile(saved, cur)
        elif n == FUNCTIONS_FILE and os.path.isfile(cur):
            with open(cur, "w", encoding="utf-8") as f:
                f.write(f"# ReForge Studio: funciones declaradas automáticamente ({new_tag}).\n\n[functions]\n")
        elif os.path.isfile(cur):
            os.remove(cur)
    # setjmp/longjmp detectados en la otra versión: sus direcciones ya no valen (se vuelven a detectar)
    path = manifest_path(root)
    if path:
        txt = Path(path).read_text(encoding="utf-8")
        new = re.sub(r"^\s*(setjmp|longjmp)_address\s*=.*\n?", "", txt, flags=re.M)
        if new != txt:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(new)
    invalidate_codegen(root)


def invalidate_codegen(root):
    """Obliga a regenerar el código en la próxima compilación (default.xexp no está entre las dependencias
    que vigila CMake: tras cambiar una actualización o los trucos hay que forzarlo)."""
    gen = generated_dir(root)
    for name in ("codegen.build.stamp", "codegen.stamp"):
        try:
            os.remove(os.path.join(gen, name))
        except OSError:
            pass


def forget_module_hash(root):
    """La versión exacta del juego cambió (actualización): el hash anotado ya no vale."""
    try:
        exe = game_exe(root)
    except Exception:      # noqa: BLE001
        exe = ""
    if exe:
        try:
            os.remove(os.path.join(os.path.dirname(exe), "reforge_module.txt"))
        except OSError:
            pass


def ensure_include(root):
    """Añade reforge_functions.toml a los includes de [entrypoint] del manifiesto."""
    mans = [f for f in os.listdir(root) if f.endswith("_manifest.toml")]
    if not mans:
        raise RuntimeError("No se encontró el *_manifest.toml del proyecto")
    path = os.path.join(root, mans[0])
    txt = Path(path).read_text(encoding="utf-8")
    if FUNCTIONS_FILE in txt:
        return False
    m = re.search(r"^\[entrypoint\]\s*$", txt, re.M)
    if not m:
        raise RuntimeError("El manifiesto no tiene sección [entrypoint]")
    start = m.end()
    nxt = re.search(r"^\[", txt[start:], re.M)
    end = start + nxt.start() if nxt else len(txt)
    section = txt[start:end]
    inc = re.search(r"^(\s*includes\s*=\s*\[)(.*?)(\])", section, re.M | re.S)
    if inc:
        inner = inc.group(2).strip()
        new_inner = f'"{FUNCTIONS_FILE}"' if not inner else f'{inner.rstrip(",")}, "{FUNCTIONS_FILE}"'
        section = section[:inc.start()] + inc.group(1) + new_inner + inc.group(3) + section[inc.end():]
    else:
        section = f'\nincludes = ["{FUNCTIONS_FILE}"]' + section
    txt = txt[:start] + section + txt[end:]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(txt)
    os.replace(tmp, path)
    return True


def run_streaming(cmd, cwd, env, ctx):
    ctx.log("$ " + " ".join(f'"{a}"' if " " in a else a for a in cmd), "cmd")
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=NO_WINDOW,
                         start_new_session=sys.platform != "win32")
    from .processes import stop_process_tree
    lines = []
    output = queue.Queue()

    def read_output():
        try:
            for raw in p.stdout:
                output.put(raw)
        finally:
            output.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        while True:
            if ctx.cancelled():
                stop_process_tree(p.pid, grouped=sys.platform != "win32")
                raise RuntimeError("Cancelado por el usuario")
            try:
                raw = output.get(timeout=0.1)
            except queue.Empty:
                continue
            if raw is None:
                break
            line = raw.rstrip("\r\n")
            if not line.strip():
                continue
            lines.append(line)
            m = NINJA_RE.match(line)
            if m:
                ctx.progress(int(m.group(1)), max(1, int(m.group(2))))
            else:
                m = MAKE_RE.match(line)
                if m:
                    ctx.progress(int(m.group(1)), 100)
            ctx.log(line, classify(line))
        code = p.wait()
        if ctx.cancelled():
            raise RuntimeError("Cancelado por el usuario")
        return code, lines
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        reader.join(timeout=2)
        p.stdout.close()


# ---------------------------------------------------------------- setjmp / longjmp
# Muchos juegos (libjpeg, Lua, motores con manejo de errores propio) usan setjmp/longjmp. Recompilado, longjmp no
# puede «saltar atrás» salvo que rexglue sepa qué funciones son: entonces genera ppc_setjmp/ppc_longjmp. Sin eso
# el juego sigue con registros basura y se cierra (Fast & Furious Showdown: «read of guest 0x000001A4» al
# arrancar, dentro de libjpeg). ReForge las reconoce en el código generado por su forma y las declara en el
# manifiesto (setjmp_address / longjmp_address).
_FUNC_BODY_RE = re.compile(r"DEFINE_REX_FUNC\(sub_([0-9A-Fa-f]{8})\)\s*\{(.*?)\n\}", re.S)
_ASM_RE = re.compile(r"^\s*// (.+?)\s*$", re.M)
_STORE_R3_RE = re.compile(r"^(?:std|stw) r(\d+),(\d+)\(r3\)$")
_LOAD_R3_RE = re.compile(r"^(?:ld|lwz) r\d+,(\d+)\(r3\)$")
_LOAD_ANY_RE = re.compile(r"^(?:ld|lwz) r(\d+),(\d+)\(r\d+\)$")


def _iter_functions(gen):
    try:
        names = sorted(f for f in os.listdir(gen) if f.endswith(".cpp"))
    except OSError:
        return
    for n in names:
        try:
            txt = Path(os.path.join(gen, n)).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _FUNC_BODY_RE.finditer(txt):
            yield int(m.group(1), 16), _ASM_RE.findall(m.group(2))


def detect_setjmp_longjmp(gen):
    """(setjmp, longjmp) del juego según su forma en el código generado, o (None, None)."""
    funcs = list(_iter_functions(gen))
    setjmps = []
    for addr, ins in funcs:
        if not 20 <= len(ins) <= 400 or ins[-2:] != ["li r3,0", "blr"]:
            continue
        stores = [(_m.group(1), _m.group(2)) for i in ins if (_m := _STORE_R3_RE.match(i))]
        regs = {int(r) for r, _o in stores}
        if "1" in {r for r, _o in stores} and len(regs & set(range(13, 32))) >= 12:
            setjmps.append((addr, {int(o) for _r, o in stores}))
    if len(setjmps) != 1:
        return None, None
    sj, offs = setjmps[0]
    longs = []
    for addr, ins in funcs:
        if addr == sj or len(ins) > 600:
            continue
        # longjmp: recarga desde el búfer de setjmp (mismos desplazamientos) los registros no volátiles y r1
        loads = [(int(_m.group(1)), int(_m.group(2))) for i in ins if (_m := _LOAD_ANY_RE.match(i))]
        regs = {r for r, o in loads if o in offs}
        if 1 in regs and len(regs & set(range(13, 32))) >= 12 and any(i.startswith("mtlr ") for i in ins):
            longs.append(addr)
    if len(longs) != 1:
        return None, None
    return sj, longs[0]


def manifest_path(root):
    mans = [f for f in os.listdir(root) if f.endswith("_manifest.toml")] if os.path.isdir(root) else []
    return os.path.join(root, mans[0]) if mans else ""


def ensure_setjmp(root):
    """Declara setjmp/longjmp en el manifiesto si el juego las usa y aún no están. Devuelve (sj, lj) o None."""
    path = manifest_path(root)
    if not path:
        return None
    txt = Path(path).read_text(encoding="utf-8")
    if re.search(r"^\s*(setjmp|longjmp)_address\s*=", txt, re.M):
        return None
    sj, lj = detect_setjmp_longjmp(generated_dir(root))
    if not (sj and lj):
        return None
    m = re.search(r"^\[entrypoint\]\s*$", txt, re.M)
    if not m:
        return None
    nxt = re.search(r"^\[", txt[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(txt) - m.end())
    block = txt[m.end():end].rstrip("\n")
    block += f"\nsetjmp_address = 0x{sj:08X}   # ReForge: setjmp del juego (longjmp recompilado)\nlongjmp_address = 0x{lj:08X}\n"
    new = txt[:m.end()] + block + ("\n" + txt[end:] if nxt else "")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    return sj, lj


# ---------------------------------------------------------------- optimización del código recompilado
# rexglue (como XenonRecomp) puede guardar registros del PowerPC como variables locales de C++ en vez de en la
# estructura del contexto: el compilador los deja en registros del x86, desaparecen miles de lecturas/escrituras
# a memoria y las llamadas a las funciones de guardar/restaurar registros. En Unleashed Recompiled: ~20 MB menos
# de ejecutable y varios ms menos por fotograma. Solo es correcto si el juego respeta la convención de llamadas
# del Xbox 360 (casi todos): por eso hay niveles y el Taller baja de nivel solo si el juego se cierra.
CODEGEN_OPT_KEYS = ("skip_lr", "skip_msr", "ctr_as_local", "xer_as_local", "reserved_as_local", "cr_as_local",
                    "non_argument_as_local", "non_volatile_as_local")
CODEGEN_LEVELS = ["max", "safe", "off"]
CODEGEN_LEVEL_TITLES = {"max": "Máxima", "safe": "Segura", "off": "Desactivada"}


def codegen_flags(level, manifest_text=""):
    """Opciones del codegen para un nivel. Los registros no volátiles nunca se hacen locales si el juego usa
    setjmp/longjmp o manejadores de excepciones (longjmp necesita restaurarlos desde el contexto)."""
    f = {k: False for k in CODEGEN_OPT_KEYS}
    if level in ("safe", "max"):
        f.update(skip_msr=True, ctr_as_local=True, xer_as_local=True, reserved_as_local=True, cr_as_local=True)
    if level == "max":
        f.update(non_argument_as_local=True)
        sjlj = re.search(r"^\s*(setjmp|longjmp)_address\s*=", manifest_text, re.M)
        seh = re.search(r"^\s*generate_exception_handlers\s*=\s*true", manifest_text, re.M)
        if not seh:
            f["skip_lr"] = True
        if not (sjlj or seh):
            f["non_volatile_as_local"] = True
    return f


def manifest_codegen_flags(text):
    """Opciones de optimización escritas ahora en el manifiesto."""
    out = {k: False for k in CODEGEN_OPT_KEYS}
    for k in CODEGEN_OPT_KEYS:
        m = re.search(rf"^\s*{k}\s*=\s*(true|false)", text, re.M)
        if m:
            out[k] = m.group(1) == "true"
    return out


def apply_codegen_opt(root, level=None):
    """Escribe en [entrypoint] del manifiesto las opciones del nivel elegido. Devuelve True si cambió algo
    (hay que regenerar y recompilar todo el juego)."""
    path = manifest_path(root)
    if not path:
        return False
    if level is None:
        from .game_options import GameOptions
        level = GameOptions.load(root).codegen_level()
    txt = Path(path).read_text(encoding="utf-8")
    want = codegen_flags(level, txt)
    if manifest_codegen_flags(txt) == want:
        return False
    m = re.search(r"^\[entrypoint\]\s*$", txt, re.M)
    if not m:
        return False
    nxt = re.search(r"^\[", txt[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(txt) - m.end())
    body = txt[m.end():end]
    body = re.sub(r"^\s*#\s*ReForge: optimización del código.*\n", "", body, flags=re.M)
    body = re.sub(rf"^\s*({'|'.join(CODEGEN_OPT_KEYS)})\s*=.*\n?", "", body, flags=re.M).rstrip("\n")
    body += f"\n# ReForge: optimización del código ({CODEGEN_LEVEL_TITLES.get(level, level)})\n"
    body += "".join(f"{k} = {'true' if v else 'false'}\n" for k, v in want.items())
    new = txt[:m.end()] + body + ("\n" + txt[end:] if nxt else "")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    invalidate_codegen(root)
    return True


def enable_exception_handlers(root):
    """Activa los manejadores de excepciones estructuradas (__try/__except del código del juego). Sin ellos, un
    acceso inválido que el juego tenía previsto capturar cierra el juego. Devuelve True si se activaron ahora."""
    path = manifest_path(root)
    if not path:
        return False
    txt = Path(path).read_text(encoding="utf-8")
    if re.search(r"^\s*generate_exception_handlers\s*=", txt, re.M):
        return False
    m = re.search(r"^\[entrypoint\]\s*$", txt, re.M)
    if not m:
        return False
    nxt = re.search(r"^\[", txt[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(txt) - m.end())
    block = txt[m.end():end].rstrip("\n")
    block += "\ngenerate_exception_handlers = true   # ReForge: __try/__except del juego\n"
    new = txt[:m.end()] + block + ("\n" + txt[end:] if nxt else "")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    apply_codegen_opt(root)          # con excepciones, algunas optimizaciones no son válidas
    invalidate_codegen(root)
    return True


SEH_MARK = "# ReForge: SEH_TRY header"
SEH_UNDECLARED_RE = re.compile(r"undeclared identifier '(SEH_TRY|SEH_CATCH|SEH_END|SEH_CATCH_ALL|GetExceptionCode|"
                               r"GetExceptionInformation)'")


def ensure_seh_header(root):
    """Con manejadores de excepciones, el codegen de rexglue escribe SEH_TRY/SEH_CATCH pero el SDK no incluye
    el encabezado que las define (rex/platform/exceptions.h) ni, en Windows, <excpt.h> (GetExceptionCode):
    se añaden al precompilado del código recompilado. Devuelve True si cambió CMakeLists.txt."""
    cml = os.path.join(root, "CMakeLists.txt")
    try:
        txt = Path(cml).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if SEH_MARK in txt and "<excpt.h>" in txt:
        return False
    if SEH_MARK in txt:          # bloque de una versión anterior (sin excpt.h): se rehace
        txt = re.sub(re.escape(SEH_MARK) + r".*?\nendif\(\)\n?", "", txt, flags=re.S)
    m = re.search(r"^\s*project\(\s*([A-Za-z0-9_\-]+)", txt, re.M)
    name = (m.group(1) if m else "") or manifest_project_name(root)
    if not name:
        return False
    block = (f"\n{SEH_MARK} (generate_exception_handlers: the SDK does not include it)\n"
             f"if(TARGET {name}_recomp)\n"
             f"    if(WIN32)\n"
             f"        target_precompile_headers({name}_recomp PRIVATE <excpt.h>)\n"
             f"    endif()\n"
             f"    target_precompile_headers({name}_recomp PRIVATE <rex/platform/exceptions.h>)\n"
             f"endif()\n")
    with open(cml, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt.rstrip("\n") + "\n" + block)
    # CMake reescribe cmake_pch.hxx pero ninja no siempre rehace el .pch: se borra para forzarlo
    for d in (os.path.join(root, "build", "CMakeFiles", f"{name}_recomp.dir"),):
        for f in ("cmake_pch.hxx.pch", "cmake_pch.hxx.gch"):
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass
    return True


MAP_MARK = "# ReForge: linker map"
CRASH_AT_RE = re.compile(r"\[ReForge\] Fallo en (\S+?)\+0x([0-9A-Fa-f]+)")


def ensure_link_map(root):
    """Mapa del enlazador junto al .exe (<nombre>.map): traduce «Fallo en juego.exe+0x…» a la función del juego."""
    cml = os.path.join(root, "CMakeLists.txt")
    try:
        txt = Path(cml).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if MAP_MARK in txt:
        return False
    m = re.search(r"^\s*project\(\s*([A-Za-z0-9_\-]+)", txt, re.M)
    name = (m.group(1) if m else "") or manifest_project_name(root)
    if not name:
        return False
    block = (f"\n{MAP_MARK} (crash locations)\n"
             f"if(WIN32 AND TARGET {name})\n"
             f"    target_link_options({name} PRIVATE \"LINKER:/MAP:${{CMAKE_CURRENT_BINARY_DIR}}/{name}.map\")\n"
             f"endif()\n")
    with open(cml, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt.rstrip("\n") + "\n" + block)
    return True


def map_symbols(map_path):
    """[(rva, símbolo)] ordenados del mapa del enlazador (formato MSVC/lld-link «/MAP» o el de lld)."""
    out = []
    try:
        lines = Path(map_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    base = None
    for ln in lines[:40]:
        mb = re.search(r"Preferred load address is ([0-9a-fA-F]+)", ln)
        if mb:
            base = int(mb.group(1), 16)
            break
    for ln in lines:
        mm = re.match(r"^\s*[0-9a-fA-F]{4}:[0-9a-fA-F]{8}\s+(\S+)\s+([0-9a-fA-F]{8,16})\s", ln)
        if mm and base is not None:
            sym = mm.group(1)
            if sym.startswith("__imp__sub_"):
                continue
            out.append((int(mm.group(2), 16) - base, sym))
            continue
        mm = re.match(r"^\s*([0-9a-fA-F]{6,16})\s+([0-9a-fA-F]+)\s+\d+\s+(\S.*)$", ln)
        if mm:
            va = int(mm.group(1), 16)
            sym = mm.group(3).strip()
            lb = base if base is not None else (va & ~0xFFFFF if va >= 0x100000 else 0)
            if base is None:
                base = lb
            if ":(" in sym or sym.startswith((".", "<")) or "\\" in sym or "/" in sym:
                continue
            out.append((va - lb, sym))
    out.sort()
    return out


def crash_location(exe, log_path):
    """«sub_82656F90+0x1C4 (codaw.exe+0x…)» del último fallo localizado en el log, o ""."""
    try:
        txt = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = CRASH_AT_RE.search(txt)
    if not m:
        return ""
    module, rva = m.group(1), int(m.group(2), 16)
    where = f"{module}+0x{rva:X}"
    if exe and module.lower() == os.path.basename(exe).lower():
        syms = map_symbols(os.path.splitext(exe)[0] + ".map")
        import bisect
        i = bisect.bisect_right([a for a, _s in syms], rva) - 1
        if i >= 0:
            a, sym = syms[i]
            return f"{sym}+0x{rva - a:X} ({where})"
    return where


def exception_handlers_enabled(root):
    path = manifest_path(root)
    try:
        return bool(path) and bool(re.search(r"^\s*generate_exception_handlers\s*=\s*true",
                                             Path(path).read_text(encoding="utf-8"), re.M))
    except OSError:
        return False


def codegen_opt_pending(root):
    """True si el manifiesto no tiene aún las opciones del nivel elegido."""
    path = manifest_path(root)
    if not path:
        return False
    try:
        from .game_options import GameOptions
        txt = Path(path).read_text(encoding="utf-8")
        if not re.search(r"^\[entrypoint\]\s*$", txt, re.M):
            return False
        return manifest_codegen_flags(txt) != codegen_flags(GameOptions.load(root).codegen_level(), txt)
    except Exception:      # noqa: BLE001
        return False


def codegen_with_autofix(cfg, root, build, name, env, ctx):
    from .game_profiles import apply_game_profile
    apply_game_profile(root, ctx)
    try:
        from .game_options import GameOptions
        lvl = GameOptions.load(root).codegen_level()
        if apply_codegen_opt(root, lvl):
            ctx.log(f"⚡ Optimización del código recompilado: {CODEGEN_LEVEL_TITLES.get(lvl, lvl)} (registros como "
                    "variables locales: menos accesos a memoria, más FPS). Se regenera todo el juego.", "ok")
    except Exception as e:      # noqa: BLE001
        ctx.log(f"No se pudo aplicar la optimización del código: {e}", "warn")
    for rnd in range(1, MAX_ROUNDS + 1):
        if normalize_function_overlaps(root):
            ctx.log("Ajustadas entradas que caían dentro de funciones con final declarado (como fragmento).", "dim")
        code, lines = run_streaming(cmake_codegen_cmd(cfg, build, name), root, env, ctx)
        if code == 0:
            split = fix_split_functions(root, ctx)
            if split:
                ctx.log(f"↻ Corrección automática {rnd}: {len(split)} entrada(s) de función partían funciones reales "
                        f"(el juego se cerraría con «Unresolved branch»); quitadas. Regenerando…", "warn")
                invalidate_codegen(root)
                continue
            fixed = fix_truncated_functions(root, ctx)
            warned = parse_unresolved_warnings(lines)
            have_t = {t for t, _s in warned}
            warned += [(t, s_) for t, s_ in fatal_branches_in_code(generated_dir(root)) if t not in have_t]
            new = add_functions(root, warned) if warned else []
            if new:
                ensure_include(root)
            if fixed or new:
                what = []
                if fixed:
                    what.append(f"{len(fixed)} función(es) cortadas por el análisis (declarado su final real)")
                if new:
                    what.append(f"{len(new)} salto(s) a código sin función, que cerrarían el juego al llegar ahí "
                                f"({', '.join(f'0x{t:08X}' for t, _s in new[:4])}{'…' if len(new) > 4 else ''})")
                ctx.log(f"↻ Corrección automática {rnd}: " + "; ".join(what) + f" → {FUNCTIONS_FILE}. Regenerando…",
                        "warn")
                continue
            sjlj = ensure_setjmp(root)
            if sjlj:
                apply_codegen_opt(root)        # con setjmp/longjmp, los registros no volátiles no pueden ser locales
                ctx.log(f"↻ Corrección automática {rnd}: el juego usa setjmp/longjmp (0x{sjlj[0]:08X} / "
                        f"0x{sjlj[1]:08X}); declarados en el manifiesto para que rexglue los recompile bien "
                        "(sin esto el juego se cierra al recuperarse de un error). Regenerando…", "warn")
                continue
            if rnd > 1:
                ctx.log(f"✔ Codegen completado tras {rnd - 1} corrección(es) automática(s). "
                        f"Funciones declaradas: {len(declared_functions(root))} ({FUNCTIONS_FILE})", "ok")
            return
        unresolved = parse_unresolved(lines)
        if not unresolved:
            raise RuntimeError(f"codegen terminó con código {code} (revisa el log)")
        ensure_include(root)
        new = add_functions(root, unresolved)
        if not new:
            raise RuntimeError(f"{len(unresolved)} llamada(s) siguen sin resolverse aunque ya están declaradas "
                               f"en {FUNCTIONS_FILE}. Puede que necesiten 'size' o 'parent' a mano.")
        ctx.log(f"↻ Corrección automática {rnd}: declaradas {len(new)} función(es) en {FUNCTIONS_FILE} "
                f"({', '.join(f'0x{t:08X}' for t, _s in new[:6])}{'…' if len(new) > 6 else ''}). Reintentando…",
                "warn")
    raise RuntimeError(f"Se alcanzó el límite de {MAX_ROUNDS} correcciones automáticas")


# ---------------------------------------------------------------- caché de CMake
def cache_value(build, key):
    path = os.path.join(build, "CMakeCache.txt")
    try:
        txt = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(rf"^{re.escape(key)}:[A-Z]+=(.*)$", txt, re.M)
    return m.group(1).strip() if m else ""


def cache_mismatch(cfg, build):
    """Motivo para reconfigurar desde cero (compilador o generador distintos) o ''."""
    cur = cache_value(build, "CMAKE_CXX_COMPILER")
    if cur is None:
        return ""
    want = (cfg.cxx_compiler or "").strip()
    norm = lambda p: os.path.normcase(os.path.normpath(p.replace("/", os.sep))) if p else ""  # noqa: E731
    if want and norm(cur) != norm(want) and os.path.basename(norm(cur)) != os.path.basename(norm(want)):
        return f"el build usaba {os.path.basename(cur) or 'otro compilador'} y ahora se usa {os.path.basename(want)}"
    gen = cache_value(build, "CMAKE_GENERATOR")
    if cfg.generator and gen and gen != cfg.generator:
        return f"el build usaba el generador «{gen}» y ahora «{cfg.generator}»"
    return sdk_mismatch(cfg, build)


def sdk_mismatch(cfg, build):
    """El build se configuró con otro SDK de rexglue (p. ej. ahora el que trae FSR/CAS)."""
    cur = cache_value(build, "rexglue_DIR")
    try:
        prefix = cfg.sdk_prefix()
    except Exception:      # noqa: BLE001
        prefix = ""
    if not cur or not prefix:
        return ""
    norm = lambda p: os.path.normcase(os.path.normpath(p.replace("/", os.sep)))  # noqa: E731
    if not norm(cur).startswith(norm(prefix)):
        return "el SDK de rexglue cambió (" + os.path.basename(os.path.dirname(norm(prefix))) + ")"
    return ""


def reset_cache(build):
    try:
        os.remove(os.path.join(build, "CMakeCache.txt"))
    except OSError:
        pass
    shutil.rmtree(os.path.join(build, "CMakeFiles"), ignore_errors=True)


def is_clang(path):
    return "clang" in os.path.basename(path or "").lower()


# ---------------------------------------------------------------- ejecutar el juego
def game_exe(root, fallback_name=""):
    """Ejecutable recompilado del proyecto (nombre real del manifiesto)."""
    from .core import find_outputs
    real = manifest_project_name(root) or fallback_name
    outs = find_outputs(os.path.join(root, "build"), real)
    want = real.lower()
    for o in outs:
        if os.path.splitext(os.path.basename(o))[0].lower() == want:
            return o
    return outs[0] if outs else ""


def consume_restart_flag(exe, max_age=120):
    """El juego se cerró para volver a abrirse solo (cargar una ranura del menú Guía): no es un fin de partida."""
    flag = os.path.join(os.path.dirname(exe or ""), "reforge_restart.flag")
    try:
        recent = time.time() - os.path.getmtime(flag) < max_age
    except OSError:
        return False
    try:
        os.remove(flag)
    except OSError:
        pass
    return recent


def rebuild_reason(root, exe, cfg=None):
    """Por qué el ejecutable no tiene lo último de ReForge (texto) o "" si está al día: extensión de una versión
    anterior, trucos/mejoras para PC o correcciones de funciones guardadas después de compilar."""
    if not exe or not os.path.isfile(exe):
        return ""
    try:
        built = os.path.getmtime(exe)
    except OSError:
        return ""
    try:
        from .game_options import GameOptions
        from . import ext_cpp
        if GameOptions.load(root).reforge_ext and os.path.isfile(os.path.join(root, "src", "main.cpp")):
            cpp = os.path.join(root, "src", "reforge_ext.cpp")
            try:
                cur = open(cpp, encoding="utf-8").read()
            except OSError:
                cur = None
            if cur is not None and cur != ext_cpp.EXT_SOURCE:
                return "el juego tiene la extensión ReForge de una versión anterior (sin las últimas mejoras)"
            if cur is not None and os.path.getmtime(cpp) > built + 2:
                return "la extensión ReForge se actualizó pero el juego no se volvió a compilar"
    except Exception:      # noqa: BLE001
        pass
    if cfg is not None:
        why = sdk_mismatch(cfg, os.path.join(root, "build"))
        if why:
            return why
    if codegen_opt_pending(root):
        return "hay una optimización del código recompilado sin aplicar (más rendimiento)"
    checks = [(os.path.join(root, "assets", "default.xexp"), "hay trucos o mejoras para PC sin compilar"),
              (os.path.join(root, FUNCTIONS_FILE), "hay correcciones de funciones sin compilar")]
    for path, why in checks:
        try:
            if path and os.path.getmtime(path) > built + 2:
                return why
        except OSError:
            pass
    return ""


def launch_args(exe, root):
    return [exe, f"--game_data_root={os.path.join(root, 'assets')}", "--gpu_plugin=xenos"]


def launch_env(cfg):
    env = dict(os.environ)
    prefix = cfg.sdk_prefix()
    if prefix:
        b = os.path.join(prefix, "bin")
        key = "Path" if ("Path" in env and "PATH" not in env) else "PATH"
        env[key] = b + os.pathsep + env.get(key, "")
    return env


def prepare_game_runtime(cfg, exe, root):
    """Stage the matching SDK GPU plugin beside the already-built executable."""
    if not os.path.isfile(os.path.join(root, "assets", "default.xex")):
        raise RuntimeError("No se encuentra assets/default.xex en este proyecto.")
    if sys.platform != "win32":
        return
    build_type = cache_value(os.path.join(root, "build"), "CMAKE_BUILD_TYPE") or cfg.build_type
    suffix = {"debug": "d", "relwithdebinfo": "rd"}.get(build_type.lower(), "")
    plugin = f"rexgpu-xenos{suffix}.dll"
    sdk_bin = os.path.join(cfg.sdk_prefix() or "", "bin")
    destination = os.path.dirname(exe)
    source = os.path.join(sdk_bin, plugin)
    if not os.path.isfile(source):
        raise RuntimeError(f"No se encuentra {plugin} en el SDK seleccionado. "
                           "Selecciona en Entorno el SDK con el que compilaste el juego.")
    # FidelityFX (FSR/CAS): solo existe en el SDK compilado con él; rexruntime.dll la necesita a su lado
    for name in (plugin, f"TracyClient{suffix}.dll", "amd_fidelityfx_dx12.dll", "amd_fidelityfx_vk.dll"):
        src = os.path.join(sdk_bin, name)
        dst = os.path.join(destination, name)
        if not os.path.isfile(src) or os.path.realpath(src) == os.path.realpath(dst):
            continue
        try:
            same = os.path.isfile(dst) and os.path.getsize(src) == os.path.getsize(dst) and \
                int(os.path.getmtime(src)) == int(os.path.getmtime(dst))
        except OSError:
            same = False
        if same:
            continue
        try:
            shutil.copy2(src, dst)
        except PermissionError:
            # el juego está abierto y tiene la DLL cargada: la que hay ya sirve si es la del mismo SDK
            if not os.path.isfile(dst):
                raise
    from .gameicon import ensure as ensure_icon      # icono oficial del juego en el .exe (nunca impide jugar)
    ensure_icon(exe, root, manifest_project_name(root) or "")
    try:      # base de mapeos de mando al día junto al juego (DualSense, DualShock 4, Switch Pro…); nunca impide jugar
        from . import controllerdb
        controllerdb.place(destination)
    except Exception:      # noqa: BLE001
        pass
    apply_visual_layers(root, exe)
    try:      # opciones al día también en los arranques vigilados (reparación automática, Live sin conexión…)
        from .game_options import GameOptions, write_runtime_config
        o = GameOptions.load(root)
        learned = learned_tune(exe)
        if learned.get("readback_resolve") and learned["readback_resolve"] != o.readback_mode:
            o.readback_mode = learned["readback_resolve"]          # lo que el guardián de imagen aprendió
            o.save(root)
        write_runtime_config(exe, o)
    except Exception:      # noqa: BLE001
        pass


def learned_tune(exe):
    """Ajustes que la extensión aprendió jugando (reforge_tune.ini junto al .exe)."""
    out = {}
    try:
        with open(os.path.join(os.path.dirname(exe), "reforge_tune.ini"), encoding="utf-8") as f:
            for ln in f:
                k, sep, v = ln.partition("=")
                if sep and not k.strip().startswith("#"):
                    out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def apply_visual_layers(root, exe="", log=None):
    """Iconos de botones (PlayStation con un DualSense/DualShock, o lo elegido) y packs de mods/.
    Con el SDK de ReForge (parche texswap en rexgpu-xenos.dll) los iconos se cambian en la GPU para cualquier
    juego y en caliente; si no, en las texturas .xpr del juego. Nunca impide jugar."""
    from .game_options import GameOptions
    msgs = []
    try:
        from . import controller, mods, texswap
        o = GameOptions.load(root)
        if exe:
            chosen = texswap.menu_style(exe)           # lo último elegido dentro del juego manda
            if chosen and chosen != o.button_style:
                o.button_style = chosen
                o.save(root)
        style = controller.resolve(o.button_style)
        gpu = bool(exe) and texswap.plugin_supports(os.path.join(os.path.dirname(exe), "rexgpu-xenos.dll"))
        if gpu:
            n = texswap.prepare(exe, root, style, learn=o.button_style != "xbox")
            texswap.start_live(exe, root)
            if n:
                msgs.append(f"🎮 {n} textura(s) de botones reconocidas en este juego (iconos de PlayStation).")
        file_style = "xbox" if gpu else style
        if file_style != "xbox" or os.path.isdir(mods.mods_dir(root)):
            msgs += mods.apply(root, file_style, set(o.mods_disabled or []))
    except Exception as e:      # noqa: BLE001
        msgs.append(f"⚠ Capas visuales no aplicadas: {e}")
    for m in msgs:
        (log or print)(m)
    return msgs


def popen_game(cfg, exe, root):
    """Lanza el juego con las optimizaciones de arranque (prioridad y GPU de alto rendimiento)."""
    from .game_options import GameOptions
    from .optimizer import launch_flags, quarantine_dxvk, set_gpu_preference
    o = GameOptions.load(root)
    moved = quarantine_dxvk(exe)
    if moved:
        print(f"[reforge] DLL de DXVK apartadas a _dxvk_desactivado: {', '.join(moved)} (rompen Direct3D 12)")
    if o.perf_mode != "off":
        set_gpu_preference(exe)
    return subprocess.Popen(launch_args(exe, root), cwd=os.path.dirname(exe), env=launch_env(cfg),
                            stdin=subprocess.DEVNULL, creationflags=launch_flags(o))


def launch_game(cfg, exe, root):
    from .game_options import GameOptions, write_runtime_config
    prepare_game_runtime(cfg, exe, root)
    try:
        write_runtime_config(exe, GameOptions.load(root))
    except OSError:
        pass
    write_launcher(exe, root, os.path.basename(root))
    return popen_game(cfg, exe, root)


def reforge_executable():
    """ReForgeStudio.exe instalado (para abrir el lanzador del juego); '' si se ejecuta desde código."""
    if getattr(sys, "frozen", False) and os.path.basename(sys.executable).lower().startswith("reforgestudio"):
        return sys.executable
    return ""


def write_launcher(exe, root, title):
    """Crea «Jugar <título>.bat» (abre el lanzador del juego) y «Jugar <título> (directo).bat»
    junto al .exe. Devuelve la ruta del principal."""
    if sys.platform != "win32":
        path = os.path.join(os.path.dirname(exe), f"jugar_{os.path.basename(exe)}.sh")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f'#!/bin/sh\ncd "$(dirname "$0")"\nexec "./{os.path.basename(exe)}" '
                    f'"--game_data_root={os.path.join(root, "assets")}" --gpu_plugin=xenos "$@"\n')
        os.chmod(path, 0o755)
        return path
    direct = os.path.join(os.path.dirname(exe), f"Jugar {title} (directo).bat")
    with open(direct, "w", encoding="utf-8") as f:
        f.write("@echo off\r\nchcp 65001 >nul\r\ncd /d \"%~dp0\"\r\n"
                f"start \"\" \"%~dp0{os.path.basename(exe)}\" \"--game_data_root={os.path.join(root, 'assets')}\" --gpu_plugin=xenos %*\r\n")
    rf = reforge_executable()
    path = os.path.join(os.path.dirname(exe), f"Jugar {title}.bat")
    if not rf:
        shutil.copyfile(direct, path)
        return path
    with open(path, "w", encoding="utf-8") as f:
        f.write("@echo off\r\nchcp 65001 >nul\r\n"
                f"if exist \"{rf}\" (\r\n  start \"\" \"{rf}\" --launcher \"{os.path.abspath(root)}\"\r\n) else (\r\n"
                f"  call \"%~dp0Jugar {title} (directo).bat\"\r\n)\r\n")
    return path


def desktop_shortcut(exe, root, title):
    """Acceso directo en el Escritorio: abre el lanzador del juego (motor, idioma, controles)."""
    if sys.platform != "win32":
        raise RuntimeError("Solo disponible en Windows")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                       capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL, timeout=30, creationflags=NO_WINDOW)
    desk = r.stdout.strip()
    lnk = os.path.join(desk, f"{title}.lnk")
    esc = lambda s: s.replace("'", "''")  # noqa: E731
    rf = reforge_executable()
    if rf:
        target, args, workdir = rf, f'--launcher "{os.path.abspath(root)}"', os.path.dirname(rf)
    else:
        target, args, workdir = exe, f'--game_data_root="{os.path.join(root, "assets")}" --gpu_plugin=xenos', os.path.dirname(exe)
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                    f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{esc(lnk)}');"
                    f"$s.TargetPath='{esc(target)}';$s.Arguments='{esc(args)}';"
                    f"$s.WorkingDirectory='{esc(workdir)}';$s.IconLocation='{esc(exe)},0';"
                    f"$s.Description='{esc(title)} · ReForge';$s.Save()"],
                   capture_output=True, timeout=60, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    return lnk


# ---------------------------------------------------------------- reparar arranque
RUNTIME_SPLIT_RE = re.compile(r"Unresolved (?:branch|call) from 0x([0-9A-Fa-f]{8}) to 0x([0-9A-Fa-f]{8})")
RUNTIME_UNREG_RE = re.compile(r"Call to invalid or unregistered function at guest address 0x([0-9A-Fa-f]{8})")
RUNTIME_BAD_RE = re.compile(r"\[(critical|error)\]")


def game_log_dir(exe):
    return os.path.join(os.path.dirname(exe), "logs")


def _read_log_text(path):
    """El texto de un log, o '' si no se puede leer."""
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def newest_log(exe, since=0.0):
    import glob
    logs = [p for p in glob.glob(os.path.join(game_log_dir(exe), "*.log")) if os.path.getmtime(p) >= since]
    return max(logs, key=os.path.getmtime) if logs else ""


# Mensajes de [error] que rexglue escribe en todos los juegos y no cierran nada.
HARMLESS_ERROR_RE = re.compile(r"ResolvePath\((cache|ShaderDump)[^)]*\) failed|Unimplemented XLIVEBASE message|"
                               r"device not found|\[NtCreateFile\] FAILED")
CLEAN_EXIT_RE = re.compile(r"Window closing, shutting down|Title terminated")
HOTPLUG_RE = re.compile(r"Controller disconnected from slot")
GUEST_AV_RE = re.compile(r"Unhandled guest access violation: (read|write) of guest 0x([0-9A-Fa-f]{8})")
CRASH_CODES = {
    0xC0000005: "acceso a memoria no válido (0xC0000005)",
    0xC0000374: "memoria dañada (0xC0000374)",
    0xC000001D: "instrucción no válida (0xC000001D)",
    0xC0000409: "comprobación de seguridad (0xC0000409)",
    0xC00000FD: "desbordamiento de pila (0xC00000FD)",
    0x80000003: "punto de ruptura de depuración (0x80000003)",
}


def crash_description(exit_code):
    """Texto del código de salida de Windows si es un cierre por fallo; '' si no lo es."""
    if exit_code is None:
        return ""
    code = int(exit_code) & 0xFFFFFFFF
    if code in CRASH_CODES:
        return CRASH_CODES[code]
    return f"código 0x{code:08X}" if code >= 0xC0000000 else ""


def analyze_runtime_log(path, exit_code=None):
    """{'kind': 'unregistered'|'fatal'|'crash'|'clean'|'nolog', 'address': int|None, 'lines': [...]}
    'crash': el proceso cayó sin dejar el motivo en el log (fallo dentro del runtime). 'hotplug': True si el
    mando se desconectó justo antes (fallo conocido del controlador SDL de rexglue)."""
    crash = crash_description(exit_code)
    if not path or not os.path.isfile(path):
        if crash:
            return {"kind": "crash", "address": None, "lines": [], "path": path, "crash": crash, "hotplug": False}
        return {"kind": "nolog", "address": None, "lines": [], "path": path}
    txt = Path(path).read_text(encoding="utf-8", errors="replace")
    m = RUNTIME_UNREG_RE.search(txt)
    bad = [ln for ln in txt.splitlines() if RUNTIME_BAD_RE.search(ln) and not HARMLESS_ERROR_RE.search(ln)]
    tail = txt.splitlines()[-40:]
    hotplug = any(HOTPLUG_RE.search(ln) for ln in tail)
    if m:
        return {"kind": "unregistered", "address": int(m.group(1), 16), "lines": bad[-6:], "path": path}
    sb = RUNTIME_SPLIT_RE.search(txt)
    if sb:
        return {"kind": "split", "address": None, "lines": bad[-6:], "path": path,
                "branch": (int(sb.group(1), 16), int(sb.group(2), 16))}
    av = GUEST_AV_RE.search(txt)
    if av:
        at = CRASH_AT_RE.search(txt)
        if at:
            bad = bad + [at.group(0)]
        return {"kind": "guest_av", "address": None, "lines": bad[-6:], "path": path, "crash": crash,
                "access": av.group(1), "guest_address": int(av.group(2), 16), "hotplug": hotplug}
    if crash:
        return {"kind": "crash", "address": None, "lines": bad[-8:], "path": path, "crash": crash,
                "hotplug": hotplug}
    if bad and not CLEAN_EXIT_RE.search(txt):
        return {"kind": "fatal", "address": None, "lines": bad[-8:], "path": path}
    return {"kind": "clean", "address": None, "lines": [], "path": path}


ONLINE_STUB_RE = re.compile(r"__imp__(XamGetToken|XamGetServiceEndpoint|NetDll_XHttp\w+|XampXAuth\w+|XOnline\w+|"
                            r"NetDll_XNetLogon\w+|XamUserGetOnlineCountryFromXUID|XStorage\w+|XMarketplace\w+|"
                            r"XSession\w+|XUserReadStats|XUserWriteAchievements_never)\s+STUB")
CRASH_LINE_RE = re.compile(r"Unhandled guest access violation|\[FATAL\]|SEH exception caught")


def online_crash(log_path, window=12):
    """¿El juego cayó justo después de llamar a funciones de Xbox Live que el runtime no implementa? (con
    «Live simulado» los juegos entran en su código online y leen datos que nunca llegan)."""
    try:
        lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for i, ln in enumerate(lines):
        if CRASH_LINE_RE.search(ln):
            near = lines[max(0, i - window):i]
            return sorted({m.group(1) for x in near for m in [ONLINE_STUB_RE.search(x)] if m})
    return []


def recent_crash_dump(exe, since):
    """Volcado de Windows del juego creado después de `since` (el juego cayó aunque el log no lo diga)."""
    base = os.environ.get("LOCALAPPDATA") or ""
    folder = os.path.join(base, "CrashDumps") if base else ""
    name = os.path.basename(exe).lower()
    best = ""
    try:
        for f in os.listdir(folder):
            if f.lower().startswith(name + ".") and f.lower().endswith(".dmp"):
                p = os.path.join(folder, f)
                if os.path.getmtime(p) >= since - 2:
                    best = p
    except OSError:
        return ""
    return best


def session_result(exe, log, started):
    """Análisis de una partida que ya terminó (lanzada desde cualquier sitio): log + volcado de Windows."""
    dump = recent_crash_dump(exe, started)
    info = analyze_runtime_log(log, 0xC0000005 if dump else None)
    if dump:
        info["dump"] = dump
    return info


def crash_advice(info):
    """Explicación para el jugador de un cierre 'crash' o 'guest_av'."""
    if info.get("kind") == "guest_av":
        a = info.get("guest_address", 0)
        what = "lectura" if info.get("access") == "read" else "escritura"
        null = " (un puntero nulo: el juego usó un objeto que no llegó a crearse)" if a < 0x10000 else ""
        return (f"El código del juego hizo una {what} en una dirección no válida 0x{a:08X}{null}.")
    msg = f"El juego se cerró por un fallo del runtime de rexglue ({info.get('crash', '?')}), sin mensaje en el log."
    if info.get("hotplug"):
        msg += (" Justo antes el mando se desconectó y reconectó: el controlador SDL de rexglue 0.10 daña la "
                "memoria al reconectar. Con mandos de Xbox usa «XInput» (Opciones → Controles; «Automático» "
                "ya lo elige) y revisa el cable/receptor del mando.")
    return msg


def declare_runtime_function(root, address):
    """Declara una función descubierta en ejecución. Devuelve False si ya estaba (o si no es válida).

    Si la dirección cae fuera del módulo del juego no es una función: es un salto a través de un puntero
    dañado. Declararla haría que el runtime rechazara toda la tabla al arrancar, así que se anota como
    no-función y no se declara.
    """
    if address in declared_functions(root):
        return False
    if not in_module(root, address):
        reject_functions(root, [(address, "fuera del modulo del juego: puntero danado, no una funcion")])
        return False
    ensure_include(root)
    path = os.path.join(root, FUNCTIONS_FILE)
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("# ReForge Studio: funciones declaradas automáticamente.\n\n[functions]\n")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"0x{address:08X} = {{}}  # llamada indirecta detectada al ejecutar el juego\n")
    return True


RUNTIME_FATAL_RE = re.compile(r"\[FATAL\]")


def _kill_tree(proc):
    """El runtime llama a std::abort() en un [FATAL]; en Windows eso abre el cuadro «dejó de funcionar»
    y el proceso NO termina hasta cerrarlo. Se cierra a la fuerza con todo su árbol."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=30)
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def _log_has_fatal(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return bool(RUNTIME_FATAL_RE.search(f.read()))
    except OSError:
        return False


def _log_snapshot(exe):
    import glob
    out = {}
    for f in glob.glob(os.path.join(game_log_dir(exe), "*.log")):
        try:
            st = os.stat(f)
            out[f] = (st.st_mtime_ns, st.st_size)
        except OSError:
            pass
    return out


def _fresh_log(exe, before):
    """El log de ESTA ejecución: nuevo o modificado desde la foto tomada antes de lanzar."""
    now = _log_snapshot(exe)
    fresh = [f for f, sig in now.items() if before.get(f) != sig]
    return max(fresh, key=lambda f: now[f][0]) if fresh else ""


def _looks_hung(log_path, quiet_s=20.0):
    """El juego no entregó ninguna imagen (la extensión anota los FPS cada 5 s) y el log no se mueve."""
    import time
    try:
        txt = open(log_path, encoding="utf-8", errors="replace").read()
        quiet = time.time() - os.path.getmtime(log_path)
    except OSError:
        return False
    return "[ReForge] FPS" not in txt and "[ReForge] Tir" not in txt and quiet >= quiet_s


def launch_and_watch(cfg, exe, root, seconds, ctx, detect_hang=False):
    """Lanza el juego y lo vigila leyendo su log. Si sigue abierto y sin [FATAL] pasados `seconds`,
    se deja corriendo. Si el log muestra un [FATAL] (aunque Windows mantenga el proceso colgado en el
    cuadro de error), se cierra y se devuelve el análisis."""
    import time
    prepare_game_runtime(cfg, exe, root)
    before = _log_snapshot(exe)
    t0 = time.time()
    p = popen_game(cfg, exe, root)
    ctx.log(f"▶ {os.path.basename(exe)} (pid {p.pid}) · vigilando {seconds} s…")
    log_path, last_size, killed = "", -1, False
    while time.time() - t0 < seconds:
        if p.poll() is not None:
            break
        if ctx.cancelled():
            _kill_tree(p)
            raise RuntimeError("Cancelado por el usuario")
        log_path = _fresh_log(exe, before) or log_path
        if log_path:
            try:
                size = os.path.getsize(log_path)
            except OSError:
                size = -1
            if size != last_size:
                last_size = size
                if _log_has_fatal(log_path):
                    time.sleep(0.5)
                    ctx.log("El juego registró un error [FATAL]; se cierra para repararlo.", "warn")
                    _kill_tree(p)
                    killed = True
                    break
        ctx.progress(int((time.time() - t0) * 10), seconds * 10)
        time.sleep(0.25)
    if p.poll() is None and not killed:
        log_path = _fresh_log(exe, before) or log_path
        if detect_hang and log_path and _looks_hung(log_path):
            ctx.log("El juego sigue abierto pero no ha dibujado ni una imagen y su log lleva más de 20 s sin "
                    "moverse: está colgado.", "warn")
            _kill_tree(p)
            return {"kind": "hang", "address": None, "lines": [], "path": log_path, "exit_code": None,
                    "seconds": round(time.time() - t0, 1)}
        if not (log_path and _log_has_fatal(log_path)):
            return {"kind": "running", "address": None, "lines": [], "path": log_path, "pid": p.pid,
                    "proc": p, "before": before}
        _kill_tree(p)
    time.sleep(0.5)
    res = analyze_runtime_log(_fresh_log(exe, before) or log_path, None if killed else p.returncode)
    res["exit_code"] = p.returncode
    res["seconds"] = round(time.time() - t0, 1)
    return res


def check_running_game(exe, res):
    """Para el juego ya en marcha (resultado 'running'): None si sigue bien; si apareció un [FATAL] o
    terminó, lo cierra y devuelve el análisis del log."""
    p = res.get("proc")
    if p is None:
        return None
    path = _fresh_log(exe, res.get("before", {})) or res.get("path", "")
    fatal = bool(path) and _log_has_fatal(path)
    if p.poll() is None and not fatal:
        return None
    if p.poll() is None:
        _kill_tree(p)
    out = analyze_runtime_log(path, p.returncode)
    out["exit_code"] = p.returncode
    return out


def ext_build_failed(lines):
    """¿Falló la compilación por la extensión ReForge (src/reforge_ext.cpp)?"""
    return any("reforge_ext" in ln and ("error" in ln.lower() or "FAILED" in ln) for ln in lines)


def _audit(lines, build, ctx):
    """Revisa los avisos del compilador de esta compilación (los críticos se anotan en el log)."""
    try:
        from .sweep import audit_build_warnings
        a = audit_build_warnings(lines, build)
    except Exception:      # noqa: BLE001
        return
    if a["critical"]:
        ctx.log(f"⚠ Avisos del compilador que pueden cambiar lo que hace el código: "
                + ", ".join(f"{k} ×{v}" for k, v in a["critical"].items()), "warn")


def build_with_ext_fallback(cfg, root, build, env, ctx):
    """Compila el juego. Si falla por la extensión ReForge, la quita del proyecto y compila sin ella:
    el juego sigue funcionando (sin perfil, idioma ni notificación propia) en vez de quedar sin .exe."""
    from .core import cmake_build_cmd, cmake_configure_cmd
    ensure_link_map(root)
    if exception_handlers_enabled(root) and ensure_seh_header(root):
        ctx.log("🔧 Manejadores de excepciones activos: añadido el encabezado SEH que el SDK no incluye.", "dim")
    rc, lines = run_streaming(cmake_build_cmd(cfg, build), root, env, ctx)
    if rc == 0:
        _audit(lines, build, ctx)
        return
    if any(SEH_UNDECLARED_RE.search(ln) for ln in lines) and ensure_seh_header(root):
        ctx.log("↻ El código usa SEH_TRY sin su encabezado (fallo del SDK): añadido y compilando de nuevo…", "warn")
        rc, lines = run_streaming(cmake_build_cmd(cfg, build), root, env, ctx)
        if rc == 0:
            _audit(lines, build, ctx)
            return
    if any(UNDECLARED_LABEL_RE.search(ln) for ln in lines):
        fixed = fix_truncated_functions(root, ctx)
        if fixed:
            ctx.log(f"↻ {len(fixed)} función(es) cortadas por el análisis de rexglue: declarado su final real en "
                    f"{FUNCTIONS_FILE}. Regenerando y compilando de nuevo…", "warn")
            name = manifest_project_name(root) or os.path.basename(root)
            codegen_with_autofix(cfg, root, build, name, env, ctx)
            rc, lines = run_streaming(cmake_build_cmd(cfg, build), root, env, ctx)
            if rc == 0:
                _audit(lines, build, ctx)
                return
    if ext_build_failed(lines):
        from .ext_cpp import remove_reforge_ext
        from .game_options import GameOptions
        ctx.log("La extensión ReForge no compiló en este juego: se quita y se compila sin ella…", "warn")
        remove_reforge_ext(root)
        o = GameOptions.load(root)
        o.reforge_ext = False
        o.save(root)
        rc, _ = run_streaming(cmake_configure_cmd(cfg, root, build), root, env, ctx)
        if rc == 0:
            rc, _ = run_streaming(cmake_build_cmd(cfg, build), root, env, ctx)
        if rc == 0:
            ctx.log("✔ Compilado sin la extensión ReForge. Perfil, idioma y notificación de logros quedan "
                    "desactivados en este juego (puedes reactivarlos en 🎮 Opciones tras actualizar ReForge).", "warn")
            return
    raise RuntimeError(f"El proceso terminó con código {rc}")
