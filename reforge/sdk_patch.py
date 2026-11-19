"""Parches de ReForge sobre el código de rexglue (se aplican al compilar el SDK con FSR/CAS).

* mouseaim: puntería con el ratón de verdad en el driver de teclado y ratón (src/input/mnk). El SDK
  convierte los píxeles de cada fotograma en deflexión del stick derecho, y eso no sirve para apuntar:
  un stick manda velocidad de giro y un ratón manda distancia, así que lo lento se queda por debajo de
  la zona muerta del juego y lo rápido pega un salto. El parche acumula el recorrido y lo gasta a lo
  largo de varios fotogramas, siempre por encima de la zona muerta, y añade sensibilidad separada para
  X y para Y. Va en rexruntime.dll, que ReForge copia junto a cada juego.
* texswap: cambio de texturas en la GPU (iconos de botones Xbox ↔ PlayStation en cualquier juego, en
  caliente). Añade reforge_texswap.cpp/.h a la caché de texturas y dos llamadas en cache.cpp. Va en
  rexgpu-xenos.dll, que ReForge copia junto a cada juego: los juegos ya compilados lo heredan sin recompilar.

Idempotente: se puede aplicar varias veces sobre el mismo árbol.
"""
import os
import shutil

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sdk_patches")
TEXSWAP_TAG = "reforge_texswap"
INCLUDE_ANCHOR = "#include <rex/graphics/pipeline/texture/util.h>\n"
INCLUDE_LINES = '#include <rex/system/xmemory.h>\n#include "reforge_texswap.h"\n'
LOAD_ANCHOR = "  TextureKey texture_key = texture.key();\n  if (base_outdated) {\n"
LOAD_HOOK = ("  TextureKey texture_key = texture.key();\n"
             "  if (base_outdated && !texture_key.scaled_resolve) {  // ReForge: texswap\n"
             "    reforge_texswap::OnLoad(shared_memory().reforge_memory().TranslatePhysical<uint8_t*>(0),\n"
             "                            texture_key.base_page << 12, texture.GetGuestBaseSize(),\n"
             "                            texture_key.GetWidth(), texture_key.GetHeight(), texture_key.pitch * 32,\n"
             "                            texture_key.tiled, static_cast<uint32_t>(texture_key.format),\n"
             "                            static_cast<uint32_t>(texture_key.endianness), texture_key.mip_page != 0);\n"
             "  }\n"
             "  if (base_outdated) {\n")
TICK_ANCHOR = "  if (texture_became_outdated_.exchange(false, std::memory_order_acquire)) {\n"
TICK_HOOK = ("  reforge_texswap::Tick(shared_memory().reforge_memory().TranslatePhysical<uint8_t*>(0));  // ReForge: texswap\n"
             + TICK_ANCHOR)
CMAKE_ANCHOR = "    pipeline/texture/cache.cpp\n"
SHM_ANCHOR = " protected:\n  SharedMemory(memory::Memory& memory);\n"
SHM_HOOK = ("  // ReForge: texswap (acceso a la memoria del juego desde la caché de texturas)\n"
            "  memory::Memory& reforge_memory() const { return memory_; }\n\n" + SHM_ANCHOR)


class PatchError(Exception):
    pass


def _patch_text(path, pairs):
    with open(path, encoding="utf-8", newline="") as f:
        txt = f.read()
    crlf = "\r\n" in txt
    work = txt.replace("\r\n", "\n")
    for anchor, new, done_marker in pairs:
        if done_marker in work:
            continue
        if work.count(anchor) != 1:
            raise PatchError(f"{os.path.basename(path)}: no encuentro el punto exacto para el parche")
        work = work.replace(anchor, new, 1)
    if crlf:
        work = work.replace("\n", "\r\n")
    if work != txt:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(work)
        return True
    return False


def apply_texswap(src):
    """Aplica el parche al árbol de rexglue en `src`. Devuelve True si cambió algo."""
    tex_dir = os.path.join(src, "src", "graphics", "pipeline", "texture")
    cache = os.path.join(tex_dir, "cache.cpp")
    cml = os.path.join(src, "src", "graphics", "CMakeLists.txt")
    shm = os.path.join(src, "include", "rex", "graphics", "shared_memory.h")
    if not (os.path.isfile(cache) and os.path.isfile(cml)):
        raise PatchError("El código de rexglue no tiene la caché de texturas donde se esperaba")
    changed = False
    for name in ("reforge_texswap.cpp", "reforge_texswap.h"):
        dst = os.path.join(tex_dir, name)
        new = open(os.path.join(HERE, name), "rb").read()
        if not os.path.isfile(dst) or open(dst, "rb").read() != new:
            shutil.copyfile(os.path.join(HERE, name), dst)
            changed = True
    changed |= _patch_text(cache, [
        (INCLUDE_ANCHOR, INCLUDE_ANCHOR + INCLUDE_LINES, '#include "reforge_texswap.h"'),
        (LOAD_ANCHOR, LOAD_HOOK, "reforge_texswap::OnLoad("),
        (TICK_ANCHOR, TICK_HOOK, "reforge_texswap::Tick("),
    ])
    changed |= _patch_text(shm, [(SHM_ANCHOR, SHM_HOOK, "reforge_memory()")])
    changed |= _patch_text(cml, [
        (CMAKE_ANCHOR, CMAKE_ANCHOR + "    pipeline/texture/reforge_texswap.cpp\n", "reforge_texswap.cpp"),
    ])
    return changed


CRASH_INCLUDE_ANCHOR = "#include <rex/types.h>\n\nusing namespace rex::arch;\n"
CRASH_INCLUDE = ("#include <rex/types.h>\n\n#if REX_PLATFORM_WIN32\n#include <windows.h>  // ReForge: crashinfo\n#endif\n\n"
                 "using namespace rex::arch;\n")
CRASH_ANCHOR = ("    if (access_violation_callback_) {\n"
                "      return access_violation_callback_(std::move(lock), access_violation_callback_context_,\n"
                "                                        fault_host_address, is_write);\n"
                "    }\n")
CRASH_HOOK = ("    if (access_violation_callback_) {\n"
              "      const bool handled = access_violation_callback_(std::move(lock), access_violation_callback_context_,\n"
              "                                                      fault_host_address, is_write);\n"
              "#if REX_PLATFORM_WIN32\n"
              "      if (!handled) {  // ReForge: crashinfo (módulo+desplazamiento del código que falló)\n"
              "        HMODULE mod = nullptr;\n"
              "        wchar_t name[MAX_PATH] = {};\n"
              "        if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |\n"
              "                                   GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,\n"
              "                               reinterpret_cast<LPCWSTR>(ex->pc()), &mod) &&\n"
              "            GetModuleFileNameW(mod, name, MAX_PATH)) {\n"
              "          const wchar_t* base = name;\n"
              "          for (const wchar_t* c = name; *c; ++c)\n"
              "            if (*c == L'\\\\' || *c == L'/') base = c + 1;\n"
              "          char narrow[MAX_PATH] = {};\n"
              "          WideCharToMultiByte(CP_UTF8, 0, base, -1, narrow, MAX_PATH, nullptr, nullptr);\n"
              "          REXLOG_ERROR(\"[ReForge] Fallo en {}+0x{:X}\", narrow,\n"
              "                       static_cast<uint64_t>(ex->pc() - reinterpret_cast<uintptr_t>(mod)));\n"
              "        }\n"
              "      }\n"
              "#endif\n"
              "      return handled;\n"
              "    }\n")


def apply_crashinfo(src):
    """El log dice en qué parte del código cae un acceso inválido (módulo+desplazamiento): con el mapa del
    enlazador del juego, ReForge sabe en qué función del juego ocurre."""
    path = os.path.join(src, "src", "system", "mmio_handler.cpp")
    if not os.path.isfile(path):
        raise PatchError("El código de rexglue no tiene mmio_handler.cpp donde se esperaba")
    return _patch_text(path, [(CRASH_INCLUDE_ANCHOR, CRASH_INCLUDE, "ReForge: crashinfo\n#endif"),
                              (CRASH_ANCHOR, CRASH_HOOK, "[ReForge] Fallo en")])


ASYNC_ANCHOR = ("  if (!creation_threads_.empty()) {\n"
                "    CreateQueuedPipelinesOnProcessorThread();\n"
                "    // Await creation of all queued pipelines.\n")
ASYNC_HOOK = ("  // ReForge: asyncpso — con compilación asíncrona, los pipelines pendientes se terminan en segundo plano\n"
              "  // (los dibujos que los usan se saltan hasta que estén listos) en vez de frenar la GPU en cada envío.\n"
              "  if (!creation_threads_.empty() && !REXCVAR_GET(async_shader_compilation)) {\n"
              "    CreateQueuedPipelinesOnProcessorThread();\n"
              "    // Await creation of all queued pipelines.\n")


def apply_asyncpso(src):
    """Sin esperas a la creación de pipelines al final de cada envío cuando la compilación es asíncrona."""
    changed = False
    for api in ("d3d12", "vulkan"):
        path = os.path.join(src, "src", "graphics", api, "pipeline_cache.cpp")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", newline="") as f:
            work = f.read().replace("\r\n", "\n")
        if "ReForge: asyncpso" in work or work.count(ASYNC_ANCHOR) != 1:
            continue
        changed |= _patch_text(path, [(ASYNC_ANCHOR, ASYNC_HOOK, "ReForge: asyncpso")])
    return changed



# ---------------------------------------------------------------- mouseaim
MNK_CVAR_ANCHOR = """REXCVAR_DEFINE_DOUBLE(mnk_sensitivity, 1.0, "Input", "Mouse sensitivity for right stick")
    .range(0.01, 10.0);
"""
MNK_CVAR_HOOK = MNK_CVAR_ANCHOR + """
// ReForge: mouseaim. Sensibilidad por eje (0 = usar mnk_sensitivity para los dos) y cuánto stick
// vale el empujón mínimo, que tiene que pasar la zona muerta del juego para que se note.
REXCVAR_DEFINE_DOUBLE(mnk_sensitivity_x, 0.0, "Input",
                      "ReForge: horizontal mouse sensitivity (0 = use mnk_sensitivity)")
    .range(0.0, 10.0);
REXCVAR_DEFINE_DOUBLE(mnk_sensitivity_y, 0.0, "Input",
                      "ReForge: vertical mouse sensitivity (0 = use mnk_sensitivity)")
    .range(0.0, 10.0);
REXCVAR_DEFINE_DOUBLE(mnk_aim_floor, 0.40, "Input",
                      "ReForge: smallest right-stick push the mouse produces, as a fraction of range")
    .range(0.0, 0.95);
REXCVAR_DEFINE_DOUBLE(mnk_aim_tail, 8.0, "Input",
                      "ReForge: how many frames of mouse travel may queue up (lower = less drift)")
    .range(1.0, 60.0);
"""

MNK_STATE_ANCHOR = "std::atomic<bool> mouse_look_active{true};\n"
MNK_STATE_HOOK = ("std::atomic<bool> mouse_look_active{true};\n"
                  "\n"
                  "// ReForge: mouseaim. Recorrido del ratón pendiente de convertir en giro, en unidades\n"
                  "// de stick. Solo se tocan con state_mutex_ cogido (GetDeviceState) o al perder el foco.\n"
                  "double reforge_aim_x = 0.0;\n"
                  "double reforge_aim_y = 0.0;\n")

MNK_AIM_ANCHOR = """  if (REXCVAR_GET(mnk_mouse) && IsMouseLookActive()) {
    double sensitivity = REXCVAR_GET(mnk_sensitivity);
    constexpr double kBaseScale = 200.0;
    rx += static_cast<int32_t>(double(mouse_dx_) * sensitivity * kBaseScale);
    ry += static_cast<int32_t>(double(-mouse_dy_) * sensitivity * kBaseScale);
  }
"""
MNK_AIM_HOOK = """  if (REXCVAR_GET(mnk_mouse) && IsMouseLookActive()) {
    // ReForge: mouseaim.
    //
    // El stick manda VELOCIDAD de giro y el ratón manda DISTANCIA. Convertir los píxeles de un solo
    // fotograma en deflexión no sirve para apuntar: un gesto normal se queda por debajo de la zona
    // muerta del juego y no pasa nada, y uno rápido entra de golpe en la parte alta de su curva de
    // respuesta y pega un salto.
    //
    // Aquí el recorrido se acumula y se gasta a lo largo de varios fotogramas con una deflexión que
    // siempre supera la zona muerta: el giro total sale proporcional a lo que se movió el ratón y los
    // movimientos pequeños también cuentan. El techo lo pone el giro máximo del propio juego, así que
    // un gesto muy rápido no cabe en un fotograma y se reparte entre los siguientes; mnk_aim_tail
    // limita esa cola para que no se sienta como inercia.
    const double sens = REXCVAR_GET(mnk_sensitivity);
    double sens_x = REXCVAR_GET(mnk_sensitivity_x);
    double sens_y = REXCVAR_GET(mnk_sensitivity_y);
    if (sens_x <= 0.0) {
      sens_x = sens;
    }
    if (sens_y <= 0.0) {
      sens_y = sens;
    }
    constexpr double kUnitsPerPixel = 1600.0;
    const double floor_units = REXCVAR_GET(mnk_aim_floor) * double(INT16_MAX);
    const double max_accum = REXCVAR_GET(mnk_aim_tail) * double(INT16_MAX);
    reforge_aim_x += double(mouse_dx_) * sens_x * kUnitsPerPixel;
    reforge_aim_y += double(-mouse_dy_) * sens_y * kUnitsPerPixel;
    double mag = std::sqrt(reforge_aim_x * reforge_aim_x + reforge_aim_y * reforge_aim_y);
    if (mag > max_accum && mag > 0.0) {
      reforge_aim_x *= max_accum / mag;
      reforge_aim_y *= max_accum / mag;
      mag = max_accum;
    }
    if (mag >= floor_units && mag > 0.0) {
      // Hay bastante recorrido guardado para un empujón que el juego sí nota: se suelta y se
      // descuenta exactamente lo soltado, de modo que el giro total siga el recorrido del ratón.
      const double out = std::min(mag, double(INT16_MAX));
      rx += static_cast<int32_t>(reforge_aim_x / mag * out);
      ry += static_cast<int32_t>(reforge_aim_y / mag * out);
      reforge_aim_x -= reforge_aim_x / mag * out;
      reforge_aim_y -= reforge_aim_y / mag * out;
    } else if (mouse_dx_ == 0.0f && mouse_dy_ == 0.0f) {
      // Por debajo del mínimo no se emite nada: se guarda y se suelta en cuanto haya bastante
      // (emitir el mínimo por cada píxel haría que los gestos diminutos giraran más que los
      // grandes). Si además el ratón se ha parado, lo que sobra se tira para que no se arrastre
      // al siguiente movimiento.
      reforge_aim_x = 0.0;
      reforge_aim_y = 0.0;
    }
  } else {
    reforge_aim_x = 0.0;   // con el ratón apagado no se guarda cola
    reforge_aim_y = 0.0;
  }
"""


def apply_mouseaim(src):
    """Puntería con el ratón en el driver mnk. Devuelve True si cambió algo."""
    path = os.path.join(src, "src", "input", "mnk", "mnk_input_driver.cpp")
    if not os.path.isfile(path):
        return False
    return _patch_text(path, [
        # Cada marca tiene que ser exclusiva de su trozo: si una aparece también en otro, ese
        # trozo se da por puesto y se queda sin aplicar.
        (MNK_CVAR_ANCHOR, MNK_CVAR_HOOK, "REXCVAR_DEFINE_DOUBLE(mnk_sensitivity_x"),
        (MNK_STATE_ANCHOR, MNK_STATE_HOOK, "double reforge_aim_x = 0.0;"),
        (MNK_AIM_ANCHOR, MNK_AIM_HOOK, "reforge_aim_x += double(mouse_dx_)"),
    ])


def apply_all(src):
    changed = apply_texswap(src)
    changed |= apply_crashinfo(src)
    changed |= apply_asyncpso(src)
    changed |= apply_mouseaim(src)
    return changed


def is_applied(src):
    """¿Están puestos los parches de ReForge en este árbol de rexglue?"""
    cache = os.path.join(src, "src", "graphics", "pipeline", "texture", "cache.cpp")
    mnk = os.path.join(src, "src", "input", "mnk", "mnk_input_driver.cpp")
    try:
        if "reforge_texswap::OnLoad(" not in open(cache, encoding="utf-8").read():
            return False
    except OSError:
        return False
    try:
        return "reforge_aim_x += double(mouse_dx_)" in open(mnk, encoding="utf-8").read()
    except OSError:
        return True      # un SDK sin el driver de teclado y ratón no puede llevar ese parche
