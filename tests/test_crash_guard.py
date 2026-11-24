"""Cierres del runtime: análisis del log/código de salida y mandos en serie.
   python tests/test_crash_guard.py"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-crash-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
sys.path.insert(0, ROOT)

from reforge import ext_cpp, game, game_options as go  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


# Final real del log de Gears of War 2 (13:17, cierre con 0xC0000005 dentro de rexruntime).
LOG = """[2026-10-16 13:15:49.189] [warning] [fs] [t23772] VFS: 'cache:\\' -> [no device]
[2026-10-16 13:15:49.189] [error] [fs] [t23772] ResolvePath(cache:\\) failed - device not found
[2026-10-16 13:15:51.442] [error] [krnl] [t23772] Unimplemented XLIVEBASE message app=000000FC, msg=00058009, arg1=70189E10, arg2=00000010
[2026-10-16 13:16:11.018] [error] [krnl] [t23772] Unimplemented XLIVEBASE message app=000000FC, msg=00058009, arg1=7018BDC0, arg2=00000010
[2026-10-16 13:17:16.836] [info] [core] [t10600] Controller disconnected from slot 0.
[2026-10-16 13:17:16.849] [info] [core] [t23772] New controller connected to slot 0.
"""
print("Análisis del cierre")
lp = os.path.join(TMP, "g_036.log")
open(lp, "w", encoding="utf-8").write(LOG)
r = game.analyze_runtime_log(lp, 0xC0000005)
check(r["kind"] == "crash" and r["hotplug"] and r["lines"] == [],
      "0xC0000005 sin mensaje: fallo del runtime (no los avisos de cache:\\ ni XLIVEBASE)")
adv = game.crash_advice(r)
check("acceso a memoria" in adv and "XInput" in adv, "explica el fallo y el mando reconectado")
check(game.analyze_runtime_log(lp, 0)["kind"] == "clean", "salida normal: esos avisos no son un error")
open(lp, "a", encoding="utf-8").write("[info] Window closing, shutting down...\n[info] Title terminated; hard-exiting process.\n")
check(game.analyze_runtime_log(lp)["kind"] == "clean", "cerrar la ventana es una salida limpia")
check(game.analyze_runtime_log("", 3221225477)["kind"] == "crash", "sin log pero con código de fallo → crash")
check(game.crash_description(1) == "" and "0xC0000374" in game.crash_description(0xC0000374),
      "solo los códigos de fallo de Windows cuentan")

AV = ("[2026-10-16 14:42:22.600] [info] [gpu] [t27192] SetInterruptCallback(823BE628, 40001A80)\n"
      "[2026-10-16 14:42:22.601] [error] [sys] [t27192] Unhandled guest access violation: read of guest 0x000001A4 "
      "(host 0x00000001000001A4) on thread 0xF8000028\n")
open(lp, "w", encoding="utf-8").write(AV)
r = game.analyze_runtime_log(lp, 0xC0000005)
check(r["kind"] == "guest_av" and r["guest_address"] == 0x1A4 and r["access"] == "read",
      "acceso inválido del código del juego (Fast & Furious Showdown): dirección y tipo")
check("puntero nulo" in game.crash_advice(r) and "sin mensaje" not in game.crash_advice(r),
      "lo explica (ya no dice «sin mensaje en el log»)")

print("setjmp / longjmp (libjpeg de Fast & Furious Showdown)")
def fn(addr, ins):
    return f"DEFINE_REX_FUNC(sub_{addr:08X}) {{\n" + "".join(f"\t// {i}\n\tctx.x=0;\n" for i in ins) + "}\n\n"
regs = list(range(13, 32))
SJ = (["lis r4,-32170", "lwz r0,-7760(r4)", "cmpwi r0,0", "mtctr r0", "bnectr", "mflr r0", "mfcr r4"]
      + [f"stfd f{i},{(i-14)*8}(r3)" for i in range(14, 32)] + [f"std r{r},{152+(r-13)*8}(r3)" for r in regs]
      + ["stw r0,308(r3)", "stw r4,304(r3)", "std r1,144(r3)", "li r0,0", "stw r0,312(r3)", "li r3,0", "blr"])
LJ = (["mflr r0", "stwu r1,-80(r1)", "stw r0,8(r1)", "mr r6,r4", "cmpwi r4,0", "lwz r0,312(r3)", "mr r7,r3"]
      + [f"ld r{r},{152+(r-13)*8}(r7)" for r in regs] + ["lwz r5,308(r7)", "mtlr r5", "ld r1,144(r7)", "mr r3,r6", "blr"])
OTHER = ["cmpwi cr6,r4,0", "lwz r11,168(r3)", "li r3,0", "blr"] * 6
proj = os.path.join(TMP, "ff")
gen = os.path.join(proj, "generated", "default")
os.makedirs(gen)
open(os.path.join(gen, "ffshowdown_recomp.0.cpp"), "w").write(fn(0x824D6670, SJ) + fn(0x823FE5E0, LJ) + fn(0x8232B7E8, OTHER))
check(game.detect_setjmp_longjmp(gen) == (0x824D6670, 0x823FE5E0), "reconoce setjmp y longjmp por su forma")
open(os.path.join(proj, "ffshowdown_manifest.toml"), "w").write(
    '[project]\nname = "ffshowdown"\n\n[entrypoint]\nfile_path = "assets/default.xex"\n'
    'includes = ["reforge_functions.toml"]\n')
check(game.ensure_setjmp(proj) == (0x824D6670, 0x823FE5E0), "los declara en el manifiesto")
man = open(os.path.join(proj, "ffshowdown_manifest.toml")).read()
check("setjmp_address = 0x824D6670" in man and "longjmp_address = 0x823FE5E0" in man and game.ensure_setjmp(proj) is None,
      "en [entrypoint] y una sola vez")
import tomllib  # noqa: E402
check(tomllib.loads(man)["entrypoint"]["setjmp_address"] == 0x824D6670, "el manifiesto sigue siendo TOML válido")

print("Mandos en serie (rexglue reconstruye la lista sin cerrojo)")
src = ext_cpp.EXT_SOURCE
for name in ("XamInputGetCapabilities", "XamInputGetState", "XamInputSetState", "XamInputGetKeystroke"):
    check(f"REX_HOOK(__imp__{name}, reforge::{name}_hook)" in src and f"{name}_entry(" in src,
          f"{name}: pasa por un cerrojo y llama a la implementación de rexglue")
check(src.count("std::lock_guard<std::mutex> lock(InputMutex());") == 7, "las 6 funciones de mando y el menú Guía comparten cerrojo")

print("Backend de mando automático")
check(go.GameOptions().input_backend == "auto", "por defecto: automático")
check(go.resolve_input_backend("sdl") == "sdl" and go.resolve_input_backend("xinput") == "xinput",
      "la elección manual se respeta")
check(go.resolve_input_backend("auto") in ("sdl", "xinput"), "automático elige uno de los dos")
root = os.path.join(TMP, "p")
os.makedirs(root)
json.dump({"input_backend": "sdl"}, open(os.path.join(root, go.OPTIONS_FILE), "w"))
check(go.GameOptions.load(root).input_backend == "auto", "«sdl» de versiones anteriores pasa a automático")
json.dump({"input_backend": "sdl", "input_backend_chosen": True}, open(os.path.join(root, go.OPTIONS_FILE), "w"))
check(go.GameOptions.load(root).input_backend == "sdl", "si lo eligió el jugador, se queda")

print("¿El juego compilado tiene lo último?")
import time  # noqa: E402
rr = os.path.join(TMP, "rebuild")
os.makedirs(os.path.join(rr, "src"))
os.makedirs(os.path.join(rr, "build"))
os.makedirs(os.path.join(rr, "assets"))
open(os.path.join(rr, "src", "main.cpp"), "w").write("")
open(os.path.join(rr, "src", "reforge_ext.cpp"), "w", encoding="utf-8", newline="\n").write(ext_cpp.EXT_SOURCE)
old = time.time() - 600
os.utime(os.path.join(rr, "src", "reforge_ext.cpp"), (old, old))
rexe = os.path.join(rr, "build", "juego.exe")
open(rexe, "w").write("")
check(game.rebuild_reason(rr, rexe) == "", "al día: no hace falta recompilar")
open(os.path.join(rr, "src", "reforge_ext.cpp"), "w", encoding="utf-8").write("// extensión de la 1.14")
os.utime(os.path.join(rr, "src", "reforge_ext.cpp"), (old, old))
check("versión anterior" in game.rebuild_reason(rr, rexe), "extensión de una versión anterior → recompilar")
open(os.path.join(rr, "src", "reforge_ext.cpp"), "w", encoding="utf-8", newline="\n").write(ext_cpp.EXT_SOURCE)
os.utime(os.path.join(rr, "src", "reforge_ext.cpp"), (old, old))
open(os.path.join(rr, "assets", "default.xexp"), "w").write("x")
os.utime(rexe, (old + 50, old + 50))
check("trucos" in game.rebuild_reason(rr, rexe), "trucos/mejoras guardados después de compilar → recompilar")
check(game.rebuild_reason(rr, os.path.join(rr, "build", "no.exe")) == "", "sin ejecutable: nada")

print("Optimización del código recompilado (universal)")
f = game.codegen_flags("max", "")
check(all(f.values()), "máxima: todos los registros como locales en un juego sin setjmp ni excepciones")
f = game.codegen_flags("max", "setjmp_address = 0x82000000\n")
check(not f["non_volatile_as_local"] and f["cr_as_local"] and f["skip_lr"],
      "con setjmp/longjmp los no volátiles siguen en el contexto (longjmp los restaura de ahí)")
f = game.codegen_flags("max", "generate_exception_handlers = true\n")
check(not f["skip_lr"] and not f["non_volatile_as_local"], "con excepciones: ni skip_lr ni no volátiles")
check(not game.codegen_flags("safe")["non_argument_as_local"] and game.codegen_flags("safe")["ctr_as_local"],
      "segura: solo CR, CTR, XER y reserva")
check(not any(game.codegen_flags("off").values()), "desactivada: como el original")
ro = os.path.join(TMP, "cgopt")
os.makedirs(os.path.join(ro, "generated"))
mp = os.path.join(ro, "juego_manifest.toml")
open(mp, "w").write('[project]\nname = "juego"\n\n[entrypoint]\nfile_path = "assets/default.xex"\n'
                    'includes = ["reforge_functions.toml"]\n\n[otros]\nx = 1\n')
check(game.codegen_opt_pending(ro), "proyecto sin optimizar: pendiente (el Taller recompila al jugar)")
check(game.apply_codegen_opt(ro, "max") and game.manifest_codegen_flags(open(mp).read()) == game.codegen_flags("max"),
      "se escribe en [entrypoint]")
import tomllib as _tl  # noqa: E402
t = _tl.loads(open(mp).read())
check(t["entrypoint"]["non_volatile_as_local"] is True and t["otros"]["x"] == 1, "manifiesto válido y el resto intacto")
check(not game.apply_codegen_opt(ro, "max"), "no reescribe si ya está")
game.apply_codegen_opt(ro, "safe")
t = _tl.loads(open(mp).read())
check(t["entrypoint"]["non_argument_as_local"] is False and open(mp).read().count("ctr_as_local") == 1,
      "bajar de nivel reemplaza las opciones (sin duplicarlas)")
check(not game.codegen_opt_pending(ro), "con el nivel por defecto ya aplicado no hay nada pendiente")
o = go.GameOptions()
check(o.codegen_level() == "safe", "por defecto: automática en Segura (la Máxima colgó Fast & Furious)")
o.codegen_opt_level = "off"
check(o.codegen_level() == "off", "automática recuerda el nivel al que bajó")
hl = os.path.join(ro, "hung.log")
open(hl, "w").write("[2026-10-18 10:00:00.000] [info] [gpu] [t1] DXGI adapter\n")
os.utime(hl, (time.time() - 60, time.time() - 60))
check(game._looks_hung(hl), "sin ninguna imagen y el log quieto 60 s → colgado")
open(hl, "a").write("[2026-10-18 10:00:05.000] [info] [core] [t9] [ReForge] FPS 30 · peor 40 ms\n")
os.utime(hl, (time.time() - 60, time.time() - 60))
check(not game._looks_hung(hl), "ya dibuja imágenes: no está colgado (puede ser un menú quieto)")
check(not game.exception_handlers_enabled(ro) and game.enable_exception_handlers(ro), "activa los manejadores __try/__except")
t = _tl.loads(open(mp).read())
check(t["entrypoint"]["generate_exception_handlers"] is True and game.exception_handlers_enabled(ro)
      and not game.enable_exception_handlers(ro), "una sola vez y el manifiesto sigue siendo válido")

print("SDK con FSR/CAS")
from reforge import fidelityfx  # noqa: E402
check(fidelityfx.commit_for_version("0.10.0.24-dev.gbd833a2") == "bd833a2" and
      fidelityfx.commit_for_version("0.10.0") == "v0.10.0" and
      fidelityfx.commit_for_version("0.10.0.24-dev.gbd833a2-fsr") == "bd833a2", "misma versión exacta que la instalada")
check(fidelityfx.is_fsr_version("0.10.0.24-dev.gbd833a2-fsr") and not fidelityfx.is_fsr_version("0.10.0"),
      "reconoce el SDK con FSR")
from reforge import toolchain  # noqa: E402
check(toolchain.version_from_zip_name("rexglue-sdk-0.10.0.24-dev.gbd833a2-fsr-win-amd64.zip") ==
      "0.10.0.24-dev.gbd833a2-fsr", "el instalador reconoce el zip de respaldo")
bd = os.path.join(TMP, "sdkb")
os.makedirs(bd)
open(os.path.join(bd, "CMakeCache.txt"), "w").write(
    "rexglue_DIR:PATH=C:/tools/rexglue-sdk/0.10.0.24-dev.gbd833a2/win-amd64/lib/cmake/rexglue\n")
class _Cfg:
    def __init__(s, pre): s.pre = pre
    def sdk_prefix(s): return s.pre
check(game.sdk_mismatch(_Cfg("C:/tools/rexglue-sdk/0.10.0.24-dev.gbd833a2-fsr/win-amd64"), bd).startswith("el SDK"),
      "al cambiar al SDK con FSR, el juego se reconfigura y recompila")
check(game.sdk_mismatch(_Cfg("C:/tools/rexglue-sdk/0.10.0.24-dev.gbd833a2/win-amd64"), bd) == "", "mismo SDK: nada")
print("Volcado de Windows: qué acceso, en qué dirección y desde qué módulo")
import struct  # noqa: E402
from reforge import crashdump  # noqa: E402


def minidump(path, code=0xC0000005, access=1, address=0x20D559000,
             rip=0x7FFBC9000000 + 0xF88B, module="C:\\juego\\VCRUNTIME140.dll",
             base=0x7FFBC9000000, size=0x100000):
    """Mini volcado real (MDMP) con una excepción de acceso y un módulo cargado."""
    key6, key4 = 0x100, 0x800
    ctx = 0x400
    name = 0x900
    body = bytearray(0xA00)
    struct.pack_into("<4sIIIIIQ", body, 0, b"MDMP", 0xA793, 2, 0x20, 0, 0, 0)
    struct.pack_into("<III", body, 0x20, 6, 0xA8, key6)              # stream de excepción
    struct.pack_into("<III", body, 0x2C, 4, 0, key4)                 # lista de módulos
    struct.pack_into("<II", body, key6, 1234, 0)                     # ThreadId + relleno
    struct.pack_into("<IIQQII", body, key6 + 8, code, 0, 0, 0, 2, 0)
    struct.pack_into("<QQ", body, key6 + 40, access, address)
    struct.pack_into("<II", body, key6 + 160, 0x300, ctx)            # ThreadContext
    struct.pack_into("<Q", body, ctx + 0xF8, rip)                    # RIP del hilo que falló
    struct.pack_into("<I", body, key4, 1)                            # un módulo
    struct.pack_into("<QI", body, key4 + 4, base, size)              # BaseOfImage, SizeOfImage
    struct.pack_into("<I", body, key4 + 4 + 20, name)                # ModuleNameRva
    raw = module.encode("utf-16-le")
    struct.pack_into("<I", body, name, len(raw))
    body[name + 4:name + 4 + len(raw)] = raw
    open(path, "wb").write(bytes(body))
    return path


dmp = minidump(os.path.join(TMP, "juego.exe.1.dmp"))
d = crashdump.read(dmp)
check(d.get("code") == 0xC0000005 and d.get("access") == "write",
      "el volcado dice que fue una ESCRITURA (no solo «sin mensaje en el log»)")
check(d.get("address") == 0x20D559000 and d.get("module") == "VCRUNTIME140.dll" and d.get("offset") == 0xF88B,
      "dirección que se tocó y módulo+desplazamiento del código que falló")
adv2 = game.crash_advice({"kind": "crash", "crash": "acceso a memoria no válido (0xC0000005)", "dump_info": d})
check("escritura" in adv2 and "0x20D559000" in adv2 and "VCRUNTIME140.dll+0xF88B" in adv2,
      "el diagnóstico lo explica: escritura en 0x… desde módulo+0x…")
check("sin mensaje" not in adv2, "y ya no dice «sin mensaje en el log»")
d2 = crashdump.read(minidump(os.path.join(TMP, "juego.exe.2.dmp"), access=0, address=0x1000))
check(d2.get("access") == "read" and "lectura" in game.crash_advice({"kind": "crash", "dump_info": d2}),
      "también distingue una lectura")
basura = os.path.join(TMP, "basura.dmp")
open(basura, "wb").write(b"no es un volcado")
check(crashdump.read(basura) == {} and crashdump.read(os.path.join(TMP, "no-existe.dmp")) == {},
      "un archivo que no es un volcado (o que no existe) no rompe nada")
check("sin mensaje" in game.crash_advice({"kind": "crash", "crash": "0xC0000005"}),
      "sin volcado se mantiene el texto de antes")

print(f"\nTodas las pruebas pasaron ({ok}).")
