"""Parches de ReForge sobre el código de rexglue (se aplican al compilar el SDK con FSR/CAS).

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


def apply_all(src):
    changed = apply_texswap(src)
    changed |= apply_crashinfo(src)
    changed |= apply_asyncpso(src)
    return changed


def is_applied(src):
    cache = os.path.join(src, "src", "graphics", "pipeline", "texture", "cache.cpp")
    try:
        return "reforge_texswap::OnLoad(" in open(cache, encoding="utf-8").read()
    except OSError:
        return False
