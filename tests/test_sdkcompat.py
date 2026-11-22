"""Validación de compatibilidad SDK ↔ proyecto (sdkcompat)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import sdkcompat  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


def _proj(target):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "generated"), exist_ok=True)
    with open(os.path.join(d, "generated", "rexglue.cmake"), "w", encoding="utf-8") as f:
        f.write(f"target_link_libraries(juego PRIVATE {target})\n")
    return d


def _sdk(*targets):
    p = tempfile.mkdtemp()
    d = os.path.join(p, "lib", "cmake", "rexglue")
    os.makedirs(d)
    with open(os.path.join(d, "rexglueTargets.cmake"), "w", encoding="utf-8") as f:
        f.write("\n".join(f"add_library({t} SHARED IMPORTED)" for t in targets))
    return p


print("Detección de targets necesarios")
proj = _proj("rex::runtime")
check(sdkcompat.needed_targets(proj) == {"rex::runtime"}, "lee rex::runtime del proyecto generado")
check(sdkcompat.needed_targets(tempfile.mkdtemp()) == set(), "proyecto no generado → nada que validar")

print("Compatibilidad")
sdk10 = _sdk("rex::runtime", "rex::gpu")
sdk11 = _sdk("rexglue::runtime", "rexglue::gpu")   # 0.11 renombró el target
needed = sdkcompat.needed_targets(proj)
check(sdkcompat.sdk_covers(sdk10, needed) is True, "SDK con rex::runtime es compatible")
check(sdkcompat.sdk_covers(sdk11, needed) is False, "SDK que renombró el target NO es compatible")
check(sdkcompat.sdk_covers(tempfile.mkdtemp(), needed) is True, "SDK ilegible no bloquea (fail-open)")

print("Orden de versión (elige el mejor)")
vs = ["0.9.0.1", "0.10.0.24-dev.gfff-fsr", "0.11.0.13-dev.gaaa", "0.10.0.24-dev.gfff"]
best = sorted(vs, key=lambda v: (sdkcompat._version_key(v), v.endswith("-fsr")), reverse=True)[0]
check(best == "0.11.0.13-dev.gaaa", "la versión más alta va primero")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
