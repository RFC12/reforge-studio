"""Menú Guía de ReForge para los proyectos del SDK 0.11 (API `rex::app::TitleApp`).

El SDK 0.11 no tiene `ReXApp` ni el dibujante inmediato de 0.10, así que la extensión de 0.10 no compila
ahí. Este módulo genera el mismo menú (mismo aspecto: panel lateral, ejecución deslizante, pestañas con el
color de acento, filas con su valor a la derecha, pies con los iconos de los botones y aviso flotante)
dibujado con ImGui, que es lo que el propio SDK usa en 0.11:

* `rex::ui::DialogBase` + `IUISystem::AddDialog` para montarlo.
* **Entrada por ImGui**: el SDK manda el mando a ImGui (dpad, stick, A/B, LB/RB), así que la navegación
  funciona con mando aunque el juego esté bloqueado; antes se leía `IInputSystem::GetState`, que devuelve
  el mando neutral mientras el diálogo lo bloquea (por eso el mando «no respondía»).
* `TitleRuntime::SetAudioPaused` para el silencio al instante.
* `TitleRuntime::GetAchievementManager` para la lista de logros.

Lo que el runtime no cambia en caliente (fotogramas, idioma) se guarda en `reforge_menu.ini`, el mismo
formato que la extensión de 0.10: ReForge lo aplica al arrancar el juego.
"""

SOURCE = r"""// ReForge Studio: menú Guía para proyectos del SDK 0.11 (generado; no editar a mano).
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

#include <windows.h>
#include <imgui.h>

#include <rex/app/app.h>
#include <rex/hid/input_system.h>
#include <rex/kernel/title_runtime.h>
#include <rex/title.h>
#include <rex/ui/ui_system.h>
#include <rex/xam/achievement_manager.h>

namespace reforge {

namespace {

constexpr uint16_t kGuideButton = 0x0400;

const char* const kFpsNames[] = {"El de ReForge", "30 FPS con VSync", "60 FPS con VSync", "Sin límite"};
const char* const kFpsKeys[] = {"30", "60", "unlimited"};
const char* const kLanguageNames[] = {"English", "日本語", "Deutsch", "Français", "Español", "Italiano",
                                      "한국어", "中文", "Português", "Polski", "Русский", "Türkçe"};
constexpr uint32_t kAccents[] = {0x19D3A2, 0x107C10, 0x2D7FF9, 0xE8A317, 0xE3306B, 0x9B59F6};
const char* const kAccentNames[] = {"Turquesa", "Verde Xbox", "Azul", "Dorado", "Rosa", "Violeta"};

std::string Trim(std::string s) {
  const char* ws = " \t\r\n\"";
  s.erase(0, s.find_first_not_of(ws));
  const auto end = s.find_last_not_of(ws);
  s.erase(end == std::string::npos ? 0 : end + 1);
  return s;
}

std::filesystem::path ExeFolder() {
  wchar_t buf[MAX_PATH] = {};
  GetModuleFileNameW(nullptr, buf, MAX_PATH);
  return std::filesystem::path(buf).parent_path();
}

// ---------------------------------------------------------------- preferencias (reforge_menu.ini)
struct Prefs {
  bool show_fps = true;
  int accent = -1;             // -1 = el del perfil de ReForge
  int fps_mode = -1;           // -1 = el de ReForge · 0 = 30 · 1 = 60 · 2 = sin límite
  int mute = -1;               // -1 = el de ReForge · 0 = con sonido · 1 = silenciado
  int language = 0;            // 0 = el de ReForge · 1..12 código de idioma del Xbox
  int button_style = -1;       // -1 = el del perfil · 0 = Xbox · 1 = PlayStation
  bool loaded = false;
};

Prefs& GetPrefs() {
  static Prefs prefs;
  if (!prefs.loaded) {
    prefs.loaded = true;
    std::ifstream file(ExeFolder() / "reforge_menu.ini");
    std::string line;
    while (std::getline(file, line)) {
      const auto eq = line.find('=');
      if (eq == std::string::npos || line.empty() || line[0] == '#') continue;
      const std::string key = Trim(line.substr(0, eq)), val = Trim(line.substr(eq + 1));
      if (key == "show_fps") prefs.show_fps = (val == "1");
      else if (key == "accent") prefs.accent = std::clamp(std::atoi(val.c_str()), -1, 5);
      else if (key == "fps_mode") prefs.fps_mode = (val == "30") ? 0 : (val == "60" ? 1 : (val == "unlimited" ? 2 : -1));
      else if (key == "mute") prefs.mute = (val == "1") ? 1 : 0;
      else if (key == "language") prefs.language = std::clamp(std::atoi(val.c_str()), 0, 12);
      else if (key == "button_style")
        prefs.button_style = (val == "playstation") ? 1 : (val == "xbox" ? 0 : -1);
    }
  }
  return prefs;
}

void SavePrefs() {
  const Prefs& p = GetPrefs();
  std::string other;
  {  // conserva las claves que no gestiona el menú (posición de avisos, puntero…)
    std::ifstream in(ExeFolder() / "reforge_menu.ini");
    std::string line;
    while (std::getline(in, line)) {
      const auto eq = line.find('=');
      if (eq == std::string::npos) continue;
      const std::string key = Trim(line.substr(0, eq));
      if (key.empty() || key[0] == '#' || key == "show_fps" || key == "accent" || key == "fps_mode" ||
          key == "mute" || key == "language" || key == "button_style")
        continue;
      other += line + "\n";
    }
  }
  std::ofstream f(ExeFolder() / "reforge_menu.ini", std::ios::trunc);
  f << "# Ajustes elegidos en el menú Guía del juego (botón Xbox/PS)\n"
    << "show_fps = " << (p.show_fps ? 1 : 0) << "\n"
    << "accent = " << p.accent << "\n";
  if (p.button_style >= 0) f << "button_style = " << (p.button_style == 1 ? "playstation" : "xbox") << "\n";
  if (p.fps_mode >= 0) f << "fps_mode = " << kFpsKeys[std::clamp(p.fps_mode, 0, 2)] << "\n";
  if (p.mute >= 0) f << "mute = " << (p.mute == 1 ? 1 : 0) << "\n";
  if (p.language > 0) f << "language = " << std::clamp(p.language, 1, 12) << "\n";
  f << other;
}

// ---------------------------------------------------------------- perfil (reforge_ext.ini)
struct Profile {
  std::string gamertag = "ReForge";
  std::string game_name;
  uint32_t accent = 0x19D3A2;
  bool playstation = false;
  std::string avatar_style = "hex";      // la «imagen de jugador» del perfil de ReForge
  uint32_t avatar_fg = 0x19D3A2;
  uint32_t avatar_bg = 0x0B3D30;
};

const Profile& GetProfile() {
  static Profile profile;
  static bool loaded = false;
  if (!loaded) {
    loaded = true;
    std::ifstream file(ExeFolder() / "reforge_ext.ini");
    std::string line;
    while (std::getline(file, line)) {
      const auto eq = line.find('=');
      if (eq == std::string::npos || line.empty() || line[0] == '#') continue;
      const std::string key = Trim(line.substr(0, eq)), val = Trim(line.substr(eq + 1));
      if (key == "gamertag" && !val.empty()) profile.gamertag = val;
      else if (key == "game_name") profile.game_name = val;
      else if (key == "pad_style") profile.playstation = (val == "playstation");
      else if (key == "accent") profile.accent = static_cast<uint32_t>(std::strtoul(val.c_str(), nullptr, 16));
      else if (key == "avatar_style" && !val.empty()) profile.avatar_style = val;
      else if (key == "avatar_fg") profile.avatar_fg = static_cast<uint32_t>(std::strtoul(val.c_str(), nullptr, 16));
      else if (key == "avatar_bg") profile.avatar_bg = static_cast<uint32_t>(std::strtoul(val.c_str(), nullptr, 16));
    }
    if (profile.accent == 0) profile.accent = 0x19D3A2;
  }
  return profile;
}

float Clamp01(float v) { return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v); }
float OutCubic(float t) { return 1.0f - (1.0f - t) * (1.0f - t) * (1.0f - t); }

ImU32 Rgba(uint32_t rgb, float a) {
  return IM_COL32((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF, static_cast<int>(255.0f * Clamp01(a)));
}

uint32_t AccentColor() {
  const int a = GetPrefs().accent;
  return a >= 0 ? kAccents[a] : GetProfile().accent;
}

bool PadIsPlayStation() {
  const int style = GetPrefs().button_style;
  if (style >= 0) return style == 1;
  return GetProfile().playstation;
}

void DrawTrophy(ImDrawList* dl, ImVec2 c, float ir, float sq, ImU32 col) {
  auto P = [&](float x, float y) { return ImVec2(c.x + x * ir * sq, c.y + y * ir); };
  ImVec2 cup[12];
  cup[0] = P(-0.42f, -0.46f);
  for (int i = 0; i <= 10; ++i) {
    const float th = 3.14159265f * static_cast<float>(i) / 10.0f;
    cup[i + 1] = P(0.42f * std::cos(th), -0.46f + 0.58f * std::sin(th));
  }
  std::reverse(cup + 1, cup + 12);
  dl->AddConvexPolyFilled(cup, 12, col);
  const float th = std::max(1.0f, 0.09f * ir);
  for (int side = -1; side <= 1; side += 2) {
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

// Candado para los logros aún no conseguidos (como la Guía de 0.10 cuando no hay icono).
void DrawLock(ImDrawList* dl, ImVec2 c, float r, ImU32 col) {
  const float th = std::max(1.5f, r * 0.26f);
  // arco superior
  dl->PathArcTo(ImVec2(c.x, c.y - r * 0.18f), r * 0.55f, 3.14159265f, 2.0f * 3.14159265f, 12);
  dl->PathStroke(col, 0, th);
  // cuerpo
  dl->AddRectFilled(ImVec2(c.x - r * 0.75f, c.y - r * 0.1f), ImVec2(c.x + r * 0.75f, c.y + r), col, r * 0.18f);
}

// La imagen de jugador del perfil de ReForge (Perfil → Imagen de jugador), dibujada con primitivas: en 0.11
// no hay texturas a mano y la figura es la misma que enseña ReForge, con sus colores.
void DrawAvatar(ImDrawList* dl, ImVec2 p, float size, float a, uint32_t accent, const Profile& prof) {
  const float round = size * 0.18f;
  const ImU32 white = IM_COL32(255, 255, 255, static_cast<int>(255 * a));
  if (prof.avatar_style.empty() || prof.avatar_style == "none") {
    dl->AddRectFilled(p, ImVec2(p.x + size, p.y + size), Rgba(accent, 0.85f * a), round);
    DrawTrophy(dl, ImVec2(p.x + size / 2, p.y + size / 2), size * 0.42f, 1.0f, white);
    return;
  }
  dl->AddRectFilled(p, ImVec2(p.x + size, p.y + size), Rgba(prof.avatar_bg, a), round);
  const ImU32 fg = Rgba(prof.avatar_fg, a);
  const ImVec2 o(p.x + size / 2, p.y + size / 2);
  const float r = size * 0.30f, th = std::max(2.0f, size * 0.075f);
  auto P = [&](float x, float y) { return ImVec2(o.x + x, o.y + y); };
  const std::string& s = prof.avatar_style;
  if (s == "hex") {
    ImVec2 pts[6];
    for (int i = 0; i < 6; ++i) {
      const float t = 3.14159265f / 3.0f * static_cast<float>(i) + 3.14159265f / 6.0f;
      pts[i] = P(r * std::cos(t), r * std::sin(t));
    }
    dl->AddConvexPolyFilled(pts, 6, fg);
  } else if (s == "diamond") {
    const ImVec2 pts[4] = {P(0.0f, -r * 1.1f), P(r * 0.8f, 0.0f), P(0.0f, r * 1.1f), P(-r * 0.8f, 0.0f)};
    dl->AddConvexPolyFilled(pts, 4, fg);
  } else if (s == "star") {
    for (int i = 0; i < 10; ++i) {
      const float t = -3.14159265f / 2.0f + static_cast<float>(i) * 3.14159265f / 5.0f;
      const float k = (i % 2 == 0) ? r : r * 0.45f;
      dl->PathLineTo(P(k * std::cos(t), k * std::sin(t)));
    }
    dl->PathStroke(fg, ImDrawFlags_Closed, th);
  } else if (s == "bolt") {
    static const float k[7][2] = {{0.55f, 0.12f}, {0.28f, 0.55f}, {0.48f, 0.55f}, {0.40f, 0.88f},
                                  {0.72f, 0.42f}, {0.52f, 0.42f}, {0.62f, 0.12f}};
    for (int i = 0; i < 7; ++i) dl->PathLineTo(ImVec2(p.x + k[i][0] * size, p.y + k[i][1] * size));
    dl->PathStroke(fg, ImDrawFlags_Closed, th);
  } else if (s == "crown") {
    static const float k[7][2] = {{0.20f, 0.70f}, {0.20f, 0.35f}, {0.35f, 0.50f}, {0.50f, 0.28f},
                                  {0.65f, 0.50f}, {0.80f, 0.35f}, {0.80f, 0.70f}};
    for (int i = 0; i < 7; ++i) dl->PathLineTo(ImVec2(p.x + k[i][0] * size, p.y + k[i][1] * size));
    dl->PathStroke(fg, ImDrawFlags_Closed, th);
  } else if (s == "ring") {
    dl->AddCircle(o, r, fg, 0, th);
    dl->AddCircleFilled(o, r * 0.35f, fg);
  } else if (s == "wave") {
    float x = p.x + size * 0.15f;
    dl->PathLineTo(ImVec2(x, o.y));
    for (int i = 0; i < 4; ++i) {
      const float up = (i % 2 == 0) ? -r * 0.8f : r * 0.8f;
      dl->PathBezierQuadraticCurveTo(ImVec2(x + size * 0.0875f, o.y + up), ImVec2(x + size * 0.175f, o.y));
      x += size * 0.175f;
    }
    dl->PathStroke(fg, 0, th);
  } else {   // «pad»
    dl->AddRectFilled(ImVec2(o.x - r * 1.2f, o.y - r * 0.55f), ImVec2(o.x + r * 1.2f, o.y + r * 0.55f), fg,
                      r * 0.5f);
    const ImU32 back = Rgba(prof.avatar_bg, a);
    dl->AddCircleFilled(ImVec2(o.x + r * 0.6f, o.y), r * 0.16f, back);
    dl->AddRectFilled(ImVec2(o.x - r * 0.67f, o.y - r * 0.25f), ImVec2(o.x - r * 0.53f, o.y + r * 0.25f), back);
    dl->AddRectFilled(ImVec2(o.x - r * 0.85f, o.y - r * 0.07f), ImVec2(o.x - r * 0.35f, o.y + r * 0.07f), back);
  }
}

std::string Hms(uint64_t s) {
  char buf[32];
  if (s >= 3600)
    std::snprintf(buf, sizeof(buf), "%llu h %02llu min", static_cast<unsigned long long>(s / 3600),
                  static_cast<unsigned long long>((s / 60) % 60));
  else
    std::snprintf(buf, sizeof(buf), "%llu min", static_cast<unsigned long long>(s / 60));
  return buf;
}

std::string DateFromFiletime(uint64_t ft) {
  if (!ft) return "";
  const std::time_t t = static_cast<std::time_t>(ft / 10000000ull - 11644473600ull);
  std::tm tm{};
  localtime_s(&tm, &t);
  char buf[32];
  std::snprintf(buf, sizeof(buf), "%02d/%02d/%04d", tm.tm_mday, tm.tm_mon + 1, tm.tm_year + 1900);
  return buf;
}

// Tiempo de juego: el de esta partida y el total (reforge_playtime.txt junto al .exe, se guarda cada minuto).
class PlayClock {
 public:
  PlayClock() : start_(std::chrono::steady_clock::now()) {
    std::ifstream f(ExeFolder() / "reforge_playtime.txt");
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
    std::ofstream f(ExeFolder() / "reforge_playtime.txt", std::ios::trunc);
    f << Total() << "\n";
  }

 private:
  std::chrono::steady_clock::time_point start_;
  uint64_t before_ = 0;
  uint64_t saved_at_ = 0;
};

// Botones del mando: el SDK manda el pad a ImGui, así que se lee de ahí (el estado del juego queda neutral
// mientras el menú está abierto) y también llega la cruceta del teclado y el ratón.
enum : uint32_t {
  kUp = 0x0001,
  kDown = 0x0002,
  kLeft = 0x0004,
  kRight = 0x0008,
  kLB = 0x0100,
  kRB = 0x0200,
  kA = 0x1000,
  kB = 0x2000,
  kY = 0x8000,
};

struct Status {
  std::string text;
  double until = 0.0;
};

}  // namespace

class GuideMenu final : public rex::ui::DialogBase {
 public:
  GuideMenu(rex::app::App& app, rex::kernel::TitleRuntime& title) : app_(app), title_(title) {
    if (GetPrefs().mute == 1) title_.SetAudioPaused(true);   // silenciado en una partida anterior
  }

  bool NeedsContinuousPaint() const override { return true; }
  bool WantsExclusiveInput() const override { return open_; }   // el menú se queda el mando, como la Guía

  bool Draw(ImGuiIO& io) override {
    if (!nav_enabled_) {   // el SDK manda el mando a ImGui con esto: es de donde se lee la navegación
      nav_enabled_ = true;
      io.ConfigFlags |= ImGuiConfigFlags_NavEnableGamepad;
    }
    clock_.MaybeSave();
    const double now = ImGui::GetTime();
    uint32_t pressed = ReadInput();
    if (!open_ && (pressed & kGuideButton)) {
      SetOpen(true);
      pressed = 0;
    }
    if (GetPrefs().show_fps) DrawFpsCounter(io);
    const float target = open_ ? 1.0f : 0.0f;
    anim_ += (target - anim_) * std::min(1.0f, io.DeltaTime * 14.0f);
    if (anim_ < 0.01f) return true;                  // cerrado: la Guía del juego sigue su curso
    if (open_) HandleInput(pressed, now);
    Render(io);
    return true;
  }

 private:
  enum Tab { kGraphics = 0, kAchievements = 1, kSettings = 2, kTabs = 3 };

  // ---------------------------------------------------------------- entrada
  uint32_t ReadInput() {
    uint32_t nav = 0;
    auto down = [](ImGuiKey k) { return ImGui::IsKeyPressed(k, false); };
    if (down(ImGuiKey_GamepadDpadUp) || down(ImGuiKey_GamepadLStickUp) || down(ImGuiKey_UpArrow)) nav |= kUp;
    if (down(ImGuiKey_GamepadDpadDown) || down(ImGuiKey_GamepadLStickDown) || down(ImGuiKey_DownArrow)) nav |= kDown;
    if (down(ImGuiKey_GamepadDpadLeft) || down(ImGuiKey_GamepadLStickLeft) || down(ImGuiKey_LeftArrow)) nav |= kLeft;
    if (down(ImGuiKey_GamepadDpadRight) || down(ImGuiKey_GamepadLStickRight) || down(ImGuiKey_RightArrow)) nav |= kRight;
    if (down(ImGuiKey_GamepadL1) || down(ImGuiKey_Q)) nav |= kLB;
    if (down(ImGuiKey_GamepadR1) || down(ImGuiKey_E)) nav |= kRB;
    if (down(ImGuiKey_GamepadFaceDown) || down(ImGuiKey_Enter) || down(ImGuiKey_Space)) nav |= kA;
    if (down(ImGuiKey_GamepadFaceRight) || down(ImGuiKey_Backspace)) nav |= kB;
    if (down(ImGuiKey_GamepadFaceUp) || down(ImGuiKey_Y)) nav |= kY;

    // repetición al mantener la cruceta (o el stick izquierdo) arriba/abajo
    held_ = 0;
    if (ImGui::IsKeyDown(ImGuiKey_GamepadDpadUp) || ImGui::IsKeyDown(ImGuiKey_GamepadLStickUp) ||
        ImGui::IsKeyDown(ImGuiKey_UpArrow))
      held_ |= kUp;
    if (ImGui::IsKeyDown(ImGuiKey_GamepadDpadDown) || ImGui::IsKeyDown(ImGuiKey_GamepadLStickDown) ||
        ImGui::IsKeyDown(ImGuiKey_DownArrow))
      held_ |= kDown;
    if (held_ & kUp || held_ & kDown) {
      const double now = ImGui::GetTime();
      if (nav & (kUp | kDown)) repeat_at_ = now + 0.38;
      else if (now >= repeat_at_) {
        nav |= held_ & (kUp | kDown);
        repeat_at_ = now + 0.07;
      }
    }

    // Botón Guía del mando (Xbox/PS) y tecla Inicio: abrir y cerrar. Se mira también el estado del pad por
    // si el SDK no manda ese botón a ImGui.
    if (auto pad = app_.GetInput().GetState(0); pad.has_value()) {
      // El estado del pad es un nivel (lo que está pulsado), no un evento: hay que quedarse solo con lo que
      // ACABA de pulsarse. Sin esto, LB/RB (y la cruceta) disparaban en cada fotograma mientras se mantenían
      // y las pestañas saltaban sin control.
      const uint16_t buttons = pad.value().state.buttons;
      const uint16_t pressed = static_cast<uint16_t>(buttons & ~last_buttons_);
      if (pressed & kGuideButton) nav |= kGuideButton;
      if (pressed & 0x0001) nav |= kUp;
      if (pressed & 0x0002) nav |= kDown;
      if (pressed & 0x0004) nav |= kLeft;
      if (pressed & 0x0008) nav |= kRight;
      if (pressed & 0x1000) nav |= kA;
      if (pressed & 0x2000) nav |= kB;
      if (pressed & 0x0100) nav |= kLB;
      if (pressed & 0x0200) nav |= kRB;
      last_buttons_ = buttons;
    }
    if (down(ImGuiKey_Home) || down(ImGuiKey_F9)) nav |= kGuideButton;
    if (open_ && down(ImGuiKey_Escape)) nav |= kB;
    return nav;
  }

  void SetOpen(bool open) {
    if (open == open_) return;
    open_ = open;
    anim_ = open ? 0.02f : 1.0f;
    if (open) {
      tab_ = kGraphics;
      sel_[kGraphics] = 0;
    } else {
      SavePrefs();
    }
  }

  void HandleInput(uint32_t nav, double now) {
    if (nav & kGuideButton) {
      SetOpen(false);
      return;
    }
    if (nav & kB) {
      SetOpen(false);
      return;
    }
    // Las pestañas, de una en una: aunque el botón se repita (o llegue por las dos vías, ImGui y el pad),
    // no puede saltar varias pestañas en el mismo instante.
    if ((nav & (kLB | kRB)) && now >= tab_at_) {
      ChangeTab((nav & kLB) ? -1 : +1);
      tab_at_ = now + 0.25;
    }
    const int n = ItemCount();
    if (n > 0) {
      if (nav & kUp) sel_[tab_] = (sel_[tab_] + n - 1) % n;
      if (nav & kDown) sel_[tab_] = (sel_[tab_] + 1) % n;
    }
    if (tab_ == kAchievements) {
      if (nav & kA) Change(sel_[tab_], 1);
      return;
    }
    if (nav & kLeft) Change(sel_[tab_], -1);
    if (nav & kRight) Change(sel_[tab_], 1);
    if (nav & kA) Change(sel_[tab_], 1);
    (void)now;
  }

  void ChangeTab(int d) {
    tab_ = (tab_ + kTabs + d) % kTabs;
    imgs_dirty_ = true;
  }

  int ItemCount() const {
    if (tab_ == kGraphics) return 2;
    if (tab_ == kSettings) return 4;
    return std::max(1, static_cast<int>(Achievements().size()));
  }

  void Change(int item, int dir) {
    Prefs& p = GetPrefs();
    char msg[192];
    if (tab_ == kGraphics) {
      if (item == 0) {
        p.fps_mode = (p.fps_mode < 0 ? 0 : (p.fps_mode + 3 + dir) % 3);
        std::snprintf(msg, sizeof(msg), "Fotogramas: %s · se aplica al reiniciar", kFpsNames[p.fps_mode + 1]);
      } else {
        p.show_fps = dir > 0 ? !p.show_fps : !p.show_fps;
        std::snprintf(msg, sizeof(msg), "%s", p.show_fps ? "Contador de FPS activado" : "Contador de FPS desactivado");
      }
    } else if (tab_ == kSettings) {
      if (item == 0) {
        p.accent = (p.accent + dir + 7) % 7 - 1;
        std::snprintf(msg, sizeof(msg), "Color de acento: %s",
                      p.accent >= 0 ? kAccentNames[p.accent] : "el del perfil");
      } else if (item == 1) {
        const bool ps = !PadIsPlayStation();
        p.button_style = ps ? 1 : 0;
        std::snprintf(msg, sizeof(msg), "Iconos de botones: %s", ps ? "PlayStation" : "Xbox");
      } else if (item == 2) {
        const bool mute = !(p.mute == 1);
        p.mute = mute ? 1 : 0;
        title_.SetAudioPaused(mute);          // al instante, sin reiniciar
        std::snprintf(msg, sizeof(msg), "%s", mute ? "Juego silenciado" : "Sonido activado");
      } else {
        const int cur = p.language > 0 ? p.language : 5;
        p.language = (cur + dir + 12 - 1) % 12 + 1;
        std::snprintf(msg, sizeof(msg), "Idioma del juego: %s · se aplica al reiniciar",
                      kLanguageNames[p.language - 1]);
      }
    } else {
      return;
    }
    status_ = {msg, ImGui::GetTime() + 3.0};
    SavePrefs();
  }

  // ---------------------------------------------------------------- logros
  const std::vector<rex::Achievement>& Achievements() const {
    if (!achievements_loaded_) {
      achievements_loaded_ = true;
      try {
        achievements_ = title_.GetAchievementManager().ListAchievements();
      } catch (...) {
        achievements_.clear();
      }
      std::stable_sort(achievements_.begin(), achievements_.end(),
                       [](const rex::Achievement& x, const rex::Achievement& y) {
                         if (x.unlocked != y.unlocked) return x.unlocked;
                         return x.unlock_time > y.unlock_time;
                       });
      unlocked_ = 0;
      score_ = 0;
      score_total_ = 0;
      for (const auto& a : achievements_) {
        score_total_ += a.gamerscore;
        if (a.unlocked) {
          ++unlocked_;
          score_ += a.gamerscore;
        }
      }
    }
    return achievements_;
  }

  void DrawFpsCounter(ImGuiIO& io) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%.0f FPS", io.Framerate);
    ImDrawList* dl = ImGui::GetForegroundDrawList();
    const float fs = ImGui::GetFontSize() * 1.1f;
    const ImVec2 sz = ImGui::GetFont()->CalcTextSizeA(fs, 1e9f, 0.0f, buf);
    dl->AddRectFilled(ImVec2(10, 10), ImVec2(22 + sz.x, 18 + sz.y), IM_COL32(0, 0, 0, 150), 6.0f);
    dl->AddText(ImGui::GetFont(), fs, ImVec2(16, 14), Rgba(AccentColor(), 1.0f), buf);
  }

  static void Text(ImDrawList* dl, float size, ImVec2 pos, ImU32 col, const char* text, float wrap = 0.0f) {
    dl->AddText(ImGui::GetFont(), size, pos, col, text, nullptr, wrap);
  }

  static float TextWidth(float size, const char* text) {
    return ImGui::GetFont()->CalcTextSizeA(size, 1e9f, 0.0f, text).x;
  }

  static std::string Ellipsize(const std::string& t, float size, float max_w) {
    if (TextWidth(size, t.c_str()) <= max_w) return t;
    std::string out = t;
    while (!out.empty()) {
      do out.pop_back(); while (!out.empty() && (static_cast<unsigned char>(out.back()) & 0xC0) == 0x80);
      if (!out.empty()) out.pop_back();
      if (TextWidth(size, (out + "...").c_str()) <= max_w) return out + "...";
    }
    return "...";
  }

  bool Clicked(const ImVec2& a, const ImVec2& b) const {
    const ImVec2 m = ImGui::GetIO().MousePos;
    return ImGui::IsMouseClicked(0) && m.x >= a.x && m.x < b.x && m.y >= a.y && m.y < b.y;
  }

  // ---------------------------------------------------------------- dibujo
  void Render(ImGuiIO& io) {
    if (open_ && tab_ == kAchievements && imgs_dirty_) {
      imgs_dirty_ = false;
    }
    const float a = anim_;
    const ImVec2 ds = io.DisplaySize;
    const float u = std::max(0.75f, std::min(ds.x / 1280.0f, ds.y / 720.0f));   // escala con la resolución
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
    const float x = x0 + pad;
    float y = y0 + pad;
    char line[200];

    // cabecera: perfil, puntos, hora y fecha
    const float av = 72.0f * u;
    DrawAvatar(dl, ImVec2(x, y), av, a, accent, GetProfile());
    const auto& list = Achievements();
    const size_t n_ach = list.size();
    Text(dl, fs * 1.35f, ImVec2(x + av + 16 * u, y + 2 * u), white, GetProfile().gamertag.c_str());
    std::snprintf(line, sizeof(line), "G %u / %u  ·  %u de %zu logros", score_, score_total_, unlocked_, n_ach);
    Text(dl, fs, ImVec2(x + av + 16 * u, y + 34 * u), Rgba(accent, a), line);
    const std::time_t now_t = std::time(nullptr);
    std::tm tm{};
    localtime_s(&tm, &now_t);
    static const char* const kDays[] = {"domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"};
    static const char* const kMonths[] = {"enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                                          "agosto", "septiembre", "octubre", "noviembre", "diciembre"};
    std::snprintf(line, sizeof(line), "%02d:%02d  ·  %s %d de %s", tm.tm_hour, tm.tm_min,
                  kDays[tm.tm_wday % 7], tm.tm_mday, kMonths[tm.tm_mon % 12]);
    Text(dl, fs * 0.9f, ImVec2(x + av + 16 * u, y + 58 * u), dim, line);
    y += av + 18 * u;
    if (!GetProfile().game_name.empty()) {
      const std::string shown = Ellipsize(GetProfile().game_name, fs * 1.1f, w - 2 * pad);
      Text(dl, fs * 1.1f, ImVec2(x, y), white, shown.c_str());
      y += fs * 1.5f;
    }
    std::snprintf(line, sizeof(line), "Jugando: %s  ·  Total: %s  ·  %.0f FPS",
                  Hms(clock_.Session()).c_str(), Hms(clock_.Total()).c_str(), io.Framerate);
    Text(dl, fs * 0.9f, ImVec2(x, y), dim, line);
    y += fs * 1.8f;

    // pestañas (LB / RB o el ratón)
    static const char* const kTabNames[kTabs] = {"Gráficos", "Logros", "Ajustes"};
    float tx = x;
    for (int t = 0; t < kTabs; ++t) {
      const float tw = TextWidth(fs, kTabNames[t]);
      const ImVec2 ta(tx - 10 * u, y - 6 * u), tb(tx + tw + 10 * u, y + fs + 6 * u);
      if (t == tab_) dl->AddRectFilled(ta, tb, Rgba(accent, 0.9f * a), 8 * u);
      Text(dl, fs, ImVec2(tx, y), t == tab_ ? IM_COL32(10, 12, 14, static_cast<int>(255 * a)) : dim, kTabNames[t]);
      if (open_ && Clicked(ta, tb)) {
        tab_ = t;
        imgs_dirty_ = true;
      }
      tx += tw + 30 * u;
    }
    if (tx + 70 * u < x0 + w - pad) Text(dl, fs * 0.75f, ImVec2(x0 + w - pad - 70 * u, y + 2 * u), dim, "LB  ·  RB");
    y += fs * 2.2f;

    const float list_bottom = y1 - pad - fs * 1.9f;
    dl->PushClipRect(ImVec2(x, y), ImVec2(x0 + w - pad, list_bottom), true);
    if (tab_ == kGraphics) {
      const Prefs& p = GetPrefs();
      const std::string vals[2] = {p.fps_mode < 0 ? "El de ReForge" : kFpsNames[p.fps_mode + 1],
                                   p.show_fps ? "Sí" : "No"};
      const char* names[2] = {"Fotogramas", "Contador de FPS"};
      for (int i = 0; i < 2; ++i) {
        const ImVec2 q(x, y + i * fs * 2.6f);
        Row(dl, q, w - 2 * pad, fs, sel_[kGraphics] == i, names[i], u, a, accent, vals[i].c_str());
        if (open_ && Clicked(q, ImVec2(q.x + w - 2 * pad, q.y + fs * 2.2f))) {
          sel_[kGraphics] = i;
          Change(i, 1);
        }
      }
      Text(dl, fs * 0.8f, ImVec2(x, y + 2 * fs * 2.6f + 4 * u), dim,
           "La cruceta o A cambian el valor. Lo que el runtime no cambia en caliente se aplica la próxima "
           "vez que abras el juego.", w - 2 * pad);
    } else if (tab_ == kSettings) {
      const Prefs& p = GetPrefs();
      std::string vals[4] = {p.accent >= 0 ? kAccentNames[p.accent] : "El del perfil",
                             PadIsPlayStation() ? "PlayStation" : "Xbox",
                             p.mute == 1 ? "Sí" : "No",
                             kLanguageNames[std::clamp(p.language > 0 ? p.language : 5, 1, 12) - 1]};
      const char* names[4] = {"Color de acento", "Iconos de botones", "Silenciar el juego", "Idioma del juego"};
      for (int i = 0; i < 4; ++i) {
        const ImVec2 q(x, y + i * fs * 2.6f);
        Row(dl, q, w - 2 * pad, fs, sel_[kSettings] == i, names[i], u, a, accent, vals[i].c_str());
        if (open_ && Clicked(q, ImVec2(q.x + w - 2 * pad, q.y + fs * 2.2f))) {
          sel_[kSettings] = i;
          Change(i, 1);
        }
      }
      float ty = y + 4 * fs * 2.6f + 4 * u;
      Text(dl, fs * 0.8f, ImVec2(x, ty), dim,
           "El silencio se nota al momento; el idioma y los fotogramas, al volver a abrir el juego.", w - 2 * pad);
    } else {
      if (list.empty()) {
        Text(dl, fs, ImVec2(x, y), dim, "Este juego no tiene logros registrados.", w - 2 * pad);
      } else {
        const float right = x0 + w - pad;
        // Resumen y barra de progreso arriba de la lista, como la Guía del 360 de 0.10.
        std::snprintf(line, sizeof(line), "%u de %zu logros  ·  %u / %u G", unlocked_, list.size(), score_,
                      score_total_);
        Text(dl, fs * 0.95f, ImVec2(x, y), dim, line);
        const float barY = y + fs * 1.45f, barH = 7.0f * u, barW = right - x;
        dl->AddRectFilled(ImVec2(x, barY), ImVec2(x + barW, barY + barH),
                          IM_COL32(40, 44, 52, static_cast<int>(255 * a)), barH * 0.5f);
        const float frac = list.empty() ? 0.0f : static_cast<float>(unlocked_) / static_cast<float>(list.size());
        if (frac > 0.0f)
          dl->AddRectFilled(ImVec2(x, barY), ImVec2(x + barW * frac, barY + barH), Rgba(accent, a), barH * 0.5f);
        y += fs * 2.3f;

        const float row = 64.0f * u;
        const float detail_h = fs * 3.4f;   // descripción completa + puntos y fecha del logro elegido (como 0.10)
        const int visible = std::max(1, static_cast<int>((list_bottom - detail_h - y) / row));
        int& sel = sel_[kAchievements];
        if (sel >= static_cast<int>(list.size())) sel = 0;
        if (sel < scroll_) scroll_ = sel;
        if (sel >= scroll_ + visible) scroll_ = sel - visible + 1;
        for (int i = scroll_; i < static_cast<int>(list.size()) && i < scroll_ + visible; ++i) {
          const auto& ach = list[i];
          const bool got = ach.unlocked;
          const float ry = y + (i - scroll_) * row;
          if (i == sel)
            dl->AddRectFilled(ImVec2(x - 8 * u, ry - 4 * u), ImVec2(right + 8 * u, ry + row - 8 * u),
                              Rgba(accent, 0.22f * a), 8 * u);
          if (open_ && Clicked(ImVec2(x, ry), ImVec2(right, ry + row))) sel = i;
          const float ic = row - 16 * u;
          dl->AddRectFilled(ImVec2(x, ry), ImVec2(x + ic, ry + ic), IM_COL32(40, 44, 52, static_cast<int>(255 * a)),
                            6 * u);
          if (got)
            DrawTrophy(dl, ImVec2(x + ic / 2, ry + ic / 2), ic * 0.40f, 1.0f, Rgba(accent, a));
          else
            DrawLock(dl, ImVec2(x + ic / 2, ry + ic / 2), ic * 0.30f, dim);
          const float tx2 = x + ic + 12 * u;
          const bool secret = !got && ach.GetDescription().empty();
          const std::string name = secret ? std::string("Logro secreto") : std::string(ach.label);
          const std::string title = Ellipsize(name, fs, right - 70 * u - tx2);
          Text(dl, fs, ImVec2(tx2, ry), got ? white : dim, title.c_str());
          const std::string desc = secret ? std::string("Se revela al conseguirlo") : ach.GetDescription();
          const std::string shown = Ellipsize(desc, fs * 0.78f, right - 96 * u - tx2);
          Text(dl, fs * 0.78f, ImVec2(tx2, ry + fs * 1.25f), dim, shown.c_str());
          std::snprintf(line, sizeof(line), "%uG", ach.gamerscore);
          Text(dl, fs * 0.9f, ImVec2(right - 50 * u, ry), got ? Rgba(accent, a) : dim, line);
          if (got) {
            const std::string d = DateFromFiletime(ach.unlock_time);
            Text(dl, fs * 0.7f, ImVec2(right - 84 * u, ry + fs * 1.3f), dim, d.c_str());
          }
        }
        if (sel >= 0 && sel < static_cast<int>(list.size())) {
          const auto& ach = list[sel];
          const bool got = ach.unlocked;
          const float dy = list_bottom - detail_h + fs * 0.4f;
          dl->AddLine(ImVec2(x, dy - fs * 0.3f), ImVec2(right, dy - fs * 0.3f),
                      IM_COL32(60, 66, 76, static_cast<int>(255 * a)));
          const std::string desc = (!got && ach.GetDescription().empty())
                                       ? std::string("Logro secreto · se revela al conseguirlo")
                                       : ach.GetDescription();
          Text(dl, fs * 0.82f, ImVec2(x, dy), white, desc.c_str(), w - 2 * pad);
          std::snprintf(line, sizeof(line), got ? "%uG · conseguido el %s" : "%uG · bloqueado",
                        ach.gamerscore, got ? DateFromFiletime(ach.unlock_time).c_str() : "");
          Text(dl, fs * 0.76f, ImVec2(x, dy + fs * 1.9f), got ? Rgba(accent, a) : dim, line);
        }
      }
    }
    dl->PopClipRect();

    // aviso de lo que acabas de cambiar
    if (!status_.text.empty() && ImGui::GetTime() < status_.until) {
      const float sy = y1 - pad - fs * 2.6f;
      const ImVec2 ss = ImGui::GetFont()->CalcTextSizeA(fs * 0.85f, 1e9f, w - 2 * pad, status_.text.c_str());
      dl->AddRectFilled(ImVec2(x - 8 * u, sy - 6 * u),
                        ImVec2(x + std::min(ss.x, w - 2 * pad) + 8 * u, sy + ss.y + 6 * u), Rgba(accent, 0.9f * a),
                        6 * u);
      Text(dl, fs * 0.85f, ImVec2(x, sy), IM_COL32(10, 12, 14, static_cast<int>(255 * a)), status_.text.c_str(),
           w - 2 * pad);
    }

    // ayuda de botones abajo
    {
      float hx = x;
      const float hy2 = y1 - pad - fs * 0.9f;
      auto hint = [&](const char* glyph, uint32_t col, const char* text) {
        const float r = fs * 0.55f;
        const ImVec2 c(hx + r, hy2 + r * 0.8f);
        const bool ps = PadIsPlayStation();
        if (ps && glyph[0] != 'G') {
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
          const char* shown = (ps && glyph[0] == 'G') ? "PS" : glyph;
          dl->AddCircleFilled(c, r, Rgba(ps ? 0x1C1D21 : col, a));
          const ImVec2 gs2 = ImGui::GetFont()->CalcTextSizeA(fs * 0.7f, 1e9f, 0.0f, shown);
          Text(dl, fs * 0.7f, ImVec2(c.x - gs2.x / 2, c.y - gs2.y / 2), IM_COL32(255, 255, 255, 255 * a), shown);
        }
        hx += 2 * r + 6 * u;
        Text(dl, fs * 0.8f, ImVec2(hx, hy2), dim, text);
        hx += TextWidth(fs * 0.8f, text) + 18 * u;
      };
      hint("A", 0x107C10, tab_ == kAchievements ? "Seleccionar" : "Cambiar");
      hint("B", 0xC0392B, "Volver al juego");
      hint("G", 0x2D7FF9, "Cerrar");
      if (hx < x0 + w - pad) Text(dl, fs * 0.75f, ImVec2(x0 + w - pad - 66 * u, hy2 + 2 * u), dim, "LB · RB");
    }
  }

  static void Row(ImDrawList* dl, ImVec2 p, float width, float fs, bool selected, const char* text, float u,
                  float a, uint32_t accent, const char* value) {
    const ImVec2 b(p.x + width, p.y + fs * 2.2f);
    dl->AddRectFilled(p, b, selected ? Rgba(accent, 0.95f * a) : IM_COL32(32, 36, 42, static_cast<int>(255 * a)),
                      9 * u);
    const ImU32 col = selected ? IM_COL32(8, 10, 12, static_cast<int>(255 * a))
                               : IM_COL32(236, 238, 241, static_cast<int>(255 * a));
    Text(dl, fs, ImVec2(p.x + 16 * u, p.y + fs * 0.55f), col, text);
    if (value) {
      const auto sz = ImGui::GetFont()->CalcTextSizeA(fs, 1e9f, 0.0f, value);
      Text(dl, fs, ImVec2(b.x - 16 * u - sz.x, p.y + fs * 0.55f), col, value);
    }
  }

  rex::app::App& app_;
  rex::kernel::TitleRuntime& title_;
  int tab_ = kGraphics;
  int sel_[kTabs] = {0, 0, 0};
  bool open_ = false;
  float anim_ = 0.0f;
  uint16_t last_buttons_ = 0;
  bool nav_enabled_ = false;
  uint32_t held_ = 0;
  double repeat_at_ = 0.0;
  double tab_at_ = 0.0;
  int scroll_ = 0;
  bool imgs_dirty_ = true;
  mutable bool achievements_loaded_ = false;
  mutable unsigned unlocked_ = 0, score_ = 0, score_total_ = 0;
  mutable std::vector<rex::Achievement> achievements_;
  PlayClock clock_;
  Status status_{};
};

void InstallGuideMenu(rex::app::App& app, rex::kernel::TitleRuntime& title) {
  // El botón Guía (Xbox/PS) lo filtra el sistema de entrada salvo que se pida; el menú lo necesita.
  app.GetInput().GetSettings().guide_button.Set(true);
  app.GetUI().AddDialog(std::make_unique<GuideMenu>(app, title));
}

}  // namespace reforge
"""

BLOCK_BEGIN = "  // >>> ReForge Studio: menú Guía (no editar este bloque)"
BLOCK_END = "  // <<< ReForge Studio menú Guía"
BLOCK = (f"{BLOCK_BEGIN}\n"
         "  rex::Result<void> OnTitleLaunch(rex::kernel::TitleRuntime& title) override {\n"
         "    reforge::InstallGuideMenu(*this, title);\n"
         "    return rex::app::TitleApp::OnTitleLaunch(title);\n"
         "  }\n"
         f"{BLOCK_END}\n")

DECL = ("// >>> ReForge Studio: menú Guía (no editar este bloque)\n"
        "namespace reforge {\n"
        "void InstallGuideMenu(rex::app::App& app, rex::kernel::TitleRuntime& title);\n"
        "}  // namespace reforge\n"
        "// <<< ReForge Studio menú Guía\n")

SOURCE_NAME = "reforge_menu.cpp"


def _write_if_changed(path, text):
    try:
        if open(path, encoding="utf-8").read() == text:
            return False
    except OSError:
        pass
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return True


def applies(root):
    """¿Es un proyecto del SDK 0.11 (API `rex::app::TitleApp`) con `src/main.cpp`?"""
    import os
    main = os.path.join(root, "src", "main.cpp")
    try:
        with open(main, encoding="utf-8") as f:
            txt = f.read()
    except OSError:
        return False
    return "REX_TITLE_APP" in txt or "rex::app::TitleApp" in txt


def remove(root):
    """Quita el menú Guía de un proyecto 0.11 (vuelve al comportamiento normal del SDK)."""
    import os
    import re

    changes = []
    src = os.path.join(root, "src")
    for name, label in ((SOURCE_NAME, f"src/{SOURCE_NAME}"),
                        ("main.cpp", "src/main.cpp"), (os.path.join("..", "CMakeLists.txt"), "CMakeLists.txt")):
        path = os.path.normpath(os.path.join(src, name))
        try:
            txt = open(path, encoding="utf-8").read()
        except OSError:
            continue
        if name == SOURCE_NAME:
            try:
                os.remove(path)
                changes.append(label)
            except OSError:
                pass
            continue
        new = re.sub(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END) + r"\n", lambda _m: "", txt, flags=re.S)
        # la declaración de InstallGuideMenu tiene su propio bloque
        new = re.sub(r"// >>> ReForge Studio: menú Guía \(no editar este bloque\)\n(?:.*?\n)*?// <<< ReForge Studio menú Guía\n\n?",
                     "", new)
        new = new.replace(f" src/{SOURCE_NAME}", "")
        if new != txt:
            _write_if_changed(path, new)
            changes.append(label)
    return changes


def ensure(root):
    """Genera/actualiza el menú Guía de 0.11. Devuelve la lista de archivos cambiados (vacía si ya estaba)."""
    import os
    import re

    changes = []
    src = os.path.join(root, "src")
    main = os.path.join(src, "main.cpp")
    cml = os.path.join(root, "CMakeLists.txt")
    if not (os.path.isfile(main) and os.path.isfile(cml)) or not applies(root):
        return changes
    if _write_if_changed(os.path.join(src, SOURCE_NAME), SOURCE):
        changes.append(f"src/{SOURCE_NAME}")

    txt = open(main, encoding="utf-8").read()
    orig = txt
    if "InstallGuideMenu" not in txt.split("class ")[0]:
        anchor = re.search(r"^(#include[^\n]*\n)(?!#include)", txt, re.M)
        if anchor:      # la declaración va tras el último #include
            last = None
            for last in re.finditer(r"^#include[^\n]*\n", txt, re.M):
                pass
            if last:
                txt = txt[:last.end()] + "\n" + DECL + txt[last.end():]
    if BLOCK_BEGIN in txt:
        txt = re.sub(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END) + r"\n", lambda _m: BLOCK, txt, flags=re.S)
    else:
        m = re.search(r"(class\s+\w+\s*:\s*public\s+rex::app::TitleApp\s*\{\s*\n\s*public:\s*\n)", txt)
        if m:
            txt = txt[:m.end()] + BLOCK + "\n" + txt[m.end():]
    if txt != orig:
        _write_if_changed(main, txt)
        changes.append("src/main.cpp")

    build = open(cml, encoding="utf-8").read()
    if f"src/{SOURCE_NAME}" not in build:
        # Los proyectos 0.11 meten las fuentes del host en <PROYECTO>_HOST_SOURCES (biblioteca OBJECT);
        # así el archivo hereda los includes/defines de rexglue. Si no existe, se añade al ejecutable.
        new, n = re.subn(r"^(set\(\w*_HOST_SOURCES[^\n)]*)\)", r"\1 src/" + SOURCE_NAME + r")", build, count=1,
                         flags=re.M)
        if not n:
            new, n = re.subn(r"^(\s*)(add_executable\([^\n]*src/main\.cpp)",
                             r"\1\2 src/" + SOURCE_NAME, build, count=1, flags=re.M)
        if n:
            _write_if_changed(cml, new)
            changes.append("CMakeLists.txt")
    return changes
