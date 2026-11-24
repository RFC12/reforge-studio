"""Extensión C++ que ReForge añade a cada proyecto rexglue (src/reforge_ext.*).

* Perfil: Gamertag propio y «Xbox Live simulado» (el juego cree que hay sesión en Live).
* Idioma real: sustituye XGetLanguage (rexglue 0.10 siempre responde inglés).
* Notificación de logros animada (logo del perfil, icono/trofeo, sonido) y posición elegible.

Funciona porque rexglue llama a las funciones del sistema por su nombre (__imp__X...) y permite que el
juego aporte su propia versión (REX_HOOK); comprobado enlazando contra el rexruntime.dll real.
La configuración se lee al arrancar de «reforge_ext.ini» junto al .exe (la escribe ReForge).
"""
import os
import re

EXT_HEADER = r'''// ReForge Studio: perfil, idioma y notificación de logros.
// Archivo generado por ReForge Studio: se regenera al compilar (no lo edites).
#pragma once

#include <memory>

#include <rex/rex_app.h>
#include <rex/ui/overlay/achievement_notification.h>

namespace rex::system {
class AchievementManager;
}  // namespace rex::system

namespace reforge {
// Notificación de logros + menú Guía (botón Xbox/PS del mando o tecla Inicio).
std::unique_ptr<rex::ui::AchievementNotificationDialog> MakeAchievementToast(
    rex::ui::ImGuiDrawer* drawer, rex::ui::ImmediateDrawer* immediate_drawer, rex::Runtime* runtime,
    rex::ui::Window* window = nullptr, rex::system::AchievementManager* achievements = nullptr);
}  // namespace reforge
'''

EXT_SOURCE = r'''// ReForge Studio: perfil, idioma y notificación de logros.
// Archivo generado por ReForge Studio: se regenera al compilar (no lo edites).
// Configuración: reforge_ext.ini junto al .exe (la escribe ReForge Studio / el lanzador del juego).
#include "reforge_ext.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <ctime>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include <imgui.h>
#include <rex/filesystem.h>
#include <rex/hook.h>
#include <rex/logging.h>
#include <rex/string.h>
#include <rex/system/xtypes.h>
#include <rex/types.h>
#include <rex/ui/imgui_drawer.h>
#include <rex/ui/immediate_drawer.h>
#include <rex/ui/overlay/achievement_icon_cache.h>
#include <rex/ui/window.h>
#include <rex/input/input.h>
#include <rex/input/input_system.h>
#include <rex/runtime.h>
#include <rex/system/achievement_manager.h>
#include <rex/system/kernel_state.h>
#include <rex/system/util/xdbf_utils.h>
#include <rex/system/interfaces/graphics.h>
#include <rex/ui/presenter.h>
#include <rex/system/user_module.h>
#include <rex/cvar.h>
#include <rex/system/xex_module.h>
#include <rex/system/xmemory.h>

#define XXH_INLINE_ALL
#include <xxhash.h>

#if defined(_WIN32)
#include <windows.h>  // PlaySoundW se carga en tiempo de ejecución desde winmm.dll (nada que enlazar)
#else
#include <SDL3/SDL.h>
#endif

// Implementación original de rexglue de las funciones de mando (exportadas por rexruntime).
namespace rex::kernel::xam {
uint32_t XamInputGetCapabilities_entry(uint32_t, uint32_t, rex::MappedPtr<rex::input::X_INPUT_CAPABILITIES>);
uint32_t XamInputGetCapabilitiesEx_entry(uint32_t, uint32_t, uint32_t,
                                         rex::MappedPtr<rex::input::X_INPUT_CAPABILITIES>);
uint32_t XamInputGetState_entry(uint32_t, uint32_t, rex::MappedPtr<rex::input::X_INPUT_STATE>);
uint32_t XamInputSetState_entry(uint32_t, uint32_t, rex::MappedPtr<rex::input::X_INPUT_VIBRATION>);
uint32_t XamInputGetKeystroke_entry(uint32_t, uint32_t, rex::MappedPtr<rex::input::X_INPUT_KEYSTROKE>);
uint32_t XamInputGetKeystrokeEx_entry(rex::MappedPtr<rex::be_u32>, uint32_t,
                                      rex::MappedPtr<rex::input::X_INPUT_KEYSTROKE>);
}  // namespace rex::kernel::xam
namespace rex::kernel::xboxkrnl {
void VdSwap_entry(rex::MappedPtr<void>, rex::MappedPtr<void>, rex::MappedPtr<void>, rex::MappedPtr<void>,
                  rex::MappedPtr<void>, rex::MappedPtr<rex::be_u32>, rex::MappedPtr<rex::be_u32>,
                  rex::MappedPtr<rex::be_u32>, rex::MappedPtr<rex::be_u32>, rex::MappedPtr<rex::be_u32>);
}  // namespace rex::kernel::xboxkrnl

namespace reforge {
using namespace rex;  // tipos y códigos de error del Xbox (X_RESULT, X_E_*, be<>…)

struct Settings {
  std::string gamertag = "Player";  // perfil del jugador
  bool live = false;
  uint32_t language = 0;  // 0 = el que diga el juego (inglés)
  std::string toast_position = "bottom_right";
  float toast_seconds = 5.0f;
  std::string toast_title = "Logro desbloqueado";
  uint32_t accent = 0x19D3A2;
  std::string sound;  // WAV junto al .exe (reforge_achievement.wav) o vacío = sin sonido
  std::string badge;  // logo del perfil junto al .exe (reforge_badge.rgba) o vacío
  bool cheats = false;  // hay trucos aplicados (default.xexp de ReForge): el código ya no es el original
  bool hide_cursor = true;  // esconder el puntero del ratón mientras se juega con mando
  bool diagnostics = false;  // diagnóstico de rendimiento: tiempos de cada fotograma en reforge_frametimes.csv
  std::string avatar;       // avatar del perfil junto al .exe (reforge_avatar.rgba) o vacío
  std::string game_name;    // nombre del juego para el menú Guía
  bool guide_menu = true;   // menú Guía con el botón Xbox/PS
  bool playstation = false; // iconos de botones de PlayStation (✕ ○ □ △) en vez de los de Xbox
  bool image_guard = true;  // guardián de imagen (detecta la imagen blanca y lo corrige en caliente)
  float frame_cap = 0.0f;   // tope de FPS que aplica la extensión (30 = base para Smooth Motion · 0 = sin tope)
};

static std::string Trim(std::string s) {
  const char* ws = " \t\r\n\"";
  s.erase(0, s.find_first_not_of(ws));
  const auto end = s.find_last_not_of(ws);
  s.erase(end == std::string::npos ? 0 : end + 1);
  return s;
}

const Settings& Config() {
  static const Settings settings = [] {
    Settings s;
    std::ifstream file(rex::filesystem::GetExecutableFolder() / "reforge_ext.ini");
    std::string line;
    while (std::getline(file, line)) {
      const auto eq = line.find('=');
      if (line.empty() || line[0] == '#' || line[0] == ';' || eq == std::string::npos) continue;
      const std::string key = Trim(line.substr(0, eq));
      const std::string val = Trim(line.substr(eq + 1));
      if (key == "gamertag" && !val.empty()) s.gamertag = val.substr(0, 15);
      else if (key == "live") s.live = (val == "1" || val == "true");
      else if (key == "language") s.language = static_cast<uint32_t>(std::strtoul(val.c_str(), nullptr, 10));
      else if (key == "toast_position") s.toast_position = val;
      else if (key == "toast_seconds") s.toast_seconds = std::clamp(std::strtof(val.c_str(), nullptr), 2.0f, 15.0f);
      else if (key == "toast_title" && !val.empty()) s.toast_title = val;
      else if (key == "accent") s.accent = static_cast<uint32_t>(std::strtoul(val.c_str(), nullptr, 16));
      else if (key == "sound" && val.find_first_of("/\\:") == std::string::npos) s.sound = val;
      else if (key == "badge" && val.find_first_of("/\\:") == std::string::npos) s.badge = val;
      else if (key == "cheats") s.cheats = (val == "1" || val == "true");
      else if (key == "hide_cursor") s.hide_cursor = !(val == "0" || val == "false");
      else if (key == "diagnostics") s.diagnostics = (val == "1" || val == "true");
      else if (key == "avatar" && val.find_first_of("/\\:") == std::string::npos) s.avatar = val;
      else if (key == "game_name") s.game_name = val.substr(0, 60);
      else if (key == "guide_menu") s.guide_menu = !(val == "0" || val == "false");
      else if (key == "pad_style") s.playstation = (val == "playstation");
      else if (key == "image_guard") s.image_guard = !(val == "0" || val == "false");
      else if (key == "frame_cap") s.frame_cap = std::clamp(std::strtof(val.c_str(), nullptr), 0.0f, 240.0f);
    }
    return s;
  }();
  return settings;
}

// Tope de fotogramas (30 FPS para el movimiento suave del driver). -1 = aún no leído de reforge_ext.ini.
static std::atomic<float> g_frame_cap{-1.0f};

static float FrameCap() {
  float cap = g_frame_cap.load(std::memory_order_relaxed);
  if (cap < 0.0f) {
    cap = std::clamp(Config().frame_cap, 0.0f, 240.0f);
    g_frame_cap.store(cap, std::memory_order_relaxed);
  }
  return cap;
}

// ---------------------------------------------------------------- perfil, Live e idioma
// Mismo XUID que el perfil por defecto de rexglue: las partidas guardadas siguen siendo válidas.
static constexpr uint64_t kXuid = 0xB13EBABEBABEBABEull;

static u32 SigninState() { return Config().live ? 2u : 1u; }  // 1 = local, 2 = Xbox Live

// Idioma elegido en el menú Guía: 0 = el de reforge_ext.ini. El juego pregunta por XGetLanguage al cargar
// sus textos, así que cambiarlo desde el menú se aplica en la siguiente pantalla que los lea (sin reiniciar).
static std::atomic<uint32_t> g_language{0};

static u32 GameLanguage() {
  const uint32_t want = g_language.load(std::memory_order_relaxed);
  const uint32_t lang = want ? want : Config().language;
  return (lang >= 1 && lang <= 12) ? lang : 1u;
}

static u32 XGetLanguage_hook() {
  return GameLanguage();
}

static u32 XamUserGetSigninState_hook(u32 user_index) {
  return user_index == 0 ? SigninState() : 0u;
}

struct SigninInfo {
  rex::be<uint64_t> xuid;
  rex::be<uint32_t> unk08;
  rex::be<uint32_t> signin_state;
  rex::be<uint32_t> unk10;
  rex::be<uint32_t> unk14;
  char name[16];
};
static_assert(sizeof(SigninInfo) == 40, "X_USER_SIGNIN_INFO");

static i32 XamUserGetSigninInfo_hook(u32 user_index, u32 flags, ppc_ptr_t<SigninInfo> info) {
  (void)flags;
  if (!info) return X_E_INVALIDARG;
  std::memset(info, 0, sizeof(SigninInfo));
  if (user_index) return X_E_NO_SUCH_USER;
  info->xuid = kXuid;
  info->signin_state = SigninState();
  rex::string::copy_truncating(info->name, Config().gamertag, 16);
  return X_E_SUCCESS;
}

static u32 XamUserGetName_hook(u32 user_index, mapped_string buffer, u32 buffer_len) {
  if (user_index >= 4) return X_E_INVALIDARG;
  if (user_index) return X_E_NO_SUCH_USER;
  rex::string::copy_truncating(buffer, Config().gamertag, std::min(buffer_len, uint32_t(16)));
  return X_E_SUCCESS;
}

static u32 XamUserGetGamerTag_hook(u32 user_index, mapped_wstring buffer, u32 buffer_len) {
  if (user_index >= 4) return X_E_INVALIDARG;
  if (user_index) return X_E_NO_SUCH_USER;
  if (!buffer || buffer_len < 16) return X_E_INVALIDARG;
  rex::string::copy_and_swap_truncating(buffer, rex::string::to_utf16(Config().gamertag),
                                        std::min(buffer_len, uint32_t(16)));
  return X_E_SUCCESS;
}

static u32 XamUserCheckPrivilege_hook(u32 user_index, u32 mask, mapped_u32 out_value) {
  (void)mask;
  if (user_index != 0xFF) {
    if (user_index >= 4) return X_ERROR_INVALID_PARAMETER;
    if (user_index) return X_ERROR_NO_SUCH_USER;
  }
  *out_value = Config().live ? 1u : 0u;  // con Live simulado se conceden los privilegios online
  return X_ERROR_SUCCESS;
}

static u32 XNetGetEthernetLinkStatus_hook(u32 caller) {
  (void)caller;
  return Config().live ? 0x0Bu : 0u;  // activo · 100 Mbps · full duplex
}

// ---------------------------------------------------------------- sonido del logro
static void PlayAchievementSound() {
  const Settings& cfg = Config();
  if (cfg.sound.empty()) return;
  const std::filesystem::path path = rex::filesystem::GetExecutableFolder() / cfg.sound;
#if defined(_WIN32)
  using PlaySoundFn = BOOL(WINAPI*)(LPCWSTR, HMODULE, DWORD);
  static PlaySoundFn play_sound = [] {
    HMODULE winmm = LoadLibraryW(L"winmm.dll");
    return winmm ? reinterpret_cast<PlaySoundFn>(GetProcAddress(winmm, "PlaySoundW")) : nullptr;
  }();
  // SND_FILENAME | SND_ASYNC | SND_NODEFAULT: suena sin bloquear el juego y en silencio si falta el archivo.
  if (play_sound) play_sound(path.wstring().c_str(), nullptr, 0x00020000 | 0x0001 | 0x0002);
#else
  struct Clip {
    SDL_AudioStream* stream = nullptr;
    Uint8* data = nullptr;
    Uint32 size = 0;
  };
  static Clip clip = [&path] {
    Clip c;
    SDL_AudioSpec spec;
    if (SDL_InitSubSystem(SDL_INIT_AUDIO) && SDL_LoadWAV(path.string().c_str(), &spec, &c.data, &c.size)) {
      c.stream = SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, &spec, nullptr, nullptr);
      if (c.stream) SDL_ResumeAudioStreamDevice(c.stream);
    }
    return c;
  }();
  if (clip.stream && clip.data) {
    SDL_ClearAudioStream(clip.stream);
    SDL_PutAudioStreamData(clip.stream, clip.data, static_cast<int>(clip.size));
  }
#endif
}

// ---------------------------------------------------------------- versión exacta del juego (trucos)
// Hash de módulo igual al de Xenia: XXH3-64 de las páginas de código del ejecutable ya cargado (con su
// actualización si la hay), con los «thunks» de importación reescritos como hace Xenia (sc 2; blr; nop; nop).
// Identifica qué parches de la base de datos de Xenia corresponden exactamente a este juego.
static uint32_t LoadBe32(const uint8_t* p) {
  return (uint32_t(p[0]) << 24) | (uint32_t(p[1]) << 16) | (uint32_t(p[2]) << 8) | uint32_t(p[3]);
}

static void WriteModuleInfo(rex::Runtime* runtime) {
  static bool done = false;
  if (done || !runtime || !runtime->kernel_state()) return;
  auto module = runtime->kernel_state()->GetExecutableModule();
  if (!module) return;
  auto* xex = module->xex_module();
  if (!xex) return;
  done = true;
  auto* memory = runtime->memory();
  const uint32_t base = xex->base_address();
  const auto* heap = memory ? memory->LookupHeap(base) : nullptr;
  const auto* sec = xex->xex_security_info();
  const auto* hdr = reinterpret_cast<const uint8_t*>(xex->xex_header());
  if (!heap || !sec || !sec->page_descriptors || !hdr) return;
  // Imagen completa del juego ya cargado: ReForge la usa para encontrar de una vez las entradas de función
  // que rexglue no vio (tablas de métodos virtuales…) en vez de una por arranque.
  if (sec->image_size && sec->image_size < 0x10000000u) {
    std::ofstream img(rex::filesystem::GetExecutableFolder() / "reforge_image.bin", std::ios::binary | std::ios::trunc);
    img.write(reinterpret_cast<const char*>(memory->TranslateVirtual<const uint8_t*>(base)),
              static_cast<std::streamsize>(sec->image_size));
  }
  if (Config().cheats) return;  // con trucos el código está modificado: no sería el hash original
  int64_t first = -1, last = -1;
  for (uint32_t i = 0; i < sec->page_descriptor_count; ++i) {
    const uint32_t v = sec->page_descriptors[i].value;
    if ((v & 0xF) == 1) {  // XEX_SECTION_CODE (Xenia usa el índice del descriptor como nº de página)
      if (first < 0) first = i;
      last = i;
    }
  }
  if (first < 0) return;
  const uint32_t page = heap->page_size();
  const uint32_t start = base + static_cast<uint32_t>(first) * page;
  const uint32_t end = base + static_cast<uint32_t>(last + 1) * page;
  const uint8_t* src = memory->TranslateVirtual<const uint8_t*>(start);
  std::vector<uint8_t> code(src, src + (end - start));

  // Thunks de importación (registros de tipo 1) → como los deja Xenia al cargar.
  const uint32_t header_count = LoadBe32(hdr + 0x14);
  for (uint32_t h = 0; h < header_count && h < 64; ++h) {
    if (LoadBe32(hdr + 0x18 + h * 8) != 0x000103FF) continue;  // XEX_HEADER_IMPORT_LIBRARIES
    const uint8_t* il = hdr + LoadBe32(hdr + 0x1C + h * 8);
    const uint32_t total = LoadBe32(il);
    uint32_t off = 12 + LoadBe32(il + 4);
    while (off + 0x28 <= total) {
      const uint8_t* lib = il + off;
      const uint32_t lib_size = LoadBe32(lib);
      if (!lib_size) break;
      const uint32_t count = (uint32_t(lib[0x26]) << 8) | lib[0x27];
      for (uint32_t i = 0; i < count; ++i) {
        const uint32_t rec = LoadBe32(lib + 0x28 + i * 4);
        const uint32_t value = LoadBe32(memory->TranslateVirtual<const uint8_t*>(rec));
        if ((value >> 24) != 1 || rec < start || rec + 16 > end) continue;
        static const uint8_t stub[16] = {0x44, 0x00, 0x00, 0x42, 0x4E, 0x80, 0x00, 0x20,
                                         0x60, 0x00, 0x00, 0x00, 0x60, 0x00, 0x00, 0x00};
        std::memcpy(code.data() + (rec - start), stub, sizeof(stub));
      }
      off += lib_size;
    }
  }
  const uint64_t hash = XXH3_64bits(code.data(), code.size());
  std::ofstream out(rex::filesystem::GetExecutableFolder() / "reforge_module.txt", std::ios::trunc);
  char line[96];
  std::snprintf(line, sizeof(line), "title_id=%08X\nhash=%016llX\n", module->title_id(),
                static_cast<unsigned long long>(hash));
  out << line;
}

// ---------------------------------------------------------------- notificación de logros
// >>> toast-render: solo depende de ImGui (se prueba fuera del juego; misma línea de tiempo que toast_anim.py)
struct ToastView {
  const char* title = "";
  const char* label = "";
  unsigned gamerscore = 0;
  ImTextureID icon = 0;   // icono del logro (0 = trofeo dibujado)
  ImTextureID badge = 0;  // logo del perfil (0 = sin logo: solo icono/trofeo)
  uint32_t accent = 0x19D3A2;
  const char* position = "bottom_right";
};

struct ToastFrame {
  float alpha, circle, open, title_a, label_a, title_in, label_in, count, shine, wave, wave2, sparks, ring, squash;
  int face;  // 0 = logo del perfil, 1 = icono del logro / trofeo
};

static float Clamp01(float v) { return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v); }
static float Seg(float t, float a, float b) { return Clamp01((t - a) / (b - a)); }
static float OutCubic(float t) { return 1.0f - (1.0f - t) * (1.0f - t) * (1.0f - t); }
static float InCubic(float t) { return t * t * t; }
static float OutBack(float t) {
  const float c1 = 1.70158f, c3 = c1 + 1.0f, u = t - 1.0f;
  return 1.0f + c3 * u * u * u + c1 * u * u;
}

static ToastFrame ComputeToastFrame(float age, float total, bool has_badge) {
  ToastFrame f{};
  f.alpha = Seg(age, 0.0f, 0.08f) * (1.0f - Seg(age, total - 0.12f, total));
  const float k = Seg(age, total - 0.40f, total);  // cierre: pequeño pulso y desaparece
  f.circle = k <= 0.0f ? OutBack(Seg(age, 0.0f, 0.38f))
                       : (k < 0.35f ? 1.0f + 0.15f * OutCubic(k / 0.35f)
                                    : 1.15f * (1.0f - InCubic((k - 0.35f) / 0.65f)));
  f.open = OutCubic(Seg(age, 0.28f, 0.74f)) * (1.0f - InCubic(Seg(age, total - 0.90f, total - 0.40f)));
  const float out = 1.0f - Seg(age, total - 1.10f, total - 0.85f);
  f.title_in = OutCubic(Seg(age, 0.55f, 0.90f));
  f.label_in = OutCubic(Seg(age, 0.68f, 1.05f));
  f.title_a = f.title_in * out;
  f.label_a = f.label_in * out;
  f.count = OutCubic(Seg(age, 0.75f, 1.55f));
  f.shine = Seg(age, 0.85f, 1.55f);
  f.wave = Seg(age, 0.04f, 0.80f);
  f.wave2 = Seg(age, total - 0.40f, total - 0.05f);
  f.sparks = Seg(age, 0.30f, 1.25f);
  f.ring = age * 3.6f;
  f.squash = 1.0f;
  f.face = has_badge ? 0 : 1;
  if (has_badge && age > 1.4f) {  // alterna logo ↔ icono cada 1,8 s con un giro
    const float freeze = total - 1.0f;
    const float ph = std::max(0.0f, std::min(age, freeze) - 1.4f) / 1.8f;
    const int n = static_cast<int>(ph);
    const float fr = ph - static_cast<float>(n);
    int face = n % 2;
    if (fr > 0.84f) {
      const float g = (fr - 0.84f) / 0.16f;
      if (age < freeze) f.squash = std::fabs(std::cos(3.14159265f * g));
      if (g >= 0.5f || age >= freeze) face ^= 1;  // un giro a medias al empezar el cierre se completa
    }
    if (age >= freeze && face == 1) {  // al despedirse vuelve al logo con un último giro
      const float g = Seg(age, freeze, freeze + 0.22f);
      f.squash = std::fabs(std::cos(3.14159265f * g));
      if (g >= 0.5f) face = 0;
    }
    f.face = face;
  }
  return f;
}

static ImU32 Rgba(uint32_t rgb, float a) {
  return IM_COL32((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF, static_cast<int>(255.0f * Clamp01(a)));
}

static void DrawTrophy(ImDrawList* dl, ImVec2 c, float ir, float sq, ImU32 col) {
  auto P = [&](float x, float y) { return ImVec2(c.x + x * ir * sq, c.y + y * ir); };
  ImVec2 cup[12];
  cup[0] = P(-0.42f, -0.46f);
  for (int i = 0; i <= 10; ++i) {  // copa: media elipse convexa
    const float th = 3.14159265f * static_cast<float>(i) / 10.0f;
    cup[i + 1] = P(0.42f * std::cos(th), -0.46f + 0.58f * std::sin(th));
  }
  std::reverse(cup + 1, cup + 12);
  dl->AddConvexPolyFilled(cup, 12, col);
  const float th = std::max(1.0f, 0.09f * ir);
  for (int side = -1; side <= 1; side += 2) {  // asas
    for (int i = 0; i <= 8; ++i) {
      const float a = -1.5707963f + 3.14159265f * static_cast<float>(i) / 8.0f;
      dl->PathLineTo(P(side * (0.40f + 0.17f * std::cos(a)), -0.27f + 0.17f * std::sin(a)));
    }
    dl->PathStroke(col, 0, th * sq + 0.5f);
  }
  dl->AddRectFilled(P(-0.07f, 0.08f), P(0.07f, 0.30f), col);
  dl->AddRectFilled(P(-0.18f, 0.26f), P(0.18f, 0.32f), col, 0.02f * ir);
  dl->AddRectFilled(P(-0.27f, 0.32f), P(0.27f, 0.43f), col, 0.04f * ir);
}

static void DrawAchievementToast(ImDrawList* dl, ImFont* font, ImVec2 display, float age, float total,
                                 const ToastView& v) {
  const ToastFrame f = ComputeToastFrame(age, total, v.badge != 0);
  if (f.alpha <= 0.0f) return;
  const float a = f.alpha;
  const float s = std::clamp(display.y / 720.0f, 0.75f, 2.5f);
  const float h = 64.0f * s, r = h * 0.5f, margin = 28.0f * s;
  const float full_w = 440.0f * s;
  const float w = h + (full_w - h) * f.open;
  const std::string pos = v.position ? v.position : "";
  const bool left = pos.find("left") != std::string::npos;
  const bool center = pos.find("center") != std::string::npos;
  const bool top = pos.find("top") != std::string::npos;
  float x = left ? margin : (center ? (display.x - full_w) * 0.5f : display.x - margin - full_w);
  if (!left && !center) x += full_w - w;  // a la derecha se despliega hacia la izquierda
  if (center) x += (full_w - w) * 0.5f;
  const float y = top ? margin : display.y - margin - h;
  const bool icon_left = left || center;
  const ImVec2 c(icon_left ? x + r : x + w - r, y + r);
  const ImVec2 p0(x, y), p1(x + w, y + h);

  // cápsula: sombra suave, cuerpo, brillo superior y borde con resplandor del color del perfil
  if (f.open > 0.0f) {
    for (int i = 3; i >= 1; --i) {
      const float o = 2.0f * s * static_cast<float>(i);
      dl->AddRectFilled(ImVec2(p0.x - o * 0.5f, p0.y + o * 0.6f), ImVec2(p1.x + o * 0.5f, p1.y + o * 1.2f),
                        IM_COL32(0, 0, 0, static_cast<int>(38 * a)), r + o);
    }
    dl->AddRectFilled(p0, p1, IM_COL32(36, 37, 41, static_cast<int>(238 * a)), r);
    dl->AddRectFilled(p0, ImVec2(p1.x, y + r), IM_COL32(255, 255, 255, static_cast<int>(16 * a)), r,
                      ImDrawFlags_RoundCornersTop);
    if (f.shine > 0.0f && f.shine < 1.0f) {  // destello que recorre la cápsula
      const float bw = 70.0f * s, bx = x + r * 0.5f + (w - r) * f.shine;
      dl->PushClipRect(ImVec2(x + r * 0.45f, y + 2.0f * s), ImVec2(x + w - r * 0.45f, y + h - 2.0f * s), true);
      const ImU32 clear = IM_COL32(255, 255, 255, 0), lit = IM_COL32(255, 255, 255, static_cast<int>(46 * a));
      dl->AddRectFilledMultiColor(ImVec2(bx - bw, y), ImVec2(bx, y + h), clear, lit, lit, clear);
      dl->AddRectFilledMultiColor(ImVec2(bx, y), ImVec2(bx + bw, y + h), lit, clear, clear, lit);
      dl->PopClipRect();
    }
    const float glow = 0.16f + 0.55f * (1.0f - Seg(age, 0.75f, 1.8f));
    dl->AddRect(ImVec2(p0.x - 1.5f * s, p0.y - 1.5f * s), ImVec2(p1.x + 1.5f * s, p1.y + 1.5f * s),
                Rgba(v.accent, glow * 0.45f * a), r + 1.5f * s, 0, 3.0f * s);
    dl->AddRect(p0, p1, IM_COL32(112, 114, 120, static_cast<int>(210 * a)), r, 0, 1.6f * s);
  }

  const float br = (r - 5.0f * s) * f.circle;
  // onda expansiva al aparecer y al despedirse
  for (float wv : {f.wave, f.wave2}) {
    if (wv > 0.0f && wv < 1.0f) {
      const float e = OutCubic(wv);
      dl->AddCircle(c, (r - 5.0f * s) * (1.0f + 1.5f * e), Rgba(v.accent, (1.0f - wv) * (1.0f - wv) * 0.85f * a), 64,
                    (3.5f * (1.0f - wv) + 1.0f) * s);
    }
  }
  // chispas
  if (f.sparks > 0.0f && f.sparks < 1.0f) {
    const float e = OutCubic(f.sparks), fade = 1.0f - f.sparks;
    for (int i = 0; i < 12; ++i) {
      const float ang = 0.35f + static_cast<float>(i) * 0.5235988f;
      const float d = (r - 5.0f * s) * (1.05f + (1.4f + 0.35f * static_cast<float>(i % 3)) * e);
      const ImVec2 q(c.x + std::cos(ang) * d, c.y + std::sin(ang) * d);
      const float sz = (2.2f + static_cast<float>(i % 2)) * s * (0.4f + 0.6f * fade);
      const ImU32 col = i % 2 ? IM_COL32(255, 255, 255, static_cast<int>(220 * fade * a)) : Rgba(v.accent, fade * a);
      dl->AddQuadFilled(ImVec2(q.x, q.y - sz * 1.6f), ImVec2(q.x + sz, q.y), ImVec2(q.x, q.y + sz * 1.6f),
                        ImVec2(q.x - sz, q.y), col);
    }
  }
  if (br <= 0.5f) return;

  // insignia: disco, anillo con arcos que giran y marcas (como la consola)
  dl->AddCircleFilled(c, br + 3.0f * s, IM_COL32(14, 14, 16, static_cast<int>(255 * a)), 64);
  const float rr = br + 1.2f * s;
  dl->AddCircle(c, rr, IM_COL32(64, 66, 72, static_cast<int>(255 * a)), 64, 3.2f * s);
  for (int i = 0; i < 2; ++i) {
    const float a0 = f.ring + 3.14159265f * static_cast<float>(i);
    dl->PathArcTo(c, rr, a0, a0 + 1.25f, 24);
    dl->PathStroke(Rgba(v.accent, (i ? 0.55f : 1.0f) * a), 0, 3.2f * s);
  }
  for (int i = 0; i < 4; ++i) {
    const float ang = 0.7853982f + 1.5707963f * static_cast<float>(i);
    const ImVec2 d(std::cos(ang), std::sin(ang));
    dl->AddLine(ImVec2(c.x + d.x * (rr - 2.6f * s), c.y + d.y * (rr - 2.6f * s)),
                ImVec2(c.x + d.x * (rr + 2.6f * s), c.y + d.y * (rr + 2.6f * s)),
                IM_COL32(14, 14, 16, static_cast<int>(255 * a)), 2.4f * s);
  }
  const float ir = br - 3.0f * s;
  const float sq = f.squash;
  if (ir > 1.0f && sq > 0.03f) {
    const ImVec2 q0(c.x - ir * sq, c.y - ir), q1(c.x + ir * sq, c.y + ir);
    const ImTextureID tex = f.face == 0 ? v.badge : v.icon;
    if (tex) {
      dl->AddImageRounded(tex, q0, q1, ImVec2(0, 0), ImVec2(1, 1), IM_COL32(255, 255, 255, static_cast<int>(255 * a)),
                          ir * sq);
    } else {
      dl->AddEllipseFilled(c, ImVec2(ir * sq, ir), IM_COL32(40, 42, 47, static_cast<int>(255 * a)), 0.0f, 48);
      dl->AddEllipseFilled(ImVec2(c.x, c.y - ir * 0.10f), ImVec2(ir * 0.84f * sq, ir * 0.84f),
                           IM_COL32(54, 56, 62, static_cast<int>(255 * a)), 0.0f, 48);
      DrawTrophy(dl, c, ir * 0.95f, sq, IM_COL32(238, 238, 240, static_cast<int>(255 * a)));
    }
  }

  // textos: entran deslizándose; los G cuentan hasta el valor del logro
  if (f.open < 0.5f || (f.title_a <= 0.0f && f.label_a <= 0.0f)) return;
  const float tx = icon_left ? x + h + 12.0f * s : x + 24.0f * s;
  const float tmax = w - h - 36.0f * s;
  dl->PushClipRect(ImVec2(tx - 2.0f * s, y), ImVec2(tx + tmax, y + h), true);
  dl->AddText(font, 15.0f * s, ImVec2(tx - (1.0f - f.title_in) * 18.0f * s, y + 10.0f * s),
              Rgba(v.accent, f.title_a * a), v.title);
  char line[256];
  std::snprintf(line, sizeof(line), "%uG - %s", static_cast<unsigned>(std::lround(v.gamerscore * f.count)), v.label);
  dl->AddText(font, 21.0f * s, ImVec2(tx - (1.0f - f.label_in) * 26.0f * s, y + 29.0f * s),
              IM_COL32(240, 240, 242, static_cast<int>(255 * f.label_a * a)), line);
  dl->PopClipRect();
}
// <<< toast-render

// Logo del perfil: reforge_badge.rgba junto al .exe ("RFBG", ancho, alto, píxeles RGBA; lo escribe ReForge).
static std::unique_ptr<rex::ui::ImmediateTexture> LoadRgbaPath(rex::ui::ImmediateDrawer* drawer,
                                                                const std::filesystem::path& path) {
  if (!drawer) return nullptr;
  std::ifstream file(path, std::ios::binary);
  char magic[4] = {};
  uint32_t wh[2] = {};
  if (!file.read(magic, 4) || std::memcmp(magic, "RFBG", 4) != 0 || !file.read(reinterpret_cast<char*>(wh), 8))
    return nullptr;
  if (wh[0] == 0 || wh[1] == 0 || wh[0] > 1024 || wh[1] > 1024) return nullptr;
  std::vector<uint8_t> px(static_cast<size_t>(wh[0]) * wh[1] * 4);
  if (!file.read(reinterpret_cast<char*>(px.data()), static_cast<std::streamsize>(px.size()))) return nullptr;
  return drawer->CreateTexture(wh[0], wh[1], rex::ui::ImmediateTextureFilter::kLinear, false, px.data());
}

static std::unique_ptr<rex::ui::ImmediateTexture> LoadRgba(rex::ui::ImmediateDrawer* drawer,
                                                            const std::string& name) {
  if (name.empty()) return nullptr;
  return LoadRgbaPath(drawer, rex::filesystem::GetExecutableFolder() / name);
}

static std::unique_ptr<rex::ui::ImmediateTexture> LoadBadge(rex::ui::ImmediateDrawer* drawer) {
  return LoadRgba(drawer, Config().badge);
}

// ---------------------------------------------------------------- mandos: acceso en serie
// rexglue 0.10 reconstruye su lista de mandos (InputSystem::RefreshDevices) en cada consulta del juego y sin
// cerrojo. Los juegos consultan el mando desde varios hilos (vibración al disparar, conexión, teclas): dos
// reconstrucciones a la vez dañan la memoria y el juego se cierra (sobre todo al desconectar/reconectar el
// mando). Aquí las llamadas del juego pasan de una en una a la implementación original del runtime.
static std::mutex& InputMutex() {
  static std::mutex m;
  return m;
}
static u32 XamInputGetCapabilities_hook(u32 user, u32 flags, rex::MappedPtr<rex::input::X_INPUT_CAPABILITIES> caps) {
  std::lock_guard<std::mutex> lock(InputMutex());
  return rex::kernel::xam::XamInputGetCapabilities_entry(user, flags, caps);
}
static u32 XamInputGetCapabilitiesEx_hook(u32 unk, u32 user, u32 flags,
                                          rex::MappedPtr<rex::input::X_INPUT_CAPABILITIES> caps) {
  std::lock_guard<std::mutex> lock(InputMutex());
  return rex::kernel::xam::XamInputGetCapabilitiesEx_entry(unk, user, flags, caps);
}
// Menú Guía abierto: el juego no recibe el mando (como en la consola). El botón Guía nunca le llega.
static std::atomic<bool> g_guide_open{false};
static constexpr uint16_t kGuideButton = 0x0400;

static u32 XamInputGetState_hook(u32 user, u32 flags, rex::MappedPtr<rex::input::X_INPUT_STATE> state) {
  std::lock_guard<std::mutex> lock(InputMutex());
  const u32 r = rex::kernel::xam::XamInputGetState_entry(user, flags, state);
  if (r == 0 && state) {
    auto& gp = state->gamepad;
    if (g_guide_open.load()) {
      gp.buttons = 0;
      gp.left_trigger = gp.right_trigger = 0;
      gp.thumb_lx = gp.thumb_ly = gp.thumb_rx = gp.thumb_ry = 0;
    } else {
      gp.buttons = static_cast<uint16_t>(static_cast<uint16_t>(gp.buttons) & ~kGuideButton);
    }
  }
  return r;
}
static u32 XamInputSetState_hook(u32 user, u32 unk, rex::MappedPtr<rex::input::X_INPUT_VIBRATION> vib) {
  std::lock_guard<std::mutex> lock(InputMutex());
  return rex::kernel::xam::XamInputSetState_entry(user, unk, vib);
}
static u32 XamInputGetKeystroke_hook(u32 user, u32 flags, rex::MappedPtr<rex::input::X_INPUT_KEYSTROKE> key) {
  std::lock_guard<std::mutex> lock(InputMutex());
  if (g_guide_open.load()) return 0x10D2;  // ERROR_EMPTY: sin pulsaciones mientras el menú está abierto
  return rex::kernel::xam::XamInputGetKeystroke_entry(user, flags, key);
}
static u32 XamInputGetKeystrokeEx_hook(rex::MappedPtr<rex::be_u32> user, u32 flags,
                                       rex::MappedPtr<rex::input::X_INPUT_KEYSTROKE> key) {
  std::lock_guard<std::mutex> lock(InputMutex());
  if (g_guide_open.load()) return 0x10D2;
  return rex::kernel::xam::XamInputGetKeystrokeEx_entry(user, flags, key);
}

// ---------------------------------------------------------------- puntero del ratón y mando
// Se esconde en cuanto se usa el mando (o si el ratón lleva 3 s quieto) y vuelve al mover el ratón.
// Se comprueba en cada fotograma desde el dibujo de la interfaz, que corre en el hilo de la ventana.
class CursorGuard {
 public:
  void Update(rex::ui::Window* window, const ImGuiIO& io) {
    if (!window) return;
    const auto now = std::chrono::steady_clock::now();
    bool mouse = false;
#if defined(_WIN32)
    POINT pt{};
    if (GetCursorPos(&pt)) {
      if (have_pos_ && (std::abs(pt.x - last_.x) > 2 || std::abs(pt.y - last_.y) > 2)) mouse = true;
      last_ = pt;
      have_pos_ = true;
    }
#endif
    if (io.MouseDelta.x * io.MouseDelta.x + io.MouseDelta.y * io.MouseDelta.y > 4.0f) mouse = true;
    for (bool down : io.MouseDown) mouse = mouse || down;
    if (io.MouseWheel != 0.0f) mouse = true;
    if (mouse) last_mouse_ = now;
    const bool pad = PadActive(now);
    if (mouse && hidden_) {
      window->SetCursorVisibility(restore_);
      hidden_ = false;
    } else if (!mouse && !hidden_ && (pad || now - last_mouse_ > std::chrono::seconds(3))) {
      restore_ = window->GetCursorVisibility();
      if (restore_ == rex::ui::Window::CursorVisibility::kHidden) restore_ = rex::ui::Window::CursorVisibility::kVisible;
      window->SetCursorVisibility(rex::ui::Window::CursorVisibility::kHidden);
      hidden_ = true;
    }
  }

 private:
  bool PadActive(std::chrono::steady_clock::time_point now) {
#if defined(_WIN32)
    struct PadState {
      DWORD packet;
      WORD buttons;
      BYTE lt, rt;
      SHORT lx, ly, rx, ry;
    };
    using GetStateFn = DWORD(WINAPI*)(DWORD, PadState*);
    static const GetStateFn get_state = [] {
      for (const wchar_t* dll : {L"xinput1_4.dll", L"xinput1_3.dll", L"xinput9_1_0.dll"}) {
        if (HMODULE m = LoadLibraryW(dll)) {
          if (auto fn = reinterpret_cast<GetStateFn>(GetProcAddress(m, "XInputGetState"))) return fn;
        }
      }
      return GetStateFn(nullptr);
    }();
    if (!get_state) return false;
    bool active = false;
    for (DWORD i = 0; i < 4; ++i) {
      if (now < retry_[i]) continue;  // consultar un mando desconectado es lento: se espera 2 s
      PadState st{};
      if (get_state(i, &st) != 0) {
        retry_[i] = now + std::chrono::seconds(2);
        continue;
      }
      const auto big = [](SHORT v) { return v > 9000 || v < -9000; };
      if (st.packet != packet_[i] &&
          (st.buttons || st.lt > 40 || st.rt > 40 || big(st.lx) || big(st.ly) || big(st.rx) || big(st.ry)))
        active = true;
      packet_[i] = st.packet;
    }
    return active;
#else
    (void)now;
    return false;
#endif
  }

  bool hidden_ = false;
  rex::ui::Window::CursorVisibility restore_ = rex::ui::Window::CursorVisibility::kVisible;
  std::chrono::steady_clock::time_point last_mouse_ = std::chrono::steady_clock::now();
#if defined(_WIN32)
  POINT last_{};
  bool have_pos_ = false;
  DWORD packet_[4] = {};
  std::chrono::steady_clock::time_point retry_[4] = {};
#endif
};

// ---------------------------------------------------------------- tirones (diagnóstico de rendimiento)
// Mide el tiempo entre imágenes que entrega el juego (VdSwap: una por fotograma del Xbox 360, no los
// repintados de la ventana). Cada tirón (> 50 ms) se anota en el log del juego con su hora,
// junto a lo que rexglue estaba haciendo (shaders, texturas, disco, audio): ReForge lo analiza al cerrar.
// Con el diagnóstico activado, además guarda el tiempo de cada fotograma en reforge_frametimes.csv.
static std::atomic<float> g_live_fps{0.0f};  // FPS del juego (medio segundo) para el contador en pantalla

class FramePacer {
 public:
  void Tick() {
    const auto now = std::chrono::steady_clock::now();
    if (have_last_) {
      const double ms = std::chrono::duration<double, std::milli>(now - last_).count();
      live_ms_ += ms;
      ++live_frames_;
      if (live_ms_ >= 500.0) {
        g_live_fps.store(static_cast<float>(live_frames_ * 1000.0 / live_ms_));
        live_ms_ = 0.0;
        live_frames_ = 0;
      }
      if (ms > 50.0 && ms < 10000.0 && ++hitches_logged_ <= 2000)
        REXLOG_WARN("[ReForge] Tirón de {:.0f} ms", ms);
      // Cada 5 s: FPS reales del juego y el peor fotograma (los bajones de 82 a 41 FPS no son «tirones»).
      if (ms < 700.0) {
        window_ms_ += ms;
        ++window_frames_;
        worst_ms_ = std::max(worst_ms_, ms);
      }
      if (window_ms_ >= 5000.0) {
        REXLOG_INFO("[ReForge] FPS {:.0f} · peor {:.0f} ms", window_frames_ * 1000.0 / window_ms_, worst_ms_);
        window_ms_ = 0.0;
        window_frames_ = 0;
        worst_ms_ = 0.0;
      }
      if (Config().diagnostics) {
        samples_.push_back(static_cast<float>(ms));
        if (samples_.size() >= 512) Flush();
      }
    }
    last_ = now;
    have_last_ = true;
  }
  ~FramePacer() { Flush(); }

 private:
  void Flush() {
    if (samples_.empty()) return;
    std::ofstream f(rex::filesystem::GetExecutableFolder() / "reforge_frametimes.csv",
                    first_flush_ ? std::ios::trunc : std::ios::app);
    if (first_flush_) f << "frame_ms\n";
    first_flush_ = false;
    for (float v : samples_) f << v << '\n';
    samples_.clear();
  }
  std::chrono::steady_clock::time_point last_;
  bool have_last_ = false;
  bool first_flush_ = true;
  unsigned hitches_logged_ = 0;
  double window_ms_ = 0.0;
  unsigned window_frames_ = 0;
  double worst_ms_ = 0.0;
  double live_ms_ = 0.0;
  unsigned live_frames_ = 0;
  std::vector<float> samples_;
};

static FramePacer& GuestPacer() {
  static FramePacer pacer;
  return pacer;
}

// El juego entrega cada fotograma con VdSwap: se mide aquí y se pasa a la implementación de rexglue.
// Si hay un tope (30 FPS con VSync, la base que duplica NVIDIA Smooth Motion), se espera aquí hasta el
// siguiente hueco: es una vez por fotograma del Xbox 360 y vale para cualquier juego.
static void WaitFrameCap() {
  static std::chrono::steady_clock::time_point next{};
  const float cap = FrameCap();
  if (cap < 1.0f) {
    next = {};
    return;
  }
  const auto now = std::chrono::steady_clock::now();
  const auto period = std::chrono::duration_cast<std::chrono::steady_clock::duration>(
      std::chrono::duration<double>(1.0 / cap));
  if (next.time_since_epoch().count() == 0 || now - next > period) next = now;  // tras un parón no se acumulan esperas
  next += period;
  if (next > now) std::this_thread::sleep_until(next);
}

static void VdSwap_hook(rex::MappedPtr<void> a, rex::MappedPtr<void> b, rex::MappedPtr<void> c,
                        rex::MappedPtr<void> d, rex::MappedPtr<void> e, rex::MappedPtr<rex::be_u32> f,
                        rex::MappedPtr<rex::be_u32> g, rex::MappedPtr<rex::be_u32> h,
                        rex::MappedPtr<rex::be_u32> i, rex::MappedPtr<rex::be_u32> j) {
  GuestPacer().Tick();
  rex::kernel::xboxkrnl::VdSwap_entry(a, b, c, d, e, f, g, h, i, j);
  WaitFrameCap();
}

// ---------------------------------------------------------------- copias de partida (4 ranuras)
// Un juego recompilado corre como código nativo: no se puede «congelar» su estado exacto como en un emulador
// (su pila de llamadas es la del procesador, y la GPU y el sonido viven en el driver). Lo que sí se puede es
// copiar sus partidas guardadas (puntos de control, perfil del juego) en ranuras y volver a ellas: al cargar
// una ranura el juego se reinicia solo con esas partidas, como al cargar desde su menú.
static constexpr int kSlotCount = 4;

static bool CopyTree(const std::filesystem::path& from, const std::filesystem::path& to) {
  std::error_code ec;
  std::filesystem::remove_all(to, ec);
  if (!std::filesystem::exists(from, ec)) return true;
  std::filesystem::create_directories(to.parent_path(), ec);
  std::filesystem::copy(from, to, std::filesystem::copy_options::recursive, ec);
  return !ec;
}

static std::string NowText() {
  const std::tm tm = [] {
    const std::time_t t = std::time(nullptr);
    std::tm r{};
#if defined(_WIN32)
    localtime_s(&r, &t);
#else
    localtime_r(&t, &r);
#endif
    return r;
  }();
  char buf[40];
  std::snprintf(buf, sizeof(buf), "%04d-%02d-%02d %02d:%02d:%02d", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
                tm.tm_hour, tm.tm_min, tm.tm_sec);
  return buf;
}

static std::string PathU8(const std::filesystem::path& p) {
  const auto u = p.u8string();
  return std::string(u.begin(), u.end());
}

static std::filesystem::path U8Path(const std::string& s) {
  return std::filesystem::path(std::u8string(s.begin(), s.end()));
}

static std::filesystem::path RestoreMarker() {
  return rex::filesystem::GetExecutableFolder() / "reforge_restore.txt";
}

// Al arrancar (antes de que el juego lea sus partidas): si se pidió cargar una ranura, se espera a que el
// juego anterior se cierre y se ponen sus partidas en su sitio.
struct SlotRestoreAtStartup {
  SlotRestoreAtStartup() {
    std::ifstream f(RestoreMarker());
    if (!f) return;
    std::string line, slot, save, profile;
    unsigned long pid = 0;
    while (std::getline(f, line)) {
      const auto eq = line.find('=');
      if (eq == std::string::npos) continue;
      const std::string k = line.substr(0, eq), v = line.substr(eq + 1);
      if (k == "pid") pid = std::strtoul(v.c_str(), nullptr, 10);
      else if (k == "slot") slot = v;
      else if (k == "save") save = v;
      else if (k == "profile") profile = v;
    }
    f.close();
    std::error_code ec;
    std::filesystem::remove(RestoreMarker(), ec);
#if defined(_WIN32)
    if (pid) {
      if (HANDLE h = OpenProcess(SYNCHRONIZE, 0, static_cast<DWORD>(pid))) {
        WaitForSingleObject(h, 20000);
        CloseHandle(h);
      }
    }
#endif
    if (slot.empty() || save.empty()) return;
    const std::filesystem::path s = U8Path(slot);
    CopyTree(s / "save", U8Path(save));
    if (!profile.empty()) CopyTree(s / "profile", U8Path(profile));
  }
};
static SlotRestoreAtStartup g_slot_restore;

class SaveSlots {
 public:
  struct Info {
    bool used = false;
    std::string when;
  };

  void Init(rex::Runtime* runtime) {
    if (ready_ || !runtime || !runtime->kernel_state()) return;
    const uint32_t tid = runtime->kernel_state()->title_id();
    if (!tid) return;
    char t[16], x[24];
    std::snprintf(t, sizeof(t), "%08X", tid);
    std::snprintf(x, sizeof(x), "%016llX", static_cast<unsigned long long>(kXuid));
    std::error_code ec;
    const auto user = std::filesystem::absolute(runtime->user_data_root(), ec);
    save_ = user / x / t;
    profile_ = user / t / "profile";
    root_ = user / "reforge_slots" / t;
    ready_ = true;
  }
  bool ready() const { return ready_; }
  std::filesystem::path Dir(int i) const { return root_ / std::to_string(i + 1); }

  Info Get(int i) const {
    Info info;
    std::ifstream f(Dir(i) / "info.txt");
    std::string line;
    while (std::getline(f, line))
      if (line.rfind("when=", 0) == 0) {
        info.when = line.substr(5);
        info.used = true;
      }
    return info;
  }

  // Partidas del juego: contenido guardado (XUID/título) o ajustes de perfil del título (algunos arcade guardan
  // su progreso solo ahí).
  bool HasSaves() const {
    std::error_code ec;
    return std::filesystem::exists(save_, ec) || std::filesystem::exists(profile_, ec);
  }

  // Copia las partidas del juego en la ranura (y una miniatura de la imagen actual).
  bool Save(int i, rex::ui::Presenter* presenter) {
    if (!ready_) return false;
    const auto dir = Dir(i), tmp = root_ / (std::to_string(i + 1) + ".tmp");
    std::error_code ec;
    std::filesystem::remove_all(tmp, ec);
    std::filesystem::create_directories(tmp, ec);
    if (!CopyTree(save_, tmp / "save") || !CopyTree(profile_, tmp / "profile")) return false;
    if (presenter) WriteThumb(presenter, tmp / "thumb.rgba");
    {
      std::ofstream info(tmp / "info.txt", std::ios::trunc);
      info << "when=" << NowText() << "\n";
    }
    std::filesystem::remove_all(dir, ec);
    std::filesystem::rename(tmp, dir, ec);
    return !ec;
  }

  // Cargar: el juego se cierra y se vuelve a abrir solo con las partidas de la ranura.
  bool Load(int i, rex::ui::Window* window) {
    if (!ready_ || !Get(i).used) return false;
#if defined(_WIN32)
    {
      std::ofstream m(RestoreMarker(), std::ios::trunc);
      m << "pid=" << GetCurrentProcessId() << "\n"
        << "slot=" << PathU8(Dir(i)) << "\n"
        << "save=" << PathU8(save_) << "\n"
        << "profile=" << PathU8(profile_) << "\n";
    }
    std::ofstream(rex::filesystem::GetExecutableFolder() / "reforge_restart.flag", std::ios::trunc) << NowText();
    wchar_t exe[MAX_PATH];
    GetModuleFileNameW(nullptr, exe, MAX_PATH);
    std::wstring cmd = GetCommandLineW();
    STARTUPINFOW si{};
    si.cb = sizeof(si);
    PROCESS_INFORMATION pi{};
    const std::wstring dir = rex::filesystem::GetExecutableFolder().wstring();
    if (!CreateProcessW(exe, cmd.data(), nullptr, nullptr, 0, 0, nullptr, nullptr, &si, &pi)) {
      std::error_code ec;
      std::filesystem::remove(RestoreMarker(), ec);
      return false;
    }
    (void)dir;
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    if (window) window->RequestClose();
    return true;
#else
    (void)window;
    return false;
#endif
  }

  std::unique_ptr<rex::ui::ImmediateTexture>& Thumb(int i, rex::ui::ImmediateDrawer* drawer) {
    if (!thumb_loaded_[i]) {
      thumb_loaded_[i] = true;
      thumbs_[i] = LoadRgbaPath(drawer, Dir(i) / "thumb.rgba");
    }
    return thumbs_[i];
  }
  void Forget(int i) { thumb_loaded_[i] = false; thumbs_[i].reset(); }

 private:
  static void WriteThumb(rex::ui::Presenter* presenter, const std::filesystem::path& path) {
    rex::ui::RawImage img;
    if (!presenter->CaptureGuestOutput(img) || !img.width || !img.height) return;
    const uint32_t tw = 320, th = std::max<uint32_t>(1, 320 * img.height / img.width);
    std::vector<uint8_t> px(static_cast<size_t>(tw) * th * 4);
    for (uint32_t y = 0; y < th; ++y)
      for (uint32_t x = 0; x < tw; ++x) {
        const uint32_t sx = x * img.width / tw, sy = y * img.height / th;
        const uint8_t* s = img.data.data() + sy * img.stride + sx * 4;
        uint8_t* d = px.data() + (static_cast<size_t>(y) * tw + x) * 4;
        d[0] = s[0];
        d[1] = s[1];
        d[2] = s[2];
        d[3] = 255;
      }
    std::ofstream f(path, std::ios::binary | std::ios::trunc);
    f.write("RFBG", 4);
    f.write(reinterpret_cast<const char*>(&tw), 4);
    f.write(reinterpret_cast<const char*>(&th), 4);
    f.write(reinterpret_cast<const char*>(px.data()), static_cast<std::streamsize>(px.size()));
  }

  bool ready_ = false;
  std::filesystem::path save_, profile_, root_;
  std::unique_ptr<rex::ui::ImmediateTexture> thumbs_[kSlotCount];
  bool thumb_loaded_[kSlotCount] = {};
};

// ---------------------------------------------------------------- menú Guía (botón Xbox / PS)
// Como la Guía del Xbox 360: el botón Xbox/PS del mando (o la tecla Inicio) abre un panel con el perfil, los
// logros, la hora, el tiempo de juego, ajustes y «Salir del juego», todo manejable con el mando. Mientras está
// abierto el juego no recibe el mando y se le avisa como en la consola (XN_SYS_UI): la mayoría se pausa.

// Preferencias que se cambian desde el propio juego (reforge_menu.ini junto al .exe).
struct MenuPrefs {
  bool show_fps = false;
  int accent = -1;            // -1 = el color del perfil de ReForge
  std::string toast_position; // vacío = la del perfil
  bool hide_cursor = true;
  int button_style = -1;      // -1 = el de ReForge · 0 = Xbox · 1 = PlayStation (elegido en el menú Guía)
  int fps_mode = -1;          // -1 = el de ReForge · 0 = 30 FPS · 1 = 60 · 2 = sin límite (menú Guía → Gráficos)
  int resolution_scale = 0;   // 0 = la de ReForge · 1..3 (menú Guía → Gráficos)
  int mute = -1;              // -1 = la de ReForge · 0 = con sonido · 1 = silenciado (menú Guía → Ajustes)
  int language = 0;           // 0 = el de ReForge · 1..12 código de idioma del Xbox (menú Guía → Ajustes)
  bool loaded = false;
};

// Valores que entiende ReForge (reforge_menu.ini → .toml y reforge_ext.ini en el próximo arranque).
static const char* const kFpsKeys[] = {"30", "60", "unlimited"};

static constexpr uint32_t kAccents[] = {0x19D3A2, 0x107C10, 0x2D7FF9, 0xE8A317, 0xE3306B, 0x9B59F6};
static const char* const kAccentNames[] = {"Turquesa", "Verde Xbox", "Azul", "Dorado", "Rosa", "Violeta"};
// Códigos de idioma del Xbox (XGetLanguage): 1 inglés, 2 japonés, 3 alemán, 4 francés, 5 español, 6 italiano…
static const char* const kLanguageNames[] = {"English", "日本語", "Deutsch", "Français", "Español", "Italiano",
                                            "한국어", "中文", "Português", "Polski", "Русский", "Türkçe"};
static const char* const kPositions[] = {"top_left", "top_center", "top_right",
                                         "bottom_left", "bottom_center", "bottom_right"};
static const char* const kPositionNames[] = {"Arriba a la izquierda", "Arriba al centro", "Arriba a la derecha",
                                             "Abajo a la izquierda", "Abajo al centro", "Abajo a la derecha"};

static std::mutex& PrefsMutex() {
  static std::mutex m;
  return m;
}

static MenuPrefs& Prefs() {
  static MenuPrefs prefs;
  if (!prefs.loaded) {
    prefs.loaded = true;
    prefs.hide_cursor = Config().hide_cursor;
    std::ifstream file(rex::filesystem::GetExecutableFolder() / "reforge_menu.ini");
    std::string line;
    while (std::getline(file, line)) {
      const auto eq = line.find('=');
      if (eq == std::string::npos) continue;
      const std::string key = Trim(line.substr(0, eq)), val = Trim(line.substr(eq + 1));
      if (key == "show_fps") prefs.show_fps = (val == "1");
      else if (key == "accent") prefs.accent = std::clamp(std::atoi(val.c_str()), -1, 5);
      else if (key == "toast_position") prefs.toast_position = val;
      else if (key == "hide_cursor") prefs.hide_cursor = (val != "0");
      else if (key == "button_style") prefs.button_style = (val == "playstation") ? 1 : (val == "xbox" ? 0 : -1);
      else if (key == "fps_mode") prefs.fps_mode = (val == "30") ? 0 : (val == "60" ? 1 : (val == "unlimited" ? 2 : -1));
      else if (key == "resolution_scale") prefs.resolution_scale = std::clamp(std::atoi(val.c_str()), 0, 3);
      else if (key == "mute") prefs.mute = (val == "1") ? 1 : 0;
      else if (key == "language") prefs.language = std::clamp(std::atoi(val.c_str()), 0, 12);
    }
  }
  return prefs;
}

static void SavePrefs() {
  const MenuPrefs& p = Prefs();
  std::ofstream f(rex::filesystem::GetExecutableFolder() / "reforge_menu.ini", std::ios::trunc);
  f << "# Ajustes elegidos en el menú Guía del juego (botón Xbox/PS)\n"
    << "show_fps = " << (p.show_fps ? 1 : 0) << "\n"
    << "accent = " << p.accent << "\n"
    << "toast_position = " << p.toast_position << "\n"
    << "hide_cursor = " << (p.hide_cursor ? 1 : 0) << "\n"
    << "button_style = " << (p.button_style == 1 ? "playstation" : (p.button_style == 0 ? "xbox" : "")) << "\n";
  if (p.fps_mode >= 0) f << "fps_mode = " << kFpsKeys[std::clamp(p.fps_mode, 0, 2)] << "\n";
  if (p.resolution_scale > 0) f << "resolution_scale = " << std::clamp(p.resolution_scale, 1, 3) << "\n";
  if (p.mute >= 0) f << "mute = " << (p.mute == 1 ? 1 : 0) << "\n";
  if (p.language > 0) f << "language = " << std::clamp(p.language, 1, 12) << "\n";
}

// Iconos de botones: los de PlayStation se ven en el menú Guía y, con el SDK de ReForge, en las texturas del
// propio juego (reforge_textures/style.txt: la GPU lo vigila y cambia los iconos al momento).
static std::atomic<int> g_pad_ps{-1};

static bool PadPS() {
  int v = g_pad_ps.load();
  if (v < 0) {
    v = Config().playstation ? 1 : 0;
    std::ifstream f(rex::filesystem::GetExecutableFolder() / "reforge_textures" / "style.txt");
    std::string s;
    if (f >> s) v = (s == "playstation") ? 1 : 0;
    g_pad_ps.store(v);
  }
  return v == 1;
}

static void SetPadPS(bool ps) {
  g_pad_ps.store(ps ? 1 : 0);
  std::error_code ec;
  const auto dir = rex::filesystem::GetExecutableFolder() / "reforge_textures";
  std::filesystem::create_directories(dir, ec);
  std::ofstream f(dir / "style.txt", std::ios::trunc);
  f << (ps ? "playstation" : "xbox") << "\n";
}

static uint32_t AccentColor() {
  const int a = Prefs().accent;
  return a >= 0 ? kAccents[a] : Config().accent;
}

static const char* ToastPosition() {
  const std::string& p = Prefs().toast_position;
  for (const char* k : kPositions)
    if (p == k) return k;
  return Config().toast_position.c_str();
}

// Sonido: lo que elige el menú Guía manda sobre reforge_ext.ini; el runtime lo lee en cada envío de audio,
// así que se corta al momento (sin reiniciar).
static bool Muted() {
  const int m = Prefs().mute;
  if (m >= 0) return m == 1;
  const std::string v = rex::cvar::GetFlagByName("audio_mute");
  return v == "1" || v == "true";
}

static void ApplyMute(bool mute) {
  rex::cvar::SetFlagByName("audio_mute", mute ? "true" : "false");
}

// Tiempo de juego: el de esta partida y el total (reforge_playtime.txt junto al .exe, se guarda cada minuto).
class PlayClock {
 public:
  PlayClock() : start_(std::chrono::steady_clock::now()) {
    std::ifstream f(rex::filesystem::GetExecutableFolder() / "reforge_playtime.txt");
    f >> before_;
  }
  uint64_t Session() const {
    return static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::seconds>(std::chrono::steady_clock::now() - start_).count());
  }
  uint64_t Total() const { return before_ + Session(); }
  void MaybeSave() {
    const uint64_t s = Session();
    if (s < saved_at_ + 60) return;
    saved_at_ = s;
    std::ofstream f(rex::filesystem::GetExecutableFolder() / "reforge_playtime.txt", std::ios::trunc);
    f << Total() << "\n";
  }

 private:
  std::chrono::steady_clock::time_point start_;
  uint64_t before_ = 0;
  uint64_t saved_at_ = 0;
};

static std::string Hms(uint64_t s) {
  char buf[32];
  if (s >= 3600)
    std::snprintf(buf, sizeof(buf), "%llu h %02llu min", static_cast<unsigned long long>(s / 3600),
                  static_cast<unsigned long long>((s / 60) % 60));
  else
    std::snprintf(buf, sizeof(buf), "%llu min", static_cast<unsigned long long>(s / 60));
  return buf;
}

static std::tm LocalNow() {
  const std::time_t t = std::time(nullptr);
  std::tm tm{};
#if defined(_WIN32)
  localtime_s(&tm, &t);
#else
  localtime_r(&t, &tm);
#endif
  return tm;
}

static std::string DateFromFiletime(uint64_t ft) {
  if (!ft) return "";
  const std::time_t t = static_cast<std::time_t>(ft / 10000000ull - 11644473600ull);
  std::tm tm{};
#if defined(_WIN32)
  localtime_s(&tm, &t);
#else
  localtime_r(&t, &tm);
#endif
  char buf[32];
  std::snprintf(buf, sizeof(buf), "%02d/%02d/%04d", tm.tm_mday, tm.tm_mon + 1, tm.tm_year + 1900);
  return buf;
}

class GuideMenu {
 public:
  GuideMenu(rex::ui::ImmediateDrawer* immediate, rex::Runtime* runtime, rex::ui::Window* window,
            rex::system::AchievementManager* achievements, rex::ui::AchievementIconCache* icons)
      : immediate_(immediate), runtime_(runtime), window_(window), achievements_(achievements), icons_(icons) {}

  bool open() const { return open_; }

  void Draw(ImGuiIO& io) {
    clock_.MaybeSave();
    slots_.Init(runtime_);
    if (!Config().guide_menu) return;
    const uint16_t pad = PollPad();
    const uint16_t pressed = static_cast<uint16_t>(pad & ~last_pad_);
    last_pad_ = pad;
    const bool home_key = ImGui::IsKeyPressed(ImGuiKey_Home, false);
    if ((pressed & kGuideButton) || home_key) {
      SetOpen(!open_);
    } else if (open_ && ImGui::IsKeyPressed(ImGuiKey_Escape, false)) {
      SetOpen(false);
    }
    if (Prefs().show_fps) DrawFpsCounter(io);
    const float target = open_ ? 1.0f : 0.0f;
    anim_ += (target - anim_) * std::min(1.0f, io.DeltaTime * 14.0f);
    if (anim_ < 0.01f) return;
    if (open_) HandleInput(pressed, pad, io);
    Render(io);
  }

 private:
  enum Tab { kHome = 0, kGraphics = 1, kSaves = 2, kAchievements = 3, kSettings = 4, kTabs = 5 };

  uint16_t PollPad() {
    uint16_t buttons = 0;
    auto* input = runtime_ ? static_cast<rex::input::InputSystem*>(runtime_->input_system()) : nullptr;
    if (!input) return 0;
    std::lock_guard<std::mutex> lock(InputMutex());
    for (uint32_t user = 0; user < 4; ++user) {
      rex::input::X_INPUT_STATE st{};
      if (input->GetStateForUI(user, &st) != 0) continue;
      uint16_t b = static_cast<uint16_t>(st.gamepad.buttons);
      const int ly = static_cast<int16_t>(st.gamepad.thumb_ly);
      if (ly > 16000) b |= 0x0001;          // stick izquierdo como cruceta
      if (ly < -16000) b |= 0x0002;
      const int lx = static_cast<int16_t>(st.gamepad.thumb_lx);
      if (lx < -16000) b |= 0x0004;
      if (lx > 16000) b |= 0x0008;
      buttons |= b;
    }
    return buttons;
  }

  void SetOpen(bool open) {
    if (open == open_) return;
    open_ = open;
    g_guide_open.store(open);
    confirm_exit_ = false;
    confirm_load_ = -1;
    if (open) {
      recent_dirty_ = true;
      tab_ = kHome;
      sel_[kHome] = 0;
      opened_at_ = std::chrono::steady_clock::now();
    }
    if (runtime_ && runtime_->kernel_state())
      runtime_->kernel_state()->BroadcastNotification(0x00000009 /* XN_SYS_UI */, open ? 1 : 0);
  }

  int ItemCount(int tab) const {
    if (tab == kHome) return 2;
    if (tab == kGraphics) return 3;
    if (tab == kSettings) return 7;
    if (tab == kSaves) return kSlotCount;
    return static_cast<int>(list_.size());
  }

  void HandleInput(uint16_t pressed, uint16_t held, ImGuiIO& io) {
    // repetición al mantener arriba/abajo
    const auto now = std::chrono::steady_clock::now();
    uint16_t nav = pressed;
    if (held & 0x0003) {
      if (pressed & 0x0003) repeat_at_ = now + std::chrono::milliseconds(380);
      else if (now >= repeat_at_) {
        nav |= held & 0x0003;
        repeat_at_ = now + std::chrono::milliseconds(70);
      }
    }
    if (ImGui::IsKeyPressed(ImGuiKey_UpArrow)) nav |= 0x0001;
    if (ImGui::IsKeyPressed(ImGuiKey_DownArrow)) nav |= 0x0002;
    if (ImGui::IsKeyPressed(ImGuiKey_LeftArrow)) nav |= 0x0004;
    if (ImGui::IsKeyPressed(ImGuiKey_RightArrow)) nav |= 0x0008;
    if (ImGui::IsKeyPressed(ImGuiKey_Enter, false)) nav |= 0x1000;
    if (ImGui::IsKeyPressed(ImGuiKey_Backspace, false)) nav |= 0x2000;
    if (ImGui::IsKeyPressed(ImGuiKey_Q, false)) nav |= 0x0100;
    if (ImGui::IsKeyPressed(ImGuiKey_E, false)) nav |= 0x0200;
    if (ImGui::IsKeyPressed(ImGuiKey_Y, false)) nav |= 0x8000;
    (void)io;
    if (confirm_load_ >= 0) {
      if (nav & 0x1000) {           // A: cargar la ranura (el juego se reinicia)
        const int i = confirm_load_;
        confirm_load_ = -1;
        clock_.MaybeSave();
        SetOpen(false);
        if (!slots_.Load(i, window_)) Status("No se pudo cargar la ranura.");
      } else if (nav & 0x2000) {
        confirm_load_ = -1;
      }
      return;
    }
    if (confirm_exit_) {
      if (nav & 0x1000) {           // A: salir de verdad
        clock_.MaybeSave();
        SetOpen(false);
        if (window_) window_->RequestClose();
      } else if (nav & 0x2000) {
        confirm_exit_ = false;
      }
      return;
    }
    if (nav & 0x0100) ChangeTab(-1);  // LB
    if (nav & 0x0200) ChangeTab(+1);  // RB
    const int n = ItemCount(tab_);
    if (n > 0) {
      if (nav & 0x0001) sel_[tab_] = (sel_[tab_] + n - 1) % n;
      if (nav & 0x0002) sel_[tab_] = (sel_[tab_] + 1) % n;
    }
    if (nav & 0x2000) {             // B: volver al juego
      SetOpen(false);
      return;
    }
    if (tab_ == kSaves && (nav & 0x8000)) {  // Y: cargar
      if (slots_.Get(sel_[kSaves]).used) confirm_load_ = sel_[kSaves];
      else Status("Esa ranura está vacía.");
      return;
    }
    if (nav & (0x1000 | 0x0004 | 0x0008)) Activate(nav);
  }

  void Status(const char* text) {
    status_ = text;
    status_until_ = std::chrono::steady_clock::now() + std::chrono::seconds(4);
  }

  void SaveSlot(int i) {
    if (!slots_.ready()) return Status("El juego aún no ha cargado: inténtalo en unos segundos.");
    if (!slots_.HasSaves())
      return Status("El juego todavía no ha guardado nada: guarda o llega a un punto de control y vuelve.");
    auto* gs = runtime_ ? runtime_->graphics_system() : nullptr;
    if (slots_.Save(i, gs ? gs->presenter() : nullptr)) {
      slots_.Forget(i);
      char b[64];
      std::snprintf(b, sizeof(b), "Partida copiada en la ranura %d.", i + 1);
      Status(b);
    } else {
      Status("No se pudo copiar la partida.");
    }
  }

  void ChangeTab(int d) {
    tab_ = (tab_ + kTabs + d) % kTabs;
    if (tab_ == kAchievements) RefreshList();
  }

  // ---------------------------------------------------------------- pestaña Gráficos
  // Cambia las cvars de rexglue en caliente (escala de resolución, ritmo de fotogramas, contador de FPS) y
  // guarda lo elegido en reforge_menu.ini: ReForge lo pasa al .toml y al reforge_ext.ini en el próximo arranque.
  static bool VsyncOn() { return rex::cvar::GetFlagByName("vsync") != "false"; }

  static int CurrentFpsMode() {
    const float cap = FrameCap();
    if (cap >= 29.0f && cap <= 31.0f && VsyncOn()) return 0;   // 30 FPS con VSync
    if (!VsyncOn()) return 2;                                  // sin límite
    return 1;                                                  // 60 con VSync
  }

  static void SetCvar(const char* name, const char* value, bool& restart) {
    if (!rex::cvar::SetFlagByName(name, value)) return;
    const auto* info = rex::cvar::GetFlagInfo(name);
    if (info && info->lifecycle != rex::cvar::Lifecycle::kHotReload) restart = true;
  }

  void ApplyGraphics(int item, int dir) {
    bool restart = false;
    std::lock_guard<std::mutex> lock(PrefsMutex());
    MenuPrefs& p = Prefs();
    std::string text;
    if (item == 0) {
      const int next = (CurrentFpsMode() + 3 + dir) % 3;
      if (next == 2) {
        g_frame_cap.store(0.0f);
        SetCvar("vsync", "false", restart);
        SetCvar("d3d12_allow_variable_refresh_rate_and_tearing", "true", restart);
        text = "Sin límite de fotogramas";
      } else {
        g_frame_cap.store(next == 0 ? 30.0f : 0.0f);
        SetCvar("vsync", "true", restart);
        SetCvar("video_mode_refresh_rate", "60", restart);
        SetCvar("d3d12_allow_variable_refresh_rate_and_tearing", "false", restart);
        text = next == 0 ? "30 FPS con VSync · NVIDIA Smooth Motion lo duplica a 60" : "60 FPS con VSync";
      }
      p.fps_mode = next;
    } else if (item == 1) {
      const int cur = std::clamp(std::atoi(rex::cvar::GetFlagByName("draw_resolution_scale_x").c_str()), 1, 3);
      const int next = std::clamp(cur + dir, 1, 3);
      const std::string v = std::to_string(next);
      SetCvar("draw_resolution_scale_x", v.c_str(), restart);
      SetCvar("draw_resolution_scale_y", v.c_str(), restart);
      p.resolution_scale = next;
      text = "Resolución interna: " + v + "×";
    } else {
      p.show_fps = !p.show_fps;
      text = p.show_fps ? "Contador de FPS activado" : "Contador de FPS desactivado";
    }
    SavePrefs();
    if (restart) text += " (se aplica al reiniciar el juego)";
    Status(text.c_str());
  }

  void Activate(uint16_t nav) {
    const bool a = nav & 0x1000;
    const int dir = (nav & 0x0004) ? -1 : 1;
    if (tab_ == kHome && a) {
      if (sel_[kHome] == 0) SetOpen(false);
      else confirm_exit_ = true;
    } else if (tab_ == kGraphics) {
      ApplyGraphics(sel_[kGraphics], dir);
    } else if (tab_ == kSaves && a) {
      SaveSlot(sel_[kSaves]);
    } else if (tab_ == kSettings) {
      std::lock_guard<std::mutex> lock(PrefsMutex());
      MenuPrefs& p = Prefs();
      switch (sel_[kSettings]) {
        case 0: p.show_fps = !p.show_fps; break;
        case 1: p.accent = (p.accent + 1 + dir + 7) % 7 - 1; break;  // -1..5
        case 2: {
          int i = 0;
          const char* cur = ToastPosition();
          for (int k = 0; k < 6; ++k)
            if (std::strcmp(cur, kPositions[k]) == 0) i = k;
          p.toast_position = kPositions[(i + 6 + dir) % 6];
          break;
        }
        case 3: p.hide_cursor = !p.hide_cursor; break;
        case 4: {
          const bool ps = !PadPS();
          p.button_style = ps ? 1 : 0;
          SetPadPS(ps);
          status_ = ps ? "Iconos de PlayStation" : "Iconos de Xbox";
          status_until_ = std::chrono::steady_clock::now() + std::chrono::seconds(2);
          break;
        }
        case 6: {
          const uint32_t cur = GameLanguage();
          uint32_t next = (cur + dir + 12 - 1) % 12 + 1;      // 1..12 en bucle, en el sentido de la cruceta
          p.language = static_cast<int>(next);
          g_language.store(next);
          status_ = std::string("Idioma del juego: ") + kLanguageNames[next - 1];
          status_until_ = std::chrono::steady_clock::now() + std::chrono::seconds(3);
          break;
        }
        case 5: {
          const bool mute = !Muted();
          p.mute = mute ? 1 : 0;
          ApplyMute(mute);
          status_ = mute ? "Juego silenciado" : "Sonido activado";
          status_until_ = std::chrono::steady_clock::now() + std::chrono::seconds(2);
          break;
        }
      }
      SavePrefs();
    }
  }

  void RefreshList() {
    list_.clear();
    if (!achievements_) return;
    list_ = achievements_->ListAchievements();
    // desbloqueados primero (los más recientes arriba), luego el resto
    std::stable_sort(list_.begin(), list_.end(), [&](const auto& x, const auto& y) {
      const uint64_t tx = achievements_->GetUnlockTime(x.id), ty = achievements_->GetUnlockTime(y.id);
      const bool ux = achievements_->IsUnlocked(x.id), uy = achievements_->IsUnlocked(y.id);
      if (ux != uy) return ux;
      return tx > ty;
    });
    if (sel_[kAchievements] >= static_cast<int>(list_.size())) sel_[kAchievements] = 0;
  }

  void DrawFpsCounter(ImGuiIO& io) {
    (void)io;
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%.0f FPS", g_live_fps.load());
    ImDrawList* dl = ImGui::GetForegroundDrawList();
    const float fs = ImGui::GetFontSize() * 1.1f;
    const ImVec2 sz = ImGui::GetFont()->CalcTextSizeA(fs, 1e9f, 0.0f, buf);
    dl->AddRectFilled(ImVec2(10, 10), ImVec2(22 + sz.x, 18 + sz.y), IM_COL32(0, 0, 0, 150), 6.0f);
    dl->AddText(ImGui::GetFont(), fs, ImVec2(16, 14), Rgba(AccentColor(), 1.0f), buf);
  }

  void Text(ImDrawList* dl, float size, ImVec2 pos, ImU32 col, const char* text, float wrap = 0.0f) {
    dl->AddText(ImGui::GetFont(), size, pos, col, text, nullptr, wrap);
  }

  // Recorta el texto a una línea de ancho máximo con «…» (cuidando no partir un carácter UTF-8).
  static std::string Ellipsize(const std::string& t, float size, float max_w) {
    ImFont* f = ImGui::GetFont();
    if (f->CalcTextSizeA(size, 1e9f, 0.0f, t.c_str()).x <= max_w) return t;
    std::string out = t;
    while (!out.empty()) {
      do out.pop_back();
      while (!out.empty() && (static_cast<unsigned char>(out.back()) & 0xC0) == 0x80);
      if (!out.empty()) out.pop_back();
      if (f->CalcTextSizeA(size, 1e9f, 0.0f, (out + "...").c_str()).x <= max_w) return out + "...";
    }
    return "...";
  }

  bool Clicked(ImGuiIO& io, ImVec2 a, ImVec2 b) const {
    return ImGui::IsMouseClicked(0) && io.MousePos.x >= a.x && io.MousePos.x < b.x && io.MousePos.y >= a.y &&
           io.MousePos.y < b.y;
  }

  void Render(ImGuiIO& io) {
    if (!avatar_loaded_) {
      avatar_ = LoadRgba(immediate_, Config().avatar);
      if (!avatar_) avatar_ = LoadRgba(immediate_, Config().badge);
      avatar_loaded_ = true;
    }
    if (open_ && tab_ == kAchievements && list_.empty()) RefreshList();
    const float a = anim_;
    const ImVec2 ds = io.DisplaySize;
    const float u = std::max(0.75f, std::min(ds.x / 1280.0f, ds.y / 720.0f));  // escala con la resolución
    const float fs = 18.0f * u;
    const uint32_t accent = AccentColor();
    ImDrawList* dl = ImGui::GetForegroundDrawList();
    dl->AddRectFilled(ImVec2(0, 0), ds, IM_COL32(0, 0, 0, static_cast<int>(140 * a)));

    // panel lateral que entra desde la izquierda, como la Guía del 360
    const float w = std::min(ds.x * 0.92f, 560.0f * u);
    const float x0 = -w + w * OutCubic(a) + 24.0f * u * a;
    const float y0 = 24.0f * u, y1 = ds.y - 24.0f * u;
    dl->AddRectFilled(ImVec2(x0, y0), ImVec2(x0 + w, y1), IM_COL32(16, 18, 22, static_cast<int>(240 * a)), 14 * u);
    dl->AddRectFilled(ImVec2(x0, y0), ImVec2(x0 + w, y0 + 6 * u), Rgba(accent, a), 14 * u,
                      ImDrawFlags_RoundCornersTop);
    const ImU32 white = IM_COL32(240, 242, 245, static_cast<int>(255 * a));
    const ImU32 dim = IM_COL32(160, 168, 178, static_cast<int>(255 * a));
    const float pad = 22.0f * u;
    float x = x0 + pad, y = y0 + pad;

    // cabecera: avatar, gamertag, puntos, hora y fecha
    const float av = 72.0f * u;
    if (avatar_) {
      dl->AddImageRounded(reinterpret_cast<ImTextureID>(avatar_.get()), ImVec2(x, y), ImVec2(x + av, y + av),
                          ImVec2(0, 0), ImVec2(1, 1), IM_COL32(255, 255, 255, static_cast<int>(255 * a)), 12 * u);
    } else {
      dl->AddRectFilled(ImVec2(x, y), ImVec2(x + av, y + av), Rgba(accent, 0.85f * a), 12 * u);
      DrawTrophy(dl, ImVec2(x + av / 2, y + av / 2), av * 0.42f, 1.0f, white);
    }
    unsigned gs = 0, gs_total = 0, got = 0;
    if (achievements_) {
      for (const auto& ach : achievements_->ListAchievements()) {
        gs_total += ach.gamerscore;
        if (achievements_->IsUnlocked(ach.id)) {
          gs += ach.gamerscore;
          ++got;
        }
      }
    }
    const size_t n_ach = achievements_ ? achievements_->ListAchievements().size() : 0;
    Text(dl, fs * 1.35f, ImVec2(x + av + 16 * u, y + 2 * u), white, Config().gamertag.c_str());
    char line[160];
    std::snprintf(line, sizeof(line), "G %u / %u  ·  %u de %zu logros", gs, gs_total, got, n_ach);
    Text(dl, fs, ImVec2(x + av + 16 * u, y + 34 * u), Rgba(accent, a), line);
    const std::tm tm = LocalNow();
    static const char* const kDays[] = {"domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"};
    static const char* const kMonths[] = {"enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                                          "agosto", "septiembre", "octubre", "noviembre", "diciembre"};
    std::snprintf(line, sizeof(line), "%02d:%02d  ·  %s %d de %s", tm.tm_hour, tm.tm_min, kDays[tm.tm_wday % 7],
                  tm.tm_mday, kMonths[tm.tm_mon % 12]);
    Text(dl, fs * 0.9f, ImVec2(x + av + 16 * u, y + 58 * u), dim, line);
    y += av + 18 * u;
    if (!title_loaded_) {  // nombre oficial que trae el propio juego (su tabla XDBF); si no, el del proyecto
      title_loaded_ = true;
      if (runtime_ && runtime_->kernel_state()) {
        const auto db = runtime_->kernel_state()->title_xdbf();
        if (db.is_valid()) title_ = db.title();
      }
      if (title_.empty()) title_ = Config().game_name;
    }
    if (!title_.empty()) {
      const std::string shown_title = Ellipsize(title_, fs * 1.1f, w - 2 * pad);
      Text(dl, fs * 1.1f, ImVec2(x, y), white, shown_title.c_str());
      y += fs * 1.5f;
    }
    std::snprintf(line, sizeof(line), "Jugando: %s  ·  Total: %s  ·  %.0f FPS", Hms(clock_.Session()).c_str(),
                  Hms(clock_.Total()).c_str(), g_live_fps.load());
    Text(dl, fs * 0.9f, ImVec2(x, y), dim, line);
    y += fs * 1.8f;

    // pestañas (LB / RB)
    static const char* const kTabNames[] = {"Inicio", "Gráficos", "Partidas", "Logros", "Ajustes"};
    float tx = x;
    for (int t = 0; t < kTabs; ++t) {
      const ImVec2 sz = ImGui::GetFont()->CalcTextSizeA(fs, 1e9f, 0.0f, kTabNames[t]);
      const ImVec2 ta(tx - 10 * u, y - 6 * u), tb(tx + sz.x + 10 * u, y + sz.y + 6 * u);
      if (t == tab_) dl->AddRectFilled(ta, tb, Rgba(accent, 0.9f * a), 8 * u);
      Text(dl, fs, ImVec2(tx, y), t == tab_ ? IM_COL32(10, 12, 14, static_cast<int>(255 * a)) : dim, kTabNames[t]);
      if (open_ && Clicked(io, ta, tb)) {
        tab_ = t;
        if (tab_ == kAchievements) RefreshList();
      }
      tx += sz.x + 30 * u;
    }
    if (tx + 70 * u < x0 + w - pad)
      Text(dl, fs * 0.75f, ImVec2(x0 + w - pad - 70 * u, y + 2 * u), dim, "LB  ·  RB");
    y += fs * 2.2f;

    const float list_bottom = y1 - pad - fs * 1.6f;
    if (confirm_load_ >= 0) {
      std::snprintf(line, sizeof(line), "¿Cargar la ranura %d?", confirm_load_ + 1);
      Text(dl, fs * 1.2f, ImVec2(x, y), white, line);
      Text(dl, fs * 0.9f, ImVec2(x, y + fs * 1.8f), dim,
           "El juego se reinicia con las partidas de esa ranura; continúa desde «Cargar partida» o «Continuar» "
           "en su menú. Lo que no hayas guardado ahora se perderá.", w - 2 * pad);
      DrawButton(dl, io, ImVec2(x, y + fs * 5.2f), w - 2 * pad, fs, true, "A  Cargar y reiniciar", u, a, accent);
      DrawButton(dl, io, ImVec2(x, y + fs * 7.6f), w - 2 * pad, fs, false, "B  Cancelar", u, a, accent);
      if (Clicked(io, ImVec2(x, y + fs * 5.2f), ImVec2(x + w - 2 * pad, y + fs * 7.4f))) {
        const int i = confirm_load_;
        confirm_load_ = -1;
        SetOpen(false);
        if (!slots_.Load(i, window_)) Status("No se pudo cargar la ranura.");
      } else if (Clicked(io, ImVec2(x, y + fs * 7.6f), ImVec2(x + w - 2 * pad, y + fs * 9.6f))) {
        confirm_load_ = -1;
      }
    } else if (confirm_exit_) {
      Text(dl, fs * 1.2f, ImVec2(x, y), white, "¿Salir del juego?");
      Text(dl, fs * 0.9f, ImVec2(x, y + fs * 1.8f), dim,
           "Lo que no hayas guardado en el juego se perderá.", w - 2 * pad);
      DrawButton(dl, io, ImVec2(x, y + fs * 4.0f), w - 2 * pad, fs, true, "A  Salir del juego", u, a, accent);
      DrawButton(dl, io, ImVec2(x, y + fs * 6.4f), w - 2 * pad, fs, false, "B  Cancelar", u, a, accent);
      if (Clicked(io, ImVec2(x, y + fs * 4.0f), ImVec2(x + w - 2 * pad, y + fs * 6.0f))) {
        SetOpen(false);
        if (window_) window_->RequestClose();
      } else if (Clicked(io, ImVec2(x, y + fs * 6.4f), ImVec2(x + w - 2 * pad, y + fs * 8.4f))) {
        confirm_exit_ = false;
      }
    } else if (tab_ == kGraphics) {
      // pestaña Gráficos: lo que se puede cambiar sin salir del juego
      static const char* const kFpsNames[] = {"30 · Smooth Motion", "60 · VSync", "Sin límite"};
      const int sc = std::clamp(std::atoi(rex::cvar::GetFlagByName("draw_resolution_scale_x").c_str()), 1, 3);
      char scale_txt[64];
      std::snprintf(scale_txt, sizeof(scale_txt), "%d× (%s interno)", sc,
                    sc == 1 ? "720p" : (sc == 2 ? "1440p" : "2160p"));
      std::string vals[3] = {kFpsNames[CurrentFpsMode()], scale_txt, Prefs().show_fps ? "Sí" : "No"};
      const char* names[] = {"Fotogramas", "Escala de resolución", "Contador de FPS"};
      for (int i = 0; i < 3; ++i) {
        const ImVec2 q(x, y + i * fs * 2.6f);
        DrawButton(dl, io, q, w - 2 * pad, fs, sel_[kGraphics] == i, names[i], u, a, accent, vals[i].c_str());
        if (open_ && Clicked(io, q, ImVec2(q.x + w - 2 * pad, q.y + fs * 2.2f))) {
          sel_[kGraphics] = i;
          Activate(0x1000);
        }
      }
      Text(dl, fs * 0.8f, ImVec2(x, y + 3 * fs * 2.6f + 4 * u), dim,
           "«30 · Smooth Motion» deja el juego a 30 FPS reales con VSync: activa NVIDIA Smooth Motion "
           "(RTX 40/50) o AMD Fluid Motion en el driver y será él quien lo vea fluido a 60 sin acelerar el "
           "juego. La escala dibuja por dentro con más detalle sin tocar la ventana. Se guarda para la "
           "próxima vez; lo que el runtime no cambie en caliente se aplica al reiniciar.", w - 2 * pad);
    } else if (tab_ == kSaves) {
      // ranuras con miniatura, fecha y botones Guardar / Cargar
      const float th = 72.0f * u, tw = th * 16.0f / 9.0f, row = th + 14 * u;
      for (int i = 0; i < kSlotCount; ++i) {
        const float ry = y + i * row;
        if (ry + th > list_bottom - fs * 1.4f) break;
        const bool sel = sel_[kSaves] == i;
        if (sel)
          dl->AddRectFilled(ImVec2(x - 8 * u, ry - 6 * u), ImVec2(x + w - 2 * pad + 8 * u, ry + th + 6 * u),
                            Rgba(accent, 0.18f * a), 8 * u);
        const auto info = slots_.Get(i);
        auto& thumb = slots_.Thumb(i, immediate_);
        if (info.used && thumb) {
          dl->AddImageRounded(reinterpret_cast<ImTextureID>(thumb.get()), ImVec2(x, ry), ImVec2(x + tw, ry + th),
                              ImVec2(0, 0), ImVec2(1, 1), IM_COL32(255, 255, 255, static_cast<int>(255 * a)), 6 * u);
        } else {
          dl->AddRectFilled(ImVec2(x, ry), ImVec2(x + tw, ry + th), IM_COL32(30, 34, 40, static_cast<int>(255 * a)),
                            6 * u);
          std::snprintf(line, sizeof(line), "%d", i + 1);
          const ImVec2 ns = ImGui::GetFont()->CalcTextSizeA(fs * 1.6f, 1e9f, 0.0f, line);
          Text(dl, fs * 1.6f, ImVec2(x + (tw - ns.x) / 2, ry + (th - ns.y) / 2), dim, line);
        }
        const float bx = x + tw + 14 * u;
        std::snprintf(line, sizeof(line), "Ranura %d", i + 1);
        Text(dl, fs, ImVec2(bx, ry + 2 * u), white, line);
        Text(dl, fs * 0.8f, ImVec2(bx, ry + fs * 1.35f), dim, info.used ? info.when.c_str() : "Vacía");
        // botones
        const float bw = 110 * u, bh = fs * 1.7f, by = ry + th - bh;
        const ImVec2 s0(bx, by), s1(bx + bw, by + bh), l0(bx + bw + 10 * u, by), l1(bx + 2 * bw + 10 * u, by + bh);
        dl->AddRectFilled(s0, s1, sel ? Rgba(0x107C10, a) : IM_COL32(44, 48, 56, static_cast<int>(255 * a)), 6 * u);
        Text(dl, fs * 0.85f, ImVec2(s0.x + 12 * u, s0.y + bh * 0.22f), IM_COL32(240, 242, 245, 255 * a),
             "A Guardar");
        if (info.used) {
          dl->AddRectFilled(l0, l1, sel ? Rgba(0xE8A317, a) : IM_COL32(44, 48, 56, static_cast<int>(255 * a)), 6 * u);
          Text(dl, fs * 0.85f, ImVec2(l0.x + 12 * u, l0.y + bh * 0.22f),
               sel ? IM_COL32(20, 20, 20, 255 * a) : IM_COL32(240, 242, 245, 255 * a), "Y Cargar");
        }
        if (open_ && Clicked(io, s0, s1)) {
          sel_[kSaves] = i;
          SaveSlot(i);
        } else if (open_ && info.used && Clicked(io, l0, l1)) {
          sel_[kSaves] = i;
          confirm_load_ = i;
        } else if (open_ && Clicked(io, ImVec2(x, ry), ImVec2(x + tw, ry + th))) {
          sel_[kSaves] = i;
        }
      }
      const float ny = std::min(list_bottom - fs * 1.2f, y + kSlotCount * row + 4 * u);
      Text(dl, fs * 0.72f, ImVec2(x, ny), dim,
           "Copia las partidas guardadas del juego (puntos de control). Guarda en el juego antes de copiar.",
           w - 2 * pad);
    } else if (tab_ == kHome) {
      const char* items[] = {"Volver al juego", "Salir del juego"};
      for (int i = 0; i < 2; ++i) {
        const ImVec2 p(x, y + i * fs * 2.6f);
        DrawButton(dl, io, p, w - 2 * pad, fs, sel_[kHome] == i, items[i], u, a, accent);
        if (open_ && Clicked(io, p, ImVec2(p.x + w - 2 * pad, p.y + fs * 2.2f))) {
          sel_[kHome] = i;
          Activate(0x1000);
        }
      }
      // progreso de logros y los últimos desbloqueados
      float hy = y + 2 * fs * 2.6f + fs * 0.8f;
      if (n_ach) {
        std::snprintf(line, sizeof(line), "Logros: %u de %zu  (%u%%)", got, n_ach,
                      static_cast<unsigned>(got * 100 / n_ach));
        Text(dl, fs * 0.9f, ImVec2(x, hy), white, line);
        hy += fs * 1.4f;
        const float bw = w - 2 * pad;
        dl->AddRectFilled(ImVec2(x, hy), ImVec2(x + bw, hy + 8 * u), IM_COL32(40, 44, 52, static_cast<int>(255 * a)),
                          4 * u);
        dl->AddRectFilled(ImVec2(x, hy), ImVec2(x + bw * got / static_cast<float>(n_ach), hy + 8 * u),
                          Rgba(accent, a), 4 * u);
        hy += 8 * u + fs * 1.2f;
        if (recent_.empty() || recent_dirty_) {
          recent_.clear();
          for (const auto& ach : achievements_->ListAchievements())
            if (achievements_->IsUnlocked(ach.id)) recent_.push_back(ach);
          std::sort(recent_.begin(), recent_.end(), [&](const auto& p1, const auto& p2) {
            return achievements_->GetUnlockTime(p1.id) > achievements_->GetUnlockTime(p2.id);
          });
          if (recent_.size() > 3) recent_.resize(3);
          recent_dirty_ = false;
        }
        if (!recent_.empty()) {
          Text(dl, fs * 0.8f, ImVec2(x, hy), dim, "ÚLTIMOS LOGROS");
          hy += fs * 1.3f;
          for (const auto& ach : recent_) {
            const float ic = 40 * u;
            if (hy + ic > list_bottom) break;
            auto* icon = icons_ ? icons_->GetIcon(ach) : nullptr;
            if (icon) {
              dl->AddImageRounded(reinterpret_cast<ImTextureID>(icon), ImVec2(x, hy), ImVec2(x + ic, hy + ic),
                                  ImVec2(0, 0), ImVec2(1, 1), IM_COL32(255, 255, 255, static_cast<int>(255 * a)),
                                  6 * u);
            } else {
              dl->AddRectFilled(ImVec2(x, hy), ImVec2(x + ic, hy + ic),
                                IM_COL32(40, 44, 52, static_cast<int>(255 * a)), 6 * u);
              DrawTrophy(dl, ImVec2(x + ic / 2, hy + ic / 2), ic * 0.40f, 1.0f, Rgba(accent, a));
            }
            Text(dl, fs * 0.9f, ImVec2(x + ic + 10 * u, hy + 2 * u), white, ach.label.c_str());
            const std::string d = DateFromFiletime(achievements_->GetUnlockTime(ach.id));
            std::snprintf(line, sizeof(line), "%uG  ·  %s", ach.gamerscore, d.c_str());
            Text(dl, fs * 0.75f, ImVec2(x + ic + 10 * u, hy + fs * 1.15f), dim, line);
            hy += ic + 10 * u;
          }
        }
      }
    } else if (tab_ == kSettings) {
      const MenuPrefs& p = Prefs();
      const int ai = p.accent;
      std::string vals[7] = {p.show_fps ? "Sí" : "No", ai >= 0 ? kAccentNames[ai] : "El del perfil", "",
                             p.hide_cursor ? "Sí" : "No", PadPS() ? "PlayStation" : "Xbox",
                             Muted() ? "Sí" : "No", kLanguageNames[std::min<uint32_t>(GameLanguage(), 12) - 1]};
      for (int k = 0; k < 6; ++k)
        if (std::strcmp(ToastPosition(), kPositions[k]) == 0) vals[2] = kPositionNames[k];
      const char* names[] = {"Contador de FPS en pantalla", "Color de acento", "Notificación de logros",
                             "Esconder el puntero con el mando", "Iconos de botones", "Silenciar el juego",
                             "Idioma del juego"};
      for (int i = 0; i < 7; ++i) {
        const ImVec2 q(x, y + i * fs * 2.6f);
        DrawButton(dl, io, q, w - 2 * pad, fs, sel_[kSettings] == i, names[i], u, a, accent, vals[i].c_str());
        if (open_ && Clicked(io, q, ImVec2(q.x + w - 2 * pad, q.y + fs * 2.2f))) {
          sel_[kSettings] = i;
          Activate(0x1000);
        }
      }
      Text(dl, fs * 0.8f, ImVec2(x, y + 7 * fs * 2.6f + 4 * u), dim,
           "A o la cruceta (izquierda / derecha) para cambiar. Se guarda para este juego.", w - 2 * pad);
    } else {
      if (list_.empty()) {
        Text(dl, fs, ImVec2(x, y), dim, "Este juego no tiene logros registrados.", w - 2 * pad);
      } else {
        const float row = 64.0f * u;
        const float detail_h = fs * 3.2f;  // descripción completa del logro elegido
        const int visible = std::max(1, static_cast<int>((list_bottom - detail_h - y) / row));
        int& sel = sel_[kAchievements];
        if (sel < scroll_) scroll_ = sel;
        if (sel >= scroll_ + visible) scroll_ = sel - visible + 1;
        for (int i = scroll_; i < static_cast<int>(list_.size()) && i < scroll_ + visible; ++i) {
          const auto& ach = list_[i];
          const bool unlocked = achievements_->IsUnlocked(ach.id);
          const float ry = y + (i - scroll_) * row;
          if (i == sel)
            dl->AddRectFilled(ImVec2(x - 8 * u, ry - 4 * u), ImVec2(x + w - 2 * pad + 8 * u, ry + row - 8 * u),
                              Rgba(accent, 0.22f * a), 8 * u);
          if (open_ && Clicked(io, ImVec2(x, ry), ImVec2(x + w - 2 * pad, ry + row))) sel = i;
          const float ic = row - 16 * u;
          auto* icon = icons_ ? icons_->GetIcon(ach) : nullptr;
          if (icon && unlocked) {
            dl->AddImageRounded(reinterpret_cast<ImTextureID>(icon), ImVec2(x, ry), ImVec2(x + ic, ry + ic),
                                ImVec2(0, 0), ImVec2(1, 1), IM_COL32(255, 255, 255, static_cast<int>(255 * a)),
                                6 * u);
          } else {
            dl->AddRectFilled(ImVec2(x, ry), ImVec2(x + ic, ry + ic), IM_COL32(40, 44, 52, static_cast<int>(255 * a)),
                              6 * u);
            DrawTrophy(dl, ImVec2(x + ic / 2, ry + ic / 2), ic * 0.40f, 1.0f, unlocked ? Rgba(accent, a) : dim);
          }
          const float tx2 = x + ic + 12 * u;
          const std::string title = Ellipsize(ach.label, fs, x + w - 2 * pad - 70 * u - tx2);
          Text(dl, fs, ImVec2(tx2, ry), unlocked ? white : dim, title.c_str());
          const std::string& desc = unlocked || ach.unachieved_description.empty() ? ach.description
                                                                                  : ach.unachieved_description;
          const std::string shown = Ellipsize(desc, fs * 0.78f, x + w - 2 * pad - 96 * u - tx2);
          Text(dl, fs * 0.78f, ImVec2(tx2, ry + fs * 1.25f), dim, shown.c_str());
          std::snprintf(line, sizeof(line), "%uG", ach.gamerscore);
          Text(dl, fs * 0.9f, ImVec2(x + w - 2 * pad - 50 * u, ry), unlocked ? Rgba(accent, a) : dim, line);
          if (unlocked) {
            const std::string d = DateFromFiletime(achievements_->GetUnlockTime(ach.id));
            Text(dl, fs * 0.7f, ImVec2(x + w - 2 * pad - 84 * u, ry + fs * 1.3f), dim, d.c_str());
          }
        }
        if (sel >= 0 && sel < static_cast<int>(list_.size())) {
          const auto& ach = list_[sel];
          const bool unlocked = achievements_->IsUnlocked(ach.id);
          const std::string& desc = unlocked || ach.unachieved_description.empty() ? ach.description
                                                                                  : ach.unachieved_description;
          const float dy = list_bottom - detail_h + fs * 0.4f;
          dl->AddLine(ImVec2(x, dy - fs * 0.3f), ImVec2(x + w - 2 * pad, dy - fs * 0.3f),
                      IM_COL32(60, 66, 76, static_cast<int>(255 * a)));
          Text(dl, fs * 0.82f, ImVec2(x, dy), white, desc.c_str(), w - 2 * pad);
        }
      }
    }
    if (!status_.empty() && std::chrono::steady_clock::now() < status_until_) {
      const float sy = y1 - pad - fs * 2.6f;
      const ImVec2 ss = ImGui::GetFont()->CalcTextSizeA(fs * 0.85f, 1e9f, w - 2 * pad, status_.c_str());
      dl->AddRectFilled(ImVec2(x - 8 * u, sy - 6 * u), ImVec2(x + std::min(ss.x, w - 2 * pad) + 8 * u, sy + ss.y + 6 * u),
                        Rgba(accent, 0.9f * a), 6 * u);
      Text(dl, fs * 0.85f, ImVec2(x, sy), IM_COL32(10, 12, 14, static_cast<int>(255 * a)), status_.c_str(), w - 2 * pad);
    }
    // ayuda de botones abajo
    {
      float hx = x;
      const float hy2 = y1 - pad - fs * 0.9f;
      auto hint = [&](const char* glyph, uint32_t col, const char* text) {
        const float r = fs * 0.55f;
        const ImVec2 c(hx + r, hy2 + r * 0.8f);
        if (PadPS() && glyph[0] != 'G') {
          // ✕ ○ □ △ como en los mandos de PlayStation (A = ✕, B = ○, X = □, Y = △)
          dl->AddCircleFilled(c, r, IM_COL32(28, 29, 33, static_cast<int>(240 * a)));
          dl->AddCircle(c, r, IM_COL32(150, 152, 160, static_cast<int>(200 * a)), 0, 1.2f * u);
          const float k = r * 0.45f, th = std::max(1.5f, r * 0.2f);
          switch (glyph[0]) {
            case 'A': {
              const ImU32 pc = IM_COL32(0x7E, 0xB2, 0xDD, static_cast<int>(255 * a));
              dl->AddLine(ImVec2(c.x - k, c.y - k), ImVec2(c.x + k, c.y + k), pc, th);
              dl->AddLine(ImVec2(c.x - k, c.y + k), ImVec2(c.x + k, c.y - k), pc, th);
              break;
            }
            case 'B':
              dl->AddCircle(c, k * 1.05f, IM_COL32(0xFF, 0x66, 0x6E, static_cast<int>(255 * a)), 0, th);
              break;
            case 'X':
              dl->AddRect(ImVec2(c.x - k, c.y - k), ImVec2(c.x + k, c.y + k),
                          IM_COL32(0xE5, 0x9A, 0xCD, static_cast<int>(255 * a)), 0.0f, 0, th);
              break;
            default:
              dl->AddTriangle(ImVec2(c.x, c.y - k * 1.15f), ImVec2(c.x + k * 1.1f, c.y + k * 0.8f),
                              ImVec2(c.x - k * 1.1f, c.y + k * 0.8f),
                              IM_COL32(0x3F, 0xD0, 0xA8, static_cast<int>(255 * a)), th);
          }
        } else {
          const char* shown = (PadPS() && glyph[0] == 'G') ? "PS" : glyph;
          dl->AddCircleFilled(c, r, Rgba(PadPS() ? 0x1C1D21 : col, a));
          const ImVec2 gs2 = ImGui::GetFont()->CalcTextSizeA(fs * 0.7f, 1e9f, 0.0f, shown);
          Text(dl, fs * 0.7f, ImVec2(c.x - gs2.x / 2, c.y - gs2.y / 2), IM_COL32(255, 255, 255, 255 * a), shown);
        }
        hx += 2 * r + 6 * u;
        Text(dl, fs * 0.8f, ImVec2(hx, hy2), dim, text);
        hx += ImGui::GetFont()->CalcTextSizeA(fs * 0.8f, 1e9f, 0.0f, text).x + 18 * u;
      };
      if (confirm_exit_ || confirm_load_ >= 0) {
        hint("A", 0x107C10, "Confirmar");
        hint("B", 0xC0392B, "Cancelar");
      } else if (tab_ == kSaves) {
        hint("A", 0x107C10, "Guardar");
        hint("Y", 0xE8A317, "Cargar");
        hint("B", 0xC0392B, "Volver");
      } else {
        hint("A", 0x107C10, (tab_ == kSettings || tab_ == kGraphics) ? "Cambiar" : "Seleccionar");
        hint("B", 0xC0392B, "Volver al juego");
        hint("G", 0x2D7FF9, "Cerrar");
      }
    }
  }

  void DrawButton(ImDrawList* dl, ImGuiIO& io, ImVec2 p, float width, float fs, bool selected, const char* text,
                  float u, float a, uint32_t accent, const char* value = nullptr) {
    (void)io;
    const ImVec2 b(p.x + width, p.y + fs * 2.2f);
    dl->AddRectFilled(p, b, selected ? Rgba(accent, 0.95f * a) : IM_COL32(32, 36, 42, static_cast<int>(255 * a)),
                      9 * u);
    const ImU32 col = selected ? IM_COL32(8, 10, 12, static_cast<int>(255 * a))
                               : IM_COL32(236, 238, 241, static_cast<int>(255 * a));
    Text(dl, fs, ImVec2(p.x + 16 * u, p.y + fs * 0.55f), col, text);
    if (value) {
      const ImVec2 sz = ImGui::GetFont()->CalcTextSizeA(fs, 1e9f, 0.0f, value);
      Text(dl, fs, ImVec2(b.x - 16 * u - sz.x, p.y + fs * 0.55f), col, value);
    }
  }

  rex::ui::ImmediateDrawer* immediate_ = nullptr;
  rex::Runtime* runtime_ = nullptr;
  rex::ui::Window* window_ = nullptr;
  rex::system::AchievementManager* achievements_ = nullptr;
  rex::ui::AchievementIconCache* icons_ = nullptr;
  std::unique_ptr<rex::ui::ImmediateTexture> avatar_;
  bool avatar_loaded_ = false;
  bool open_ = false;
  bool confirm_exit_ = false;
  float anim_ = 0.0f;
  int tab_ = kHome;
  int sel_[kTabs] = {0, 0, 0, 0, 0};
  SaveSlots slots_;
  int confirm_load_ = -1;
  std::string status_;
  std::chrono::steady_clock::time_point status_until_{};
  int scroll_ = 0;
  uint16_t last_pad_ = 0;
  std::chrono::steady_clock::time_point repeat_at_{};
  std::chrono::steady_clock::time_point opened_at_{};
  std::vector<rex::system::AchievementInfo> list_;
  std::vector<rex::system::AchievementInfo> recent_;
  bool recent_dirty_ = true;
  std::string title_;
  bool title_loaded_ = false;
  PlayClock clock_;
};

// ---------------------------------------------------------------- guardián de imagen
// Mira la imagen del juego cada pocos segundos (miniatura, sin coste apreciable). Si sale casi toda blanca
// varias veces seguidas (exposición automática rota: el juego mide el brillo leyendo desde la CPU una textura
// que dibuja la GPU y, sin esa lectura, sube la exposición al máximo), activa en caliente la lectura de
// resolves de rexglue: primero «some» (solo cuando el juego lo pide), luego «fast» (cada fotograma) y si no basta
// «full» (inmediata). Lo anota en
// el log y en reforge_tune.ini para que ReForge lo use desde el arranque en las siguientes partidas.
class ImageGuard {
 public:
  void Tick(rex::Runtime* runtime) {
    const auto now = std::chrono::steady_clock::now();
    if (!started_) {
      started_ = true;
      begin_ = now;
      next_ = now + std::chrono::seconds(20);  // logos y vídeos de arranque: aún no
      ApplySaved();
      return;
    }
    if (done_ || now < next_ || !Config().image_guard) return;
    const auto played = std::chrono::duration_cast<std::chrono::minutes>(now - begin_).count();
    next_ = now + std::chrono::seconds(played < 5 ? 2 : (played < 20 ? 6 : 15));
    auto* gs = runtime ? runtime->graphics_system() : nullptr;
    auto* presenter = gs ? gs->presenter() : nullptr;
    if (!presenter) return;
    rex::ui::RawImage img;
    if (!presenter->CaptureGuestOutput(img) || !img.width || !img.height) return;
    uint32_t white = 0, total = 0;
    for (uint32_t gy = 0; gy < 36; ++gy) {
      for (uint32_t gx = 0; gx < 64; ++gx) {
        const uint32_t x = (gx * 2 + 1) * img.width / 128, y = (gy * 2 + 1) * img.height / 72;
        const uint8_t* p = img.data.data() + static_cast<size_t>(y) * img.stride + static_cast<size_t>(x) * 4;
        const uint32_t luma = (p[0] * 54u + p[1] * 183u + p[2] * 19u) >> 8;
        ++total;
        if (luma >= 232) ++white;
      }
    }
    const bool washed = white * 100u >= total * 72u;
    if (!washed) {
      if (stage_ > 0 && streak_ == 0 && ++clean_ >= 5 && !reported_) {
        reported_ = true;
        REXLOG_INFO("[ReForge] Guardián: imagen normal con readback_resolve={}", kModes[stage_]);
      }
      streak_ = 0;
      return;
    }
    clean_ = 0;
    if (++streak_ < 3) return;
    streak_ = 0;
    if (stage_ + 1 >= static_cast<int>(sizeof(kModes) / sizeof(kModes[0]))) {
      REXLOG_WARN("[ReForge] Guardián: la imagen sigue sobreexpuesta con readback_resolve={}", kModes[stage_]);
      done_ = true;
      return;
    }
    ++stage_;
    reported_ = false;
    rex::cvar::SetFlagByName("readback_resolve", kModes[stage_]);
    REXLOG_WARN("[ReForge] Guardián: imagen sobreexpuesta ({}% blanca) → readback_resolve={}",
                white * 100u / total, kModes[stage_]);
    Save();
  }

 private:
  static constexpr const char* kModes[] = {"none", "some", "fast", "full"};

  static std::filesystem::path TunePath() { return rex::filesystem::GetExecutableFolder() / "reforge_tune.ini"; }

  void ApplySaved() {
    std::ifstream f(TunePath());
    std::string line;
    while (std::getline(f, line)) {
      const auto eq = line.find('=');
      if (eq == std::string::npos || Trim(line.substr(0, eq)) != "readback_resolve") continue;
      const std::string v = Trim(line.substr(eq + 1));
      for (int i = 1; i < 4; ++i)
        if (v == kModes[i]) stage_ = i;
    }
  }

  void Save() {
    std::ofstream f(TunePath(), std::ios::trunc);
    f << "# ReForge: ajustes que el guardián de imagen aprendió jugando\nreadback_resolve = " << kModes[stage_]
      << "\n";
  }

  bool started_ = false, done_ = false, reported_ = false;
  int stage_ = 0, streak_ = 0, clean_ = 0;
  std::chrono::steady_clock::time_point begin_{}, next_{};
};

class Toast;

// El aviso en pantalla, para poder empujarlo desde la suscripción al desbloqueo.
static std::atomic<Toast*>& ToastSlot() {
  static std::atomic<Toast*> slot{nullptr};
  return slot;
}

class Toast final : public rex::ui::AchievementNotificationDialog {
 public:
  Toast(rex::ui::ImGuiDrawer* drawer, rex::ui::ImmediateDrawer* immediate_drawer, rex::Runtime* runtime,
        rex::ui::Window* window, rex::system::AchievementManager* achievements)
      : AchievementNotificationDialog(drawer),
        icons_(immediate_drawer, runtime),
        immediate_(immediate_drawer),
        runtime_(runtime),
        window_(window),
        guide_(immediate_drawer, runtime, window, achievements, &icons_) {
    if (Prefs().mute == 1) ApplyMute(true);        // silenciado desde el menú Guía en una partida anterior
    if (Prefs().language > 0) g_language.store(static_cast<uint32_t>(Prefs().language));
  }

  ~Toast() override { ToastSlot().store(nullptr); }

  void Push(const rex::system::AchievementEvent& event) override {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto now = std::chrono::steady_clock::now();
    for (const auto& pending : queue_) {                     // ya está en la cola: no repetir
      if (pending.event.achievement.id == event.achievement.id) return;
    }
    if (last_id_ == event.achievement.id && now - last_push_ < std::chrono::seconds(15)) {
      return;  // el mismo logro llega por el desbloqueo y por la notificación del runtime
    }
    last_id_ = event.achievement.id;
    last_push_ = now;
    REXLOG_INFO("[ReForge] Logro desbloqueado: {} ({}G)", event.achievement.label.c_str(),
                static_cast<unsigned>(event.achievement.gamerscore));
    queue_.push_back({event, std::nullopt});
  }

 protected:
  void OnDraw(ImGuiIO& io) override {
    WriteModuleInfo(runtime_);  // una sola vez, en cuanto el juego está cargado
    image_guard_.Tick(runtime_);
    if (!guide_.open() && Prefs().hide_cursor) cursor_.Update(window_, io);
    guide_.Draw(io);
    const auto now = std::chrono::steady_clock::now();
    const Settings& cfg = Config();
    const float total = std::max(cfg.toast_seconds, 3.0f);
    rex::system::AchievementEvent event;
    float age = 0.0f;
    bool started = false;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      while (!queue_.empty()) {
        if (!queue_.front().shown) {
          queue_.front().shown = now;
          started = true;
        }
        age = std::chrono::duration<float>(now - *queue_.front().shown).count();
        if (age < total) break;
        queue_.pop_front();
      }
      if (queue_.empty()) return;
      event = queue_.front().event;
    }
    if (started) PlayAchievementSound();  // suena justo cuando aparece la notificación
    if (!badge_loaded_) {
      badge_ = LoadBadge(immediate_);
      badge_loaded_ = true;
    }
    ToastView view;
    view.title = cfg.toast_title.c_str();
    view.label = event.achievement.label.c_str();
    view.gamerscore = static_cast<unsigned>(event.achievement.gamerscore);
    if (auto* icon = icons_.GetIcon(event.achievement)) view.icon = reinterpret_cast<ImTextureID>(icon);
    if (badge_) view.badge = reinterpret_cast<ImTextureID>(badge_.get());
    view.accent = AccentColor();
    view.position = ToastPosition();
    DrawAchievementToast(ImGui::GetForegroundDrawList(), ImGui::GetFont(), io.DisplaySize, age, total, view);
  }

 private:
  struct Pending {
    rex::system::AchievementEvent event;
    std::optional<std::chrono::steady_clock::time_point> shown;
  };
  std::mutex mutex_;
  std::deque<Pending> queue_;
  uint32_t last_id_ = 0;      // último logro empujado (para no repetir el mismo aviso)
  std::chrono::steady_clock::time_point last_push_{};
  rex::ui::AchievementIconCache icons_;
  rex::ui::ImmediateDrawer* immediate_ = nullptr;
  rex::Runtime* runtime_ = nullptr;
  rex::ui::Window* window_ = nullptr;
  CursorGuard cursor_;
  std::unique_ptr<rex::ui::ImmediateTexture> badge_;
  bool badge_loaded_ = false;
  GuideMenu guide_;
  ImageGuard image_guard_;
};

// ---------------------------------------------------------------- ejecutable siempre en memoria
// El código recompilado ocupa decenas o cientos de MB. Windows lo carga por páginas la primera vez que se ejecuta
// cada zona (y puede sacarlas de memoria): un efecto, un arma o un nivel nuevos = fallos de página que leen del
// disco en mitad de la partida = tirón «sin causa». Como hacen Zelda 64: Recompiled y Unleashed Recompiled, se
// lee el .exe entero al arrancar (en segundo plano) y se bloquea en memoria.
struct ExePreload {
  ExePreload() {
#if defined(_WIN32)
    // Temporizador del sistema a 0,5 ms: el «vblank» del Xbox 360 de rexglue y las esperas del juego usan
    // Sleep(1); con la resolución por defecto de Windows (15,6 ms, o 1 ms si SDL la sube) ese ritmo tiembla.
    if (HMODULE ntdll = GetModuleHandleW(L"ntdll.dll")) {
      using SetRes = LONG(WINAPI*)(ULONG, BOOLEAN, PULONG);
      if (auto fn = reinterpret_cast<SetRes>(GetProcAddress(ntdll, "NtSetTimerResolution"))) {
        ULONG actual = 0;
        fn(5000, 1, &actual);
      }
    }
    // Windows 11 no debe «ahorrar energía» con el juego (EcoQoS / temporizador relajado).
    {
      struct { ULONG Version, ControlMask, StateMask; } pt{1, 0x1 | 0x4, 0};   // EXECUTION_SPEED | IGNORE_TIMER_RES
      using SetInfo = BOOL(WINAPI*)(HANDLE, int, LPVOID, DWORD);
      if (auto fn = reinterpret_cast<SetInfo>(
              GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "SetProcessInformation")))
        fn(GetCurrentProcess(), 4 /* ProcessPowerThrottling */, &pt, sizeof(pt));
    }
    std::thread([] {
      SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL);
      std::this_thread::sleep_for(std::chrono::seconds(2));   // tras iniciar el runtime (y su log)
      wchar_t name[MAX_PATH];
      if (!GetModuleFileNameW(nullptr, name, MAX_PATH)) return;
      HANDLE file = CreateFileW(name, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                                FILE_ATTRIBUTE_NORMAL, nullptr);
      if (file == INVALID_HANDLE_VALUE) return;
      LARGE_INTEGER size{};
      HANDLE map = nullptr;
      void* view = nullptr;
      if (GetFileSizeEx(file, &size) && size.QuadPart > 0 && size.QuadPart < (1ll << 30))
        map = CreateFileMappingW(file, nullptr, PAGE_READONLY, 0, 0, nullptr);
      if (map) view = MapViewOfFile(map, FILE_MAP_READ, 0, 0, 0);
      if (view) {
        SIZE_T lo = 0, hi = 0;
        HANDLE self = GetCurrentProcess();
        const SIZE_T n = static_cast<SIZE_T>(size.QuadPart);
        if (GetProcessWorkingSetSize(self, &lo, &hi) && SetProcessWorkingSetSize(self, lo + n, hi + n) &&
            VirtualLock(view, n)) {
          REXLOG_INFO("[ReForge] Ejecutable en memoria ({} MB): sin lecturas de disco del código al jugar",
                      static_cast<unsigned>(n >> 20));
          return;   // queda bloqueado mientras dure el juego
        }
        // Sin permiso para bloquearlo: al menos se lee entero (queda en la caché de disco de Windows).
        volatile unsigned char sum = 0;
        for (SIZE_T i = 0; i < n; i += 4096) sum += static_cast<const unsigned char*>(view)[i];
        UnmapViewOfFile(view);
      }
      if (map) CloseHandle(map);
      CloseHandle(file);
    }).detach();
#endif
  }
};
static ExePreload g_exe_preload;

std::unique_ptr<rex::ui::AchievementNotificationDialog> MakeAchievementToast(
    rex::ui::ImGuiDrawer* drawer, rex::ui::ImmediateDrawer* immediate_drawer, rex::Runtime* runtime,
    rex::ui::Window* window, rex::system::AchievementManager* achievements) {
  if (!drawer || !immediate_drawer || !runtime) return nullptr;
  auto toast = std::make_unique<Toast>(drawer, immediate_drawer, runtime, window, achievements);
  // El juego desbloquea los logros por XGI y el runtime los guarda, pero su notificación solo sale si
  // el desbloqueo se pidió «con aviso» (y no siempre es así). Nos suscribimos al desbloqueo en sí:
  // el aviso sale siempre. Push() descarta el duplicado si también llega el del runtime.
  ToastSlot().store(toast.get());
  if (achievements) {
    achievements->RegisterUnlockCallback([](const rex::system::AchievementEvent& event) {
      if (Toast* slot = ToastSlot().load()) slot->Push(event);
    });
  }
  return toast;
}

}  // namespace reforge

// El juego usa estas versiones en lugar de las del runtime (rexglue llama por nombre a __imp__X...).
REX_HOOK(__imp__XGetLanguage, reforge::XGetLanguage_hook)
REX_HOOK(__imp__XamUserGetSigninState, reforge::XamUserGetSigninState_hook)
REX_HOOK(__imp__XamUserGetSigninInfo, reforge::XamUserGetSigninInfo_hook)
REX_HOOK(__imp__XamUserGetName, reforge::XamUserGetName_hook)
REX_HOOK(__imp__XamUserGetGamerTag, reforge::XamUserGetGamerTag_hook)
REX_HOOK(__imp__XamUserCheckPrivilege, reforge::XamUserCheckPrivilege_hook)
REX_HOOK(__imp__NetDll_XNetGetEthernetLinkStatus, reforge::XNetGetEthernetLinkStatus_hook)
REX_HOOK(__imp__XamInputGetCapabilities, reforge::XamInputGetCapabilities_hook)
REX_HOOK(__imp__XamInputGetCapabilitiesEx, reforge::XamInputGetCapabilitiesEx_hook)
REX_HOOK(__imp__XamInputGetState, reforge::XamInputGetState_hook)
REX_HOOK(__imp__XamInputSetState, reforge::XamInputSetState_hook)
REX_HOOK(__imp__XamInputGetKeystroke, reforge::XamInputGetKeystroke_hook)
REX_HOOK(__imp__XamInputGetKeystrokeEx, reforge::XamInputGetKeystrokeEx_hook)
REX_HOOK(__imp__VdSwap, reforge::VdSwap_hook)

// Servicios de Xbox Live que el runtime deja vacíos (REX_STUB no fija el valor de retorno: el juego recibe
// su propio primer argumento y lo toma por «éxito»). Aquí responden como una consola sin conexión, con el
// mismo tipo de resultado que la API real, para que el juego siga por su camino «offline».
REX_HOOK_RAW(__imp__XamGetToken) {
  (void)base;
  ctx.r3.u64 = 1245;  // ERROR_NOT_LOGGED_ON (DWORD de error de Win32; el juego lo convierte en HRESULT)
}
REX_HOOK_RAW(__imp__XamGetServiceEndpoint) {
  (void)base;
  ctx.r3.u64 = 1245;  // ERROR_NOT_LOGGED_ON
}
REX_HOOK_RAW(__imp__XamBackgroundDownloadSetMode) {
  (void)base;
  ctx.r3.u64 = 0;  // modo anterior: «sin descargas en segundo plano»
}
REX_HOOK_RAW(__imp__NetDll_XHttpStartup) {
  (void)base;
  ctx.r3.u64 = 0;  // FALSE: sin pila HTTP
}
REX_HOOK_RAW(__imp__NetDll_XHttpOpen) {
  (void)base;
  ctx.r3.u64 = 0;  // NULL: sin sesión HTTP
}
REX_HOOK_RAW(__imp__NetDll_XHttpConnect) {
  (void)base;
  ctx.r3.u64 = 0;  // NULL
}
REX_HOOK_RAW(__imp__NetDll_XHttpOpenRequest) {
  (void)base;
  ctx.r3.u64 = 0;  // NULL
}
REX_HOOK_RAW(__imp__NetDll_XHttpSendRequest) {
  (void)base;
  ctx.r3.u64 = 0;  // FALSE
}
REX_HOOK_RAW(__imp__NetDll_XHttpCrackUrl) {
  (void)base;
  ctx.r3.u64 = 0;  // FALSE
}
'''

APP_BEGIN = "  // >>> ReForge Studio: notificación de logros (no editar este bloque)"
APP_END = "  // <<< ReForge Studio logros"
APP_BLOCK = (f"{APP_BEGIN}\n"
             "  std::unique_ptr<rex::ui::AchievementNotificationDialog> CreateAchievementNotificationDialog()\n"
             "      override {\n"
             "    if (auto toast = reforge::MakeAchievementToast(imgui_drawer(), immediate_drawer(), runtime(), window(),\n"
             "                                                   &achievements()))\n"
             "      return toast;\n"
             "    return rex::ReXApp::CreateAchievementNotificationDialog();\n"
             "  }\n"
             f"{APP_END}\n")


def _write_if_changed(path, text):
    try:
        if open(path, encoding="utf-8").read() == text:
            return False
    except OSError:
        pass
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return True


def ext_unavailable_reason(root):
    """«» si la extensión se puede generar; si no, por qué (para avisarlo en vez de callar).

    Los proyectos del SDK 0.11 no tienen clase de app en un `*_app.h`: usan `rex::app::TitleApp` y su
    `REX_TITLE_APP` en `src/main.cpp`, que es otra API (sin `ReXApp` ni los diálogos de ImGui de 0.10), así
    que el menú Guía todavía no se puede montar ahí.
    """
    from .game_options import app_header
    if app_header(root):
        return ""
    try:
        with open(os.path.join(root, "src", "main.cpp"), encoding="utf-8") as f:
            main = f.read()
    except OSError:
        return ""
    if "REX_TITLE_APP" in main or "rex::app::TitleApp" in main:
        from . import ext11
        if ext11.applies(root):
            return ""     # el SDK 0.11 tiene su propia versión del menú (ext11)
        return ("este proyecto usa la API de app del SDK 0.11: el menú Guía necesita `src/main.cpp` con "
                "`REX_TITLE_APP` para montarse.")
    return ""


def ensure_reforge_ext(root):
    """Añade/actualiza la extensión en el proyecto. Devuelve la lista de cambios (vacía si ya estaba)."""
    from .game_options import app_header
    changes = []
    src = os.path.join(root, "src")
    hdr = app_header(root)
    cml = os.path.join(root, "CMakeLists.txt")
    if not (hdr and os.path.isfile(cml)):
        return changes      # sin clase de app (p. ej. SDK 0.11): ext_unavailable_reason() lo explica
    if _write_if_changed(os.path.join(src, "reforge_ext.h"), EXT_HEADER):
        changes.append("src/reforge_ext.h")
    if _write_if_changed(os.path.join(src, "reforge_ext.cpp"), EXT_SOURCE):
        changes.append("src/reforge_ext.cpp")

    txt = open(cml, encoding="utf-8").read()
    if "src/reforge_ext.cpp" not in txt:
        new, n = re.subn(r"^(\s*)src/main\.cpp\s*$", r"\g<0>\n\1src/reforge_ext.cpp", txt, count=1, flags=re.M)
        if n:
            _write_if_changed(cml, new)
            changes.append("CMakeLists.txt")

    t = open(hdr, encoding="utf-8").read()
    orig = t
    if '#include "reforge_ext.h"' not in t:
        t = t.replace("#include <rex/rex_app.h>", '#include <rex/rex_app.h>\n#include "reforge_ext.h"', 1)
    if APP_BEGIN in t:
        t = re.sub(re.escape(APP_BEGIN) + r".*?" + re.escape(APP_END) + r"\n", lambda _m: APP_BLOCK, t, flags=re.S)
    elif not re.search(r"^\s*std::unique_ptr<[^>]*AchievementNotificationDialog>\s*CreateAchievementNotificationDialog\(\)"
                       r"\s*override", t, re.M):
        m = re.search(r"^(\s*using rex::ReXApp::ReXApp;\s*\n)", t, re.M)
        if m:
            t = t[:m.end()] + "\n" + APP_BLOCK + t[m.end():]
    if t != orig:
        _write_if_changed(hdr, t)
        changes.append(os.path.relpath(hdr, root))
    return changes


def remove_reforge_ext(root):
    """Quita la extensión del proyecto (vuelve al comportamiento normal de rexglue)."""
    from .game_options import app_header
    changes = []
    for f in ("reforge_ext.h", "reforge_ext.cpp"):
        p = os.path.join(root, "src", f)
        if os.path.isfile(p):
            os.remove(p)
            changes.append("src/" + f)
    cml = os.path.join(root, "CMakeLists.txt")
    if os.path.isfile(cml):
        t = open(cml, encoding="utf-8").read()
        n = re.sub(r"^\s*src/reforge_ext\.cpp\s*\n", "", t, flags=re.M)
        if n != t:
            _write_if_changed(cml, n)
            changes.append("CMakeLists.txt")
    hdr = app_header(root)
    if hdr:
        t = open(hdr, encoding="utf-8").read()
        n = re.sub(r"\n?" + re.escape(APP_BEGIN) + r".*?" + re.escape(APP_END) + r"\n", "", t, flags=re.S)
        n = n.replace('#include "reforge_ext.h"\n', "")
        if n != t:
            _write_if_changed(hdr, n)
            changes.append(os.path.relpath(hdr, root))
    return changes
