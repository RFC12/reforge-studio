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


class PatchFileMissing(PatchError):
    """El archivo que el parche toca no existe en esta versión del SDK (la reorganizaron). Se salta siempre,
    también para los parches imprescindibles: no es que el parche esté roto, es que esa versión movió el
    código y hay que re-anclarlo. ReForge compila igual y avisa."""


def _gfx(src, *relparts):
    """Ruta de un archivo del árbol de gráficos, tanto en el diseño viejo (src/graphics/…) como en el nuevo
    de rexglue 0.11 (src/gpu/xenos/…). Devuelve la primera que exista, o la nueva si ninguna existe todavía."""
    nueva = os.path.join(src, "src", "gpu", "xenos", *relparts)
    vieja = os.path.join(src, "src", "graphics", *relparts)
    if os.path.exists(nueva):
        return nueva
    if os.path.exists(vieja):
        return vieja
    return nueva


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
    tex_dir = os.path.dirname(_gfx(src, "pipeline", "texture", "cache.cpp"))
    cache = os.path.join(tex_dir, "cache.cpp")
    cml = _gfx(src, "CMakeLists.txt")
    shm = _gfx(src, "shared_memory.h") if os.path.exists(_gfx(src, "shared_memory.h")) \
        else os.path.join(src, "include", "rex", "graphics", "shared_memory.h")
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
        path = _gfx(src, api, "pipeline_cache.cpp")
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


FUNCMAP_ANCHOR = """    if (rejected > 0) {
      REXSYS_ERROR("PPCImageInfo registration: {} func_mappings entries rejected", rejected);
      Shutdown();
      return X_STATUS_UNSUCCESSFUL;
    }
"""
FUNCMAP_HOOK = """    if (rejected > 0) {
      // ReForge: no abortar el arranque por esto. Una entrada rechazada cae fuera de todos los módulos
      // registrados (SetFunction lo comprueba), así que es una dirección que el juego nunca podrá llamar
      // de forma válida —normalmente un salto a través de un puntero sin inicializar que el recompilador
      // recogió del XEX—. Saltarla y seguir deja el juego arrancar; si acaso el juego la llama de verdad,
      // fallará en esa llamada concreta en vez de negarse a abrir entero.
      REXSYS_WARN("PPCImageInfo registration: {} func_mappings entries skipped (outside module range)",
                  rejected);
    }
"""


RESOLVE_ANCHOR = """  assert_true(x0 < x1 && y0 < y1);
  if (x0 >= x1 || y0 >= y1) {
    REXGPU_ERROR("Resolve region is empty");
    return false;
  }
"""
RESOLVE_HOOK = """  if (x0 >= x1 || y0 >= y1) {
    // ReForge: un resolve vacío no es un error. El llamador (render_target_cache: \"Nothing to copy/clear\")
    // ya trata tamaño 0 como un no-op con éxito, así que se devuelve éxito con tamaño 0 en vez de false,
    // que abortaba el frame entero. Documentado para FH1/FH2 (fh1-recomp-findings) y es lo que hace Xenia.
    // Los juegos que no generan resolves vacíos nunca entran aquí, así que no les afecta.
    info_out.coordinate_info.width_div_8 = 0;
    info_out.height_div_8 = 0;
    return true;
  }
"""


# --- Precompilado de shaders al cargar (AOT) -------------------------------------------------------------
# rexglue ya guarda los shaders (gpu.xenos.store_shaders) y recrea sus pipelines al abrir el juego, pero lo
# hace en segundo plano (InitializeShaderStorage(..., false) fijo), así que los primeros segundos aún pueden
# tener tirones mientras terminan de compilarse. Este parche añade un cvar para hacerlo BLOQUEANTE: precompila
# todos los pipelines guardados antes del primer frame (carga más larga, pero sin tirones de shader en juego),
# al estilo del precompilado AOT de Pinyon Shift. ReForge lo activa por juego como «Precompilar shaders al
# cargar»; por defecto queda en false, así que sin tocar nada el comportamiento es el de siempre.
PREWARM_SETTING_ANCHOR = """  REX_SETTING(bool, store_shaders, true,
              "Keep compiled shaders on disk and load them on later runs to avoid stutter");
"""
PREWARM_SETTING_HOOK = """  REX_SETTING(bool, store_shaders, true,
              "Keep compiled shaders on disk and load them on later runs to avoid stutter");
  REX_SETTING(bool, shader_storage_blocking, false,
              "ReForge: precompile every stored shader pipeline before the first frame (longer load, no "
              "in-game shader stutter)");
"""
PREWARM_CALL_ANCHOR = \
    "    REX_TRY_VOID(InitializeShaderStorage(cache_root, title_info_.title_id, false));"
PREWARM_CALL_HOOK = \
    "    REX_TRY_VOID(InitializeShaderStorage(cache_root, title_info_.title_id, shader_storage_blocking.Get()));"


def apply_shader_prewarm(src):
    """Cvar gpu.xenos.shader_storage_blocking: precompilar todos los shaders guardados antes de jugar."""
    settings = _gfx(src, "xenos_settings.h")
    driver = _gfx(src, "xenos_graphics_driver_base.cpp")
    if not (os.path.isfile(settings) and os.path.isfile(driver)):
        raise PatchFileMissing("xenos_settings.h / xenos_graphics_driver_base.cpp no están donde se esperaba "
                               "(SDK reorganizado)")
    a = _patch_text(settings, [(PREWARM_SETTING_ANCHOR, PREWARM_SETTING_HOOK, "shader_storage_blocking")])
    b = _patch_text(driver, [(PREWARM_CALL_ANCHOR, PREWARM_CALL_HOOK, "shader_storage_blocking.Get()")])
    return a or b


def apply_resolve_noop(src):
    """Un resolve de región vacía no aborta el frame: se trata como «nada que copiar»."""
    path = _gfx(src, "util", "draw.cpp")
    if not os.path.isfile(path):
        raise PatchFileMissing(f"{os.path.basename(path)}: no está en esta versión del SDK (reorganizada)")
    return _patch_text(path, [
        (RESOLVE_ANCHOR, RESOLVE_HOOK, "un resolve vacío no es un error"),
    ])


def apply_funcmap_tolerant(src):
    """El arranque no se aborta porque una función caiga fuera del módulo: se salta con un aviso."""
    path = os.path.join(src, "src", "system", "runtime.cpp")
    if not os.path.isfile(path):
        raise PatchFileMissing(f"{os.path.basename(path)}: no está en esta versión del SDK (reorganizada)")
    return _patch_text(path, [
        (FUNCMAP_ANCHOR, FUNCMAP_HOOK, "func_mappings entries skipped (outside module range)"),
    ])


def apply_mouseaim(src):
    """Puntería con el ratón en el driver mnk. Devuelve True si cambió algo."""
    path = os.path.join(src, "src", "input", "mnk", "mnk_input_driver.cpp")
    if not os.path.isfile(path):
        raise PatchFileMissing(f"{os.path.basename(path)}: no está en esta versión del SDK (reorganizada)")
    return _patch_text(path, [
        # Cada marca tiene que ser exclusiva de su trozo: si una aparece también en otro, ese
        # trozo se da por puesto y se queda sin aplicar.
        (MNK_CVAR_ANCHOR, MNK_CVAR_HOOK, "REXCVAR_DEFINE_DOUBLE(mnk_sensitivity_x"),
        (MNK_STATE_ANCHOR, MNK_STATE_HOOK, "double reforge_aim_x = 0.0;"),
        (MNK_AIM_ANCHOR, MNK_AIM_HOOK, "reforge_aim_x += double(mouse_dx_)"),
    ])


# (clave, función, ¿imprescindible?). Un parche no imprescindible que no encaje en una versión nueva
# del SDK se salta con un aviso en vez de tumbar toda la compilación: así ReForge sigue sirviendo con las
# versiones nuevas de rexglue aunque un parche cosmético haya quedado desfasado por un cambio del código.
PATCHES = (
    ("iconos de botones PlayStation", apply_texswap, False),
    ("localización de fallos en el log", apply_crashinfo, False),
    ("compilación de shaders en segundo plano", apply_asyncpso, False),
    ("puntería con el ratón", apply_mouseaim, False),
    ("el arranque tolera funciones fuera del módulo", apply_funcmap_tolerant, True),
    ("un resolve vacío no aborta el frame", apply_resolve_noop, False),
    ("precompilar shaders al cargar (AOT)", apply_shader_prewarm, False),
)


def apply_all(src, on_skip=None):
    """Aplica todos los parches. Devuelve (cambió_algo, [nombres aplicados], [(nombre, motivo) saltados]).

    Un parche que no encaja (p. ej. porque una versión nueva movió el código) se salta con su motivo en
    vez de abortar, salvo los imprescindibles, que sí propagan el error.
    """
    changed = False
    aplicados, saltados = [], []
    for nombre, fn, imprescindible in PATCHES:
        try:
            if fn(src):
                changed = True
            aplicados.append(nombre)
        except PatchFileMissing as e:
            # El SDK reorganizó el código: el parche no puede aplicarse aquí. Nunca aborta, ni siquiera
            # un imprescindible, para no impedir usar una versión nueva de rexglue.
            saltados.append((nombre, str(e)))
            if on_skip:
                on_skip(nombre, str(e))
        except PatchError as e:
            # El archivo está pero el punto exacto cambió: un parche cosmético se salta; uno imprescindible
            # sí detiene la compilación, porque indica que algo no es como se esperaba.
            if imprescindible:
                raise
            saltados.append((nombre, str(e)))
            if on_skip:
                on_skip(nombre, str(e))
    return changed, aplicados, saltados


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
        if "reforge_aim_x += double(mouse_dx_)" not in open(mnk, encoding="utf-8").read():
            return False
    except OSError:
        pass             # un SDK sin el driver de teclado y ratón no puede llevar ese parche
    rt = os.path.join(src, "src", "system", "runtime.cpp")
    try:
        if "func_mappings entries skipped" not in open(rt, encoding="utf-8").read():
            return False
    except OSError:
        return True
    draw = _gfx(src, "util", "draw.cpp")
    try:
        return "un resolve vacío no es un error" in open(draw, encoding="utf-8").read()
    except OSError:
        return True
