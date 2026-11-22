"""Parches NATIVOS a nivel de codegen (desbloqueo de FPS y similares) para rexglue.

Por qué este módulo existe y qué NO hace:

rexglue (como XenonRecomp, del que deriva) NO aplica «pokes» de memoria en runtime como Xenia. El código PPC
ya está traducido a C++, así que escribir un byte en una dirección guest no cambia nada. Los cambios nativos se
hacen en el **codegen**, con los mecanismos que trae el SDK (verificados en include/rex/ppc/midasm.h y
src/codegen/config_keys.cpp):

* `REX_MIDASM_BRANCH(nombre, (params)) { return bool; }` + `REX_MIDASM_AT(nombre, dir, before, destino, regs)`:
  cuando el cuerpo devuelve true, el código salta a `destino`. Un cuerpo que siempre devuelve true y salta a la
  instrucción siguiente equivale a un `nop` nativo de la instrucción original (así se porta un «Unlock FPS» de
  Xenia, que nopea la instrucción del tope de fotogramas).
* `REX_MIDASM_HOOK(nombre, (PPCRegister& r)) { ... }`: ejecuta C++ en una instrucción y puede tocar registros.

GUARDA DE VERSIÓN (imprescindible): las direcciones de un parche valen para un `default.xex` concreto. Con un
title update aplicado las direcciones se desplazan, así que un parche del juego base NO sirve tal cual en una
versión actualizada. `applies_to_version` + `version_ok` evitan aplicar un parche a una versión que no le toca.

Este módulo solo GENERA el C++ y escribe/retira los archivos; no se engancha solo al pipeline. Es opt-in,
reversible y experimental hasta que se valida por juego.
"""
import os
import re

HOOK_FILE = "src/reforge_hooks.cpp"          # se compila con el proyecto (src ya entra en el build)
HOOK_INCLUDE = "reforge_hooks.toml"          # se añade a includes del manifest (como reforge_functions.toml)
_MARK = "// ReForge: hooks nativos generados — no editar a mano"


def _ident(address):
    return f"ReforgeHook_{address & 0xFFFFFFFF:08x}"


def hook_cpp(ops):
    """Genera el texto C++ del archivo de hooks a partir de una lista de operaciones.

    Cada op es un dict:
      {"kind": "skip", "address": 0x824d7130}            → nopea la instrucción (salta a address+4)
      {"kind": "skip_to", "address": 0x..., "target": 0x...}  → salta de address a target
    """
    lines = [_MARK, "#include <rex/ppc/midasm.h>", ""]
    for op in ops:
        addr = int(op["address"])
        if op.get("kind") in ("skip", "skip_to"):
            target = int(op.get("target") or (addr + 4))
            name = _ident(addr)
            lines.append(f"REX_MIDASM_BRANCH({name}, ()) {{ return true; }}")
            lines.append(f"REX_MIDASM_AT({name}, 0x{addr:08x}, before, 0x{target:08x});")
            lines.append("")
        else:
            raise ValueError(f"operación de parche no soportada: {op.get('kind')!r}")
    return "\n".join(lines).rstrip() + "\n"


def validate_ops(ops):
    """Comprueba que las operaciones son aplicables (direcciones múltiplo de 4, no nulas). Devuelve [errores]."""
    errs = []
    for op in ops or []:
        for key in ("address",) + (("target",) if op.get("target") is not None else ()):
            v = int(op.get(key) or 0)
            if v == 0 or v % 4 != 0:
                errs.append(f"{op.get('kind','?')}: {key}=0x{v:08x} debe ser múltiplo de 4 y no nulo")
    return errs


def _xex_info(root):
    try:
        from .xex import read_xex_info
        return read_xex_info(os.path.join(root, "assets", "default.xex")) or {}
    except Exception:      # noqa: BLE001
        return {}


def project_version(root):
    """Versión del juego del proyecto (p. ej. '0.0.1.5'), o '' si no se puede leer."""
    info = _xex_info(root)
    return str(info.get("version") or info.get("title_version") or "").strip()


def has_title_update(root):
    """True si el proyecto tiene un title update aplicado (lo anota reforge_functions.toml: 'tu-<versión>')."""
    try:
        with open(os.path.join(root, "reforge_functions.toml"), encoding="utf-8", errors="replace") as f:
            head = f.read(400)
        return bool(re.search(r"\btu-\d", head))
    except OSError:
        return False


def version_ok(root, applies_to_version):
    """(ok, motivo). Si el parche declara una versión y no coincide con la del proyecto, no se debe aplicar."""
    if not applies_to_version:
        return True, ""
    pv = project_version(root)
    if applies_to_version == "base" and has_title_update(root):
        return False, ("el parche es para el juego BASE, pero este proyecto tiene un title update aplicado "
                       f"({'tu ' + pv if pv else 'TU'}); las direcciones no coinciden")
    if pv and applies_to_version not in ("base", pv):
        return False, f"el parche es para la versión {applies_to_version} y el proyecto es {pv}"
    return True, ""


def is_applied(root):
    path = os.path.join(root, HOOK_FILE)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return _MARK in f.read(200)
    except OSError:
        return False


def _ensure_include(root):
    """Añade reforge_hooks.toml a includes del manifest y deja hook_sources=['src'] en ese include."""
    import glob
    # include con hook_sources (igual que reforge_functions.toml aporta [functions])
    inc = os.path.join(root, HOOK_INCLUDE)
    if not os.path.isfile(inc):
        with open(inc, "w", encoding="utf-8") as f:
            f.write("# ReForge Studio: hooks nativos (mid-asm). Generado; no editar a mano.\n"
                    'hook_sources = ["src"]\n')
    # añadir el include al manifest si no está
    for man in glob.glob(os.path.join(root, "*_manifest.toml")):
        txt = open(man, encoding="utf-8", errors="replace").read()
        if HOOK_INCLUDE in txt:
            continue
        m = re.search(r"(includes\s*=\s*\[)([^\]]*)\]", txt)
        if m:
            inner = m.group(2).rstrip()
            sep = "" if inner.strip().endswith(",") or not inner.strip() else ", "
            new = f'{m.group(1)}{inner}{sep}"{HOOK_INCLUDE}"]'
            txt = txt[:m.start()] + new + txt[m.end():]
        else:   # no hay includes: añadir bajo [entrypoint]
            txt = re.sub(r"(\[entrypoint\][^\[]*)", r'\1includes = ["' + HOOK_INCLUDE + '"]\n', txt, count=1)
        with open(man, "w", encoding="utf-8") as f:
            f.write(txt)


def apply(root, ops, applies_to_version=""):
    """Escribe el archivo de hooks y lo engancha al codegen. (ok, mensaje).

    No comprueba la versión por su cuenta more allá de version_ok; el llamador decide. Reversible con remove().
    """
    errs = validate_ops(ops)
    if errs:
        return False, "No se aplicó el desbloqueo nativo: " + "; ".join(errs)
    ok, motivo = version_ok(root, applies_to_version)
    if not ok:
        return False, "No se aplicó el desbloqueo nativo: " + motivo + "."
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    with open(os.path.join(root, HOOK_FILE), "w", encoding="utf-8") as f:
        f.write(hook_cpp(ops))
    _ensure_include(root)
    return True, f"Desbloqueo nativo preparado ({len(ops)} hook(s)). Recompila para aplicarlo."


def remove(root):
    """Quita el archivo de hooks y su include. True si había algo que quitar."""
    changed = False
    p = os.path.join(root, HOOK_FILE)
    if os.path.isfile(p):
        os.remove(p)
        changed = True
    inc = os.path.join(root, HOOK_INCLUDE)
    if os.path.isfile(inc):
        os.remove(inc)
        changed = True
    import glob
    for man in glob.glob(os.path.join(root, "*_manifest.toml")):
        txt = open(man, encoding="utf-8", errors="replace").read()
        new = re.sub(r'\s*,?\s*"' + re.escape(HOOK_INCLUDE) + r'"', "", txt)
        if new != txt:
            with open(man, "w", encoding="utf-8") as f:
                f.write(new)
            changed = True
    return changed


def describe(ops, accelerates=True):
    """Texto honesto de lo que hace el parche, con el aviso de aceleración si procede."""
    n = len(ops or [])
    base = f"Desbloqueo de FPS nativo: {n} hook(s) mid-asm que saltan la instrucción del tope de fotogramas."
    if accelerates:
        base += (" ⚠ En un juego con la lógica atada al framerate, esto ACELERA cinemáticas, físicas y QTE. "
                 "Para fluidez sin acelerar, usa Movimiento Suave (interpolación del driver) o un parche de "
                 "timestep específico del juego.")
    return base
